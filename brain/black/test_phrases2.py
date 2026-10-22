"""Second, harder round: colloquial Portuguese, negation, repeats, stop/speed variants and short
phrases that could fool the instant keyword path. Same routing as the server (test_phrases.route)."""
import sys

sys.argv = sys.argv[:1]
from test_phrases import matches, route  # noqa: E402  (runs the first suite's imports only)

CASES = [
    ("vira no talo pra direita", "pt", [("right", "max")]),
    ("joga tudo pra esquerda", "pt", [("left", "max")]),
    ("lá pro alto", "pt", [("up", "max")]),
    ("pra cima", "pt", [("up", "normal")]),
    ("pra baixo", "pt", [("down", "normal")]),
    ("bem lá embaixo", "pt", [("down", "max")]),
    ("não, pra esquerda não, pra direita", "pt", [("right", "normal")]),
    ("esquerda não, direita", "pt", [("right", "normal")]),
    ("para tudo", "pt", [("stop", None)]),
    ("pare agora", "pt", [("stop", None)]),
    ("chega", "pt", [("stop", None)]),
    ("acelera", "pt", [("faster", None)]),
    ("vai devagarinho", "pt", [("slower", None)]),
    ("devagar pra direita", "pt", [("slower", None), ("right", "normal")]),
    ("abre a mão", "pt", [("open", None)]),
    ("solta", "pt", [("open", None)]),
    ("pega", "pt", [("close", None)]),
    ("fica em pé", "pt", [("home", None)]),
    ("posição inicial", "pt", [("home", None)]),
    ("olha pra frente", "pt", [("center", None)]),
    ("acena com a mão", "pt", [("wave", None)]),
    ("oi robô", "pt", [("wave", None)]),
    ("dança", "pt", [("show", None)]),
    ("vira tudo pra direita e depois tudo pra esquerda", "pt", [("right", "max"), ("left", "max")]),
    ("sobe, desce e sobe de novo", "pt", [("up", "normal"), ("down", "normal"), ("up", "normal")]),
    ("turn right a bit", "en", [("right", "little")]),
    ("slightly to the left", "en", [("left", "little")]),
    ("max left", "en", [("left", "max")]),
    ("all the way down", "en", [("down", "max")]),
    ("lower your arm completely", "en", [("down", "max")]),
    ("stop right now", "en", [("stop", None)]),
    ("say hi", "en", [("wave", None)]),
    ("向右转到底", "zh", [("right", "max")]),
    ("往下一点点", "zh", [("down", "little")]),
    ("停", "zh", [("stop", None)]),
    ("跳个舞", "zh", [("show", None)]),
    ("唔該向左轉少少", "zh", [("left", "little")]),
    ("gira un poco a la izquierda", "es", [("left", "little")]),
    ("थोड़ा ऊपर जाओ", "hi", [("up", "little")]),
]

bad = 0
for text, lang, want in CASES:
    path, got = route(text, lang)
    ok = matches(got, want)
    bad += not ok
    print(f"{'ok ' if ok else 'BAD'} [{path:6}] {text!r:52} -> {got}" + ("" if ok else f"   expected {want}"), flush=True)
print(f"\n{len(CASES) - bad}/{len(CASES)} correct")
