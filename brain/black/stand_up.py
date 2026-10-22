"""Stand the black arm up from a collapsed pose without browning out its 5 V supply.

Low gain (P 16) and one joint at a time: fold the forearm up first (shorter lever on the shoulder),
then raise the shoulder slowly. Only once it is nearly vertical is the gain raised to 32.
Usage: python stand_up.py PORT ID
"""
import sys
import time

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

from show import SKY
from crazy_show import Performer


def connect(port, robot_id, p_gain):
    robot = SO101Follower(
        SO101FollowerConfig(
            port=port,
            id=robot_id,
            max_relative_target=10.0,
            disable_torque_on_disconnect=False,
            position_p_coefficient=p_gain,
        )
    )
    robot.connect(calibrate=False)
    return robot


def stand_up(port, robot_id):
    robot = connect(port, robot_id, p_gain=16)
    try:
        p = Performer(robot)
        p.glide("fold forearm up", {"elbow_flex": -95, "wrist_flex": 0}, 3.0)
        time.sleep(0.5)
        p.glide("raise shoulder slowly", {"shoulder_lift": 0}, 5.0)
        time.sleep(0.5)
    finally:
        robot.disconnect()
    robot = connect(port, robot_id, p_gain=32)
    try:
        Performer(robot).glide("firm stance", SKY, 2.0)
    finally:
        robot.disconnect()


if __name__ == "__main__":
    stand_up(sys.argv[1], sys.argv[2])
