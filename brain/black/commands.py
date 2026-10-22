"""Turn a spoken sentence (Portuguese or English) into arm intents.

Keyword rules, no network: fast and predictable on hackathon Wi-Fi. One sentence can hold several
intents ("sobe e abre a garra mais rápido"); they are returned in reading order.
"""
import re
import unicodedata
from dataclasses import dataclass, field

COLORS = {
    "verde": "green", "green": "green",
    "vermelho": "red", "vermelha": "red", "red": "red",
    "azul": "blue", "blue": "blue",
    "amarelo": "yellow", "amarela": "yellow", "yellow": "yellow",
}

# (intent, keywords) — matched on accent-free lowercase words / phrases, in this priority order
RULES = [
    ("stop", ["pare", "parar", "parado", "stop", "chega", "freeze", "segura ai"]),
    ("show", ["show", "danca", "dance", "apresentacao"]),
    ("wave", ["acena", "tchau", "wave", "hello", "oi"]),
    ("invert", ["inverte", "invert", "lado errado", "wrong side"]),
    ("faster", ["aumenta a velocidade", "aumenta", "mais rapido", "rapido", "acelera", "faster", "speed up", "quick"]),
    ("slower", ["diminui a velocidade", "diminui", "reduz", "mais devagar", "devagar", "lento", "desacelera", "slower", "slow down"]),
    ("home", ["em pe", "posicao inicial", "home", "stand up", "levanta tudo"]),
    ("center", ["centro", "meio", "reto", "frente", "center", "straight", "forward"]),
    ("left", ["esquerda", "left"]),
    ("right", ["direita", "right"]),
    ("side", ["lado", "side"]),
    ("up", ["cima", "sobe", "suba", "levanta", "alto", "ceu", "up", "raise", "higher"]),
    ("down", ["baixo", "desce", "desca", "abaixa", "down", "lower"]),
    ("open", ["abre", "abra", "abrir", "open", "solta", "larga", "release", "let go"]),
    ("close", ["fecha", "feche", "fechar", "close", "grab", "pega"]),
    ("spin", ["gira", "roda", "girar", "spin", "rotate", "twist"]),
    ("nod", ["sim", "yes", "nod", "concorda"]),
    ("shake", ["nao", "no", "nega"]),
]


@dataclass
class Intent:
    name: str
    amount: str = "normal"  # little | normal | max
    degrees: float | None = None
    color: str | None = None
    frames: list | None = None  # "keyframes": Claude's own choreography, one pose per entry


@dataclass
class Parsed:
    text: str
    intents: list[Intent] = field(default_factory=list)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def _find(text: str, phrase: str) -> int:
    m = re.search(rf"\b{re.escape(phrase)}\b", text)
    return m.start() if m else -1


def parse(raw: str) -> Parsed:
    text = normalize(raw)
    out = Parsed(text=text)
    if not text:
        return out

    # a lone "para" is "stop"; inside a sentence it is the preposition ("vai para a esquerda")
    if text in ("para", "para para", "para tudo"):
        out.intents.append(Intent("stop"))
        return out

    amount = "normal"
    if re.search(r"\b(pouco|pouquinho|little|bit|slightly)\b", text):
        amount = "little"
    if re.search(r"\b(muito|tudo|maximo|todo|toda|totalmente|completamente|total|inteiro|inteira|ate o fim|"
                 r"ao maximo|o maximo|no talo|de vez|ao extremo|la pro alto|la em cima|la embaixo|no alto|"
                 r"all the way|max|maximum|fully|completely|bastante)\b", text):
        amount = "max"
    degrees = None
    m = re.search(r"\b(\d{1,3})\s*(graus|grau|degrees|degree|deg)\b", text)
    if m:
        degrees = float(m.group(1))

    for word, color in COLORS.items():
        pos = _find(text, word)
        if pos >= 0:
            out.intents.append(Intent("goto_color", color=color))
            # "vai até o verde" is complete on its own; still allow e.g. "abre" in the same sentence
            break

    hits = []
    taken: list[tuple[int, int]] = []
    for name, phrases in RULES:
        for phrase in sorted(phrases, key=len, reverse=True):
            pos = _find(text, phrase)
            if pos < 0:
                continue
            span = (pos, pos + len(phrase))
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue  # already consumed by a longer phrase ("mais rapido" vs "rapido")
            taken.append(span)
            hits.append((pos, name))
            break
    if out.intents and out.intents[0].name == "goto_color":
        hits = [h for h in hits if h[1] not in ("left", "right", "side", "center", "down")]
    if any(name == "stop" for _, name in hits):
        out.intents = [Intent("stop")]  # "stop right now": stopping wins over everything else
        return out
    for _, name in sorted(hits):
        if name == "spin" and amount == "max":
            name = "roll_full"  # "gira o punho todo" = the full turn, not 90 degrees
        out.intents.append(Intent(name, amount=amount, degrees=degrees))
    return out
