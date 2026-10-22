"""Presentation routine for the black arm: point at the sky, spin, wave, open/close the gripper, bow.

Keyframes are joint angles in degrees (0 = calibrated middle; elbow_flex negative = forearm up),
gripper in 0-100. Every keyframe is reached with an eased glide.
Usage: python show.py PORT ID
"""
import sys
import time

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
HZ = 30

SKY = {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": -95, "wrist_flex": 0, "wrist_roll": 0, "gripper": 50}

# (label, changes from the previous keyframe, seconds)
ROUTINE = [
    ("point at the sky", SKY, 2.5),
    ("look left", {"shoulder_pan": 60}, 1.5),
    ("look right", {"shoulder_pan": -60}, 2.5),
    ("center", {"shoulder_pan": 0}, 1.5),
    ("spin wrist", {"wrist_roll": 120}, 1.2),
    ("spin back", {"wrist_roll": -120}, 1.8),
    ("wrist center", {"wrist_roll": 0}, 1.0),
    ("open", {"gripper": 100}, 0.8),
    ("close", {"gripper": 0}, 0.8),
    ("open", {"gripper": 100}, 0.6),
    ("close", {"gripper": 0}, 0.6),
    ("nod up", {"wrist_flex": 40}, 0.8),
    ("nod down", {"wrist_flex": -40}, 1.0),
    ("nod center", {"wrist_flex": 0}, 0.8),
    ("bow", {"shoulder_lift": 30, "elbow_flex": -50, "wrist_flex": 40}, 2.0),
    ("stand up", SKY, 2.0),
]


def main():
    port, robot_id = sys.argv[1], sys.argv[2]
    robot = SO101Follower(
        SO101FollowerConfig(
            port=port,
            id=robot_id,
            max_relative_target=15.0,
            disable_torque_on_disconnect=False,
            position_p_coefficient=32,
        )
    )
    robot.connect(calibrate=False)
    try:
        obs = robot.get_observation()
        pose = {j: obs[f"{j}.pos"] for j in JOINTS}
        for label, changes, seconds in ROUTINE:
            target = {**pose, **changes}
            steps = max(1, int(seconds * HZ))
            for i in range(1, steps + 1):
                t = i / steps
                t = t * t * (3 - 2 * t)
                robot.send_action({f"{j}.pos": pose[j] + (target[j] - pose[j]) * t for j in JOINTS})
                time.sleep(1 / HZ)
            pose = target
            obs = robot.get_observation()
            print(f"{time.strftime('%H:%M:%S')} {label:16} " + " ".join(f"{j[:5]} {obs[f'{j}.pos']:6.1f}" for j in JOINTS), flush=True)
    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()
