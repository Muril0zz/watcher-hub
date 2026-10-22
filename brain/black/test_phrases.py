"""Double-check that spoken commands become the right intents AND the right size, through the same
routing the server uses (instant keyword path for very short pt/en commands, Claude otherwise).
No arm needed. Usage: python test_phrases.py"""
import re

import claude_intents
from routing import fast_intents

# (phrase, language Whisper would report, expected [(intent, amount or degrees)])
CASES = [
    # --- size words, pt ---
    ("vira pra direita", "pt", [("right", "normal")]),
    ("vira um pouco pra direita", "pt", [("right", "little")]),
    ("vá totalmente para a direita", "pt", [("right", "max")]),
    ("vai tudo pra esquerda", "pt", [("left", "max")]),
    ("gira até o fim pra esquerda", "pt", [("left", "max")]),
    ("vira o máximo que der pra direita", "pt", [("right", "max")]),
    ("esquerda", "pt", [("left", "normal")]),
    ("sobe", "pt", [("up", "normal")]),
    ("sobe tudo", "pt", [("up", "max")]),
    ("sobe um pouquinho", "pt", [("up", "little")]),
    ("desce tudo", "pt", [("down", "max")]),
    ("desce até o fim", "pt", [("down", "max")]),
    ("abaixa totalmente o braço", "pt", [("down", "max")]),
    ("levanta o braço até o teto", "pt", [("up", "max")]),
    ("desce só um pouquinho", "pt", [("down", "little")]),
    ("vira 30 graus pra esquerda", "pt", [("left", 30)]),
    # --- other intents, pt ---
    ("abre a garra", "pt", [("open", None)]),
    ("fecha a mão", "pt", [("close", None)]),
    ("gira o punho todo", "pt", [("roll_full", None)]),
    ("acena pra mim", "pt", [("wave", None)]),
    ("dá tchau", "pt", [("wave", None)]),
    ("faz que sim", "pt", [("nod", None)]),
    ("faz que não", "pt", [("shake", None)]),
    ("volta pro centro", "pt", [("center", None)]),
    ("mais rápido", "pt", [("faster", None)]),
    ("mais devagar", "pt", [("slower", None)]),
    ("faz o show", "pt", [("show", None)]),
    ("vira pra direita e depois sobe tudo", "pt", [("right", "normal"), ("up", "max")]),
    # --- en ---
    ("turn all the way right", "en", [("right", "max")]),
    ("go down a little", "en", [("down", "little")]),
    ("raise it fully", "en", [("up", "max")]),
    ("turn left", "en", [("left", "normal")]),
    ("wave goodbye", "en", [("wave", None)]),
    # --- zh / yue / es / hi ---
    ("完全向右转", "zh", [("right", "max")]),
    ("向左转一点", "zh", [("left", "little")]),
    ("把手臂放到最低", "zh", [("down", "max")]),
    ("举到最高", "zh", [("up", "max")]),
    ("向右轉到盡", "zh", [("right", "max")]),
    ("舉高少少", "zh", [("up", "little")]),
    ("gira todo a la derecha", "es", [("right", "max")]),
    ("पूरा दाईं ओर घूमो", "hi", [("right", "max")]),
]


def route(text: str, lang: str):
    intents = fast_intents(text, lang)
    if intents is not None:
        return "fast", [(i.name, i.degrees or i.amount) for i in intents]
    p = claude_intents.plan(text)
    if not p.get("for_robot", True):
        return "ignored", []
    return "claude", [(i["name"], i["degrees"] or i["amount"]) for i in p["intents"]]


def matches(got, want) -> bool:
    if len(got) != len(want):
        return False
    for (gn, gs), (wn, ws) in zip(got, want):
        if gn != wn:
            return False
        if ws is not None and str(gs) != str(ws) and not (isinstance(ws, int) and abs(float(gs) - ws) < 1):
            return False
    return True


if __name__ == "__main__":
    bad = 0
    for text, lang, want in CASES:
        path, got = route(text, lang)
        ok = matches(got, want)
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} [{path:6}] {text!r:44} -> {got}" + ("" if ok else f"   expected {want}"), flush=True)
    print(f"\n{len(CASES) - bad}/{len(CASES)} correct")
