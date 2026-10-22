"""Minimal SO-101 follower bus helpers on top of the Feetech SDK (STS3215 servos)."""

import termios
import time

import scservo_sdk as scs
import serial

PORT = "/dev/tty.usbmodem5B901033751"
BAUDRATE = 1_000_000
PROTOCOL_END = 0  # STS series: little endian

# Motor ids as configured on the SO-101 (same as LeRobot)
MOTORS = {
    "shoulder_pan": 1,
    "shoulder_lift": 2,
    "elbow_flex": 3,
    "wrist_flex": 4,
    "wrist_roll": 5,
    "gripper": 6,
}
# These carry the arm's weight: released away from the resting pose, the arm drops.
GRAVITY_JOINTS = ("shoulder_lift", "elbow_flex", "wrist_flex")
# Big moves go in two groups so the gripper never swings around while the arm is folded:
# going up, raise the arm first and then turn the wrist; going back to rest, the reverse.
ARM_GROUP = ("shoulder_lift", "elbow_flex")
WRIST_GROUP = ("shoulder_pan", "wrist_flex", "wrist_roll", "gripper")

# STS3215 control table: name -> (address, size in bytes)
MIN_POSITION_LIMIT = (9, 2)
MAX_POSITION_LIMIT = (11, 2)
OPERATING_MODE = (33, 1)
TORQUE_ENABLE = (40, 1)
ACCELERATION = (41, 1)
GOAL_POSITION = (42, 2)
GOAL_VELOCITY = (46, 2)
TORQUE_LIMIT = (48, 2)  # 0..1000 (% x10), RAM: resets on power cycle
PRESENT_POSITION = (56, 2)
PRESENT_VOLTAGE = (62, 1)
PRESENT_TEMPERATURE = (63, 1)
MOVING = (66, 1)

STEPS_PER_REV = 4096  # 0..4095 per full turn -> ~0.088 deg per step
POSITION_REGISTERS = (GOAL_POSITION, PRESENT_POSITION)
# Status flags a servo can attach to an otherwise valid reply.
ALARMS = {1: "voltage", 2: "angle", 4: "overheat", 8: "overcurrent", 32: "overload"}


