"""Free-control phrases through Claude (no arm needed): each must come back as keyframes whose frames
stay inside the safe ranges and move the joint the person named. Usage: python test_keyframes.py"""
from claude_intents import plan
from routing import fast_intents

RANGES = {"base": (-95, 95), "shoulder": (-30, 38), "elbow": (-100, -40), "wrist": (-60, 60), "roll": (-170, 170),
          "hand": (0, 100)}

# phrase -> check(frames) on the joints that must move
CASES = {
    "move number 2 all the way down": lambda fr: fr[-1]["elbow"] is not None and fr[-1]["elbow"] >= -45,
    "move number 2 all the way up": lambda fr: fr[-1]["elbow"] is not None and fr[-1]["elbow"] <= -95,
    "número 1 todo pra frente": lambda fr: fr[-1]["shoulder"] is not None and fr[-1]["shoulder"] >= 30,
    "number 3 down": lambda fr: fr[-1]["wrist"] is not None and fr[-1]["wrist"] < 0,
    "gira o número 4 até o fim": lambda fr: fr[-1]["roll"] is not None and abs(fr[-1]["roll"]) >= 150,
    "faz uma cobrinha": lambda fr: len(fr) >= 4,
    "dobra cada articulação uma de cada vez": lambda fr: len(fr) >= 4 and all(
        sum(f[k] is not None for k in RANGES) <= 2 for f in fr),
    "go diagonal, base left and number 1 forward at the same time": lambda fr: any(
        f["base"] and f["base"] > 0 and f["shoulder"] and f["shoulder"] > 10 for f in fr),
    "junta 3 pra cima e pra baixo três vezes": lambda fr: len(fr) >= 5 and all(f["wrist"] is not None for f in fr),
    "faz um oito no ar com a mão": lambda fr: len(fr) >= 4,
}

ok = 0
for text, check in CASES.items():
    assert fast_intents(text, "pt") is None or "abre" in text, f"fast path took {text!r}"
    out = plan(text)
    kf = [i for i in out["intents"] if i["name"] == "keyframes"]
    frames = [f for i in kf for f in (i["frames"] or [])]
    inside = all(v is None or RANGES[k][0] <= v <= RANGES[k][1] for f in frames for k, v in f.items() if k in RANGES)
    good = bool(frames) and inside and check(frames)
    ok += good
    names = [i["name"] for i in out["intents"]]
    print(f"{'ok ' if good else 'BAD'} {text!r:62} -> {names} {len(frames)} frames, inside={inside}  {out['reply']}")
    if not good:
        for f in frames:
            print("      ", {k: v for k, v in f.items() if v is not None})
print(f"\n{ok}/{len(CASES)} correct")
