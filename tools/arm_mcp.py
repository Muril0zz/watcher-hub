#!/usr/bin/env python3
"""
Give the XiaoZhi agent tools to drive the arm, wirelessly, over its MCP endpoint.

  Watcher --Wi-Fi--> xiaozhi.me agent --MCP over websocket--> this script --> arm

The script connects OUT to the agent's MCP endpoint (xiaozhi.me -> agent ->
Configure role -> MCP Settings), so it works from any network without opening
a port. Run it on the arm's computer and put the real arm code in arm().

  pip install websockets
  export MCP_ENDPOINT='wss://api.xiaozhi.me/mcp/?token=...'   # secret, never commit
  python3 tools/arm_mcp.py

Without MCP_ENDPOINT it reads data/mcp_endpoint.txt (gitignored).
To add an action, add a tool to TOOLS; arm() receives its name and arguments.
"""
import asyncio
import json
import os
import sys

import websockets

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]  # SO-101
STEPS = {"type": "integer", "minimum": 1, "maximum": 10, "default": 1,
         "description": "How many steps to move (default 1)."}


def tool(name: str, description: str, properties: dict, required: list) -> dict:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


TOOLS = [
    tool("move_arm", "Move the arm's end in a direction.",
         {"direction": {"type": "string", "enum": ["up", "down", "left", "right", "forward", "backward"]},
          "steps": STEPS}, ["direction"]),
    tool("rotate_wrist", "Roll the wrist.",
         {"direction": {"type": "string", "enum": ["clockwise", "counterclockwise"]}, "steps": STEPS},
         ["direction"]),
    tool("tilt_wrist", "Bend the wrist up or down.",
         {"direction": {"type": "string", "enum": ["up", "down"]}, "steps": STEPS}, ["direction"]),
    tool("gripper", "Open or close the gripper (e.g. to grab or release something).",
         {"action": {"type": "string", "enum": ["open", "close"]}}, ["action"]),
    tool("set_joint", "Set one joint to an absolute angle in degrees.",
         {"joint": {"type": "string", "enum": JOINTS},
          "angle": {"type": "number", "minimum": -180, "maximum": 180}}, ["joint", "angle"]),
    tool("go_to_pose", "Move to a named pose or play a gesture.",
         {"pose": {"type": "string", "enum": ["home", "rest", "wave", "nod", "point"]}}, ["pose"]),
    tool("stop_arm", "Stop the arm immediately.", {}, []),
    tool("arm_command", "Anything the other tools can't express, in plain words "
                        "(e.g. 'pick up the cup'). The arm's controller interprets it.",
         {"instruction": {"type": "string"}}, ["instruction"]),
]
BY_NAME = {t["name"]: t for t in TOOLS}


# --------------------------------------------------------------------------
# Your integration hook: drive the SO-ARM101 here. Raise to report a failure.
# --------------------------------------------------------------------------
def arm(action: str, args: dict) -> str:
    print(f"ARM: {action} {json.dumps(args)}", flush=True)
    return f"OK: {action} {' '.join(str(v) for v in args.values())}".strip()


def check_args(schema: dict, args: dict) -> str | None:
    """Return an error message if args don't match the tool's schema."""
    props = schema["properties"]
    for name in schema["required"]:
        if name not in args:
            return f"Missing argument {name!r}."
    for name, value in args.items():
        spec = props.get(name)
        if spec is None:
            return f"Unknown argument {name!r}."
        if "enum" in spec and value not in spec["enum"]:
            return f"{name} must be one of {', '.join(spec['enum'])}."
        if spec["type"] in ("integer", "number"):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or \
                    (spec["type"] == "integer" and value != int(value)):
                return f"{name} must be a {spec['type']}."
            if not spec.get("minimum", value) <= value <= spec.get("maximum", value):
                return f"{name} must be between {spec['minimum']} and {spec['maximum']}."
        if spec["type"] == "string" and not isinstance(value, str):
            return f"{name} must be text."
    return None


def call_tool(name: str, args: dict) -> dict:
    def text(t: str, error: bool) -> dict:
        return {"content": [{"type": "text", "text": t}], "isError": error}
    if name not in BY_NAME:
        return text(f"Unknown tool {name!r}.", True)
    schema = BY_NAME[name]["inputSchema"]
    error = check_args(schema, args)
    if error:
        return text(error, True)
    args = {k: s["default"] for k, s in schema["properties"].items() if "default" in s} | args
    try:
        return text(arm(name, args), False)
    except Exception as e:
        return text(f"The arm did not move: {e}", True)


def handle(req: dict) -> dict | None:
    """Answer one JSON-RPC message from the agent; None for notifications."""
    method, params = req.get("method"), req.get("params") or {}
    if "id" not in req:
        return None
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "watcher-arm", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = call_tool(params.get("name"), params.get("arguments") or {})
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": req["id"],
                "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": req["id"], "result": result}


async def serve(endpoint: str) -> None:
    while True:  # the endpoint drops idle connections; always reconnect
        try:
            # proxy=None: websockets >= 15 uses the system HTTPS proxy, and local
            # proxies (e.g. on this Mac, 127.0.0.1) answer websockets with garbage.
            async with websockets.connect(endpoint, proxy=None) as ws:
                print("Connected to the XiaoZhi MCP endpoint", flush=True)
                async for raw in ws:
                    req = json.loads(raw)
                    print(f"<- {req.get('method')} {json.dumps(req.get('params') or {})}", flush=True)
                    reply = handle(req)
                    if reply is not None:
                        await ws.send(json.dumps(reply))
        except Exception as e:
            print(f"connection lost ({e}); retrying in 5 s", file=sys.stderr, flush=True)
        await asyncio.sleep(5)


if __name__ == "__main__":
    endpoint = os.environ.get("MCP_ENDPOINT")
    if not endpoint:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "mcp_endpoint.txt")
        try:
            with open(path) as f:
                endpoint = f.read().strip()
        except FileNotFoundError:
            sys.exit("Set MCP_ENDPOINT (xiaozhi.me -> agent -> MCP Settings) or create data/mcp_endpoint.txt")
    try:
        asyncio.run(serve(endpoint))
    except KeyboardInterrupt:
        pass
