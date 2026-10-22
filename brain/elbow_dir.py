"""Elbow alone, after re-zeroing: nudge +-100 steps (~9 deg) each way, logging load/voltage and a
wrist photo per position, to see that it moves and which way is up."""
import os
import time

import cv2

import arm as arm_mod
from arm import ADDR_GOAL, ADDR_LOAD, ADDR_POSITION, ADDR_SPEED, ADDR_TORQUE_ENABLE, ADDR_TORQUE_LIMIT, ADDR_VOLTAGE, JOINTS, ArmError

OUT = os.path.expanduser("~/.claude/jobs/1c0fc05f/tmp")
arm_mod.DISABLED.clear()
a = arm_mod.Arm()
e = JOINTS["elbow_flex"]
cam = cv2.VideoCapture(0)


def snap(name):
    for _ in range(6):
        ok, f = cam.read()
    if ok:
        cv2.imwrite(f"{OUT}/{name}.jpg", cv2.resize(f, (480, 270)))


a.release()
start = a._r2(e, ADDR_POSITION)
a._w2(e, ADDR_GOAL, start)
a._w2(e, ADDR_SPEED, 200)
a._w2(e, ADDR_TORQUE_LIMIT, 700)
a._w1(e, ADDR_TORQUE_ENABLE, 1)
snap("dir_start")
try:
    for label, goal in (("plus100", start + 100), ("back", start), ("minus100", start - 100), ("back2", start)):
        a._w2(e, ADDR_GOAL, goal)
        time.sleep(1.2)
        pos, load, v = a._r2(e, ADDR_POSITION), a._r2(e, ADDR_LOAD) & 0x3FF, a._r1(e, ADDR_VOLTAGE) / 10
        print(f"{label:9} goal {goal} pos {pos} load {load / 10:.1f}% volt {v}", flush=True)
        snap(f"dir_{label}")
    print("elbow moves both ways")
except ArmError as ex:
    print("supply dropped:", ex)
