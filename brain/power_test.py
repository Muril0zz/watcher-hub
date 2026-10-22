"""Power-supply check: lift the shoulder gently while logging the servo supply voltage at 20 Hz.

If the supply is too small the voltage sags and the servos reboot (torque drops to 0) mid-move.
Usage: python power_test.py [target_deg] [speed] [torque_limit] [joint]
"""
import sys
import threading
import time

from arm import ADDR_POSITION, ADDR_TORQUE_ENABLE, ADDR_TORQUE_LIMIT, ADDR_VOLTAGE, JOINTS, Arm

target = float(sys.argv[1]) if len(sys.argv) > 1 else -40
speed = int(sys.argv[2]) if len(sys.argv) > 2 else 120
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 550
joint = sys.argv[4] if len(sys.argv) > 4 else "shoulder_lift"

arm = Arm()
print("start", arm.degrees())
log, stop = [], threading.Event()
t0 = time.time()


def watch():
    while not stop.is_set():
        try:
            log.append((round(time.time() - t0, 2), arm._r1(JOINTS[joint], ADDR_VOLTAGE) / 10,
                        arm._r2(JOINTS[joint], ADDR_POSITION), arm._r1(JOINTS[joint], ADDR_TORQUE_ENABLE)))
        except Exception as e:
            log.append((round(time.time() - t0, 2), "ERR", str(e)[:40]))
        time.sleep(0.05)


th = threading.Thread(target=watch)
th.start()
try:
    arm.set_speed(speed)
    arm.enable()
    for j in ("shoulder_lift", "elbow_flex"):
        arm._w2(JOINTS[j], ADDR_TORQUE_LIMIT, limit)
    arm.move_deg({joint: target}, timeout=12)
    time.sleep(1)
except Exception as e:
    print("ERROR", e)
stop.set()
th.join()
volts = [x[1] for x in log if x[1] != "ERR"]
print("samples", len(log), "volt min", min(volts, default=None), "max", max(volts, default=None),
      "errors", sum(1 for x in log if x[1] == "ERR"))
for x in log[::5]:
    print(x)
try:
    print("end", arm.degrees(), "torque on:", arm.torque_still_on())
except Exception as e:
    print("end read failed", e)
