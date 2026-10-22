"""Noise handling: silence / faint noise must be dropped before Whisper, real commands must pass, and
side conversations must be marked not-for-robot by Claude (the arm stays still and silent)."""
import io
import wave

import numpy as np

import claude_intents
import speech

TMP = "/Users/muriloleitefilho/.claude/jobs/1c0fc05f/tmp/"


def wav_bytes(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


rng = np.random.default_rng(0)
clips = {
    "silence 2s": wav_bytes(np.zeros(32000)),
    "faint hiss 2s": wav_bytes(rng.normal(0, 0.002, 32000)),
    "click 0.2s": wav_bytes(rng.normal(0, 0.3, 3200)),
}
for name, data in clips.items():
    text, _ = speech.transcribe(data, ".wav")
    print(f"{'ok ' if not text else 'BAD'} {name:16} -> {text!r} (should be dropped)")
for name in ("pt", "en", "zh", "hi", "yue"):
    text, lang = speech.transcribe(open(TMP + name + ".aiff", "rb").read(), ".aiff")
    print(f"{'ok ' if text else 'BAD'} real {name:11} -> [{lang}] {text!r} (should pass)")

CHATTER = ["ontem eu fui no mercado e comprei pão", "hahaha que engraçado", "ele falou que a comida tava boa",
           "can you pass me the charger, Mike?", "我们等一下去吃饭吧", "Thank you."]
COMMANDS = ["robô, vira pra esquerda", "can you wave at me?", "请把手臂举起来"]
for t in CHATTER:
    p = claude_intents.plan(t)
    print(f"{'ok ' if not p['for_robot'] else 'BAD'} chatter {t!r:42} -> for_robot={p['for_robot']} {p['intents']}")
for t in COMMANDS:
    p = claude_intents.plan(t)
    print(f"{'ok ' if p['for_robot'] else 'BAD'} command {t!r:42} -> for_robot={p['for_robot']} {[i['name'] for i in p['intents']]}")
