"""Marco over Wi-Fi: gives Marco's XiaoZhi agent a `move_arm` tool through its MCP access point.

xiaozhi.me -> console -> Marco's agent -> MCP接入点 shows a secret wss:// address. This program dials
it (outbound only, so no port to open), answers the MCP JSON-RPC calls Marco's cloud sends, and
forwards each move to the arm server already running on this Mac (server.py, port 8000). Marco then
moves the arm wherever it is, no USB cable, and says "done" itself because it now has the tool.

Run (arm server running first):
    MARCO_MCP_ENDPOINT='wss://api.xiaozhi.me/mcp/?token=...' ../../.venv/bin/python marco_mcp.py
The address is a secret: keep it out of the repo and out of chats.
"""
import asyncio
import json
import os
import sys
import urllib.request

import websockets

ARM_URL = os.environ.get("ARM_URL", "http://127.0.0.1:8000")
TOOLS = [
    {
        "name": "move_arm",
        "description": (
            "Moves the robot arm on the table. Call it whenever the user asks the arm to do anything: turn "
            "left/right, go up/down (all the way or a bit), center, stand up, open/close the hand, turn the "
            "wrist, wave, nod yes, shake no, dance, go faster/slower, or stop. Pass the user's request in their "
            "own words and language, e.g. 'go all the way down and wave' or '向左转一点'. Returns what the arm did."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The movement request, in any language"}},
            "required": ["command"],
        },
    },
    {
        "name": "stop_arm",
        "description": "Stops the robot arm immediately. Call it when the user says stop, wait, enough or similar.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call_arm(text: str) -> str:
    req = urllib.request.Request(
        ARM_URL + "/api/command",
        data=json.dumps({"text": text, "source": "marco-mcp"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.load(r)
    if out.get("status") and not out.get("intents"):
        return f"The arm is not ready ({out['status']}): someone must stand it up by hand."
    if not out.get("intents"):
        return out.get("say") or "The arm could not understand that as a movement."
    return f"Done: {', '.join(out['intents'])}. {out.get('say', '')}".strip()


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message from Marco's cloud -> our reply (None for notifications)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notifications (initialized, cancelled...)
        return None
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion", "2024-11-05")
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "robot-arm", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            text = call_arm("stop" if name == "stop_arm" else str(args.get("command", "")))
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:  # arm server down, timeout
            result = {"content": [{"type": "text", "text": f"The arm is offline: {e}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


async def serve(endpoint: str):
    delay = 1
    while True:
        try:
            async with websockets.connect(endpoint, ping_interval=20, ping_timeout=20) as ws:
                print("connected to Marco's MCP access point", flush=True)
                delay = 1
                async for raw in ws:
                    msg = json.loads(raw)
                    print("<-", msg.get("method"), json.dumps(msg.get("params", {}), ensure_ascii=False)[:120], flush=True)
                    reply = await asyncio.to_thread(handle, msg)  # the arm call blocks; keep pings flowing
                    if reply is not None:
                        await ws.send(json.dumps(reply, ensure_ascii=False))
        except Exception as e:
            print(f"connection lost ({e}); retrying in {delay}s", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


if __name__ == "__main__":
    endpoint = os.environ.get("MARCO_MCP_ENDPOINT") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not endpoint.startswith("ws"):
        sys.exit("set MARCO_MCP_ENDPOINT to the wss://api.xiaozhi.me/mcp/?token=... address from the xiaozhi.me console")
    asyncio.run(serve(endpoint))
