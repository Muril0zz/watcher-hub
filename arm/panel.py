"""Web control panel for the SO-101 follower: one slider per joint, live positions.

    .venv/bin/python panel.py      then open http://127.0.0.1:8101

Every time torque is enabled, the pose the arm is resting in becomes its base: the zero of
every slider and the place it returns to before torque is released. Only one program can
use the serial port at a time, so stop the panel (Ctrl+C, once) before running secuencia.py.
"""

import base64
import json
import threading
import time
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import serial

from so101 import (
    ARM_GROUP,
    GOAL_POSITION,
    MOTORS,
    PRESENT_POSITION,
    PRESENT_TEMPERATURE,
    STEPS_PER_REV,
    TORQUE_LIMIT,
    WRIST_GROUP,
    Bus,
)

HOST, PORT = "127.0.0.1", 8101
PAGE_FILE = Path(__file__).with_name("panel.html")
POSES_FILE = Path(__file__).with_name("poses.json")  # named places, in absolute steps (base-independent)
VENDOR_DIR = (Path(__file__).parent / "vendor").resolve()  # local copies of browser libraries/models
CONTENT_TYPES = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm",
                 ".task": "application/octet-stream", ".tflite": "application/octet-stream"}
# Camera-to-arm calibration: examples of "the cup was seen at this pixel" + "the arm grasps it in this pose".
# Only valid while the camera stays where it was when the examples were taken.
VISION_FILE = Path(__file__).with_name("vision.json")
# Latest camera frame sent by the page (with detections drawn), so it can be inspected while
# debugging. Stays on this machine; overwritten every few seconds.
SNAPSHOT_FILE = Path(__file__).with_name("camera_snapshot.jpg")
MAX_SNAPSHOT_BYTES = 2_000_000
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}

# Safe absolute range per joint, in steps. With the factory homing, 2048 is the middle of each
# joint's travel; the spans come from the official SO-101 model (sim/SO101) minus a 10 deg margin.
# The resting pose is always kept inside its joint's range.
ABS_RANGES = {
    "shoulder_pan": (910, 3186),  # +-100 deg
    "shoulder_lift": (850, 3072),  # rest (folded) .. +90 deg past the middle
    "elbow_flex": (897, 3038),  # rest (folded) .. +87 deg past the middle
    "wrist_flex": (1081, 3015),  # +-85 deg
    "wrist_roll": (341, 3755),  # +-150 deg
    "gripper": (2046, 3094),  # closed .. ~90 deg open
}
# Comfortable working pose: every joint at the middle of its travel, gripper untouched.
READY = {"shoulder_pan": 2048, "shoulder_lift": 2048, "elbow_flex": 2048, "wrist_flex": 2048, "wrist_roll": 2048}
TORQUE_LIMITS = {"gripper": 400, "shoulder_lift": 800, "elbow_flex": 800}
DEFAULT_SPEED = 300  # steps/s
STALL_STEPS = 40  # a joint this far from its target...
STALL_SECONDS = 1.0  # ...without moving for this long is considered blocked
# Motor protection: holding the arm up (or pushing on something) heats the servos.
HOT_C = 60  # at this temperature the arm goes back to its base and releases torque to cool down
TEMP_EVERY_S = 2.0  # how often temperatures are read
IDLE_REST_S = 180  # with no command for this long, the arm goes back to its base and releases


def to_deg(steps: int) -> float:
    return steps * 360 / STEPS_PER_REV


class Busy(Exception):
    pass


