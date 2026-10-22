"""First move: gently rotates the wrist (no gravity load, no hard stops) and returns it.

Moves ~9 degrees each way at low speed, then releases torque.
"""

import time

from so101 import (
    ACCELERATION,
    GOAL_POSITION,
    GOAL_VELOCITY,
    MOTORS,
    MOVING,
    PRESENT_POSITION,
    TORQUE_ENABLE,
    Bus,
)

JOINT = "wrist_roll"
DELTA_STEPS = 100  # ~9 degrees
SPEED = 300  # steps/s (~26 deg/s)
ACCEL = 20


def wait_until_stopped(bus: Bus, motor_id: int, timeout: float = 3.0):
    deadline = time.time() + timeout
    time.sleep(0.1)
    while time.time() < deadline and bus.read(motor_id, MOVING):
        time.sleep(0.05)


def move_to(bus: Bus, motor_id: int, target: int):
    bus.write(motor_id, GOAL_POSITION, target)
    wait_until_stopped(bus, motor_id)
    print(f"  target={target} reached={bus.read(motor_id, PRESENT_POSITION)}")


def main():
    motor_id = MOTORS[JOINT]
    with Bus() as bus:
        if bus.ping(motor_id) is None:
            raise SystemExit(f"{JOINT} (id {motor_id}) not responding. Is the 12V supply plugged in?")

        start = bus.read(motor_id, PRESENT_POSITION)
        print(f"{JOINT} starts at {start}")

        # Goal must equal the current position BEFORE enabling torque, otherwise the
        # servo jumps to whatever stale goal is stored in its register.
        try:
            bus.write(motor_id, GOAL_POSITION, start)
            bus.write(motor_id, ACCELERATION, ACCEL)
            bus.write(motor_id, GOAL_VELOCITY, SPEED)
            bus.write(motor_id, TORQUE_ENABLE, 1)
            for target in (start + DELTA_STEPS, start, start - DELTA_STEPS, start):
                move_to(bus, motor_id, target)
        finally:
            bus.write(motor_id, TORQUE_ENABLE, 0)
            print("torque released")


if __name__ == "__main__":
    main()
