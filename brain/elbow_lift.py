"""Raise the forearm with the elbow (decreasing steps = up on this arm), slowly enough for the
12 V / 2 A supply: tiny goal increments, minimum acceleration, and whenever the supply sags below
SAG_V the goal is frozen at the current position until it recovers.
Usage: python elbow_lift.py [degrees]   (default 80)
"""
import sys
import time

import arm as arm_mod
from arm import ADDR_ACCEL, ADDR_GOAL, ADDR_POSITION, ADDR_SPEED, ADDR_TORQUE_LIMIT, ADDR_VOLTAGE, JOINTS, ArmError

DEGREES = float(sys.argv[1]) if len(sys.argv) > 1 else 80
SAG_V = 10.5
INCREMENT = 12  # steps per tick (~1 degree)
TICK = 0.08

arm_mod.DISABLED.clear()
a = arm_mod.Arm()
e = JOINTS["elbow_flex"]
a.set_speed(150)
a.enable()
a._w1(e, ADDR_ACCEL, 2)
a._w2(e, ADDR_SPEED, 120)
a._w2(e, ADDR_TORQUE_LIMIT, 700)
start = a._r2(e, ADDR_POSITION)
target = start - round(DEGREES * 4096 / 360)
goal = start
pauses, min_v = 0, 99.0
print(f"elbow {start} -> {target}", flush=True)
t0 = time.time()
try:
    while time.time() - t0 < 40:
        v = a._r1(e, ADDR_VOLTAGE) / 10
        pos = a._r2(e, ADDR_POSITION)
        min_v = min(min_v, v)
        if v < SAG_V:
            goal = pos  # stop asking for more until the supply recovers
            a._w2(e, ADDR_GOAL, goal)
            pauses += 1
            time.sleep(0.3)
            continue
        if goal > target and abs(pos - goal) < 40:
            goal = max(target, goal - INCREMENT)
            a._w2(e, ADDR_GOAL, goal)
        if goal == target and abs(pos - target) < 20:
            break
        if int((time.time() - t0) * 10) % 10 == 0:
            print(f"  t={time.time() - t0:4.1f}s pos {pos} goal {goal} volt {v}", flush=True)
        time.sleep(TICK)
except ArmError as ex:
    print("supply dropped:", ex)
try:
    pos = a._r2(e, ADDR_POSITION)
    print(f"done: elbow {start} -> {pos} ({(start - pos) * 360 / 4096:.0f} deg up), min volt {min_v}, pauses {pauses}")
except ArmError as ex:
    print("final read failed:", ex, "min volt", min_v)
