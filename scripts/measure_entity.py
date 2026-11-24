"""
Mesure la latence de GET /entities/{id} sur un serveur FastAPI actif.
Enregistre 10 appels successifs et calcule médiane et max.

Usage :
    python scripts/measure_entity.py [--port 8000] [--id bab-mansour]

Sortie : data/entity-measures.json
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--id", default="bab-mansour")
args = parser.parse_args()

measures = []
entity_body = None
for i in range(10):
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/entities/{args.id}", timeout=10) as r:
            body = json.loads(r.read())
            elapsed = round(time.perf_counter() - t0, 4)
            measures.append({"seq": i + 1, "status_code": r.status, "elapsed_seconds": elapsed})
            if entity_body is None:
                entity_body = body
                print(f"[{i+1:02d}] HTTP 200 en {elapsed:.4f}s")
                print(f"  id={body.get('id')}  name={body.get('name')}")
                facts = body.get("facts", [])
                if facts:
                    print(f"  fait: {facts[0].get('text','')[:80]}")
                    print(f"  source: {facts[0].get('url','')}")
            else:
                print(f"[{i+1:02d}] HTTP 200 en {elapsed:.4f}s")
    except Exception as e:
        elapsed = round(time.perf_counter() - t0, 4)
        measures.append({"seq": i + 1, "status_code": None, "elapsed_seconds": elapsed, "error": str(e)})
        print(f"[{i+1:02d}] ERREUR {elapsed:.4f}s : {e}")

latencies = [m["elapsed_seconds"] for m in measures if m.get("status_code") == 200]
latencies_s = sorted(latencies)
n = len(latencies_s)
median = latencies_s[n // 2] if n % 2 == 1 else (
    (latencies_s[n // 2 - 1] + latencies_s[n // 2]) / 2 if n >= 2 else None
)

result = {
    "entity_id": args.id,
    "calls": 10,
    "http_successes": n,
    "median_seconds": round(median, 4) if median is not None else None,
    "max_seconds": round(max(latencies_s), 4) if latencies_s else None,
    "latencies_ordered": [m["elapsed_seconds"] for m in measures],
    "entity_name": entity_body.get("name") if entity_body else None,
    "first_fact": entity_body.get("facts", [{}])[0].get("text") if entity_body else None,
    "first_fact_url": entity_body.get("facts", [{}])[0].get("url") if entity_body else None,
}

out = ROOT / "data" / "entity-measures.json"
out.write_text(json.dumps(result, indent=2), encoding="utf-8")
print("\n" + json.dumps(result, indent=2))
print(f"\nFichier écrit : {out}")
