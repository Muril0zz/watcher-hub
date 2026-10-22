"""Plays a sequence of poses on the real SO-101 follower.

    .venv/bin/python secuencia.py            # runs it on the arm
    .venv/bin/python secuencia.py --dry-run  # only prints the planned targets, no torque
"""

import sys

from so101 import ARM_GROUP, MOTORS, PRESENT_POSITION, PRESENT_TEMPERATURE, STEPS_PER_REV, TORQUE_LIMIT, WRIST_GROUP, Bus

# ============================ EDIT HERE ============================
# Absolute poses in steps (0..4095): read them off the panel or check_motors.py.
# START_POSE: where the arm goes before the SEQUENCE runs; the SEQUENCE degrees are relative to it.
#   None = start from wherever the arm is.
# REST_POSE: a pose where the arm sits on its own (folded), so torque can be released there at the
#   end without the arm dropping. None = go back to wherever the arm was when the script started.
START_POSE = {  # comfortable: arm raised, facing front, wrist straight, hand closed
    "shoulder_pan": 2048, "shoulder_lift": 1646, "elbow_flex": 1580,
    "wrist_flex": 2292, "wrist_roll": 3120, "gripper": 2070,
}
# The folded pose (lift 850, elbow 897) made the 12V supply cut out as soon as a motor pushed, so
# the arm now rests where it is placed by hand (stretched out, gripper closed) and returns there.
REST_POSE = None

# Each step: (label, {joint: degrees relative to the start pose}).
# Joints you don't mention in a step keep their previous target.
# Joint names: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper
SEQUENCE = [
    # 1. Turn the hand 90 deg so wrist_flex swings side to side, and open the gripper
    ("turn hand", {"wrist_roll": -90, "gripper": +30}),
    # 2. Wave: swing wrist_flex back and forth
    ("hello", {"wrist_flex": +25}),
    ("hello", {"wrist_flex": -25}),
    ("hello", {"wrist_flex": +25}),
    ("hello", {"wrist_flex": -25}),
    # 3. Undo in reverse order: straighten wrist, close hand
    ("wrist straight", {"wrist_flex": 0}),
    ("close hand", {"wrist_roll": 0, "gripper": 0}),
]

# Only these joints get torque. The rest stay loose.
ACTIVE_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]

SPEED = 300  # steps/s (~26 deg/s). Max ~3000. Keep it low while experimenting.
ACCEL = 20  # 0..254, lower = smoother starts and stops
# 0..1000 per joint (default 1000). Limits how hard a joint pushes against a hard stop or object.
TORQUE_LIMITS = {"gripper": 400, "shoulder_lift": 800, "elbow_flex": 800}
MAX_TEMPERATURE = 60  # C. Refuse to start above this: let the motors cool with torque off.
# ===================================================================


def degrees_to_steps(deg: float) -> int:
    return round(deg * STEPS_PER_REV / 360)


def plan(start: dict[str, int]) -> list[tuple[str, dict[str, int]]]:
    """Turns the relative-degree SEQUENCE into absolute step targets."""
    steps = []
    for label, joints in SEQUENCE:
        unknown = set(joints) - set(ACTIVE_JOINTS)
        if unknown:
            raise SystemExit(f"step '{label}' uses {unknown}, which are not in ACTIVE_JOINTS")
        targets = {joint: start[joint] + degrees_to_steps(deg) for joint, deg in joints.items()}
        for joint, target in targets.items():
            if not 0 <= target <= 4095:
                raise SystemExit(f"step '{label}': {joint} target {target} is outside 0..4095")
        steps.append((label, targets))
    return steps


def run_step(bus: Bus, ids: dict[str, int], label: str, targets: dict[str, int]) -> bool:
    """Moves to the targets. Returns False (and the sequence stops) if a joint got blocked."""
    blocked = bus.move({ids[j]: t for j, t in targets.items()})
    if blocked:
        names = [j for j in targets if ids[j] in blocked]
        print(f"  {label:<18} BLOCKED {names} at {list(blocked.values())} (hard stop or obstacle?): stopping")
        return False
    print(f"  {label:<18} ok")
    return True


def go_to(bus: Bus, ids: dict[str, int], label: str, pose: dict[str, int]) -> bool:
    """Absolute pose in two phases: arm first, then wrist, so the gripper never swings around
    while the arm is still on its way."""
    for group, part_name in ((ARM_GROUP, "arm"), (WRIST_GROUP, "wrist")):
        part = {j: pose[j] for j in group if j in pose and j in ids}
        if part and not run_step(bus, ids, f"{label} ({part_name})", part):
            return False
    return True


def main():
    dry_run = "--dry-run" in sys.argv
    ids = {name: MOTORS[name] for name in ACTIVE_JOINTS}

    with Bus() as bus:
        missing = [name for name, m in ids.items() if bus.ping(m) is None]
        if missing:
            raise SystemExit(f"Not responding: {missing}. Is the 12V supply plugged in?")
        temps = {name: bus.read(m, PRESENT_TEMPERATURE) for name, m in ids.items()}
        hot = {name: t for name, t in temps.items() if t > MAX_TEMPERATURE}
        if hot:
            raise SystemExit(f"Motors too hot {hot} (C): let them cool with torque off first.")

        current = {name: bus.read(m, PRESENT_POSITION) for name, m in ids.items()}
        start = {**current, **(START_POSE or {})}
        rest = {**current, **(REST_POSE or {})}
        steps = plan(start)
        print("current:", current)
        print("start:  ", start)
        print("rest:   ", rest)

        if dry_run:
            for label, targets in steps:
                print(f"  {label:<14} {targets}")
            return

        for joint, limit in TORQUE_LIMITS.items():
            if joint in ids:
                bus.write(ids[joint], TORQUE_LIMIT, limit)
        try:
            bus.hold(ids.values(), speed=SPEED, accel=ACCEL)  # no jump: holds where it is
            if START_POSE and not go_to(bus, ids, "start pose", START_POSE):
                return  # the finally below still brings it to rest
            for label, targets in steps:
                if not run_step(bus, ids, label, targets):
                    break
        finally:
            # Torque is released ONLY once the load-bearing joints are at the rest pose
            # (otherwise it stays on and raises, so the arm doesn't drop). Also runs on Ctrl+C.
            print("going to rest pose...")
            bus.return_and_release({ids[j]: p for j, p in rest.items()})
            for joint in TORQUE_LIMITS:
                if joint in ids:
                    bus.write(ids[joint], TORQUE_LIMIT, 1000)
            print("torque released")


if __name__ == "__main__":
    main()
