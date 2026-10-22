"""Show the arm moving with every joint except the elbow (its servo pulls the 12 V supply down).

The elbow is held where it is; base, shoulder, wrist pitch, wrist roll and gripper move gently.
"""
import time

from arm import ADDR_TORQUE_LIMIT, JOINTS, Arm, ArmError

arm = Arm()
start = arm.degrees()
print("start", start)
arm.set_speed(500)
try:
    arm.enable()
    arm._w2(JOINTS["shoulder_lift"], ADDR_TORQUE_LIMIT, 600)
    steps = [
        ("base left", {"shoulder_pan": start["shoulder_pan"] + 35}),
        ("base right", {"shoulder_pan": start["shoulder_pan"] - 35}),
        ("base center", {"shoulder_pan": start["shoulder_pan"]}),
        ("shoulder up", {"shoulder_lift": start["shoulder_lift"] + 20}),
        ("wrist up", {"wrist_flex": start["wrist_flex"] + 35}),
        ("wrist down", {"wrist_flex": start["wrist_flex"] - 35}),
        ("wrist center", {"wrist_flex": start["wrist_flex"]}),
        ("spin wrist", {"wrist_roll": start["wrist_roll"] + 90}),
        ("spin back", {"wrist_roll": start["wrist_roll"] - 60}),
        ("wrist roll center", {"wrist_roll": start["wrist_roll"]}),
        ("open gripper", {"gripper": 100}),
        ("close gripper", {"gripper": 0}),
        ("open gripper", {"gripper": 100}),
        ("close gripper", {"gripper": 0}),
        ("shoulder back", {"shoulder_lift": start["shoulder_lift"]}),
    ]
    for label, target in steps:
        arm.move_deg(target, timeout=6)
        now = arm.degrees()
        print(f"{label:18} " + " ".join(f"{k[:6]} {v:6.1f}" for k, v in now.items()), flush=True)
    print("done, holding pose")
except ArmError as e:
    print("ERROR", e)
