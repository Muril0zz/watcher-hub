"""Give the whole 12 V / 2 A supply to the elbow: every other joint limp, the elbow alone at full
torque, raising the forearm (decreasing steps) slowly in small increments.
Usage: python elbow_solo.py [degrees]
"""
import sys
import time

import arm as arm_mod
from arm import ADDR_ACCEL, ADDR_GOAL, ADDR_POSITION, ADDR_SPEED, ADDR_TORQUE_ENABLE, ADDR_TORQUE_LIMIT, ADDR_VOLTAGE, JOINTS, ArmError

DEGREES = float(sys.argv[1]) if len(sys.argv) > 1 else 60
arm_mod.DISABLED.clear()
a = arm_mod.Arm()
a.release()  # everyone limp
e = JOINTS["elbow_flex"]
start = a._r2(e, ADDR_POSITION)
target = start - round(DEGREES * 4096 / 360)
a._w2(e, ADDR_GOAL, start)
a._w1(e, ADDR_ACCEL, 2)
a._w2(e, ADDR_SPEED, 100)
a._w2(e, ADDR_TORQUE_LIMIT, 1000)
a._w1(e, ADDR_TORQUE_ENABLE, 1)
print(f"elbow alone {start} -> {target}", flush=True)
goal, t0 = start, time.time()
try:
    while time.time() - t0 < 30:
        pos = a._r2(e, ADDR_POSITION)
        v = a._r1(e, ADDR_VOLTAGE) / 10
        print(f"  t={time.time() - t0:4.1f}s pos {pos} goal {goal} volt {v}", flush=True)
        if abs(pos - target) < 20:
            break
        if abs(pos - goal) < 30:
            goal = max(target, goal - 20)
            a._w2(e, ADDR_GOAL, goal)
        time.sleep(0.15)
except ArmError as ex:
    print("supply dropped:", ex)
try:
    pos = a._r2(e, ADDR_POSITION)
    print(f"elbow moved {(start - pos) * 360 / 4096:.0f} deg up (pos {pos})")
except ArmError as ex:
    print("final read failed:", ex)