class Bus:
    # The half-duplex bus occasionally drops a packet; lost packets are retried,
    # but errors reported by the motor itself (overload, voltage...) are not.
    RETRIES = 3
    STALL_STEPS = 40  # a joint this far from its goal...
    STALL_WINDOW = 0.75  # ...while the whole group moved less than 3 steps in this many seconds is blocked

    def __init__(self, port: str = PORT, baudrate: int = BAUDRATE):
        self.port = scs.PortHandler(port)
        self.packet = scs.PacketHandler(PROTOCOL_END)
        if not self.port.openPort():
            raise RuntimeError(f"Could not open {port}")
        if not self.port.setBaudRate(baudrate):
            raise RuntimeError(f"Could not set baudrate {baudrate}")
        self.speed = 300  # steps/s, last speed sent to the motors; used to size move() timeouts
        self.alarms: dict[int, int] = {}  # motor id -> status flags from its latest reply

    def close(self):
        self.port.closePort()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _flush_input(self):
        # The SDK's clearPort() only flushes output. A late reply left in the input buffer
        # (from a retried timeout) would otherwise be parsed as the answer to the NEXT request.
        try:
            self.port.ser.reset_input_buffer()
        except termios.error as e:  # the USB device went away under us: report it as a port error
            raise serial.SerialException(f"serial port lost: {e}") from e

    def ping(self, motor_id: int) -> int | None:
        self._flush_input()
        model, result, _ = self.packet.ping(self.port, motor_id)
        return model if result == scs.COMM_SUCCESS else None

    def read(self, motor_id: int, register: tuple[int, int]) -> int:
        address, size = register
        fn = self.packet.read1ByteTxRx if size == 1 else self.packet.read2ByteTxRx
        for _ in range(self.RETRIES):
            self._flush_input()
            try:
                value, result, error = fn(self.port, motor_id, address)
            except IndexError:  # the SDK reports a truncated packet as success, then crashes on it
                value, result, error = 0, scs.COMM_RX_CORRUPT, 0
            if result == scs.COMM_SUCCESS and register in POSITION_REGISTERS and value > 4095:
                result = scs.COMM_RX_CORRUPT  # impossible position: a stale or garbled packet
            if result == scs.COMM_SUCCESS:
                break
        self._check(motor_id, result, error)
        return value

    def write(self, motor_id: int, register: tuple[int, int], value: int):
        self._check_value(register, value)
        address, size = register
        fn = self.packet.write1ByteTxRx if size == 1 else self.packet.write2ByteTxRx
        for _ in range(self.RETRIES):
            self._flush_input()
            result, error = fn(self.port, motor_id, address, value)
            if result == scs.COMM_SUCCESS:
                break
        self._check(motor_id, result, error)

    def sync_write(self, register: tuple[int, int], values: dict[int, int]):
        """Writes one register on several motors with a single broadcast packet. They all get
        their value at the same instant, and since motors don't reply to a broadcast, a lost
        reply can't abort it halfway (which could leave some joints without their new goal)."""
        address, size = register
        group = scs.GroupSyncWrite(self.port, self.packet, address, size)
        for m, v in values.items():
            self._check_value(register, v)
            group.addParam(m, [v & 0xFF] if size == 1 else [scs.SCS_LOBYTE(v), scs.SCS_HIBYTE(v)])
        self._flush_input()
        result = group.txPacket()
        if result != scs.COMM_SUCCESS:
            raise IOError(f"sync write to {list(values)}: {self.packet.getTxRxResult(result)}")

    @staticmethod
    def _check_value(register: tuple[int, int], value: int):
        if register == GOAL_POSITION and not 0 <= value <= 4095:
            raise ValueError(f"goal position {value} out of 0..4095")

    def _check(self, motor_id: int, result: int, error: int):
        if result != scs.COMM_SUCCESS:
            raise IOError(f"motor {motor_id}: {self.packet.getTxRxResult(result)}")
        # A status flag (overload, overheat...) doesn't make the reply wrong: record it for whoever
        # supervises the arm, but keep working. Raising here once made an overloaded gripper block
        # every read, so the arm could not even be released.
        if error:
            self.alarms[motor_id] = error
        else:
            self.alarms.pop(motor_id, None)

    def alarm_names(self, motor_id: int) -> list[str]:
        flags = self.alarms.get(motor_id, 0)
        return [name for bit, name in ALARMS.items() if flags & bit]

    def positions(self, motor_ids) -> dict[int, int]:
        return {m: self.read(m, PRESENT_POSITION) for m in motor_ids}

    def torque_on(self, motor_ids) -> list[int]:
        return [m for m in motor_ids if self.read(m, TORQUE_ENABLE)]

    def hold(self, motor_ids, speed: int = 300, accel: int = 20) -> dict[int, int]:
        """Enables torque without jumping: goal is set to the current position first.
        Returns the positions now being held."""
        held = self.positions(motor_ids)
        self.speed = speed
        self.sync_write(GOAL_POSITION, held)
        self.sync_write(ACCELERATION, {m: accel for m in held})
        self.sync_write(GOAL_VELOCITY, {m: speed for m in held})
        self.sync_write(TORQUE_ENABLE, {m: 1 for m in held})
        return held

    def set_speed(self, motor_ids, speed: int):
        self.speed = speed
        self.sync_write(GOAL_VELOCITY, {m: speed for m in motor_ids})

    def release(self, motor_ids):
        """Broadcasts torque-off to all motors at once, then confirms each one individually,
        trying every motor even if one fails, so a single bad link can't leave the rest stiff."""
        motor_ids = list(motor_ids)
        try:
            self.sync_write(TORQUE_ENABLE, {m: 0 for m in motor_ids})
        except OSError:
            pass  # the per-motor writes below still run and report what failed
        failed = []
        for m in motor_ids:
            try:
                self.write(m, TORQUE_ENABLE, 0)
            except OSError:
                failed.append(m)
        if failed:
            raise IOError(f"could not release torque on motors {failed}: check cables and power")

    def move(self, targets: dict[int, int], timeout: float | None = None, tolerance: int = 25) -> dict[int, int]:
        """Moves several motors at once and waits until they arrive. A motor that stops making
        progress while still far from its goal (hard stop, obstacle) is told to stay where it is,
        so it stops pushing. Returns the blocked motors with the position where they stopped.
        The default timeout scales with the longest travel, so slow long moves aren't cut short."""
        for v in targets.values():
            self._check_value(GOAL_POSITION, v)
        start = self.positions(targets)
        if timeout is None:
            longest = max(abs(targets[m] - start[m]) for m in targets)
            timeout = longest / max(self.speed, 1) * 1.5 + 1.5
        self.sync_write(GOAL_POSITION, targets)

        pending = {m for m in targets if abs(start[m] - targets[m]) > tolerance}
        blocked: dict[int, int] = {}
        last = dict(start)
        deadline = time.time() + timeout
        next_check = time.time() + self.STALL_WINDOW
        while pending and time.time() < deadline:
            time.sleep(0.05)
            try:
                pos = self.positions(pending)
            except OSError:
                continue  # a reply lost while motors draw current: goals are already sent, keep waiting
            pending = {m for m in pending if abs(pos[m] - targets[m]) > tolerance}
            if time.time() >= next_check:
                # Only a group that has stopped as a whole is blocked: while any joint still
                # advances it may be freeing another one (e.g. the elbow can't unfold until the
                # shoulder lifts the forearm off its rest).
                if not any(abs(pos[m] - last[m]) >= 3 for m in pending):
                    stuck = {m: pos[m] for m in pending if abs(pos[m] - targets[m]) > self.STALL_STEPS}
                    if stuck:
                        self.sync_write(GOAL_POSITION, stuck)  # stop pushing right now
                        blocked.update(stuck)
                        pending -= set(stuck)
                last.update(pos)
                next_check = time.time() + self.STALL_WINDOW
        # Anything still pending at the deadline counts as blocked too: stop it where it is.
        if pending:
            try:
                late = self.positions(pending)
            except OSError:
                late = {m: last[m] for m in pending}  # best known position
            self.sync_write(GOAL_POSITION, late)
            blocked.update(late)
        return blocked

    def return_and_release(self, rest: dict[int, int], tolerance: int = 30):
        """Moves back to the resting pose (wrist first, then the arm) and releases torque ONLY
        once every load-bearing joint is there. Otherwise torque stays ON and this raises:
        holding the arm in place is safe, releasing it mid-air drops it."""
        gravity = [MOTORS[n] for n in GRAVITY_JOINTS if MOTORS[n] in rest]
        off = gravity
        for _ in range(2):
            try:
                for group in (WRIST_GROUP, ARM_GROUP):
                    targets = {MOTORS[n]: rest[MOTORS[n]] for n in group if MOTORS[n] in rest}
                    if targets:
                        self.move(targets)
                pos = self.positions(gravity)
            except OSError:
                continue
            off = [m for m in gravity if abs(pos[m] - rest[m]) > tolerance]
            if not off:
                self.release(rest)
                return
        raise IOError(
            f"arm did not get back to rest (motors {off}): torque kept ON so it doesn't drop. "
            "Support the arm with your hand, then release torque."
        )
