"""Offline check of marco_mcp.py: a fake 'xiaozhi.me' MCP access point (local websocket server) sends
the calls Marco's cloud would send and prints the replies. With the arm server running, the
tools/call really moves the arm. Usage: python test_marco_mcp.py"""
import asyncio
import json
import subprocess
import sys

import websockets

CALLS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "move_arm", "arguments": {"command": "turn right a bit"}}},
    {"jsonrpc": "2.0", "id": 4, "method": "ping"},
]


async def main():
    done = asyncio.Event()

    async def fake_xiaozhi(ws):
        for call in CALLS:
            await ws.send(json.dumps(call))
            if "id" in call:
                reply = json.loads(await asyncio.wait_for(ws.recv(), 30))
                body = reply.get("result", reply.get("error"))
                print(f"{call['method']:12} -> {json.dumps(body, ensure_ascii=False)[:160]}", flush=True)
        done.set()

    async with websockets.serve(fake_xiaozhi, "127.0.0.1", 8765):
        proc = subprocess.Popen([sys.executable, "marco_mcp.py", "ws://127.0.0.1:8765"])
        try:
            await asyncio.wait_for(done.wait(), 60)
        finally:
            proc.terminate()


asyncio.run(main())
