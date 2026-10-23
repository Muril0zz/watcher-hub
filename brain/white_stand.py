"""Stand the (new) white arm straight up, one joint at a time, and keep holding it there.

Staged so nothing swings into the base or the table from the folded rest pose: unfold the elbow to
90 deg, bring the shoulder to vertical, straighten the elbow, then the wrist. Uses each servo's own
EEPROM limits (this arm came calibrated), not limits.json from the old arm. Usage:
    python white_stand.py [/dev/tty.usbmodemXXXX]
"""
import os
import sys

os.environ.setdefault("BRAIN_DISABLED_JOINTS", "")  # the new arm's elbow is healthy

import arm as A  # noqa: E402

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem5B7A0010951"
robot = A.Arm(port)
for j, i in A.JOINTS.items():  # this arm's own limits, kept 40 steps (~3.5 deg) inside the stops
    lo, hi = robot._r2(i, 9), robot._r2(i, 11)
    A.RANGES[j] = (lo + 40, hi - 40)

# straight = elbow about 180 deg from folded; the folded end is the elbow's max limit on this arm
lo_e, hi_e = A.RANGES["elbow_flex"]
STRAIGHT = max(lo_e, hi_e + 40 - 2048)
# Lifting the shoulder with the forearm stretched out dipped the 12 V supply and rebooted every servo;
# keep the weight close to the shoulder axis: half-lift folded, open the elbow a bit, then the rest.
STAGES = [
    ("shoulder halfway, folded", {"shoulder_lift": A.deg_to_steps(-35, "shoulder_lift")}),
    ("open elbow a bit", {"elbow_flex": A.deg_to_steps(-30, "elbow_flex")}),
    ("shoulder to vertical", {"shoulder_lift": 2048}),
    ("straighten elbow", {"elbow_flex": STRAIGHT}),
    ("wrist straight", {"wrist_flex": 2048, "wrist_roll": 2048}),
]


def show(label):
    d = robot.degrees()
    print(f"{label:24} " + "  ".join(f"{j.split('_')[0][:5]}:{v:6.1f}" for j, v in d.items()), flush=True)


robot.set_speed(150)
robot.enable()
for i in (2, 3):  # softest start the servo allows on the two joints that lift weight
    robot._w1(i, A.ADDR_ACCEL, 2)
show("start")
try:
    for label, target in STAGES:
        robot.move_steps(target, timeout=10)
        show(label)
    print("standing straight, holding torque", flush=True)
except A.Contact as c:
    show("stopped")
    print(f"CONTACT: {c} - holding here", flush=True)
except A.ArmError as e:
    print(f"ERROR: {e}", flush=True)
