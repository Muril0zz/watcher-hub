"""Runs a plan from planner.py on the arm: poses, joint moves, gestures, and vision-guided pick/push/point.

Poses live in poses.json and can be taught by hand (teach mode releases the torque), so nothing
depends on guessing which way a joint turns. Pick/push/point are "eye in hand": Claude finds the
object once, local tracking keeps it centered while the base turns and the arm leans in.
"""
import json
import math
import os
import threading
import time
from pathlib import Path

import planner
import vision
from arm import RANGES, Arm, ArmError, Contact, deg_to_steps, steps_to_deg

POSES_FILE = Path(__file__).with_name("poses.json")
JOINT_NAMES = {"base": "shoulder_pan", "shoulder": "shoulder_lift", "elbow": "elbow_flex",
               "wrist_pitch": "wrist_flex", "wrist_roll": "wrist_roll"}
# Starting guesses in degrees; teach the real ones by hand (POST /teach/<name> then /save/<name>).
DEFAULT_POSES = {
    "ready": {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 0, "wrist_flex": 0, "wrist_roll": 0},
    "up": {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 80, "wrist_flex": 0, "wrist_roll": 0},
    "forward": {"shoulder_pan": 0, "shoulder_lift": 45, "elbow_flex": 45, "wrist_flex": 0, "wrist_roll": 0},
    "look_table": {"shoulder_pan": 0, "shoulder_lift": 20, "elbow_flex": -10, "wrist_flex": 60, "wrist_roll": 0},
    # high up, camera tipped down as far as this wrist goes: sees the whole table in front
    # (camera ~48 deg below horizontal from a bit higher up; straight down was too steep)
    "overview": {"shoulder_pan": 0, "shoulder_lift": -5, "elbow_flex": 10, "wrist_flex": 63, "wrist_roll": 0},
    "give": {"shoulder_pan": 0, "shoulder_lift": 40, "elbow_flex": 40, "wrist_flex": 0, "wrist_roll": 0},
}
CAMERA_HFOV = 60.0
ALIGN_TOL = 0.04  # |x - 0.5| considered centered
NEAR_SIZE = 0.45  # object this tall in the image = within the gripper's reach
# Side grasp (cups and other upright things): gripper kept level, placed by 2-link inverse kinematics in
# the arm's vertical plane. Metres; the shoulder axis height is an estimate, so the camera also trims it.
L1, L2 = 0.116, 0.135  # SO-101 upper arm and forearm
SHOULDER_H = 0.10  # shoulder_lift axis above the table
GRAB_Z = 0.045 - SHOULDER_H  # jaws ~4.5 cm above the table
SIDE_X0, SIDE_X_MAX, SIDE_STEP = 0.10, 0.21, 0.015  # 0.21: shoulder ~75 deg, inside its limit
LIFT_Z = 0.15  # "all the way up", still level so a cup stays upright
CLOSE_W = 0.5  # object this wide in the image = between the jaws
# Top-down pick (anything but the demo cup): hover with the gripper pointing down, centre the object
# under the jaws by camera, turn the jaws across it, creep down until touching, grip, lift.
TOP_X0, TOP_X_RANGE = 0.17, (0.11, 0.22)  # wrist distance from the shoulder axis: first guess, limits
TOP_HOVER_Z = 0.03  # wrist height hovering
JAW_LEN = 0.10  # wrist pitch axis to jaw tips
# lowest wrist height: jaw tips ~1.5 cm above the table (estimated). -0.06 pushed the jaws into the table
TOP_LOW_Z = -0.03  # backstop only (the table height is an estimate); the load rise below is what stops it
JAW_AIM = (0.5, 0.65)  # where in the image (top-down) the closing jaws meet the table
PROBE_PAN, PROBE_X = 4, 0.015  # test moves that measure how the image moves (bigger ones lost the pen)
CREEP_RISE = 150  # load rise (x0.1 %) over the hovering baseline that means the jaws touched something
CUP_SPOT = (0.094, -0.062)  # demo: where the cup stands (wrist x, z from the shoulder axis; base at 0)
# gripper steps for the demo cup (~7.5 cm, four fingers): the jaws first touched the uncrushed cup at 2437;
# stop ~2 deg past that. Contact-sensing closed too far (40 steps squeezed, more on the way back).
CUP_GRIP_STEPS = 2415
RELOCATE_PAN = 70
CARRY_DZ, PLACE_DZ = 0.10, 0.005  # above CUP_SPOT height: carrying it, and setting it down / picking it up  # how far round the base carries it before setting it down
GRAB_ROLL = -90  # wrist turn before closing so the jaws close sideways; + winds the wrist cable and resets servo 5
AIM_Y = 0.62  # the jaws close on what sits a bit below the image centre
SCAN = (0, 25, -25, 45, -45)
SCAN_WIDE = (0, 30, -30, 60, -60, 85, -85)
PICK_ATTEMPTS = 3

