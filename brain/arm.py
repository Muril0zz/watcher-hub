"""SO-101 follower (white, 12 V) driven directly over the Feetech bus, in degrees.

Angles: 0 deg = step 2048, the middle of each joint's travel with the factory homing that is
already in the servos' EEPROM (nothing here rewrites it, so arm/panel.py keeps working).
The servos run their own speed/acceleration profile; this class sets goals, then watches for
arrival, stalls, heat and power drops.
"""
import json
import os
import threading
import time

from pathlib import Path

import scservo_sdk as scs

PORT = "/dev/tty.usbmodem5B901033751"
BAUD = 1_000_000
JOINTS = {"shoulder_pan": 1, "shoulder_lift": 2, "elbow_flex": 3, "wrist_flex": 4, "wrist_roll": 5, "gripper": 6}

# Safe absolute range per joint in steps (official SO-101 model minus a 10 deg margin, as in arm/panel.py)
RANGES = {
    "shoulder_pan": (910, 3186),
    "shoulder_lift": (850, 3072),
    "elbow_flex": (897, 3038),
    "wrist_flex": (1081, 3015),
    "wrist_roll": (341, 3755),
    "gripper": (2046, 3094),  # closed .. open
}
# Measured on this arm by autocal.py (creeps to each stop / the table with little torque); overrides the
# generic table above for every joint it measured.
LIMITS_FILE = Path(__file__).with_name("limits.json")
if LIMITS_FILE.exists():
    RANGES.update({j: tuple(v) for j, v in json.loads(LIMITS_FILE.read_text()).items()})

# x0.1 %, RAM (reset on power cycle). Kept low on purpose: pushing into the table (it sits right under the
# arm) at full torque stalls a servo, and a stalled servo pulls more than the 12 V / 2 A supply can give.
TORQUE_LIMITS = {"shoulder_pan": 500, "shoulder_lift": 650, "elbow_flex": 550, "wrist_flex": 450,
                 "wrist_roll": 400, "gripper": 400}
CONTACT_FRACTION = 0.8  # load at this fraction of the joint's torque limit = touching something
BACK_OFF_STEPS = 70  # ~6 degrees away from whatever it touched
# Joints kept limp and never commanded. The white arm's elbow servo (id 3) pulls the 12 V supply down to
# ~5 V whenever it produces torque, even 3 degrees at 35% (brain/elbow_probe.py); until it is replaced
# the forearm hangs free. Set BRAIN_DISABLED_JOINTS="" once a healthy servo is fitted.
DISABLED = {j for j in os.environ.get("BRAIN_DISABLED_JOINTS", "elbow_flex").split(",") if j}
HOT_C = 60

ADDR_TORQUE_ENABLE, ADDR_ACCEL, ADDR_GOAL, ADDR_SPEED, ADDR_TORQUE_LIMIT = 40, 41, 42, 46, 48
ADDR_POSITION, ADDR_LOAD, ADDR_VOLTAGE, ADDR_TEMP, ADDR_MOVING = 56, 60, 62, 63, 66

STEPS_PER_DEG = 4096 / 360


def deg_to_steps(deg: float) -> int:
    return round(2048 + deg * STEPS_PER_DEG)


def steps_to_deg(steps: int) -> float:
    return (steps - 2048) / STEPS_PER_DEG


class ArmError(Exception):
    pass


class Contact(ArmError):
    """A joint pushed into something (the table, an object, a person) and the arm backed off."""

    def __init__(self, joint: str):
        super().__init__(f"{joint} touched something and backed off")
        self.joint = joint


