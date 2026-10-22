"""Re-zero one servo so its CURRENT position reads `value` (default 2048, the middle of 0..4095).

Needed when a joint's working range ends up straddling the encoder's 0/4095 seam (e.g. after the
horn was loosened and re-seated): position mode then cannot cross the seam and drives the long way
round into the hard stop. Present_Position = raw - Homing_Offset (mod 4096); the offset is stored
sign-magnitude in EEPROM (bit 11 = negative).
Usage: python rezero.py MOTOR_ID [value]
"""
import sys
import time

import scservo_sdk as scs

from arm import BAUD, PORT

ADDR_OFFSET, ADDR_LOCK, ADDR_TORQUE, ADDR_POSITION = 31, 55, 40, 56


def decode(raw: int) -> int:
    return -(raw & 0x7FF) if raw & 0x800 else raw & 0x7FF


def encode(value: int) -> int:
    return (0x800 | -value) if value < 0 else value


motor = int(sys.argv[1])
want = int(sys.argv[2]) if len(sys.argv) > 2 else 2048
port, pk = scs.PortHandler(PORT), scs.PacketHandler(0)
port.openPort()
port.setBaudRate(BAUD)
pk.write1ByteTxRx(port, motor, ADDR_TORQUE, 0)
time.sleep(0.5)
offset = decode(pk.read2ByteTxRx(port, motor, ADDR_OFFSET)[0])
present = pk.read2ByteTxRx(port, motor, ADDR_POSITION)[0]
raw = (present + offset) % 4096
new = raw - want
new = (new + 2048) % 4096 - 2048  # keep it in -2048..2047
new = max(-2047, min(2047, new))
pk.write1ByteTxRx(port, motor, ADDR_LOCK, 0)
pk.write2ByteTxRx(port, motor, ADDR_OFFSET, encode(new))
pk.write1ByteTxRx(port, motor, ADDR_LOCK, 1)
time.sleep(0.2)
print(f"motor {motor}: offset {offset} -> {new}; position {present} -> {pk.read2ByteTxRx(port, motor, ADDR_POSITION)[0]}")
port.closePort()
