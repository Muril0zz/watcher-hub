"""Was the elbow really faulty, or was the gripper pressed into the table? Raise the shoulder so the
forearm is in the air (photo from the wrist camera), then nudge the elbow 3 degrees each way while
logging the 12 V supply and the elbow's load.
"""
import os
import time

import cv2

import arm as arm_mod
from arm import ADDR_GOAL, ADDR_LOAD, ADDR_POSITION, ADDR_SPEED, ADDR_TORQUE_ENABLE, ADDR_TORQUE_LIMIT, ADDR_VOLTAGE, JOINTS

OUT = os.path.expanduser("~/.claude/jobs/1c0fc05f/tmp")
arm_mod.DISABLED.clear()  # this test drives the elbow on purpose
a = arm_mod.Arm()
cam = cv2.VideoCapture(0)


def snap(name):
    for _ in range(8):
        ok, f = cam.read()
    cv2.imwrite(f"{OUT}/{name}.jpg", cv2.resize(f, (640, 360)))


def sample(label):
    e = JOINTS["elbow_flex"]
    print(f"{label:20} volt {a._r1(e, ADDR_VOLTAGE) / 10:4.1f}  elbow pos {a._r2(e, ADDR_POSITION)}"
          f"  load {a._r2(e, ADDR_LOAD) & 0x3FF}  torque {a._r1(e, ADDR_TORQUE_ENABLE)}", flush=True)


print("start", a.degrees())
snap("air0")
a.set_speed(300)
a.enable()
a.move_deg({"shoulder_lift": 0}, timeout=10)
print("shoulder raised", a.degrees())
snap("air1")
sample("holding")
e = JOINTS["elbow_flex"]
pos = a._r2(e, ADDR_POSITION)
a._w2(e, ADDR_SPEED, 100)
a._w2(e, ADDR_TORQUE_LIMIT, 450)
for delta in (35, 0, -35, 0):
    a._w2(e, ADDR_GOAL, pos + delta)
    for i in range(4):
        time.sleep(0.15)
        try:
            sample(f"elbow {delta:+d} #{i}")
        except Exception as ex:
            print("READ FAILED -> supply collapsed:", ex)
            raise SystemExit(1)
print("elbow OK in the air")
snap("air2")
