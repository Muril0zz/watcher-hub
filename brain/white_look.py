"""Put the white arm in a pose and save what the wrist camera sees (checks the camera points where the
pose says). Usage: python white_look.py [pose] [out.jpg]   (pose from executor.py, default look_table)"""
import sys
import time

import vision
from arm import Arm, ArmError, Contact
from executor import Executor

pose = sys.argv[1] if len(sys.argv) > 1 else "look_table"
out = sys.argv[2] if len(sys.argv) > 2 else "look.jpg"
camera = vision.Camera()
robot = Arm()
ex = Executor(robot, camera)
try:
    ex.go_pose(pose)
except (Contact, ArmError) as e:
    print("stopped:", e)
print("joints", robot.degrees(), flush=True)
time.sleep(1.0)
data = camera.jpeg(size=(640, 360), quality=80)
open(out, "wb").write(data or b"")
print("saved", out, len(data or b""), "bytes")
