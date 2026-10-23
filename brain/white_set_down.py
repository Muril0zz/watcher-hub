"""Set the held cup down right where the arm is (no base move), open, lift out, and print temperatures.
For when a routine stopped with the cup in the air (e.g. a motor too hot)."""
import time

from arm import JOINTS, Arm, ADDR_TEMP
from executor import CARRY_DZ, CUP_SPOT, PLACE_DZ, Executor

robot = Arm()
ex = Executor(robot, camera=None)
print("temps", {j: robot._r1(i, ADDR_TEMP) for j, i in JOINTS.items()}, flush=True)
robot.set_speed(150)
robot.enable()
x, z = CUP_SPOT
ex._level_to(x, z + PLACE_DZ, steps=2)
robot.move_deg({"gripper": 100}, timeout=3)
ex._level_to(x, z + CARRY_DZ, steps=2)
for r in (-60, -30, 0):
    robot.move_deg({"wrist_roll": r}, timeout=3)
time.sleep(0.5)
print("set down at base", robot.degrees()["shoulder_pan"], "temps",
      {j: robot._r1(i, ADDR_TEMP) for j, i in JOINTS.items()}, flush=True)
