"""Runs a plan from planner.py on the arm: poses, joint moves, gestures, and vision-guided pick/push/point.

Poses live in poses.json and can be taught by hand (teach mode releases the torque), so nothing
depends on guessing which way a joint turns. Pick/push/point are "eye in hand": Claude finds the
object once, local tracking keeps it centered while the base turns and the arm leans in.
"""
import json
import threading
import time
from pathlib import Path

import vision
from arm import RANGES, Arm, ArmError, deg_to_steps, steps_to_deg

POSES_FILE = Path(__file__).with_name("poses.json")
JOINT_NAMES = {"base": "shoulder_pan", "shoulder": "shoulder_lift", "elbow": "elbow_flex",
               "wrist_pitch": "wrist_flex", "wrist_roll": "wrist_roll"}
# Starting guesses in degrees; teach the real ones by hand (POST /teach/<name> then /save/<name>).
DEFAULT_POSES = {
    "ready": {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 0, "wrist_flex": 0, "wrist_roll": 0},
    "up": {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 80, "wrist_flex": 0, "wrist_roll": 0},
    "forward": {"shoulder_pan": 0, "shoulder_lift": 45, "elbow_flex": 45, "wrist_flex": 0, "wrist_roll": 0},
    "look_table": {"shoulder_pan": 0, "shoulder_lift": 20, "elbow_flex": -10, "wrist_flex": 60, "wrist_roll": 0},
    "give": {"shoulder_pan": 0, "shoulder_lift": 40, "elbow_flex": 40, "wrist_flex": 0, "wrist_roll": 0},
}
CAMERA_HFOV = 60.0
ALIGN_TOL = 0.04  # |x - 0.5| considered centered
NEAR_SIZE = 0.45  # object this tall in the image = within the gripper's reach
SCAN = (0, 25, -25, 45, -45)

FAIL = {
    "notfound": {"pt": "Não encontrei {t}.", "en": "I couldn't find {t}.", "zh": "我没有找到{t}。", "es": "No encontré {t}."},
    "nograb": {"pt": "Não consegui segurar {t}.", "en": "I couldn't hold {t}.", "zh": "我没能抓住{t}。", "es": "No pude agarrar {t}."},
    "power": {"pt": "Perdi a força dos motores. Verifique a fonte.", "en": "The motors lost power. Check the supply.",
              "zh": "电机断电了，请检查电源。", "es": "Los motores perdieron energía. Revise la fuente."},
    "stopped": {"pt": "Parei.", "en": "Stopped.", "zh": "已停止。", "es": "Me detuve."},
}


def fail_text(key: str, lang: str, target: str = "") -> str:
    table = FAIL[key]
    return table.get(lang, table["en"]).format(t=target)


class Stopped(Exception):
    pass


