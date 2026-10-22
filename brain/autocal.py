"""Find each joint's real limits on THIS arm by feel: creep toward each end with little torque until
the joint stops moving (hard stop, the table, the arm's own body), back off, and save the range with a
margin to limits.json, which arm.py then uses instead of the generic SO-101 table.

wrist_roll is skipped (no hard stop: forcing it only winds the cables) and disabled joints too.
Run with the arm in a normal pose and nothing in the way:  python autocal.py
"""
import json
import time
from pathlib import Path

import arm as arm_mod
from arm import ADDR_GOAL, ADDR_POSITION, ADDR_SPEED, ADDR_TORQUE_LIMIT, JOINTS, RANGES, ArmError

LIMITS_FILE = Path(__file__).with_name("limits.json")
PROBE_TORQUE = 300  # 30 %: enough to move, too little to hurt or brown out
STEP = 40  # ~3.5 degrees per nudge
MARGIN = 70  # ~6 degrees kept away from what it touched
OVERSHOOT = 230  # look up to ~20 degrees past the generic table before giving up
ORDER = ["gripper", "wrist_flex", "shoulder_pan", "shoulder_lift"]


def probe(a: arm_mod.Arm, joint: str, direction: int) -> tuple[int, bool]:
    """Creep one way; returns (last free position, touched something?)."""
    motor = JOINTS[joint]
    lo, hi = RANGES[joint]
    cap = (hi + OVERSHOOT) if direction > 0 else (lo - OVERSHOOT)
    cap = max(0, min(4095, cap))
    pos = a._r2(motor, ADDR_POSITION)
    while (pos < cap) if direction > 0 else (pos > cap):
        goal = pos + direction * STEP
        a._w2(motor, ADDR_GOAL, goal)
        time.sleep(0.35)
        new = a._r2(motor, ADDR_POSITION)
        if abs(new - pos) < STEP / 3:  # barely moved: something is in the way
            a._w2(motor, ADDR_GOAL, new - direction * MARGIN)
            time.sleep(0.4)
            return new, True
        pos = new
    return pos, False


def main():
    a = arm_mod.Arm()
    a.enable()
    found = json.loads(LIMITS_FILE.read_text()) if LIMITS_FILE.exists() else {}
    try:
        for joint in ORDER:
            if joint in arm_mod.DISABLED:
                continue
            motor = JOINTS[joint]
            start = a._r2(motor, ADDR_POSITION)
            a._w2(motor, ADDR_TORQUE_LIMIT, PROBE_TORQUE)
            a._w2(motor, ADDR_SPEED, 200)
            ends = {}
            for direction in (-1, 1):
                end, touched = probe(a, joint, direction)
                ends[direction] = (end, touched)
                a._w2(motor, ADDR_GOAL, start)  # back to the middle before trying the other way
                time.sleep(1.0)
            (lo_end, lo_touch), (hi_end, hi_touch) = ends[-1], ends[1]
            lo = lo_end + (MARGIN if lo_touch else 0)
            hi = hi_end - (MARGIN if hi_touch else 0)
            found[joint] = [lo, hi]
            print(f"{joint:14} {lo}..{hi}  (generic {RANGES[joint][0]}..{RANGES[joint][1]})"
                  f"  stops: low {'touched' if lo_touch else 'free'}, high {'touched' if hi_touch else 'free'}",
                  flush=True)
            a._w2(motor, ADDR_TORQUE_LIMIT, arm_mod.TORQUE_LIMITS.get(joint, 1000))
    except ArmError as e:
        print("stopped:", e)
    LIMITS_FILE.write_text(json.dumps(found, indent=2))
    print("saved", LIMITS_FILE)


if __name__ == "__main__":
    main()
