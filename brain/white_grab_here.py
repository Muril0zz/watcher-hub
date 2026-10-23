"""Grab whatever is in front of the gripper right where the arm is: hold the pose, turn the wrist,
close, report whether it holds something. Usage: python white_grab_here.py [roll_degrees]"""
import sys
import time

from arm import Arm, ArmError

roll = float(sys.argv[1]) if len(sys.argv) > 1 else 90
robot = Arm()
print("pose now", robot.degrees(), flush=True)
robot.set_speed(300)
try:
    robot.enable()  # holds exactly where it is
    d = robot.degrees()
    robot.move_deg({"wrist_roll": d["wrist_roll"] + roll}, timeout=4)
    print("wrist turned", robot.degrees()["wrist_roll"], flush=True)
    robot.move_deg({"gripper": 0}, timeout=3)
    time.sleep(0.4)
    print("gripper", robot.degrees()["gripper"], "holding something:", robot.gripper_contact(), flush=True)
except ArmError as e:
    print("ERROR:", e)
