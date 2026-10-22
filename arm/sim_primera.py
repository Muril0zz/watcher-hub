"""SO-101 in MuJoCo: plays a short sequence of poses using the real arm's joint names.

Run with the MuJoCo launcher (required on macOS for the passive viewer):
    .venv/bin/mjpython sim_primera.py
Headless self-check (no window):
    .venv/bin/python sim_primera.py --check
"""

import sys
import time
from pathlib import Path

import mujoco
import numpy as np

SCENE = Path(__file__).parent / "sim" / "SO101" / "scene.xml"

# Joint targets in radians. 0 = middle of each joint's range ("new calib").
# Joints not listed in a pose keep their previous target.
POSES = [
    ("home", {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 0, "wrist_flex": 0, "wrist_roll": 0, "gripper": 0}),
    ("turn left", {"shoulder_pan": 0.8}),
    ("turn right", {"shoulder_pan": -0.8}),
    ("center", {"shoulder_pan": 0}),
    ("raise", {"shoulder_lift": -0.6, "elbow_flex": 0.6}),
    ("wrist roll +", {"wrist_roll": 1.2}),
    ("wrist roll -", {"wrist_roll": -1.2}),
    ("wrist roll 0", {"wrist_roll": 0}),
    ("open gripper", {"gripper": 1.4}),
    ("close gripper", {"gripper": 0}),
    ("home", {"shoulder_lift": 0, "elbow_flex": 0}),
]
SEGMENT_SECONDS = 1.5


def build_targets(model: mujoco.MjModel) -> list[tuple[str, np.ndarray]]:
    current = np.zeros(model.nu)
    targets = []
    for name, joints in POSES:
        current = current.copy()
        for joint, value in joints.items():
            current[model.actuator(joint).id] = value
        targets.append((name, current))
    return targets


def smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def control_at(targets, sim_time: float) -> tuple[str, np.ndarray]:
    """Interpolated control for a given time, looping through the sequence."""
    total = SEGMENT_SECONDS * len(targets)
    t = sim_time % total
    i = int(t // SEGMENT_SECONDS)
    alpha = smoothstep((t % SEGMENT_SECONDS) / SEGMENT_SECONDS)
    start = targets[i - 1][1]  # wraps to the last pose for i == 0
    name, end = targets[i]
    return name, (1 - alpha) * start + alpha * end


def run_viewer(model, data, targets):
    import mujoco.viewer

    with mujoco.viewer.launch_passive(model, data) as viewer:
        last_name = None
        while viewer.is_running():
            step_start = time.time()
            name, ctrl = control_at(targets, data.time)
            if name != last_name:
                print(f"-> {name}")
                last_name = name
            data.ctrl[:] = ctrl
            mujoco.mj_step(model, data)
            viewer.sync()
            sleep = model.opt.timestep - (time.time() - step_start)
            if sleep > 0:
                time.sleep(sleep)


def run_check(model, data, targets):
    """Simulates one full sequence headless and reports how well each joint tracked."""
    seconds = SEGMENT_SECONDS * len(targets)
    worst = np.zeros(model.nu)
    while data.time < seconds:
        _, ctrl = control_at(targets, data.time)
        data.ctrl[:] = ctrl
        mujoco.mj_step(model, data)
        # Only measure once each segment has settled near its end.
        if (data.time % SEGMENT_SECONDS) > 0.9 * SEGMENT_SECONDS:
            qpos = np.array([data.joint(model.actuator(i).trnid[0]).qpos[0] for i in range(model.nu)])
            worst = np.maximum(worst, np.abs(qpos - ctrl))
    for i in range(model.nu):
        print(f"{model.actuator(i).name:<14} max tracking error {np.degrees(worst[i]):5.1f} deg")


def main():
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    data = mujoco.MjData(model)
    targets = build_targets(model)
    print(f"Loaded {SCENE.name}: {model.nu} actuators -> {[model.actuator(i).name for i in range(model.nu)]}")
    if "--check" in sys.argv:
        run_check(model, data, targets)
    else:
        run_viewer(model, data, targets)


if __name__ == "__main__":
    main()
