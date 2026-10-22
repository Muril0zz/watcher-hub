"""Read-only scan of the SO-ARM101 bus: which servo IDs answer and where they are.

Never writes to the servos, so the arm does not move.
Usage: python scan_arm.py /dev/tty.usbmodemXXXX
"""
import sys

import scservo_sdk as scs

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem5B790830241"
BAUD = 1_000_000  # LeRobot default for STS3215
JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]

# STS3215 control table (read-only addresses)
ADDR_POSITION = 56
ADDR_VOLTAGE = 62
ADDR_TEMPERATURE = 63
ADDR_TORQUE_ENABLE = 40

port = scs.PortHandler(PORT)
packet = scs.PacketHandler(0)
if not port.openPort() or not port.setBaudRate(BAUD):
    sys.exit(f"could not open {PORT} at {BAUD}")

found = 0
for servo_id in range(1, 11):
    model, result, _ = packet.ping(port, servo_id)
    if result != scs.COMM_SUCCESS:
        continue
    found += 1
    pos, _, _ = packet.read2ByteTxRx(port, servo_id, ADDR_POSITION)
    volt, _, _ = packet.read1ByteTxRx(port, servo_id, ADDR_VOLTAGE)
    temp, _, _ = packet.read1ByteTxRx(port, servo_id, ADDR_TEMPERATURE)
    torque, _, _ = packet.read1ByteTxRx(port, servo_id, ADDR_TORQUE_ENABLE)
    name = JOINTS[servo_id - 1] if servo_id <= len(JOINTS) else "?"
    print(f"id {servo_id} ({name:13}) model {model}  pos {pos:4d}/4095  "
          f"{volt / 10:.1f} V  {temp} °C  torque {'ON' if torque else 'off'}")

port.closePort()
print(f"{found} servo(s) answered")
