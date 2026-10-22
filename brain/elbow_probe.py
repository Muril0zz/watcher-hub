"""Is one servo (default: the elbow) pulling the 12 V supply down? Torque on that servo alone, hold,
then a tiny move, logging the supply voltage and the servo's load at each step.
Usage: python elbow_probe.py [motor_id] [torque_limit]
"""
import sys
import time

from arm import ADDR_GOAL, ADDR_LOAD, ADDR_POSITION, ADDR_SPEED, ADDR_TORQUE_ENABLE, ADDR_TORQUE_LIMIT, ADDR_VOLTAGE, Arm

motor = int(sys.argv[1]) if len(sys.argv) > 1 else 3
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 350
delta = int(sys.argv[3]) if len(sys.argv) > 3 else 35
arm = Arm()


def sample(label):
    try:
        print(f"{label:22} volt {arm._r1(motor, ADDR_VOLTAGE) / 10:4.1f}  pos {arm._r2(motor, ADDR_POSITION)}"
              f"  load {arm._r2(motor, ADDR_LOAD)}  torque {arm._r1(motor, ADDR_TORQUE_ENABLE)}", flush=True)
    except Exception as e:
        print(f"{label:22} READ FAILED ({e})", flush=True)
        raise SystemExit(1)


pos = arm._r2(motor, ADDR_POSITION)
sample("limp")
arm._w2(motor, ADDR_GOAL, pos)
arm._w2(motor, ADDR_SPEED, 100)
arm._w2(motor, ADDR_TORQUE_LIMIT, limit)
arm._w1(motor, ADDR_TORQUE_ENABLE, 1)
for i in range(5):
    time.sleep(0.2)
    sample(f"holding {i}")
arm._w2(motor, ADDR_GOAL, pos + delta)  # 35 steps ~ 3 degrees
for i in range(8):
    time.sleep(0.15)
    sample(f"tiny move {i}")
arm._w1(motor, ADDR_TORQUE_ENABLE, 0)
sample("released")
