"""
Test de résilience de la connexion PostGIS avec FastAPI.
1. Lance FastAPI avec TOURISMO_DATABASE_URL (1 worker, pas de reload).
2. Vérifie GET /health et GET /entities/bab-mansour (base UP).
3. Arrête le conteneur db (docker compose stop db).
4. Tente GET /entities/bab-mansour (base DOWN) -> enregistre l'échec.
5. Redémarre db (docker compose start db) et attend pg_isready.
6. Rappelle GET /entities/bab-mansour (base RESTAURÉE) sur la même instance FastAPI.
7. Arrête FastAPI et sauvegarde les résultats bruts dans data/postgis-proof.json.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UVICORN = str(ROOT / ".venv" / "Scripts" / "uvicorn.exe")
PORT = 8000
DATA_URL = os.environ.get("TOURISMO_DATABASE_URL")

if not DATA_URL:
    print("ERREUR: TOURISMO_DATABASE_URL non configuré dans l'environnement.", file=sys.stderr)
    sys.exit(1)

print(f"Lancement de FastAPI avec TOURISMO_DATABASE_URL (masqué) sur port {PORT}...")
proc = subprocess.Popen(
    [UVICORN, "tourismo.api:app", "--host", "127.0.0.1", f"--port", str(PORT), "--workers", "1"],
    cwd=ROOT,
    env=dict(os.environ),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(f"FastAPI démarré avec PID {proc.pid}")

def wait_health(port, timeout=30):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return json.loads(r.read())
        except Exception:
            pass
        time.sleep(0.2)
    return None

results = {
    "fastapi_pid": proc.pid,
    "db_service": "db",
    "steps": {}
}

try:
    # 1. Attente /health
    health_resp = wait_health(PORT)
    results["steps"]["health"] = {"status_code": 200 if health_resp else None, "response": health_resp}
    print(f"1. GET /health: {health_resp}")

    # 2. GET /entities/bab-mansour avec DB UP
    t0 = time.perf_counter()
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/entities/bab-mansour", timeout=10) as r:
        lat1 = round(time.perf_counter() - t0, 4)
        body1 = json.loads(r.read())
        results["steps"]["entity_db_up"] = {
            "status_code": r.status,
            "latency_seconds": lat1,
            "body": body1
        }
        print(f"2. GET /entities/bab-mansour (DB UP): HTTP {r.status} en {lat1}s")
        print(f"   Name: {body1.get('name')}")
        if body1.get("facts"):
            print(f"   Fait: {body1['facts'][0].get('text')}")
            print(f"   Source: {body1['facts'][0].get('url')}")

    # 3. Arrêt db uniquement
    print("3. Arrêt du conteneur db (docker compose stop db)...")
    subprocess.run(["docker", "compose", "stop", "db"], cwd=ROOT, check=True)

    # 4. GET /entities/bab-mansour avec DB DOWN
    t0 = time.perf_counter()
    status_code_down = None
    err_msg = None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/entities/bab-mansour", timeout=5) as r:
            status_code_down = r.status
            body_down = json.loads(r.read())
    except urllib.error.HTTPError as e:
        status_code_down = e.code
        err_msg = e.read().decode("utf-8", errors="replace")
    except Exception as e:
        err_msg = str(e)
    lat_down = round(time.perf_counter() - t0, 4)
    results["steps"]["entity_db_down"] = {
        "status_code": status_code_down,
        "latency_seconds": lat_down,
        "error": err_msg
    }
    print(f"4. GET /entities/bab-mansour (DB DOWN): HTTP {status_code_down} en {lat_down}s (Erreur: {err_msg[:100]}...)")

    # 5. Redémarrage de db et attente pg_isready
    print("5. Redémarrage du conteneur db (docker compose start db)...")
    subprocess.run(["docker", "compose", "start", "db"], cwd=ROOT, check=True)
    ready = False
    for i in range(30):
        chk = subprocess.run(["docker", "compose", "exec", "db", "pg_isready", "-U", "tourismo", "-d", "tourismo"],
                             cwd=ROOT, capture_output=True, text=True)
        if "accepting connections" in chk.stdout:
            print(f"   PostgreSQL prêt après {i}s")
            ready = True
            break
        time.sleep(1)

    # 6. GET /entities/bab-mansour avec DB RESTAURÉE (même PID FastAPI)
    t0 = time.perf_counter()
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/entities/bab-mansour", timeout=10) as r:
        lat3 = round(time.perf_counter() - t0, 4)
        body3 = json.loads(r.read())
        results["steps"]["entity_db_restored"] = {
            "status_code": r.status,
            "latency_seconds": lat3,
            "body": body3
        }
        print(f"6. GET /entities/bab-mansour (DB RESTAURÉE, même PID {proc.pid}): HTTP {r.status} en {lat3}s")

finally:
    proc.terminate()
    proc.wait(timeout=5)
    print(f"FastAPI (PID {proc.pid}) arrêté.")

out = ROOT / "data" / "postgis-proof.json"
out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Preuve complète écrite dans : {out}")
