#!/usr/bin/env python3
"""loadtest.py — N people ask at once. Reports per-person tokens/s, wall time, and the GPU queue while it ran.
   python3 loadtest.py https://demo.instockornot.club nfcu PASSWORD 15 [question] [persona]
Runs against the AUDIENCE door (clamped sessions, like the room will have). Needs only the standard library."""
import base64, json, sys, threading, time, urllib.request

base, user, pw, n = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], int(sys.argv[4])
question = sys.argv[5] if len(sys.argv) > 5 else "Monty Hall, but the host opens a door at random and it happens to be a goat. Should I switch?"
persona = sys.argv[6] if len(sys.argv) > 6 else "wall"          # e.g. explain = "Show your steps": long answers, hits the 600-token cap
auth = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()

def call(path, body=None, timeout=300):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": auth, "Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

results, queue_samples, stop = [], [], False
def one(i):
    try:
        sid = call("/api/session", {"mode": "compact", "board": True, "peek": True, "persona": persona, "max_tokens": 10000})["session_id"]
        t0 = time.time(); t = call("/api/turn", {"session_id": sid, "text": question, "name": f"load{i:02d}"})["turn"]; dt = time.time() - t0
        results.append({"i": i, "tokens": len(t["tokens"]), "wall": round(dt, 1), "model_s": t["seconds"], "tps": round(len(t["tokens"]) / max(dt, .01), 1), "cut": t.get("cut")})
    except Exception as e:
        results.append({"i": i, "error": f"{type(e).__name__}: {e}"})
def sample():
    while not stop:
        try: queue_samples.append(call("/api/queue")["queue"])
        except Exception: pass
        time.sleep(1)

print(f"== {n} people ask at once: {question[:60]!r}")
threading.Thread(target=sample, daemon=True).start()
T0 = time.time(); ths = [threading.Thread(target=one, args=(i,)) for i in range(n)]
[t.start() for t in ths]; [t.join() for t in ths]; stop = True
total = time.time() - T0
ok = [r for r in results if "tokens" in r]; bad = [r for r in results if "error" in r]
for r in sorted(results, key=lambda r: r["i"]):
    print(f"   {r['i']:2d}  " + (f"{r['tokens']:4d} tokens  {r['wall']:5.1f}s wall  {r['tps']:5.1f} tok/s" + ("  CUT" if r["cut"] else "") if "tokens" in r else r["error"]))
if ok:
    print(f"== all done in {total:.1f}s · per person: median {sorted(r['tps'] for r in ok)[len(ok)//2]} tok/s, slowest {min(r['tps'] for r in ok)} tok/s, "
          f"longest wait {max(r['wall'] for r in ok)}s · aggregate {sum(r['tokens'] for r in ok)/total:.0f} tok/s")
qs = [q for q in queue_samples if q]
if qs:
    print(f"== GPU queue: peak running {max(q['running'] for q in qs)}, peak waiting {max(q['waiting'] for q in qs)}, peak KV cache {max(q['kv_pct'] for q in qs)}%")
if bad:
    print(f"== {len(bad)} FAILED")
