"""The arm MCP bridge's JSON-RPC handling, without a network connection."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import arm_mcp  # noqa: E402


def call(name, args):
    reply = arm_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": name, "arguments": args}})
    return reply["result"]


class ArmMcp(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.orig = arm_mcp.arm
        arm_mcp.arm = lambda action, args: self.calls.append((action, args)) or "ok"

    def tearDown(self):
        arm_mcp.arm = self.orig

    def test_handshake_and_tool_list(self):
        init = arm_mcp.handle({"id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(init["result"]["capabilities"], {"tools": {}})
        self.assertIsNone(arm_mcp.handle({"method": "notifications/initialized"}))
        names = [t["name"] for t in arm_mcp.handle({"id": 2, "method": "tools/list"})["result"]["tools"]]
        self.assertIn("move_arm", names)
        self.assertIn("gripper", names)
        self.assertIn("arm_command", names)

    def test_valid_call_reaches_arm_with_defaults(self):
        self.assertFalse(call("move_arm", {"direction": "forward"})["isError"])
        self.assertEqual(self.calls, [("move_arm", {"steps": 1, "direction": "forward"})])

    def test_invalid_calls_never_reach_arm(self):
        for name, args in [("move_arm", {"direction": "sideways"}),
                           ("move_arm", {"direction": "up", "steps": 50}),
                           ("set_joint", {"joint": "elbow_flex"}),
                           ("set_joint", {"joint": "knee", "angle": 10}),
                           ("gripper", {"action": "open", "force": 3}),
                           ("fly", {})]:
            self.assertTrue(call(name, args)["isError"], (name, args))
        self.assertEqual(self.calls, [])

    def test_arm_failure_is_reported(self):
        def broken(action, args):
            raise RuntimeError("motor 3 not responding")
        arm_mcp.arm = broken
        result = call("stop_arm", {})
        self.assertTrue(result["isError"])
        self.assertIn("motor 3 not responding", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
