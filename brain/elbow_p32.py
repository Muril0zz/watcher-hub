"""Is the elbow healthy but just too weak at P=16? Wait for it to cool, power only the elbow
(the whole supply for it), raise its P gain to 32 (factory default), then lift the forearm in
small steps logging position, load, voltage and temperature.

The servos' own overload protection (load > 80 % for ~2 s -> output capped at 20 %) is what made it
look dead earlier, so each step is short and it backs off if the load stays very high.
"""
import time

import arm as arm_mod
from arm import ADDR_GOAL, ADDR_LOAD, ADDR_POSITION, ADDR_SPEED, ADDR_TEMP, ADDR_TORQUE_ENABLE, ADDR_TORQUE_LIMIT, ADDR_VOLTAGE, JOINTS, ArmError

ADDR_P, ADDR_LOCK = 21, 55
arm_mod.DISABLED.clear()
a = arm_mod.Arm()
e = JOINTS["elbow_flex"]

while (t := a._r1(e, ADDR_TEMP)) > 45:
    print(f"cooling: elbow {t} C", flush=True)
    time.sleep(10)

a.release()
a._w1(e, ADDR_LOCK, 0)
a._w1(e, ADDR_P, 32)
a._w1(e, ADDR_LOCK, 1)
start = a._r2(e, ADDR_POSITION)
a._w2(e, ADDR_GOAL, start)
a._w2(e, ADDR_SPEED, 150)
a._w2(e, ADDR_TORQUE_LIMIT, 1000)
a._w1(e, ADDR_TORQUE_ENABLE, 1)
print(f"elbow alone, P=32, start {start}", flush=True)
goal, best = start, start
try:
    for step in range(40):  # up to ~35 degrees, 0.9 deg per step
        goal -= 10
        a._w2(e, ADDR_GOAL, goal)
        time.sleep(0.25)
        pos, load = a._r2(e, ADDR_POSITION), a._r2(e, ADDR_LOAD) & 0x3FF
        v, t = a._r1(e, ADDR_VOLTAGE) / 10, a._r1(e, ADDR_TEMP)
        best = min(best, pos)
        print(f"step {step:2d}: goal {goal} pos {pos} load {load / 10:5.1f}% volt {v} temp {t}", flush=True)
        if goal - pos < -60 and load > 750:  # straining hard and falling behind: stop before protection
            print("straining and not keeping up: stop")
            break
except ArmError as ex:
    print("supply dropped:", ex)
try:
    a._w2(e, ADDR_GOAL, a._r2(e, ADDR_POSITION))
    print(f"result: forearm raised {(start - best) * 360 / 4096:.0f} degrees")
except ArmError as ex:
    print("final read failed:", ex)