FAIL = {
    "notfound": {"pt": "Não encontrei {t}.", "en": "I couldn't find {t}.", "zh": "我没有找到{t}。", "es": "No encontré {t}."},
    "nograb": {"pt": "Não consegui segurar {t}.", "en": "I couldn't hold {t}.", "zh": "我没能抓住{t}。", "es": "No pude agarrar {t}."},
    "power": {"pt": "Perdi a força dos motores. Verifique a fonte.", "en": "The motors lost power. Check the supply.",
              "zh": "电机断电了，请检查电源。", "es": "Los motores perdieron energía. Revise la fuente."},
    "contact": {"pt": "Encostei em alguma coisa, provavelmente a mesa, e recuei.",
                "en": "I touched something, probably the table, so I backed off.",
                "zh": "我碰到了东西，可能是桌子，已经退回来了。", "es": "Toqué algo, probablemente la mesa, y retrocedí."},
    "stopped": {"pt": "Parei.", "en": "Stopped.", "zh": "已停止。", "es": "Me detuve."},
    "network": {"pt": "Perdi a conexão por um instante. Pode pedir de novo?",
                "en": "I lost my connection for a moment. Could you ask again?",
                "zh": "网络刚才断了一下，请再说一次。", "es": "Perdí la conexión un momento. ¿Puedes pedirlo otra vez?"},
    "retry": {"pt": "Não deu, vou tentar de novo.", "en": "Missed it, trying again.", "zh": "没成功，我再试一次。",
              "es": "No salió, lo intento de nuevo."},
}


def level_ik(x: float, z: float) -> dict:
    """Joint angles (planner degrees) that put the wrist at (x forward, z up) from the shoulder axis with the
    gripper level. Elbow 0 = right angle, + stretches; wrist + tips the gripper down."""
    d = min(math.hypot(x, z), L1 + L2 - 0.005)
    acos = lambda v: math.degrees(math.acos(max(-1.0, min(1.0, v))))  # noqa: E731
    phi = acos((L1 * L1 + L2 * L2 - d * d) / (2 * L1 * L2))  # interior angle at the elbow
    s = math.degrees(math.atan2(x, z)) - acos((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d))
    e = phi - 90
    return {"shoulder_lift": s, "elbow_flex": e, "wrist_flex": e - s}


def down_ik(x: float, z: float) -> dict:
    """Wrist at (x, z) with the gripper pointing down (as near vertical as this wrist allows, max +63)."""
    a = level_ik(x, z)
    a["wrist_flex"] = max(-100.0, min(63.0, 90 - a["shoulder_lift"] + a["elbow_flex"]))
    return a


