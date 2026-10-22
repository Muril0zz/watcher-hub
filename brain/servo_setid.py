"""Give a servo its bus ID. New STS3215 servos all ship as ID 1, so plug ONLY the new servo into the
driver board, then e.g. `python servo_setid.py /dev/tty.usbmodemXXXX 1 3` to make it the elbow.
SO-101 IDs: 1 base, 2 shoulder, 3 elbow, 4 wrist flex, 5 wrist roll, 6 gripper.
Usage: python servo_setid.py PORT OLD_ID NEW_ID"""
import sys
import time

import scservo_sdk as scs

port_name, old, new = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
ADDR_ID, ADDR_LOCK, ADDR_TORQUE = 5, 55, 40
port, pk = scs.PortHandler(port_name), scs.PacketHandler(0)
port.openPort()
port.setBaudRate(1_000_000)
found = [i for i in range(0, 20) if pk.ping(port, i)[1] == scs.COMM_SUCCESS]
if found != [old]:
    sys.exit(f"expected exactly one servo with ID {old} on the bus, found {found}: plug in only the new servo")
pk.write1ByteTxRx(port, old, ADDR_TORQUE, 0)
pk.write1ByteTxRx(port, old, ADDR_LOCK, 0)
pk.write1ByteTxRx(port, old, ADDR_ID, new)
time.sleep(0.1)
pk.write1ByteTxRx(port, new, ADDR_LOCK, 1)
ok = pk.ping(port, new)[1] == scs.COMM_SUCCESS
print(f"ID {old} -> {new}: {'ok' if ok else 'FAILED (no reply on the new ID)'}")
port.closePort()
