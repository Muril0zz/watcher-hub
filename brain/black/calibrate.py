"""Calibrate an SO-101 arm as a follower robot, driven by flag files instead of ENTER.

Same steps as `lerobot-calibrate`, but meant to run in the background:
  1. arm is limp; when flags/<id>.home appears, the current pose is taken as the middle
  2. live min/max are recorded until flags/<id>.stop appears (or --max-seconds passes)
  3. calibration is written to the motors and saved where SO101Follower looks for it
Progress goes to flags/<id>.status (one line, overwritten).

Usage: python calibrate.py PORT ID
"""
import argparse
import time
from pathlib import Path

from lerobot.motors import MotorCalibration
from lerobot.motors.feetech import OperatingMode
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

FLAGS = Path(__file__).parent / "flags"
FULL_TURN_MOTOR = "wrist_roll"


def status(robot_id: str, text: str) -> None:
    (FLAGS / f"{robot_id}.status").write_text(text + "\n")
    print(text, flush=True)


def wait_for(flag: Path) -> None:
    while not flag.exists():
        time.sleep(0.1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("id")
    parser.add_argument("--max-seconds", type=float, default=90)
    args = parser.parse_args()

    FLAGS.mkdir(exist_ok=True)
    for name in ("home", "stop"):
        (FLAGS / f"{args.id}.{name}").unlink(missing_ok=True)

    robot = SO101Follower(SO101FollowerConfig(port=args.port, id=args.id))
    robot.connect(calibrate=False)
    bus = robot.bus
    try:
        bus.disable_torque()
        for motor in bus.motors:
            bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)

        status(args.id, "waiting_home: hold the arm in the middle of its range")
        wait_for(FLAGS / f"{args.id}.home")
        homing_offsets = bus.set_half_turn_homings()

        motors = [m for m in bus.motors if m != FULL_TURN_MOTOR]
        mins = bus.sync_read("Present_Position", motors, normalize=False, num_retry=5)
        maxes = dict(mins)
        status(args.id, "recording: move every joint end to end")
        stop_flag = FLAGS / f"{args.id}.stop"
        deadline = time.time() + args.max_seconds
        while not stop_flag.exists() and time.time() < deadline:
            positions = bus.sync_read("Present_Position", motors, normalize=False, num_retry=5)
            mins = {m: min(positions[m], mins[m]) for m in motors}
            maxes = {m: max(positions[m], maxes[m]) for m in motors}
            time.sleep(0.02)
        mins[FULL_TURN_MOTOR], maxes[FULL_TURN_MOTOR] = 0, 4095

        robot.calibration = {
            motor: MotorCalibration(
                id=m.id,
                drive_mode=0,
                homing_offset=homing_offsets[motor],
                range_min=mins[motor],
                range_max=maxes[motor],
            )
            for motor, m in bus.motors.items()
        }
        bus.write_calibration(robot.calibration)
        robot._save_calibration()
        ranges = ", ".join(f"{m} {mins[m]}-{maxes[m]}" for m in bus.motors)
        status(args.id, f"done: {robot.calibration_fpath} | {ranges}")
    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()
