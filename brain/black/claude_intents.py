"""Claude turns anything a person says, in any language, into the black arm's intents + a spoken reply.

The black arm (SO-101 leader on 5 V) has no camera and only a weak trigger instead of a real gripper,
so Claude maps the request onto the small set of moves server.py already knows how to do safely,
or says kindly (in the person's language) that it can't, and shakes 'no'.
"""
import json
import os
from pathlib import Path

import anthropic

# Haiku: 1.7 s avg vs Opus 5.6 s from here (bench_models.py), same intents on the test phrases.
# This call only maps a sentence onto ~20 intents, so speed wins; ARM_MODEL=claude-opus-5-5 to switch back.
MODEL = os.environ.get("ARM_MODEL", "claude-haiku-5-5")
ENV_FILE = Path.home() / ".config" / "claude-brain" / ".env"

INTENTS = ["stop", "show", "wave", "nod", "shake", "home", "center", "left", "right", "side", "up", "down",
           "open", "close", "spin", "roll_full", "wrist_up", "wrist_down", "faster", "slower", "invert",
           "keyframes"]

SYSTEM = """You control a small robot arm (SO-101, 6 joints, on a table) that keeps elderly people company.
People talk to it in any language, with any wording, slang or typos. Turn what they want into a list of
intents from this vocabulary, in order, and write a short spoken reply.

Intents (amount: "little" ~20 deg, "normal" ~50 deg, "max" = all the way; degrees overrides amount.
Moves are deliberately big so an audience can see them; only use "little" when the person asks for a bit):
- left / right: turn the base. side: swing to one side. center: base, wrist and roll back to straight.
- up / down: raise / lower the whole arm. "max" up = pointing at the ceiling, "max" down = its lowest SAFE pose
  (a bow, well above the table: it never touches the table, so "all the way down" is always safe).
- home: stand up straight (default pose). wrist_up / wrist_down: tilt the hand.
- spin: turn the wrist 90 deg. roll_full: turn the wrist completely one way then the other.
- open / close: the hand (a weak trigger, it cannot hold objects).
- wave (hello/goodbye), nod (yes), shake (no), show (a dance/show), faster / slower (speed), stop, invert (swap left/right).
- keyframes: FREE CONTROL of every joint, for ANY movement the intents above don't cover exactly: one joint at
  a time, a numbered joint, diagonals, a snake/wave motion, bending or twisting, a figure, a made-up dance, a pose
  the person describes. Fill "frames": poses played in order, each with the joints to move (null = keep it) and
  "seconds" for that step (fast 0.5, normal 1.2, slow 2.5). Max 40 frames. People name the joints like this:
    base = turns the whole arm: POSITIVE = LEFT (+95), 0 = front, NEGATIVE = RIGHT (-95), same as left/right
    number 1 / joint 1 = shoulder: -30 (leaning back) .. 0 (upper arm vertical) .. +38 (leaning forward, lowest)
    number 2 / joint 2 = elbow: -100 (forearm folded up, pointing at the ceiling) .. -40 (forearm down, lowest)
    number 3 / joint 3 = wrist bend: -60 (hand down) .. 0 (straight) .. +60 (hand up)
    number 4 / joint 4 = wrist turn: -170 .. +170 (end to end is a full turn)
    hand = gripper: 0 closed .. 100 open
  "up"/"down" on 1 or 2 raises/lowers that segment; "all the way" = the end of its range; "a bit" ~15 from
  where it is; otherwise ~40% of the range. These ranges are safe (the table is never reached); stay inside them.
  "Every joint"/"each joint" = all six: base, 1, 2, 3, 4 and hand. "One joint at a time" = each frame changes ONE joint. "Back and forth" = alternate the two ends. A snake =
  frames where base, 1, 3 and 4 swing in alternating directions. Don't add a final "go back" frame unless asked.
  Requests made only of the simple moves (left, right, up, down, center, wave, open, spin..., also several in a
  row like "all the way right then all the way left") use the simple intents, NOT keyframes. Use keyframes
  when a joint is named or numbered, or for diagonals, snakes, figures, bends, or anything the simple moves can't do.
  For every intent other than keyframes, frames is null.

The arm has NO camera and cannot see, pick up, carry, push or fetch anything, cannot leave the table, and
cannot do household tasks. For those: possible=false, explain kindly in one sentence, and use [shake].
Combine intents for compound requests ("go all the way up then wave" -> up max, wave).
Slang for "all the way": no talo, até o talo, de vez, até onde der, ao extremo -> amount "max".
Corrections replace what came before: "esquerda não, direita" / "not left, right" -> only [right].
The text comes from speech recognition and may be Cantonese, sometimes transcribed with Mandarin-style or
phonetically wrong characters: guess the intent from how it sounds before giving up. If the person speaks
Cantonese (e.g. 唔, 嘅, 咗, 喺, 啲, 係, 冇, 佢, 嚟), set language "yue" and reply in written Cantonese with
Traditional characters; Mandarin speakers get language "zh" and Simplified Chinese.
This runs at a busy public event: the microphone also catches side conversations, laughter, other people,
music and speech-recognition junk ("Thank you.", "Obrigado.", subtitles credits, single random words).
for_robot=false when the text is NOT a request to the arm (chatting with someone else, comments, noise,
greetings to other people, unrelated sentences): then intents [] and reply "" and the arm stays silent.
Be strict: only for_robot=true when it is plausibly an instruction or a question to the robot.
Unclear speech that does look like it was meant for the robot: possible=false, ask to repeat, intents [].

reply: one short warm sentence in the SAME language and script the person used (Chinese -> Simplified Chinese).
Never switch language: Portuguese words (articulação, cada, vez, junta, cobrinha) mean a Portuguese reply.
language: ISO code (pt, en, zh, yue, es, hi, ...)."""

