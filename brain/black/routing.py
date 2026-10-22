"""Which spoken commands may skip Claude: shared by server.py and the phrase tests so they never drift.

The instant keyword path is only for very short, plain pt/en commands it fully understands. Anything
longer, negated ("esquerda não, direita") or in another language goes to Claude.
"""
import re

from commands import parse

FAST_MAX_WORDS = 4
NEGATION = re.compile(r"\b(nao|não|not|don't|dont|no)\b", re.IGNORECASE)
# a named or numbered joint ("number 2 down", "junta 3", "cotovelo") is free control: Claude's keyframes
JOINT_WORDS = re.compile(r"\b(number|numero|número|joint|junta|articula\w*|base|ombro|shoulder|cotovelo|elbow|"
                         r"cobr\w*|snake|diagonal)\b", re.IGNORECASE)


def fast_intents(text: str, lang: str):
    """Intents for the instant path, or None when the sentence must go to Claude."""
    if len(text.split()) > FAST_MAX_WORDS or (lang or "pt")[:2] not in ("pt", "en"):
        return None
    if NEGATION.search(text) and len(text.split()) > 1:
        return None
    if JOINT_WORDS.search(text):
        return None
    intents = parse(text).intents
    if not intents or any(i.name == "goto_color" for i in intents):
        return None
    return intents
