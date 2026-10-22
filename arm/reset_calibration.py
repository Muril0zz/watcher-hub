"""Restores the factory calibration stored in the servos' EEPROM: original homing offsets,
position limits 0..4095.

    .venv/bin/python reset_calibration.py

The factory offsets were reconstructed with the arm in its resting pose so it reads what it
read out of the box (pan ~2180, lift ~850, elbow ~897, wrist_flex ~2292, roll ~3120, gripper ~2070).
The servo reports Present_Position = raw_encoder - Homing_Offset (mod 4096).
"""

from so101 import (
    MAX_POSITION_LIMIT,
    MIN_POSITION_LIMIT,
    MOTORS,
    PRESENT_POSITION,
    TORQUE_ENABLE,
    Bus,
)

HOMING_OFFSET = (31, 2)  # sign-magnitude: bit 11 is the sign, range -2047..2047
LOCK = (55, 1)  # 0 = EEPROM writable, 1 = EEPROM locked

FACTORY_HOMING_OFFSETS = {
    "shoulder_pan": 910,
    "shoulder_lift": -1617,
    "elbow_flex": 1194,
    "wrist_flex": -1592,
    "wrist_roll": -957,
    "gripper": 237,
}


def encode_offset(value: int) -> int:
    if not -2047 <= value <= 2047:
        raise ValueError(f"homing offset {value} out of -2047..2047")
    return (1 << 11) | -value if value < 0 else value


def decode_offset(raw: int) -> int:
    return -(raw & 0x7FF) if raw & (1 << 11) else raw & 0x7FF


def main():
    with Bus() as bus:
        for name, m in MOTORS.items():
            bus.write(m, TORQUE_ENABLE, 0)
            bus.write(m, LOCK, 0)
            try:
                bus.write(m, HOMING_OFFSET, encode_offset(FACTORY_HOMING_OFFSETS[name]))
                bus.write(m, MIN_POSITION_LIMIT, 0)
                bus.write(m, MAX_POSITION_LIMIT, 4095)
            finally:
                bus.write(m, LOCK, 1)
            print(
                f"{name:<14} offset={decode_offset(bus.read(m, HOMING_OFFSET)):>6} "
                f"limits={bus.read(m, MIN_POSITION_LIMIT)}..{bus.read(m, MAX_POSITION_LIMIT)} "
                f"pos={bus.read(m, PRESENT_POSITION)}"
            )


if __name__ == "__main__":
    main()
