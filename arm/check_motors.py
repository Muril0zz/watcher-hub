"""Read-only health check: pings every motor and prints its state. Never enables torque."""

from so101 import (
    MAX_POSITION_LIMIT,
    MIN_POSITION_LIMIT,
    MOTORS,
    OPERATING_MODE,
    PRESENT_POSITION,
    PRESENT_TEMPERATURE,
    PRESENT_VOLTAGE,
    TORQUE_ENABLE,
    Bus,
)


def main():
    with Bus() as bus:
        print(f"{'joint':<14}{'id':>3}{'model':>7}{'pos':>6}{'min':>6}{'max':>6}{'volt':>7}{'temp':>6}{'mode':>6}{'torque':>8}")
        found = 0
        for name, motor_id in MOTORS.items():
            model = bus.ping(motor_id)
            if model is None:
                print(f"{name:<14}{motor_id:>3}   -- no response --")
                continue
            found += 1
            print(
                f"{name:<14}{motor_id:>3}{model:>7}"
                f"{bus.read(motor_id, PRESENT_POSITION):>6}"
                f"{bus.read(motor_id, MIN_POSITION_LIMIT):>6}"
                f"{bus.read(motor_id, MAX_POSITION_LIMIT):>6}"
                f"{bus.read(motor_id, PRESENT_VOLTAGE) / 10:>6.1f}V"
                f"{bus.read(motor_id, PRESENT_TEMPERATURE):>5}C"
                f"{bus.read(motor_id, OPERATING_MODE):>6}"
                f"{bus.read(motor_id, TORQUE_ENABLE):>8}"
            )
        print(f"\n{found}/{len(MOTORS)} motors responding")
        if found == 0:
            print("No motor answered: check the 12V power supply on the follower's driver board.")


if __name__ == "__main__":
    main()
