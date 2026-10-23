"""Read-only: each servo's stored position limits, homing offset and mode (nothing moves).
Usage: python read_limits.py /dev/tty.usbmodemXXXX"""
import sys

import scservo_sdk as scs

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
port, pk = scs.PortHandler(sys.argv[1]), scs.PacketHandler(0)
port.openPort()
port.setBaudRate(1_000_000)
for i, name in enumerate(JOINTS, 1):
    lo, _, _ = pk.read2ByteTxRx(port, i, 9)
    hi, _, _ = pk.read2ByteTxRx(port, i, 11)
    off, _, _ = pk.read2ByteTxRx(port, i, 31)
    off = -(off & 0x7FF) if off & 0x800 else off  # sign-magnitude, bit 11
    mode, _, _ = pk.read1ByteTxRx(port, i, 33)
    pos, _, _ = pk.read2ByteTxRx(port, i, 56)
    print(f"id {i} {name:13} limits {lo:4}..{hi:4}  offset {off:5}  mode {mode}  pos {pos}")
port.closePort()
