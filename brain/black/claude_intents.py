"""Claude turns anything a person says, in any language, into the black arm's intents + a spoken reply.

The black arm (SO-101 leader on 5 V) has no camera and only a weak trigger instead of a real gripper,
so Claude maps the request onto the small set of moves server.py already knows how to do safely,
or says kindly (in the person's language) that it can't, and shakes 'no'.
"""
import json
import os
from pathlib import Path

import anthropic

MODEL = os.environ.get("ARM_MODEL", "claude-opus-5-5")
ENV_FILE = Path.home() / ".config" / "claude-brain" / ".env"

INTENTS = ["stop", "show", "wave", "nod", "shake", "home", "center", "left", "right", "side", "up", "down",
           "open", "close", "spin", "roll_full", "wrist_up", "wrist_down", "faster", "slower", "invert"]

SYSTEM = """You control a small robot arm (SO-101, 6 joints, on a table) that keeps elderly people company.
People talk to it in any language, with any wording, slang or typos. Turn what they want into a list of
intents from this vocabulary, in order, and write a short spoken reply.

Intents (amount: "little" ~10 deg, "normal" ~25 deg, "max" = all the way; degrees overrides amount):
- left / right: turn the base. side: swing to one side. center: base, wrist and roll back to straight.
- up / down: raise / lower the whole arm. "max" up = pointing at the ceiling, "max" down = its lowest SAFE pose
  (a bow, well above the table: it never touches the table, so "all the way down" is always safe).
- home: stand up straight (default pose). wrist_up / wrist_down: tilt the hand.
- spin: turn the wrist 90 deg. roll_full: turn the wrist completely one way then the other.
- open / close: the hand (a weak trigger, it cannot hold objects).
- wave (hello/goodbye), nod (yes), shake (no), show (a dance/show), faster / slower (speed), stop, invert (swap left/right).

The arm has NO camera and cannot see, pick up, carry, push or fetch anything, cannot leave the table, and
cannot do household tasks. For those: possible=false, explain kindly in one sentence, and use [shake].
Combine intents for compound requests ("go all the way up then wave" -> up max, wave).
Unclear speech: possible=false, ask to repeat, intents [].

reply: one short warm sentence in the SAME language and script the person used (Chinese -> Simplified Chinese).
language: ISO code (pt, en, zh, es, ...)."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["language", "possible", "reply", "intents"],
    "properties": {
        "language": {"type": "string"},
        "possible": {"type": "boolean"},
        "reply": {"type": "string"},
        "intents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "amount", "degrees"],
                "properties": {
                    "name": {"type": "string", "enum": INTENTS},
                    "amount": {"type": "string", "enum": ["little", "normal", "max"]},
                    "degrees": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                },
            },
        },
    },
}

_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY") and ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        _client = anthropic.Anthropic(max_retries=1, timeout=20.0)
    return _client


def plan(text: str) -> dict:
    resp = client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": text}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))