_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}
FRAME = {
    "type": "object",
    "additionalProperties": False,
    "required": ["base", "shoulder", "elbow", "wrist", "roll", "hand", "seconds"],
    "properties": {"base": _NUM, "shoulder": _NUM, "elbow": _NUM, "wrist": _NUM, "roll": _NUM, "hand": _NUM,
                   "seconds": {"type": "number"}},
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["for_robot", "language", "possible", "reply", "intents"],
    "properties": {
        "for_robot": {"type": "boolean"},
        "language": {"type": "string"},
        "possible": {"type": "boolean"},
        "reply": {"type": "string"},
        "intents": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "amount", "degrees", "frames"],
                "properties": {
                    "name": {"type": "string", "enum": INTENTS},
                    "amount": {"type": "string", "enum": ["little", "normal", "max"]},
                    "degrees": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "frames": {"anyOf": [{"type": "array", "items": FRAME}, {"type": "null"}]},
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


CANTONESE_WORDS = ("唔", "嘅", "咗", "喺", "啲", "係", "冇", "佢", "嚟", "咁", "哋", "嘢", "乜", "點樣", "跟住", "畀", "睇", "嗰")
TRADITIONAL = set("邊轉揮們這說個來時對過還後會頭裡麼東車問開關見點動們讓請聽電話隻轉")


def speech_hint(text: str) -> str:
    """Whisper calls Cantonese 'zh'; its wording and Traditional characters give it away."""
    if any(w in text for w in CANTONESE_WORDS) or sum(ch in TRADITIONAL for ch in text) >= 2:
        return "\n(The speech recognizer heard Cantonese: reply in Cantonese, language yue.)"
    return ""


ADDRESSED_NOTE = ("\n(Heard by the robot's own microphone right after its wake word 'Marco', so it IS meant for the "
                  "robot. Its speech recognizer often mishears: map sound-alikes to the closest command, e.g. "
                  "'grow right' -> go right, 'turn lift' -> turn left, 'way of' -> wave. 'Marco'/'Mark' is just its name.)")


def plan(text: str, addressed: bool = False) -> dict:
    text = text + speech_hint(text) + (ADDRESSED_NOTE if addressed else "")
    resp = client().messages.create(
        model=MODEL,
        max_tokens=4000,  # a 40-frame choreography is ~3k tokens
        system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": text}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def keep_warm(every: float = 20.0):
    """Free request every few seconds so the TLS connection to the API stays open (opening one from
    here costs ~2 s, which otherwise lands on the next spoken command)."""
    import time

    while True:
        try:
            client().models.list(limit=1)
        except Exception:
            pass
        time.sleep(every)