class Arm:
    def __init__(self):
        self.bus = Bus()
        stiff = self.bus.torque_on(MOTORS.values())
        if stiff:
            self.bus.close()
            raise SystemExit(
                f"Torque is already ON on motors {stiff} (left by a program that crashed?). "
                "The panel must start from the resting pose with torque off: hold the arm, put it at rest, "
                "then run: .venv/bin/python -c \"from so101 import *; Bus().release(MOTORS.values())\""
            )
        self.lock = threading.Lock()
        self.torque = False
        self.speed = DEFAULT_SPEED
        self.targets: dict[int, int] = {}  # last goal sent per motor (steps)
        self.last_pos: dict[int, int] = {}
        self.stuck_since: dict[int, float] = {}
        self.blocked: set[int] = set()
        self.power_drops = 0  # times the motors rebooted on their own (12V supply cut out)
        self.temps: dict[int, int] = {}
        self.last_temp_read = 0.0
        self.last_command = time.time()
        self.auto_rest = ""  # why the arm last went to rest on its own ("hot" / "idle"), for the page to say
        # Commands from other devices (e.g. the SenseCAP Watcher via watcher/arm_bridge.py). The page
        # picks them up and runs them through the same interpreter as its own voice commands.
        self.inbox: deque = deque(maxlen=20)
        self.inbox_lock = threading.Lock()
        self._set_base(self.bus.positions(MOTORS.values()))

    def _set_base(self, pos: dict[int, int]):
        """The base pose is where the arm sits on its own with torque off: the zero of every
        slider and the pose it returns to before torque is released. Re-taken at every enable."""
        self.rest = dict(pos)
        self.ranges = {}  # absolute steps, widened to always include the base pose
        for name, m in MOTORS.items():
            lo, hi = ABS_RANGES[name]
            self.ranges[name] = (max(0, min(lo, self.rest[m])), min(4095, max(hi, self.rest[m])))

    @contextmanager
    def _bus(self, wait: float = 0.3):
        """Exclusive bus access. Commands don't queue up behind a long move: if the arm is busy
        for longer than `wait`, they fail instead of running late (and out of order)."""
        if not self.lock.acquire(timeout=wait):
            raise Busy("the arm is busy moving, try again when it stops")
        try:
            yield
        finally:
            self.lock.release()

    def _require_torque(self):
        if not self.torque:
            raise ValueError("enable torque first")

    def _reconnect(self):
        """The USB cable dropped and came back: reopen the port and re-read the real torque
        state from the motors (they keep it while the 12V supply stays on)."""
        try:
            self.bus.close()
        except Exception:
            pass
        self.bus = Bus()
        self.torque = bool(self.bus.torque_on(MOTORS.values()))

    def state(self) -> dict:
        with self._bus(wait=60):  # polls simply wait for a move to finish
            try:
                pos = self.bus.positions(MOTORS.values())
            except serial.SerialException:  # port gone or stale: retried on every poll until it's back
                self._reconnect()
                pos = self.bus.positions(MOTORS.values())
            if self.torque:
                self._detect_power_drop()
            if self.torque:
                self._guard_stalls(pos)
            self._protect_motors()
        return {
            "torque": self.torque,
            "speed": self.speed,
            "power_drops": self.power_drops,
            "temps": {name: self.temps.get(m) for name, m in MOTORS.items()},
            "alarms": {name: self.bus.alarm_names(m) for name, m in MOTORS.items() if self.bus.alarm_names(m)},
            "hot_c": HOT_C,
            "auto_rest": self.auto_rest,
            "joints": {
                name: {
                    "deg": round(to_deg(pos[m] - self.rest[m]), 1),
                    "target": round(to_deg(self.targets.get(m, pos[m]) - self.rest[m]), 1),
                    "steps": pos[m],
                    "min": round(to_deg(self.ranges[name][0] - self.rest[m])),
                    "max": round(to_deg(self.ranges[name][1] - self.rest[m])),
                    "blocked": m in self.blocked,
                }
                for name, m in MOTORS.items()
            },
        }

    def _protect_motors(self):
        """Overheating or a long idle hold -> back to the base pose and release torque.
        Called with the lock held. If the arm can't get back, torque stays on (no drop) and it retries."""
        now = time.time()
        if now - self.last_temp_read >= TEMP_EVERY_S:
            self.last_temp_read = now
            try:
                self.temps = {m: self.bus.read(m, PRESENT_TEMPERATURE) for m in MOTORS.values()}
            except OSError:
                pass  # an overheated servo may answer with an error flag: keep the last reading
        if not self.torque:
            return
        gripper = MOTORS["gripper"]
        if "overload" in self.bus.alarm_names(gripper):
            # Squeezing too hard for too long: hold the gripper where it is instead of pushing further.
            p = self.bus.read(gripper, PRESENT_POSITION)
            if abs(self.targets.get(gripper, p) - p) > 10:
                self.bus.write(gripper, GOAL_POSITION, p)
                self.targets[gripper] = p
                print(f"[{time.strftime('%H:%M:%S')}] gripper overload: easing the grip at {p}", flush=True)
        overheat = any("overheat" in self.bus.alarm_names(m) for m in MOTORS.values())
        hot = overheat or max(self.temps.values(), default=0) >= HOT_C
        idle = now - self.last_command > IDLE_REST_S
        if hot or idle:
            reason = "hot" if hot else "idle"
            print(f"[{time.strftime('%H:%M:%S')}] auto rest ({reason}): temps={self.temps}", flush=True)
            try:
                self.bus.return_and_release(self.rest)
                self.torque = False
                self.auto_rest = f"{reason}@{int(now)}"
            except OSError as e:
                print(f"[{time.strftime('%H:%M:%S')}] auto rest failed, holding: {e}", flush=True)

    def _detect_power_drop(self):
        """Torque lives in RAM: if every motor reports it off while we think it's on, they all
        rebooted at once, i.e. the 12V supply cut out. Called with the lock held."""
        if not self.bus.torque_on(MOTORS.values()):
            self.torque = False
            self.power_drops += 1
            self.blocked.clear()

    def _guard_stalls(self, pos: dict[int, int]):
        """A joint far from its target that has stopped moving is pushing against something:
        make it stay where it is instead of straining. Called with the lock held."""
        now = time.time()
        for m, p in pos.items():
            if m == MOTORS["gripper"]:  # a gripper "stalled" on an object is holding it: keep squeezing
                continue                # (its TORQUE_LIMIT already caps the force)
            far = abs(self.targets.get(m, p) - p) > STALL_STEPS
            still = abs(p - self.last_pos.get(m, p)) < 3
            if far and still:
                self.stuck_since.setdefault(m, now)
                if now - self.stuck_since[m] > STALL_SECONDS:
                    self.bus.write(m, GOAL_POSITION, p)
                    self.targets[m] = p
                    self.blocked.add(m)
            else:
                self.stuck_since.pop(m, None)
            self.last_pos[m] = p

    def enable(self):
        with self._bus():
            if self.torque:
                return
            for name, limit in TORQUE_LIMITS.items():
                self.bus.write(MOTORS[name], TORQUE_LIMIT, limit)
            try:
                self.targets = self.bus.hold(MOTORS.values(), speed=self.speed)
                self.last_command = time.time()
                self.torque = True
            except Exception:
                # Find out what really happened instead of assuming torque is off.
                self.torque = bool(self.bus.torque_on(MOTORS.values()))
                raise
            self._set_base(self.targets)  # wherever the arm was left is the new base
            self.blocked.clear()

    def rest_and_release(self, wait: float = 0.3):
        """Back to the resting pose, then release. If the arm can't get there, torque stays ON
        (return_and_release raises) and the panel keeps reporting it as on.
        Shutdown passes a long `wait` so it waits for a move in progress instead of giving up."""
        with self._bus(wait=wait):
            if not self.torque:
                return
            self.bus.return_and_release(self.rest)
            self.torque = False
            for name in TORQUE_LIMITS:
                self.bus.write(MOTORS[name], TORQUE_LIMIT, 1000)

    def go_ready(self):
        targets = {MOTORS[name]: steps for name, steps in READY.items()}
        with self._bus():
            self._require_torque()
            sent, stopped = {}, {}
            for group in (ARM_GROUP, WRIST_GROUP):  # raise the arm first, then turn the wrist
                part = {MOTORS[n]: targets[MOTORS[n]] for n in group if MOTORS[n] in targets}
                sent.update(part)
                stopped.update(self.bus.move(part))
                if stopped:
                    break  # never turn the wrist if the arm didn't get up
            self.targets.update(sent)
            self.targets.update(stopped)  # blocked joints stay where they stopped
            self.blocked = set(stopped)
        return {"blocked": [name for name, m in MOTORS.items() if m in stopped]}

    def set_target(self, joint: str, deg: float):
        m = MOTORS[joint]
        lo, hi = self.ranges[joint]
        steps = min(max(self.rest[m] + round(deg * STEPS_PER_REV / 360), lo), hi)
        with self._bus():
            self._require_torque()
            self.bus.write(m, GOAL_POSITION, steps)
            self.targets[m] = steps
            self.last_command = time.time()
            self.blocked.discard(m)
            self.stuck_since.pop(m, None)

    def set_targets(self, targets_deg: dict[str, float]):
        """Several joints at once (e.g. one per finger), clamped to their ranges and sent in a
        single sync packet so they all move together."""
        steps = {}
        for joint, deg in targets_deg.items():
            m = MOTORS[joint]
            lo, hi = self.ranges[joint]
            steps[m] = min(max(self.rest[m] + round(float(deg) * STEPS_PER_REV / 360), lo), hi)
        with self._bus():
            self._require_torque()
            self.bus.sync_write(GOAL_POSITION, steps)
            self.targets.update(steps)
            self.last_command = time.time()
            for m in steps:
                self.blocked.discard(m)
                self.stuck_since.pop(m, None)

    # ---- Named places ("vaso", "mesa", "entrega"): taught once by a caregiver, used by voice ----
    @staticmethod
    def poses() -> dict:
        try:
            return json.loads(POSES_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _pose_name(name: str) -> str:
        name = " ".join(str(name).lower().split())
        if not name or len(name) > 40:
            raise ValueError("place name must be 1-40 characters")
        return name

    def save_pose(self, name: str) -> dict:
        """Stores where the arm is right now (absolute steps), whether it was placed by hand or by voice."""
        name = self._pose_name(name)
        with self._bus():
            pos = self.bus.positions(MOTORS.values())
        poses = self.poses()
        poses[name] = {joint: pos[m] for joint, m in MOTORS.items()}
        tmp = POSES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(poses, indent=2))
        tmp.replace(POSES_FILE)  # atomic: a crash mid-write can't corrupt the saved places
        return poses

    def delete_pose(self, name: str) -> dict:
        poses = self.poses()
        poses.pop(self._pose_name(name), None)
        POSES_FILE.write_text(json.dumps(poses, indent=2))
        return poses

    # Wrist-camera grasping ("look -> align -> reach"): a search pose to look from, and examples
    # of "after centering the cup, it sat this high in the image (v)" + "the grasp pose there".
    @staticmethod
    def vision() -> dict:
        try:
            data = json.loads(VISION_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        return {"search": data.get("search"), "examples": data.get("examples", [])}

    @staticmethod
    def save_vision(calib: dict) -> dict:
        search, examples = calib.get("search"), calib.get("examples", [])
        if search is not None and set(search) != set(MOTORS):
            raise ValueError("bad search pose")
        for e in examples:
            if not 0 <= float(e["v"]) <= 1 or set(e["pose"]) != set(MOTORS):
                raise ValueError("bad calibration example")
            float(e["dpan"])
        data = {"search": search, "examples": examples}
        tmp = VISION_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(VISION_FILE)
        return data

    def release_here(self):
        """Torque off WITHOUT going back to the base first: for teaching by hand. The page warns
        the person to hold the arm before calling this, because a raised arm will fall."""
        with self._bus():
            self.bus.release(MOTORS.values())
            self.torque = False

    @staticmethod
    def save_snapshot(jpeg_b64: str):
        data = base64.b64decode(jpeg_b64.split(",")[-1], validate=True)  # accepts a data: URL too
        if not data.startswith(b"\xff\xd8") or len(data) > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot must be a JPEG under 2 MB")
        tmp = SNAPSHOT_FILE.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(SNAPSHOT_FILE)

    def post_command(self, body: dict) -> dict:
        text, event = str(body.get("text", "")).strip()[:300], body.get("event")
        if not text and event != "help_gesture":
            raise ValueError("need 'text' or event 'help_gesture'")
        with self.inbox_lock:
            self.inbox.append({"text": text, "event": event, "source": str(body.get("source", "external"))[:40],
                               "at": time.time()})
        print(f"[{time.strftime('%H:%M:%S')}] inbox <- {body.get('source', 'external')}: {text or event}", flush=True)
        return {"queued": len(self.inbox)}

    def take_inbox(self) -> list:
        with self.inbox_lock:
            items = [i for i in self.inbox if time.time() - i["at"] < 30]  # stale commands are dropped
            self.inbox.clear()
        return items

    def set_speed(self, speed: int):
        with self._bus():
            self.speed = min(max(int(speed), 50), 1000)
            if self.torque:
                self.bus.set_speed(MOTORS.values(), self.speed)


class Handler(BaseHTTPRequestHandler):
    arm: Arm

    def _trusted(self, post: bool) -> bool:
        """Only this page may drive the arm. Blocks other websites open in the browser
        (cross-site requests) and DNS rebinding."""
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return False
        # Requiring JSON forces a CORS preflight for cross-site POSTs, which this server never grants.
        return not post or self.headers.get("Content-Type", "").startswith("application/json")

    def do_GET(self):
        if not self._trusted(post=False):
            return self._send(403, b"forbidden", "text/plain")
        if self.path == "/":
            self._send(200, PAGE_FILE.read_bytes(), "text/html; charset=utf-8")  # re-read: UI edits need only a reload
        elif self.path == "/api/state":
            self._json(lambda: self.arm.state())
        elif self.path == "/api/poses":
            self._json(lambda: self.arm.poses())
        elif self.path == "/api/vision":
            self._json(lambda: self.arm.vision())
        elif self.path.startswith("/vendor/"):
            self._send_vendor(self.path.removeprefix("/vendor/").split("?")[0])
        else:
            self._send(404, b"not found", "text/plain")

    def _send_vendor(self, rel: str):
        file = (VENDOR_DIR / rel).resolve()
        if not file.is_relative_to(VENDOR_DIR) or not file.is_file() or file.suffix not in CONTENT_TYPES:
            return self._send(404, b"not found", "text/plain")
        self._send(200, file.read_bytes(), CONTENT_TYPES[file.suffix])

    def do_POST(self):
        if not self._trusted(post=True):
            return self._send(403, b"forbidden", "text/plain")
        length = int(self.headers.get("Content-Length", 0))
        if length > 3_000_000:  # a camera snapshot is the largest legitimate body
            return self._send(413, b"request too large", "text/plain")
        body = json.loads(self.rfile.read(length) or b"{}")
        actions = {
            "/api/torque": lambda: self.arm.enable() if body["on"] else self.arm.rest_and_release(),
            "/api/ready": lambda: self.arm.go_ready(),
            "/api/target": lambda: self.arm.set_target(body["joint"], float(body["deg"])),
            "/api/targets": lambda: self.arm.set_targets(body["targets"]),
            "/api/poses/save": lambda: self.arm.save_pose(body["name"]),
            "/api/poses/delete": lambda: self.arm.delete_pose(body["name"]),
            "/api/vision": lambda: self.arm.save_vision(body),
            "/api/release_here": lambda: self.arm.release_here(),
            "/api/command": lambda: self.arm.post_command(body),
            "/api/inbox": lambda: self.arm.take_inbox(),
            "/api/snapshot": lambda: self.arm.save_snapshot(body["jpeg"]),
            # The page reports what voice/commands are doing, so it can be followed from the terminal.
            "/api/log": lambda: print(f"[{time.strftime('%H:%M:%S')}] page: {str(body.get('msg'))[:300]}", flush=True),
            "/api/speed": lambda: self.arm.set_speed(body["value"]),
        }
        if self.path not in actions:
            return self._send(404, b"not found", "text/plain")
        # `is None`, not `or`: an empty dict (e.g. no places left) is a real answer, not a missing one.
        self._json(lambda: {"ok": True} if (result := actions[self.path]()) is None else result)

    def _json(self, fn):
        try:
            self._send(200, json.dumps(fn()).encode(), "application/json")
        except Busy as e:
            self._send(409, json.dumps({"error": str(e)}).encode(), "application/json")
        except Exception as e:  # report bus/validation errors to the page instead of crashing
            self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the terminal quiet


def main():
    arm = Arm()
    Handler.arm = arm
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Resting pose captured: {arm.rest}")
    print(f"Panel running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nreturning to rest and releasing torque...")
        try:
            arm.rest_and_release(wait=120)
            arm.bus.close()
        except Exception as e:
            print(f"WARNING: {e}\nTorque may still be ON: support the arm before touching it.")


if __name__ == "__main__":
    main()