def reachable(x: float, z: float) -> bool:
    """Level gripper at (x, z) within this arm's joint limits (shoulder forward limit ~78, wrist >= -100)."""
    a = level_ik(x, z)
    return math.hypot(x, z) < L1 + L2 - 0.01 and a["shoulder_lift"] <= 75 and a["wrist_flex"] >= -98


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
        self.base_speed = 300
        self.lang = "en"
        # demo: base angle where the cup stands now (0 = the spot in front); survives a restart via the env
        self.cup_pan = float(os.environ.get("BRAIN_CUP_PAN", "0"))
        self.at_spot = os.environ.get("BRAIN_AT_SPOT") == "1"  # open jaws already around the cup (POST /spot)

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
        lang = self.lang = plan.get("language", "en")
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
            except Contact as e:
                self.log(f"contact: {e}")
                self.say(fail_text("contact", lang), lang)
                return False
            except ArmError as e:
                self.log(f"arm error: {e}")
                self.say(fail_text("power", lang), lang)
                return False
            except Exception as e:  # e.g. the venue Wi-Fi dropped a Claude call mid-search: say so, don't go silent
                self.log(f"run error: {type(e).__name__}: {e}")
                self.say(fail_text("network", lang), lang)
                return False

    # ---- actions ----------------------------------------------------------------------------
    def _do(self, a: dict) -> str | None:
        kind = a["type"]
        self.log(f"action: { {k: v for k, v in a.items() if v is not None} }")
        if kind == "pose" and a["name"] == "look_table":
            kind = "look"  # "look at the table" = go up and look down, never the low pose over the cup spot
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
        elif kind == "relocate":
            return self._relocate(a["direction"] or "left")
        elif kind == "look":
            self.go_pose("overview")  # high up, camera down: the whole table in view
            frame = self.camera.latest(newer_than=time.time() + 0.3)  # a frame taken after the arm settled
            jpeg = self.camera.jpeg(frame)
            if not jpeg:
                return "notfound"
            self.say(planner.describe(jpeg, self.lang), self.lang)
        elif kind == "give":
            self.go_pose("give")
            self.arm.move_deg({"gripper": 100}, timeout=3)
        elif kind in ("pick", "push", "point"):
            # a pick that misses tries again: look wider (camera tilted up/down, base further round),
            # re-align and reach again, until it holds the object or runs out of attempts
            attempts = PICK_ATTEMPTS if kind == "pick" else 1
            problem = "notfound"
            for attempt in range(attempts):
                self._check()
                if attempt:
                    self.log(f"{kind} attempt {attempt} failed ({problem}); trying again")
                    self.say(fail_text("retry", self.lang), self.lang)
                if kind == "pick":  # anything but the demo cup (that one is relocate): from above, by camera
                    problem = self._top_pick(a["target"], wide=attempt > 0)
                    if problem is None:
                        return None
                    continue
                pose = "look_table"
                target = self._search_and_align(a["target"], wide=attempt > 0, pose=pose)
                if target is None:
                    problem = "notfound"
                    continue
                if kind == "point":
                    return None
                if kind == "push":
                    return self._push(target, a["direction"] or "forward")
                problem = self._side_pick(a["target"])
                if problem is None:
                    return None
            return problem
        return None

    def go_pose(self, name: str):
        """Staged so the 12 V supply is not hit by every joint at once: rising, the shoulder goes first
        (forearm still folded, short lever); going to rest, the wrist first and the shoulder last."""
        if name == "rest":
            goal = {j: steps_to_deg(s, j) for j, s in self.arm.rest.items() if j != "gripper"}
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
            # no wrist roll in gestures: turning it the + way winds the wrist cable and resets servo 5
            if name == "no":
                for d in (20, -20, 20, -20, 0):
                    self.arm.move_deg({"shoulder_pan": now["shoulder_pan"] + d}, timeout=2)
            elif name == "yes":
                for d in (20, -10, 20, 0):
                    self.arm.move_deg({"wrist_flex": now["wrist_flex"] + d}, timeout=2)
            elif name == "wave":
                self.arm.move_deg({"gripper": 100}, timeout=2)
                for d in (30, -30, 30, -30, 0):
                    self.arm.move_deg({"wrist_flex": now["wrist_flex"] + d}, timeout=2)
            elif name == "dance":
                for d in (30, -30, 30, 0):
                    self.arm.move_deg({"shoulder_pan": now["shoulder_pan"] + d, "wrist_flex": now["wrist_flex"] - d}, timeout=3)
        finally:
            self.arm.set_speed(old_speed)

    # ---- vision-guided --------------------------------------------------------------------
    def _search_and_align(self, description: str, wide: bool = False, pose: str = "look_table"):
        self.go_pose(pose)
        start_pan = 0.0 if wide else self.arm.degrees()["shoulder_pan"]
        look = self.poses[pose]["wrist_flex"]
        target = None
        # first pass: the camera as posed; a retry also tilts it nearer/further and turns the base further
        tilts = (0, -20, -40) if wide else (0,)  # the overview wrist is already near its down limit
        for tilt in tilts:
            self.arm.move_deg({"wrist_flex": look + tilt})
            for offset in SCAN_WIDE if wide else SCAN:
                self._check()
                self.arm.move_deg({"shoulder_pan": start_pan + offset})
                target = vision.find(self.camera, description, after=time.time())
                if target:
                    break
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
            if d["shoulder_lift"] >= steps_to_deg(RANGES["shoulder_lift"][1], "shoulder_lift") - 3:
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
        d = self.arm.degrees()
        if not self.arm.gripper_contact():
            self.arm.move_deg({"gripper": 100}, timeout=3)
            self.arm.move_deg({"shoulder_lift": d["shoulder_lift"] - 15}, timeout=10)  # back off to look again
            return "nograb"
        self.arm.move_deg({"shoulder_lift": d["shoulder_lift"] - 20}, timeout=10)  # lift it off the table
        self._check()
        self.go_pose("up")  # then all the way up, still holding it
        return None

    def _level_to(self, x: float, z: float, steps: int = 1):
        """Move the wrist to (x, z) with the gripper level, in straight-line waypoints from where it is."""
        d = self.arm.degrees()
        s, e = math.radians(d["shoulder_lift"]), math.radians(d["elbow_flex"])
        # forward kinematics of the current pose (forearm angle from vertical = s + 90 deg - e)
        x0 = L1 * math.sin(s) + L2 * math.sin(s + math.pi / 2 - e)
        z0 = L1 * math.cos(s) + L2 * math.cos(s + math.pi / 2 - e)
        for k in range(1, steps + 1):
            self._check()
            f = k / steps
            self.arm.move_deg(level_ik(x0 + (x - x0) * f, z0 + (z - z0) * f), timeout=10)

    def _side_pick(self, description: str) -> str | None:
        """Come down beside the object with the gripper level and open, creep towards it keeping it centred,
        close, and lift it straight up (level, so a cup stays upright). Base already aligned from above."""
        x, z = SIDE_X0, GRAB_Z
        self.arm.move_deg({"gripper": 100}, timeout=3)
        try:
            self._level_to(x, z, steps=4)  # down from the overview in a straight line, not a swing
            target = vision.find(self.camera, description, after=time.time())
            if target is None:  # lost it coming down: tip the camera down, then up, and fix the height
                level = self.arm.degrees()["wrist_flex"]
                for tilt, dz in ((15, -0.02), (-15, 0.02)):
                    self.arm.move_deg({"wrist_flex": level + tilt})
                    target = vision.find(self.camera, description, after=time.time())
                    if target:
                        z = max(GRAB_Z - 0.03, min(GRAB_Z + 0.06, z + dz))
                        break
                self._level_to(x, z)
            if target is None:
                return "notfound"
            while True:
                self._check()
                if target.box["w"] >= CLOSE_W or x >= SIDE_X_MAX or not reachable(x + SIDE_STEP, z):
                    break
                # aim: base for left/right, height for up/down (the shoulder height above is an estimate)
                err = target.box["x"] - 0.5
                if abs(err) > ALIGN_TOL:
                    pan = self.arm.degrees()["shoulder_pan"]
                    self.arm.move_deg({"shoulder_pan": pan - self.pan_sign * err * CAMERA_HFOV * 0.6})
                dy = target.box["y"] - AIM_Y
                if abs(dy) > 0.12:
                    z = max(GRAB_Z - 0.03, min(GRAB_Z + 0.06, z - 0.01 * (1 if dy > 0 else -1)))
                x += SIDE_STEP
                self._level_to(x, z)
                if not self._refresh(target, description):
                    break  # too close for the camera to see it whole: close on what is there
            if reachable(x + SIDE_STEP, z):  # one more step so the object sits deep between the jaws
                x += SIDE_STEP
                self._level_to(x, z)
        except Contact as c:
            self.log(f"side pick touched something ({c}); closing where it is")
        # level with roll 0 the jaws open up/down; turn the wrist so they close on the object's sides
        roll = self.arm.degrees()["wrist_roll"]
        self.arm.move_deg({"wrist_roll": roll + GRAB_ROLL}, timeout=4)
        self.arm.grip()  # stops at first touch: holds a paper cup without crushing it
        time.sleep(0.3)
        if not self.arm.gripper_contact():
            self.arm.move_deg({"gripper": 100}, timeout=3)
            self._level_to(SIDE_X0, GRAB_Z + 0.05)  # back away and up, then look again from above
            return "nograb"
        self._level_to(x, z + 0.05)  # off the table first
        self._level_to(min(x, 0.12), LIFT_Z, steps=3)  # then all the way up, still level
        return None

    def _where_is_cup(self) -> float:
        """Base angle of the spot the cup is on: look straight down at the remembered spot first, then the
        other one. Falls back to memory if the camera finds it at neither."""
        for pan in (self.cup_pan, 0 if self.cup_pan else RELOCATE_PAN):
            self._check()
            self.arm.move_deg({"wrist_roll": 0})
            self.go_pose("look_table")
            self.arm.move_deg({"shoulder_pan": pan}, timeout=10)
            if vision.find(self.camera, "a paper cup standing on the table", after=time.time()):
                self.log(f"cup seen at the {pan:.0f} deg spot")
                return pan
        self.log(f"cup not seen at either spot; trying the remembered one ({self.cup_pan:.0f})")
        return self.cup_pan

    def _down_to(self, x: float, z: float, steps: int = 1):
        """Like _level_to, with the gripper pointing down."""
        d = self.arm.degrees()
        s, e = math.radians(d["shoulder_lift"]), math.radians(d["elbow_flex"])
        x0 = L1 * math.sin(s) + L2 * math.sin(s + math.pi / 2 - e)
        z0 = L1 * math.cos(s) + L2 * math.cos(s + math.pi / 2 - e)
        for k in range(1, steps + 1):
            self._check()
            f = k / steps
            self.arm.move_deg(down_ik(x0 + (x - x0) * f, z0 + (z - z0) * f), timeout=10)

    def _see(self, description: str):
        t = vision.find(self.camera, description, after=time.time())
        return (t.box["x"], t.box["y"]) if t else None

    def _top_pick(self, description: str, wide: bool = False) -> str | None:
        """Pick anything (not the demo cup) from above, guided by the wrist camera. The camera is mounted
        turned, so instead of assuming which way the image moves, two small probe moves measure it."""
        self.arm.move_deg({"wrist_roll": 0, "gripper": 100})
        self.go_pose("overview")
        start = self.arm.degrees()["shoulder_pan"] if not wide else 0.0
        seen = None
        for off in (SCAN_WIDE if wide else SCAN):
            self._check()
            self.arm.move_deg({"shoulder_pan": start + off}, timeout=10)
            seen = self._see(description)
            if seen:
                break
        if not seen:
            return "notfound"
        pan, x, z = self.arm.degrees()["shoulder_pan"], TOP_X0, TOP_HOVER_Z
        self.log(f"top pick: {description} seen from above, base {pan:.0f}")
        self._down_to(x, z + 0.04, steps=2)  # come over it from above
        self._down_to(x, z)
        p0 = self._see(description)
        # the downward view is small: if the first guess misses, search a 3 x 3 grid of reach x base angle
        grid = [(gx, gp) for gx in (TOP_X0, TOP_X_RANGE[0] + 0.01, TOP_X_RANGE[1] - 0.01) for gp in (0, -12, 12)]
        for gx, gp in grid[1:]:
            if p0:
                break
            self._check()
            x = gx
            self.arm.move_deg({"shoulder_pan": pan + gp}, timeout=6)
            self._down_to(x, z)
            p0 = self._see(description)
            if p0:
                pan += gp
        if not p0:
            return "notfound"
        self.log(f"top pick: under the camera at reach {x:.2f}, base {pan:.0f}")
        # probes: how the object moves in the image per degree of base and per metre of reach
        self.arm.move_deg({"shoulder_pan": pan + PROBE_PAN}, timeout=6)
        p1 = self._see(description)
        self._down_to(x + PROBE_X, z)
        p2 = self._see(description)
        if not (p1 and p2):
            return "notfound"
        j = [[(p1[0] - p0[0]) / PROBE_PAN, (p2[0] - p1[0]) / PROBE_X], [(p1[1] - p0[1]) / PROBE_PAN, (p2[1] - p1[1]) / PROBE_X]]
        det = j[0][0] * j[1][1] - j[0][1] * j[1][0]
        self.log(f"top pick: image moves per deg/m {j}")
        if abs(det) < 1e-4:
            return "notfound"
        pan, x, cur = pan + PROBE_PAN, x + PROBE_X, p2
        scale = 1.0
        for _ in range(6):  # centre it under the jaws, in small damped steps (the view is narrow)
            ex, ey = JAW_AIM[0] - cur[0], JAW_AIM[1] - cur[1]
            if math.hypot(ex, ey) < 0.05:
                break
            dpan = 0.6 * scale * (j[1][1] * ex - j[0][1] * ey) / det
            dx = 0.6 * scale * (-j[1][0] * ex + j[0][0] * ey) / det
            new_pan = pan + max(-5.0, min(5.0, dpan))
            new_x = max(TOP_X_RANGE[0], min(TOP_X_RANGE[1], x + max(-0.015, min(0.015, dx))))
            self.arm.move_deg({"shoulder_pan": new_pan}, timeout=6)
            self._down_to(new_x, z)
            seen = self._see(description)
            if seen:
                pan, x, cur = new_pan, new_x, seen
                continue
            # stepped it out of view: go back to where it was seen and try half the step
            self.arm.move_deg({"shoulder_pan": pan}, timeout=6)
            self._down_to(x, z)
            scale /= 2
            if scale < 0.2:
                return "notfound"
        # turn the jaws (they close along the image's width) across the object's narrow side, safe way only
        frame = self.camera.latest(newer_than=time.time())
        angle = planner.long_axis_angle(self.camera.jpeg(frame), description) if frame is not None else None
        if angle is not None:
            roll = (angle + 90) % 180 - 180  # same jaw line, expressed in -180..0
            self.arm.move_deg({"wrist_roll": roll}, timeout=4)
        try:  # creep down until it touches (the object or the table), never below the jaws-safe height
            zz = z
            feel = ("shoulder_lift", "elbow_flex", "wrist_flex")
            base = {j: self.arm._load(j) for j in feel}  # effort just holding the pose, before touching
            while zz > TOP_LOW_Z and reachable(x, zz - 0.01):  # far and low runs out of shoulder
                zz = max(TOP_LOW_Z, zz - 0.01)
                self._down_to(x, zz)
                time.sleep(0.15)
                # the jaws pressing on something shows up as a rise in effort well before anything stalls
                if any(self.arm._load(j) - base[j] > CREEP_RISE for j in feel):
                    self.log("top pick: felt the table/object, stopping the descent")
                    self._down_to(x, zz + 0.01)
                    break
        except Contact as c:
            self.log(f"top pick touched ({c}); gripping here")
        held = self.arm.grip()
        self._down_to(x, z)  # lift
        if not held:
            self.arm.move_deg({"gripper": 100}, timeout=3)
            return "nograb"
        self._level_to(0.12, LIFT_Z, steps=2)  # up high, holding it
        return None

    def _descend_to(self, pan: float):
        """The exact reverse of setting the cup down: carrying height, base round to the spot, wrist turned in
        the air, then straight down to the set-down height (turning next to the cup pushed it)."""
        x, z = CUP_SPOT
        self.arm.move_deg({"gripper": 100}, timeout=3)
        self._level_to(x, z + CARRY_DZ, steps=3)
        self.arm.move_deg({"shoulder_pan": pan}, timeout=10)
        for r in (-30, -60, GRAB_ROLL):  # the safe way, in steps
            self.arm.move_deg({"wrist_roll": r}, timeout=3)
        self._level_to(x, z + PLACE_DZ, steps=2)

    def _relocate(self, direction: str) -> str | None:
        """Demo, no camera: the cup stands at the marked spot (base angle self.cup_pan). Come down beside
        it, turn the wrist, grip gently, lift, swing the base to the other spot, set it down there, let go,
        and come back up to the middle. direction "back" returns it to the spot in front."""
        x, z = CUP_SPOT
        ready = self.at_spot  # /spot left the open jaws around the cup: grab right there
        self.at_spot = False
        if not self.arm.torque:
            self.arm.enable()  # hold exactly where it is
        # No camera check here: the look pose points the jaws down right over the spot and can hit the cup.
        # Go where memory says; if the jaws close on air, try the other spot before giving up.
        spots = [self.cup_pan] if ready else [self.cup_pan, 0 if self.cup_pan else RELOCATE_PAN]
        for i, pan in enumerate(spots):
            if i or not ready:
                self._descend_to(pan)
            self.arm.grip_to(CUP_GRIP_STEPS)  # the cup's own width: same gentle squeeze going and coming back
            # holding the cup stops the jaws short of that width; closing on air reaches it
            if self.arm.positions()["gripper"] >= CUP_GRIP_STEPS + 10:
                self.cup_pan = pan
                break
            self.log(f"no cup at the {pan:.0f} deg spot")
            self.arm.move_deg({"gripper": 100}, timeout=3)
            self._level_to(x, z + CARRY_DZ, steps=2)
        else:
            for r in (-60, -30, 0):
                self.arm.move_deg({"wrist_roll": r}, timeout=3)
            return "nograb"
        if direction == "back":
            to_pan = 0
        else:
            to_pan = RELOCATE_PAN if direction != "right" else -RELOCATE_PAN
        if to_pan == self.cup_pan:  # already there: carry it to the other side instead
            to_pan = 0 if self.cup_pan else RELOCATE_PAN
        self._level_to(x, z + CARRY_DZ, steps=2)  # lift it
        self.arm.move_deg({"shoulder_pan": to_pan}, timeout=10)  # carry it to the other spot
        self._level_to(x, z + PLACE_DZ, steps=2)  # set it down
        self.arm.move_deg({"gripper": 100}, timeout=3)  # let go
        self.cup_pan = to_pan  # remember where it is, for "bring it back"
        self._level_to(x, z + CARRY_DZ, steps=2)  # up and out of the cup
        for r in (-60, -30, 0):
            self.arm.move_deg({"wrist_roll": r}, timeout=3)
        self.arm.move_deg({"shoulder_pan": 0}, timeout=10)
        self._level_to(0.12, LIFT_Z, steps=2)
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
        d = {j: round(steps_to_deg(s, j), 1) for j, s in self.arm.positions().items() if j != "gripper"}
        self.poses[name] = d
        POSES_FILE.write_text(json.dumps(self.poses, indent=2))
        self.arm.enable()  # hold the taught pose
        return d


__all__ = ["Executor", "Stopped", "fail_text", "deg_to_steps"]
