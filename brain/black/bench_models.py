"""Latency of the intent call per model (same prompt/schema as the server), 3 runs each after a warm-up."""
import time

import claude_intents

PHRASES = ["desce tudo pra baixo", "向左转一点", "go up a little and wave"]
for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"):
    claude_intents.MODEL = model
    claude_intents.plan("oi")  # warm the connection
    times = []
    for p in PHRASES:
        t = time.time()
        out = claude_intents.plan(p)
        times.append(time.time() - t)
        print(f"{model:18} {times[-1]:4.1f}s {p!r:28} -> {[i['name'] + ':' + i['amount'] for i in out['intents']]}", flush=True)
    print(f"{model:18} avg {sum(times) / len(times):.1f}s\n", flush=True)
