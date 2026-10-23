"""From the side-grab pose with the cup between the jaws: grip it gently, lift it up high (level, so it
stays upright), put it back where it was, open, undo the wrist turn and raise the arm.
Usage: python white_cup_demo.py"""
import math
import time

from arm import Arm, ArmError, Contact
from executor import LIFT_Z, L1, L2, Executor

robot = Arm()
ex = Executor(robot, camera=None)


def step(name):
    d = robot.degrees()
    print(f"{name:22} " + "  ".join(f"{j.split('_')[0][:5]}:{v:6.1f}" for j, v in d.items()), flush=True)


def wrist_xz():
    d = robot.degrees()
    s, e = math.radians(d["shoulder_lift"]), math.radians(d["elbow_flex"])
    return (L1 * math.sin(s) + L2 * math.sin(s + math.pi / 2 - e),
            L1 * math.cos(s) + L2 * math.cos(s + math.pi / 2 - e))


robot.set_speed(150)
try:
    robot.enable()
    x0, z0 = wrist_xz()
    step(f"start x={x0:.3f} z={z0:.3f}")
    robot.move_deg({"gripper": 100}, timeout=3)  # let the crushed rim spring back; the cup stays standing
    time.sleep(0.5)
    if not robot.grip():
        step("grip: nothing between the jaws")
        raise SystemExit
    step("gripped gently")
    ex._level_to(x0, z0 + 0.05, steps=2)  # off the table
    ex._level_to(min(x0, 0.12), LIFT_Z, steps=3)  # all the way up, level
    step("lifted up")
    time.sleep(2.0)
    ex._level_to(x0, z0 + 0.05, steps=3)  # back to where it was
    ex._level_to(x0, z0)
    step("put back")
    robot.move_deg({"gripper": 100}, timeout=3)
    step("opened")
    while abs(robot.degrees()["wrist_roll"]) > 2:  # undo the turn in 10 deg steps, back to the middle
        r = robot.degrees()["wrist_roll"]
        robot.move_deg({"wrist_roll": r - math.copysign(min(10, abs(r)), r)}, timeout=3)
        if not robot.torque_still_on():
            raise ArmError("wrist servo dropped out")
    step("wrist turned back")
    ex._level_to(x0, z0 + 0.12, steps=2)  # straight up, out of the cup
    ex._level_to(0.12, LIFT_Z, steps=2)
    ex.go_pose("up")
    step("arm raised")
except Contact as c:
    step(f"CONTACT {c}")
except ArmError as e:
    print("ERROR:", e, flush=True)