class Executor:
    def __init__(self, arm: Arm, camera: vision.Camera, say=print, log=print):
        self.arm, self.camera, self.say, self.log = arm, camera, say, log
        self.poses = dict(DEFAULT_POSES)
        if POSES_FILE.exists():
            self.poses.update(json.loads(POSES_FILE.read_text()))
        self.pan_sign = 1.0  # learned while aligning: which way the image moves when the base turns
        self.stop_event = threading.Event()
        self.busy = threading.Lock()
        self.base_speed = 600

    # ---- control --------------------------------------------------------------------------
    def stop(self):
        self.stop_event.set()
        self.arm.stop()

    def _check(self):
        if self.stop_event.is_set():
            raise Stopped
        hot = self.arm.too_hot()
        if hot:
            raise ArmError(f"motors too hot: {hot}")

    def run(self, plan: dict) -> bool:
        """Execute every action; on failure say why (in the plan's language) and shake 'no'."""
        lang = plan.get("language", "en")
        with self.busy:
            self.stop_event.clear()
            try:
                for action in plan["actions"]:
                    self._check()
                    problem = self._do(action)
                    if problem:
                        self.say(fail_text(problem, lang, action.get("target") or ""), lang)
                        self._gesture("no")
                        return False
                return True
            except Stopped:
                self.say(fail_text("stopped", lang), lang)
                return False
            except ArmError as e:
                self.log(f"arm error: {e}")
                self.say(fail_text("power", lang), lang)
                return False

    # ---- actions ----------------------------------------------------------------------------
    def _do(self, a: dict) -> str | None:
        kind = a["type"]
        self.log(f"action: { {k: v for k, v in a.items() if v is not None} }")
        if kind == "pose":
            self.go_pose(a["name"] or "ready")
        elif kind == "move":
            joint = JOINT_NAMES[a["joint"]]
            now = self.arm.degrees()[joint]
            target = now + a["value"] if a["relative"] else a["value"]
            self.arm.move_deg({joint: target})
        elif kind == "gripper":
            self.arm.move_deg({"gripper": a["value"]}, timeout=3)
        elif kind == "gesture":
            self._gesture(a["name"] or "no")
        elif kind == "speed":
            self.arm.set_speed(self.base_speed * (a["value"] or 100) / 100)
        elif kind == "wait":
            end = time.time() + min(10, a["value"] or 1)
            while time.time() < end:
                self._check()
                time.sleep(0.1)
        elif kind == "stop":
            self.arm.stop()
        elif kind == "give":
            self.go_pose("give")
            self.arm.move_deg({"gripper": 100}, timeout=3)
        elif kind in ("pick", "push", "point"):
            target = self._search_and_align(a["target"])
            if target is None:
                return "notfound"
            if kind == "point":
                return None
            if kind == "pick":
                return self._pick(target)
            return self._push(target, a["direction"] or "forward")
        return None

    def go_pose(self, name: str):
        """Staged so the 12 V supply is not hit by every joint at once: rising, the shoulder goes first
        (forearm still folded, short lever); going to rest, the wrist first and the shoulder last."""
        if name == "rest":
            goal = {j: steps_to_deg(s) for j, s in self.arm.rest.items() if j != "gripper"}
            self.arm.move_deg({k: goal[k] for k in ("shoulder_pan", "wrist_flex", "wrist_roll")})
            self.arm.move_deg({"elbow_flex": goal["elbow_flex"]})
            self.arm.move_deg({"shoulder_lift": goal["shoulder_lift"]}, timeout=10)
            return
        goal = self.poses.get(name) or self.poses["ready"]
        self.arm.move_deg({"shoulder_lift": goal["shoulder_lift"]}, timeout=10)
        self._check()
        self.arm.move_deg({"elbow_flex": goal["elbow_flex"]}, timeout=10)
        self._check()
        self.arm.move_deg({k: goal[k] for k in ("shoulder_pan", "wrist_flex", "wrist_roll")})

    def _gesture(self, name: str):
        now = self.arm.degrees()
        old_speed = self.arm.speed
        self.arm.set_speed(1200)
        try:
            if name == "no":
                for d in (30, -30, 30, -30, 0):
                    self.arm.move_deg({"wrist_roll": now["wrist_roll"] + d}, timeout=2)
            elif name == "yes":
                for d in (20, -10, 20, 0):
                    self.arm.move_deg({"wrist_flex": now["wrist_flex"] + d}, timeout=2)
            elif name == "wave":
                self.arm.move_deg({"gripper": 100}, timeout=2)
                for d in (40, -40, 40, -40, 0):
                    self.arm.move_deg({"wrist_roll": now["wrist_roll"] + d}, timeout=2)
            elif name == "dance":
                for d in (30, -30, 30, 0):
                    self.arm.move_deg({"shoulder_pan": now["shoulder_pan"] + d, "wrist_roll": now["wrist_roll"] - d}, timeout=3)
        finally:
            self.arm.set_speed(old_speed)

    # ---- vision-guided --------------------------------------------------------------------
    def _search_and_align(self, description: str):
        self.go_pose("look_table")
        start_pan = self.arm.degrees()["shoulder_pan"]
        target = None
        for offset in SCAN:
            self._check()
            self.arm.move_deg({"shoulder_pan": start_pan + offset})
            target = vision.find(self.camera, description, after=time.time())
            if target:
                break
        if not target:
            return None
        self.log(f"found {description} at {target.box}")
        return target if self._align(target, description) else None

    def _align(self, target, description) -> bool:
        last_err = None
        for _ in range(10):
            self._check()
            err = target.box["x"] - 0.5
            if abs(err) < ALIGN_TOL:
                return True
            if last_err is not None and abs(err) > abs(last_err) + 0.02:
                self.pan_sign *= -1  # turned the wrong way: the camera's left is the base's right
            last_err = err
            pan = self.arm.degrees()["shoulder_pan"]
            self.arm.move_deg({"shoulder_pan": pan - self.pan_sign * err * CAMERA_HFOV * 0.8})
            if not self._refresh(target, description):
                return False
        return abs(target.box["x"] - 0.5) < 2 * ALIGN_TOL

    def _refresh(self, target, description) -> bool:
        """Follow the target in a frame taken after the last move; ask Claude again if tracking lost it."""
        frame = self.camera.latest(newer_than=time.time())
        if frame is not None and target.follow(frame):
            return True
        found = vision.find(self.camera, description, after=time.time())
        if not found:
            return False
        target.box, target.template = found.box, found.template
        return True

    def _approach(self, target, description) -> bool:
        """Lean forward/down in small steps, keeping the object centered, until it fills the gripper's view."""
        for _ in range(14):
            self._check()
            if target.box["h"] >= NEAR_SIZE or target.box["y"] >= 0.8:
                return True
            d = self.arm.degrees()
            if d["shoulder_lift"] >= steps_to_deg(RANGES["shoulder_lift"][1]) - 3:
                return False  # leaning as far as it goes: out of reach
            self.arm.move_deg({"shoulder_lift": d["shoulder_lift"] + 5, "elbow_flex": d["elbow_flex"] + 4,
                               "wrist_flex": d["wrist_flex"] - 3})
            if not self._refresh(target, description):
                return False
            err = target.box["x"] - 0.5
            if abs(err) > ALIGN_TOL:
                pan = self.arm.degrees()["shoulder_pan"]
                self.arm.move_deg({"shoulder_pan": pan - self.pan_sign * err * CAMERA_HFOV * 0.6})
        return False

    def _pick(self, target) -> str | None:
        self.arm.move_deg({"gripper": 100}, timeout=3)
        if not self._approach(target, "the object"):
            return "notfound"
        self.arm.move_deg({"gripper": 0}, timeout=3)
        time.sleep(0.3)
        if not self.arm.gripper_contact():
            self.arm.move_deg({"gripper": 100}, timeout=3)
            return "nograb"
        d = self.arm.degrees()
        self.arm.move_deg({"shoulder_lift": d["shoulder_lift"] - 20}, timeout=10)  # lift it off the table
        return None

    def _push(self, target, direction: str) -> str | None:
        self.arm.move_deg({"gripper": 0}, timeout=3)
        if not self._approach(target, "the object"):
            return "notfound"
        d = self.arm.degrees()
        if direction == "forward":
            self.arm.move_deg({"elbow_flex": d["elbow_flex"] + 15, "shoulder_lift": d["shoulder_lift"] + 8})
        else:
            # sweep the base; the sign follows what aligning learned about image left/right
            sweep = 25 * (1 if direction == "left" else -1) * self.pan_sign
            self.arm.move_deg({"shoulder_pan": d["shoulder_pan"] + sweep})
        d = self.arm.degrees()
        self.arm.move_deg({"shoulder_lift": d["shoulder_lift"] - 15}, timeout=10)  # back off
        return None

    # ---- teaching -----------------------------------------------------------------------------
    def teach_start(self):
        """Release torque so the pose can be set by hand. The arm will sag: hold it."""
        self.arm.release()

    def teach_save(self, name: str) -> dict:
        d = {j: round(steps_to_deg(s), 1) for j, s in self.arm.positions().items() if j != "gripper"}
        self.poses[name] = d
        POSES_FILE.write_text(json.dumps(self.poses, indent=2))
        self.arm.enable()  # hold the taught pose
        return d


__all__ = ["Executor", "Stopped", "fail_text", "deg_to_steps"]
