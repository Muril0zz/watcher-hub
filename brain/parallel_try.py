"""Try to hold the whole arm straight and parallel to the table, in stages, stopping at the first
problem: shoulder vertical -> forearm straightened in line (pointing up, light) -> lean forward
15 degrees at a time toward horizontal. Wrist-camera photo after each stage.
"""
import os

import cv2

import arm as arm_mod
from arm import ArmError

OUT = os.path.expanduser("~/.claude/jobs/1c0fc05f/tmp")
arm_mod.DISABLED.clear()  # this needs the elbow
a = arm_mod.Arm()
cam = cv2.VideoCapture(0)


def snap(name):
    for _ in range(6):
        ok, f = cam.read()
    if ok:
        cv2.imwrite(f"{OUT}/{name}.jpg", cv2.resize(f, (480, 270)))


def stage(label, target, timeout=10):
    a.move_deg(target, timeout=timeout)
    d = a.degrees()
    print(f"{label:28} " + " ".join(f"{k[:8]} {v:7.1f}" for k, v in d.items()), flush=True)
    snap(label.replace(" ", "_"))


a.set_speed(250)
a.enable()
reached = "start"
try:
    stage("shoulder vertical", {"shoulder_lift": 0, "wrist_flex": 0})
    reached = "shoulder vertical"
    stage("forearm straight up", {"elbow_flex": 85})
    reached = "arm straight up"
    for lean in (15, 30, 45, 60, 75, 90):
        stage(f"lean {lean}", {"shoulder_lift": lean})
        reached = f"leaning {lean} deg (90 = parallel to the table)"
    print("PARALLEL reached")
except ArmError as e:
    print(f"stopped: {e}")
print("furthest:", reached)
