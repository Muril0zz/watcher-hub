"""The "insane" show: fast whips, slow sweeps, a multi-joint sine dance, accelerating gripper chomps.

Tuned for a 5 V / 3 A supply: whips >= 0.9 s with short rests, gripper chomps capped near 2 Hz,
and if the servos brown out (bus stops answering) the arm reconnects and slowly stands back up.
Stays inside the black arm's calibrated ranges: pan ±90, shoulder 0..+35 (forward), elbow -95..-40,
wrist_flex ±50, wrist_roll ±180, gripper 0..100.
Usage: python crazy_show.py PORT ID
"""
import math
import sys
import time

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

from show import HZ, JOINTS, SKY


class Performer:
    def __init__(self, robot, revive=None):
        """revive() -> a freshly connected robot after a brownout; without it, errors propagate."""
        self.robot = robot
        self.revive = revive
        self.read_pose()

    def read_pose(self):
        obs = self.robot.get_observation()
        self.pose = {j: obs[f"{j}.pos"] for j in JOINTS}

    def send(self, pose):
        self.robot.send_action({f"{j}.pos": v for j, v in pose.items()})
        self.pose = pose
        time.sleep(1 / HZ)

    def step(self, label, frames):
        """Send every pose from `frames`; on a brownout, revive the arm and skip to the next step."""
        try:
            for pose in frames:
                self.send(pose)
            self.log(label)
        except ConnectionError as exc:
            if self.revive is None:
                raise
            print(f"BROWNOUT during '{label}': {exc}", flush=True)
            self.robot = self.revive()
            self.read_pose()
            self.log("resumed after brownout")

    def glide(self, label, changes, seconds):
        start, target = dict(self.pose), {**self.pose, **changes}
        steps = max(1, int(seconds * HZ))

        def frames():
            for i in range(1, steps + 1):
                t = i / steps
                t = t * t * (3 - 2 * t)
                yield {j: start[j] + (target[j] - start[j]) * t for j in JOINTS}

        self.step(label, frames())

    def rest(self, seconds=0.3):
        time.sleep(seconds)

    def wave(self, label, seconds, fn):
        """fn(t) -> joint changes relative to the pose at the start of the wave."""
        base = dict(self.pose)
        self.step(label, ({**base, **fn(i / HZ, base)} for i in range(int(seconds * HZ))))

    def log(self, label):
        obs = self.robot.get_observation()
        print(f"{time.strftime('%H:%M:%S')} {label:22} "
              + " ".join(f"{j[:5]} {obs[f'{j}.pos']:6.1f}" for j in JOINTS), flush=True)


def sine(amplitude, hz, t, phase=0.0):
    return amplitude * math.sin(2 * math.pi * hz * t + phase)


def routine(p: Performer):
    p.glide("slow rise to the sky", SKY, 3.0)

    for side in (60, -60, 60, -60, 0):  # whips
        p.glide("whip", {"shoulder_pan": side}, 0.9)
        p.rest()

    p.glide("prepare sweep", {"shoulder_pan": 90, "wrist_roll": 170}, 1.6)
    p.glide("slow sweep + counter spin", {"shoulder_pan": -90, "wrist_roll": -170}, 5.0)
    p.glide("back to center", {"shoulder_pan": 0, "wrist_roll": 0}, 1.0)

    p.wave("sine dance", 8.0, lambda t, b: {
        "shoulder_pan": sine(60, 0.4, t),
        "wrist_flex": sine(35, 0.9, t),
        "wrist_roll": sine(90, 0.6, t),
        "gripper": 50 + sine(50, 1.5, t),
    })
    p.glide("settle", {**SKY}, 0.8)

    hz = 0.8
    for _ in range(6):  # accelerating chomps, capped where the gripper still keeps up
        p.glide("chomp open", {"gripper": 100}, 0.5 / hz)
        p.glide("chomp close", {"gripper": 0}, 0.5 / hz)
        hz = min(hz * 1.2, 1.5)
    p.rest()

    p.glide("fast bow", {"shoulder_lift": 35, "elbow_flex": -45, "wrist_flex": 45}, 1.0)
    p.rest()
    p.glide("slow rise: forearm", {"elbow_flex": -95, "wrist_flex": 0}, 1.5)
    p.glide("slow rise: shoulder", SKY, 2.0)
    p.glide("slow bow", {"shoulder_lift": 35, "elbow_flex": -45, "wrist_flex": 45}, 3.0)
    # rising against gravity on 3 joints at once browns out the 5 V supply: forearm first, then shoulder
    p.glide("fast rise: forearm", {"elbow_flex": -95, "wrist_flex": 0}, 1.2)
    p.glide("fast rise: shoulder", SKY, 1.0)
    p.rest()

    p.glide("look at the table", {"shoulder_pan": 45, "shoulder_lift": 20, "elbow_flex": -60, "wrist_flex": -40}, 1.5)
    p.wave("shake head no", 2.0, lambda t, b: {"wrist_roll": sine(45, 2.5, t)})
    p.glide("look other side", {"shoulder_pan": -45, "wrist_roll": 0}, 1.5)
    p.wave("chomp at it", 1.6, lambda t, b: {"gripper": 50 + sine(50, 3, t)})

    p.glide("finale: forearm up", {"elbow_flex": -95, "wrist_flex": 0, "wrist_roll": 0}, 1.0)
    p.glide("finale: sky, claw wide open", {**SKY, "gripper": 100}, 1.5)
    time.sleep(1.5)


def make_robot(port, robot_id):
    robot = SO101Follower(
        SO101FollowerConfig(
            port=port,
            id=robot_id,
            max_relative_target=20.0,
            disable_torque_on_disconnect=False,
            position_p_coefficient=32,
        )
    )
    robot.connect(calibrate=False)
    return robot


def recover(port, robot_id):
    """After a brownout the servos reboot limp: stand up gently (see stand_up.py)."""
    from stand_up import stand_up

    for attempt in range(3):
        time.sleep(1.5)
        try:
            stand_up(port, robot_id)
            print("recovered: standing again", flush=True)
            return
        except Exception as exc:  # bus still down
            print(f"recover attempt {attempt + 1} failed: {exc}", flush=True)
    raise RuntimeError("could not recover the arm")


def main():
    port, robot_id = sys.argv[1], sys.argv[2]
    performer = None

    def revive():
        try:
            performer.robot.bus.port_handler.closePort()
        except Exception:
            pass
        recover(port, robot_id)
        return make_robot(port, robot_id)

    performer = Performer(make_robot(port, robot_id), revive)
    try:
        routine(performer)
    finally:
        try:
            performer.robot.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