class Arm:
    def __init__(self, port: str = PORT):
        self.lock = threading.RLock()
        self.port = scs.PortHandler(port)
        self.pk = scs.PacketHandler(0)
        if not self.port.openPort() or not self.port.setBaudRate(BAUD):
            raise ArmError(f"could not open {port}")
        missing = [j for j, i in JOINTS.items()
                   if j not in DISABLED and self.pk.ping(self.port, i)[1] != scs.COMM_SUCCESS]
        self.last_pos: dict[str, int] = {}
        if missing:
            raise ArmError(f"motors not answering: {missing} (12 V supply on?)")
        self.speed = 600  # steps/s
        self.torque = False
        self.stop_flag = threading.Event()
        self.rest = self.positions()  # wherever it is at start-up is "rest" (start it folded)

    # ---- low level ----------------------------------------------------------------------
    def _r1(self, motor_id, addr):
        with self.lock:
            for _ in range(3):
                v, res, _err = self.pk.read1ByteTxRx(self.port, motor_id, addr)
                if res == scs.COMM_SUCCESS:
                    return v
        raise ArmError(f"read {addr} from motor {motor_id} failed")

    def _r2(self, motor_id, addr):
        with self.lock:
            for _ in range(3):
                v, res, _err = self.pk.read2ByteTxRx(self.port, motor_id, addr)
                if res == scs.COMM_SUCCESS:
                    return v
        raise ArmError(f"read {addr} from motor {motor_id} failed")

    def _w1(self, motor_id, addr, value):
        with self.lock:
            for _ in range(3):
                if self.pk.write1ByteTxRx(self.port, motor_id, addr, value)[0] == scs.COMM_SUCCESS:
                    return
        raise ArmError(f"write {addr} to motor {motor_id} failed")

    def _w2(self, motor_id, addr, value):
        with self.lock:
            for _ in range(3):
                if self.pk.write2ByteTxRx(self.port, motor_id, addr, value)[0] == scs.COMM_SUCCESS:
                    return
        raise ArmError(f"write {addr} to motor {motor_id} failed")

    def positions(self) -> dict[str, int]:
        out = {}
        for j, i in JOINTS.items():
            try:
                out[j] = self.last_pos[j] = self._r2(i, ADDR_POSITION)
            except ArmError:
                if j not in DISABLED:
                    raise
                out[j] = self.last_pos.get(j, 2048)  # out-of-service joint dropped off the bus: last known
        return out

    def degrees(self) -> dict[str, float]:
        pos = self.positions()
        out = {j: round(steps_to_deg(s), 1) for j, s in pos.items() if j != "gripper"}
        lo, hi = RANGES["gripper"]
        out["gripper"] = round(100 * (pos["gripper"] - lo) / (hi - lo))
        return out

    def health(self) -> dict:
        return {j: {"temp": self._r1(i, ADDR_TEMP), "volt": self._r1(i, ADDR_VOLTAGE) / 10}
                for j, i in JOINTS.items() if j not in DISABLED}

    # ---- torque -------------------------------------------------------------------------
    def enable(self):
        """Torque on, holding the current pose (so nothing jumps). Disabled joints stay limp."""
        pos = self.positions()
        for j, i in JOINTS.items():
            if j in DISABLED:
                self._w1(i, ADDR_TORQUE_ENABLE, 0)
                continue
            self._w2(i, ADDR_GOAL, pos[j])
            self._w1(i, ADDR_ACCEL, 8)  # gentle starts: a hard start from the folded pose dips the 12 V supply
            self._w2(i, ADDR_SPEED, self.speed)
            self._w2(i, ADDR_TORQUE_LIMIT, TORQUE_LIMITS.get(j, 1000))
            self._w1(i, ADDR_TORQUE_ENABLE, 1)
        self.torque = True

    def release(self):
        for j, i in JOINTS.items():
            try:
                self._w1(i, ADDR_TORQUE_ENABLE, 0)
            except ArmError:
                if j not in DISABLED:
                    raise
        self.torque = False

    def torque_still_on(self) -> bool:
        """Servos reboot limp after a 12 V dip; detect it so the caller can stop the plan."""
        return any(self._r1(i, ADDR_TORQUE_ENABLE) for j, i in JOINTS.items() if j not in DISABLED)

    # ---- motion -------------------------------------------------------------------------
    def set_speed(self, steps_per_s: int):
        self.speed = max(100, min(2000, int(steps_per_s)))

    def move_steps(self, targets: dict[str, int], wait: bool = True, timeout: float = 8.0) -> dict[str, int]:
        if not self.torque:
            self.enable()
        self.stop_flag.clear()
        goals = {}
        for j, steps in targets.items():
            if j in DISABLED:
                continue
            lo, hi = RANGES[j]
            goals[j] = max(lo, min(hi, int(steps)))
            self._w2(JOINTS[j], ADDR_SPEED, self.speed)
            self._w2(JOINTS[j], ADDR_GOAL, goals[j])
        if wait:
            self._wait(goals, timeout)
        return goals

    def move_deg(self, targets: dict[str, float], wait: bool = True, timeout: float = 8.0):
        steps = {}
        for j, v in targets.items():
            if j == "gripper":
                lo, hi = RANGES["gripper"]
                steps[j] = lo + (hi - lo) * max(0.0, min(100.0, v)) / 100
            else:
                steps[j] = deg_to_steps(v)
        return self.move_steps(steps, wait, timeout)

    def stop(self):
        """Freeze where it is now."""
        self.stop_flag.set()
        pos = self.positions()
        for j, i in JOINTS.items():
            self._w2(i, ADDR_GOAL, pos[j])

    def _load(self, joint: str) -> int:
        """Effort the servo is putting out, 0..1000 (the register's bit 10 is only the direction)."""
        return self._r2(JOINTS[joint], ADDR_LOAD) & 0x3FF

    def _wait(self, goals: dict[str, int], timeout: float):
        start = time.time()
        origin = None
        last, still_since = None, None
        pushing = {j: 0 for j in goals}
        while time.time() - start < timeout:
            if self.stop_flag.is_set():
                return
            time.sleep(0.05)
            pos = {j: self._r2(JOINTS[j], ADDR_POSITION) for j in goals}
            origin = origin or pos
            if all(abs(pos[j] - goals[j]) <= 15 for j in goals):
                return
            for j in goals:
                if j == "gripper" or abs(pos[j] - goals[j]) <= 15:
                    continue  # the gripper is meant to squeeze things
                # straining AND not moving = blocked; straining while moving is just lifting the arm's weight
                stuck = last is not None and abs(pos[j] - last[j]) < 3
                hard = stuck and self._load(j) >= CONTACT_FRACTION * TORQUE_LIMITS.get(j, 1000)
                pushing[j] = pushing[j] + 1 if hard else 0
                if pushing[j] >= 2:  # two samples in a row: really touching, not a jerk
                    away = -1 if goals[j] > origin[j] else 1
                    hold = {k: pos[k] for k in goals}
                    hold[j] = pos[j] + away * BACK_OFF_STEPS
                    self.move_steps(hold, wait=False)
                    time.sleep(0.4)
                    raise Contact(j)
            if last is not None and all(abs(pos[j] - last[j]) < 3 for j in goals):
                still_since = still_since or time.time()
                if time.time() - still_since > 0.8:  # blocked (holding an object, hit something)
                    self.move_steps(pos, wait=False)  # stop pushing: hold where it got to
                    return
            else:
                still_since = None
            last = pos
        if not self.torque_still_on():
            self.torque = False
            raise ArmError("power drop: the motors rebooted (check the 12 V supply)")

    def gripper_contact(self) -> bool:
        """True when the gripper stopped short of closing (it is holding something)."""
        return self._r2(JOINTS["gripper"], ADDR_POSITION) > RANGES["gripper"][0] + 60

    def too_hot(self) -> list[str]:
        return [j for j, i in JOINTS.items() if j not in DISABLED and self._r1(i, ADDR_TEMP) >= HOT_C]

    def close(self):
        self.port.closePort()
