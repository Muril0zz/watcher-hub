"""Drive the elbow the OTHER way (decreasing steps) in ~9 degree nudges, with the contact guard on,
to check whether the 'faulty elbow' was really just being pushed into its own hard stop.
"""
import os

import cv2

import arm as arm_mod
from arm import ArmError, Contact

OUT = os.path.expanduser("~/.claude/jobs/1c0fc05f/tmp")
arm_mod.DISABLED.clear()
arm_mod.RANGES["elbow_flex"] = (0, 3038)  # the generic table assumed the other direction
a = arm_mod.Arm()
cam = cv2.VideoCapture(0)


def snap(name):
    for _ in range(6):
        ok, f = cam.read()
    if ok:
        cv2.imwrite(f"{OUT}/{name}.jpg", cv2.resize(f, (480, 270)))


a.set_speed(250)
a.enable()
start = a.positions()["elbow_flex"]
print("elbow start steps", start, "deg", a.degrees()["elbow_flex"], flush=True)
for i in range(1, 13):
    try:
        a.move_steps({"elbow_flex": start - 100 * i}, timeout=6)
    except Contact as e:
        print("contact:", e)
        break
    except ArmError as e:
        print("error:", e)
        break
    p = a.positions()["elbow_flex"]
    h = a.health()["elbow_flex"]
    print(f"nudge {i:2d}: goal {start - 100 * i}  now {p}  ({a.degrees()['elbow_flex']:.1f} deg)  "
          f"{h['volt']} V  {h['temp']} C", flush=True)
    snap(f"rev{i:02d}")
    if abs(p - (start - 100 * i)) > 60:
        print("not following the goal: stopping")
        break
print("final", a.degrees())
