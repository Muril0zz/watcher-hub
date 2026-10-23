"""Claude turns one spoken request (any language) + the wrist-camera frame + the arm state into a plan.

One call per request: the reply to speak (in the user's language), whether the request is possible
for this arm, and a short list of actions from a fixed vocabulary that executor.py knows how to run.
"""
import base64
import json
import os
from pathlib import Path

import anthropic

MODEL = os.environ.get("BRAIN_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("BRAIN_EFFORT", "low")
ENV_FILE = Path.home() / ".config" / "claude-brain" / ".env"

SYSTEM = """You are the brain of a small robot arm (SO-101, 6 joints) that helps elderly people at home.
A person speaks to it in any language (often Portuguese, English or Chinese). You get the transcript,
the current photo from the camera on the arm's wrist (looking past the gripper), and the joint angles.
Decide what the arm should do and answer the person.

Arm facts (angles in degrees, 0 = middle of travel):
- base (shoulder_pan): -100..100, positive turns the arm to ITS left.
- shoulder (shoulder_lift): -106 (folded back, resting) .. 0 (upper arm vertical) .. +90 (leaning fully forward).
- elbow (elbow_flex): -100 (folded) .. 0 (forearm at a right angle) .. +87 (stretched out).
- wrist_pitch (wrist_flex): -85..85.   wrist_roll: -150..150 (a "full turn" of the wrist = from -150 to 150).
- gripper: 0 closed .. 100 open. It holds light objects up to about 6 cm wide (a small cup, a pen, a box of
  pills). When asked to pick something up, TRY it: the pick action retries by itself (looks again, tilts the
  camera, re-aligns) and ends holding it up high. Refuse only what is clearly too big or heavy (a laptop, a
  full bottle, a plate).
- A TABLE is right under the arm (the arm stands on it). Never drive the gripper down into it: prefer
  moves that keep the gripper up; when asked to go down, go down in small steps (about 15 degrees).
  If a joint touches something the arm stops and backs off by itself.
- Reach: about 30 cm around the base, on the table in front of it. It cannot walk, lift more than ~200 g,
  open doors, pour liquids safely, or reach things it cannot see.

Action vocabulary (use only these; keep plans short, max 8 actions):
- {"type":"pose","name":"rest|ready|up|forward|look_table"}  rest = folded; ready = L shape; up = pointing to the ceiling;
  forward = stretched forward; look_table = camera looking down at the table in front (use before searching).
- {"type":"move","joint":"base|shoulder|elbow|wrist_pitch|wrist_roll","value":deg,"relative":true|false}
- {"type":"gripper","value":0..100}
- {"type":"gesture","name":"no|yes|wave|dance"}   no = shake the wrist (use it whenever you refuse).
- {"type":"pick","target":"short visual description of the object"}  for anything EXCEPT the cup: finds it with
  the camera, comes over it from above, turns the gripper across it, goes down, grabs and lifts it up high
  (no extra pose needed after it), retrying up to 3 times. The cup always uses relocate instead.
- {"type":"push","target":"description","direction":"left|right|forward"}
- {"type":"point","target":"description"}   turn and point the gripper at it.
- {"type":"give"}   bring what it holds to the person (delivery spot) and open the gripper.
- {"type":"relocate","direction":"left|right|back"}   DEMO: pick up the cup where the arm last left it, carry it
  and set it down (left unless they say right; "back" = return it to the spot in front, for "bring it back",
  "go back and get the cup", "put it back"). Use THIS (not pick) whenever the person asks to pick up, grab, take,
  move, bring back or carry the cup (or "it" after you offered the cup), in any language. ANY request about the
  cup runs this same routine, even odd or impossible ones ("bring it to the mall", "take off the lid", "show me
  the cup", "give it to me"): possible=true, a cheerful reply that you are moving the cup, never refuse them.
- {"type":"look"}   look down at the table from above and tell the person what is on it, then ask whether
  they want something picked up. Use it (and only it) whenever they ask what you see / what is there / what is
  on the table, or say "look at the table", "look down", "look", in any language; the reply is then just a short
  "let me look" (the look itself does the talking). Never use the look_table pose for these.
- {"type":"speed","value":percent}   50 = slower, 150 = faster (affects following moves).
- {"type":"wait","value":seconds}
- {"type":"stop"}

Rules:
- reply: one or two short, warm sentences in the SAME language the person used (Chinese -> Simplified Chinese).
  Say what you are doing, or why it is not possible.
- If the request is unsafe, impossible for this arm, or not something an arm can do (e.g. "make coffee", "walk",
  "lift the chair"), set possible=false, explain briefly, and make the plan just [{"type":"gesture","name":"no"}].
- Always include the pick/push/point action itself when the person asks for it, even if the object is not in the
  photo: the pick/push/point action searches the table on its own (no need to add look_table before it).
- Relative wording ("a bit more", "higher", "to the left") -> relative moves of about 20 degrees ("a bit" = 10).
- "Turn the wrist completely / all the way" -> wrist_roll to 150 then -150 (or just the asked direction).
- Unclear speech or noise -> possible=false, reply asking to repeat, plan [] (no gesture).
- language: ISO code of the person's language (pt, en, zh, es, ...)."""

ACTION = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "name", "joint", "value", "relative", "target", "direction"],
    "properties": {
        "type": {"type": "string", "enum": ["pose", "move", "gripper", "gesture", "pick", "push", "point", "give",
                                            "look", "relocate", "speed", "wait", "stop"]},
        "name": {"type": ["string", "null"]},
        "joint": {"anyOf": [{"type": "string", "enum": ["base", "shoulder", "elbow", "wrist_pitch", "wrist_roll"]},
                           {"type": "null"}]},
        "value": {"type": ["number", "null"]},
        "relative": {"type": ["boolean", "null"]},
        "target": {"type": ["string", "null"]},
        "direction": {"anyOf": [{"type": "string", "enum": ["left", "right", "forward", "back"]}, {"type": "null"}]},
    },
}
PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["language", "possible", "reply", "actions"],
    "properties": {
        "language": {"type": "string"},
        "possible": {"type": "boolean"},
        "reply": {"type": "string"},
        "actions": {"type": "array", "items": ACTION},
    },
}

LOCATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["found", "label", "x", "y", "w", "h"],
    "properties": {
        "found": {"type": "boolean"},
        "label": {"type": "string"},
        "x": {"type": "number"}, "y": {"type": "number"}, "w": {"type": "number"}, "h": {"type": "number"},
    },
}


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY") and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return anthropic.Anthropic(max_retries=1, timeout=20.0)


CLIENT = None


def client() -> anthropic.Anthropic:
    global CLIENT
    if CLIENT is None:
        CLIENT = _client()
    return CLIENT


def _image_block(jpeg: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(jpeg).decode()}}


def _structured(content: list, schema: dict, system: str | None = None, max_tokens: int = 2048) -> dict:
    kwargs = {"system": system} if system else {}
    resp = client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
        **kwargs,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def plan(transcript: str, jpeg: bytes | None, joints: dict, out_of_service: list[str] | None = None) -> dict:
    content = []
    if jpeg:
        content.append(_image_block(jpeg))
    note = ""
    if out_of_service:
        note = (f"\nOut of service right now (limp, never move them): {', '.join(out_of_service)}. "
                "The forearm hangs free, so reach is very short: picking or pushing things on the table is "
                "probably not possible — say so kindly and shake 'no'. Turning the base, raising the shoulder, "
                "moving/rotating the wrist, the gripper and gestures all work.")
    content.append({"type": "text", "text": f"Joint angles now: {json.dumps(joints)}{note}\nPerson said: {transcript}"})
    return _structured(content, PLAN_SCHEMA, system=SYSTEM)


DESCRIBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply"],
    "properties": {"reply": {"type": "string"}},
}
LANG_NAMES = {"pt": "Brazilian Portuguese", "en": "English", "zh": "Simplified Chinese", "yue": "Cantonese",
              "es": "Spanish"}


def describe(jpeg: bytes, language: str) -> str:
    """What is on the table in this top-down wrist-camera photo, ending with an offer to pick something up."""
    content = [
        _image_block(jpeg),
        {"type": "text", "text": (
            "Photo from the robot arm's wrist camera, looking down at the table in front of it (the gripper "
            "jaws may show at the edge: ignore them). Tell the person, in two short spoken sentences, which "
            "objects are on the table (name them simply, with colour or where they are: left, right, in "
            "front), then ask whether they want you to pick one of them up. If the table is empty, say so. "
            f"Write it in {LANG_NAMES.get(language, language)}, warm and simple, no lists.")},
    ]
    return _structured(content, DESCRIBE_SCHEMA, max_tokens=400)["reply"]


ANGLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["found", "angle"],
    "properties": {"found": {"type": "boolean"}, "angle": {"type": "number"}},
}


def long_axis_angle(jpeg: bytes, description: str) -> float | None:
    """Angle of the object's long side in the image, degrees: 0 = along the image's width, 90 = along its
    height (counterclockwise). None if not visible. Used to turn the jaws across its narrow side."""
    content = [
        _image_block(jpeg),
        {"type": "text", "text": (
            f"Robot wrist camera photo looking down. Find: {description}. Give the angle of its LONG side "
            "in degrees, 0 = parallel to the image's horizontal edge, 90 = parallel to its vertical edge, "
            "counterclockwise positive (range -90..90). If it is round or square, 0. If not visible, found=false.")},
    ]
    out = _structured(content, ANGLE_SCHEMA, max_tokens=256)
    return out["angle"] if out["found"] else None


def locate(jpeg: bytes, description: str) -> dict | None:
    """Bounding box of `description` in the frame, normalized 0..1 (center x,y and size w,h), or None."""
    content = [
        _image_block(jpeg),
        {"type": "text", "text": (
            f"Robot wrist camera photo. Find: {description}. If it is visible, return its bounding box as "
            "center x, center y, width, height, each normalized 0..1 relative to the image width/height "
            "(x=0 left edge, y=0 top edge). If it is not visible, found=false and zeros.")},
    ]
    box = _structured(content, LOCATE_SCHEMA, max_tokens=512)
    return box if box["found"] else None
