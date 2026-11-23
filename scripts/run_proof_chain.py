"""
Script d'exécution et de validation de la chaîne complète pour le Membre B / Démonstration finale.
Prérequis :
  - vision.onnx et vision.json dans artifacts/
  - Photo d'essai dans workspace-data/images/bab-mansour-essai.jpg (ou passée en argument)
  - PostGIS actif (docker compose up -d db) avec données chargées

Séquence :
  1. Vérification des artefacts et calcul des SHA-256
  2. Test unitaire benchmark_cpu sur la photo
  3. Lancement de FastAPI avec TOURISMO_DATABASE_URL
  4. Test requête invalide (422) suivi d'une requête valide
  5. Envoi photo à POST /recognitions -> analyse candidat n°1 et rang bab-mansour
  6. Appel GET /entities/{id_candidat} pour vérifier l'ouverture de fiche
  7. Enregistrement des preuves dans data/final-proof.json
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DATA = ROOT / "data"

parser = argparse.ArgumentParser(description="Chaîne de recette complète Lot 3")
parser.add_argument("--image", type=Path, required=True, help="Vraie photo d'essai de Bab Mansour")
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()
if not os.getenv("TOURISMO_DATABASE_URL"):
    parser.error("TOURISMO_DATABASE_URL est requise pour la lecture dans PostGIS.")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()

print("=" * 60)
print("TOURISMO AI - LOT 3 : VALIDATION CHAÎNE COMPLÈTE")
print("=" * 60)

# 1. Contrôles des fichiers
onnx_file = ARTIFACTS / "vision.onnx"
json_file = ARTIFACTS / "vision.json"
img_file = args.image

if not onnx_file.is_file():
    print(f"BLOQUANT : vision.onnx introuvable dans {onnx_file}", file=sys.stderr)
    sys.exit(1)
if not json_file.is_file():
    print(f"BLOQUANT : vision.json introuvable dans {json_file}. Attente livraison Membre B.", file=sys.stderr)
    sys.exit(1)
if not img_file.is_file():
    print(f"BLOQUANT : Photo d'essai introuvable : {img_file}", file=sys.stderr)
    sys.exit(1)

print(f"✓ vision.onnx : {onnx_file.stat().st_size} octets | SHA-256: {sha256_file(onnx_file)}")
print(f"✓ vision.json : {json_file.stat().st_size} octets | SHA-256: {sha256_file(json_file)}")
print(f"✓ Photo essai : {img_file.name} ({img_file.stat().st_size} octets) | SHA-256: {sha256_file(img_file)}")

# 2. Benchmark CPU unitaire
print("\n--- 2. Exécution scripts.benchmark_cpu sur la photo ---")
cmd_bench = [sys.executable, "-m", "scripts.benchmark_cpu", "--image", str(img_file)]
res_bench = subprocess.run(cmd_bench, cwd=ROOT, capture_output=True, text=True)
if res_bench.returncode != 0:
    print(f"Erreur benchmark_cpu: {res_bench.stderr}", file=sys.stderr)
else:
    print(res_bench.stdout)

# 3. Lancement FastAPI
print(f"\n--- 3. Lancement FastAPI sur le port {args.port} ---")
uvicorn_exe = str(ROOT / ".venv" / "Scripts" / "uvicorn.exe")
proc = subprocess.Popen(
    [uvicorn_exe, "tourismo.api:app", "--host", "127.0.0.1", f"--port", str(args.port), "--workers", "1"],
    cwd=ROOT,
    env=dict(os.environ),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(f"FastAPI actif - PID {proc.pid}")

proof = {
    "onnx_sha256": sha256_file(onnx_file),
    "json_sha256": sha256_file(json_file),
    "image_sha256": sha256_file(img_file),
    "image_name": img_file.name,
    "fastapi_pid": proc.pid
}

def send_photo(port, photo_bytes, filename="photo.jpg", kind="monument"):
    boundary = b"----TourismoBoundary"
    body = (
        b"--" + boundary + b"\r\n"
        + f'Content-Disposition: form-data; name="kind"\r\n\r\n{kind}\r\n'.encode()
        + b"--" + boundary + b"\r\n"
        + f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode()
        + b"Content-Type: image/jpeg\r\n\r\n"
        + photo_bytes
        + b"\r\n--" + boundary + b"--\r\n"
    )
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/recognitions",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
            "Content-Length": str(len(body))
        },
        method="POST"
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read()), round(time.perf_counter() - t0, 4)

try:
    time.sleep(3)
    # Health check
    with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=5) as r:
        h_body = json.loads(r.read())
        print(f"GET /health: HTTP {r.status} -> {h_body}")
        proof["health"] = h_body

    # 4. Test fichier invalide (texte au lieu d'une photo)
    print("\n--- 4. Test fichier invalide (attendu 422) suivi d'une requête valide ---")
    try:
        status_inv, body_inv, lat_inv = send_photo(args.port, b"ceci n'est pas une image", filename="faux.txt")
        proof["invalid_file_test"] = {"status_code": status_inv, "body": body_inv}
        print(f"Réponse inattendue pour le fichier invalide : HTTP {status_inv}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        proof["invalid_file_test"] = {"status_code": e.code, "detail": detail}
        print(f"Réponse au fichier invalide : HTTP {e.code}")

    # Immédiatement requête valide
    photo_bytes = img_file.read_bytes()
    status_rec, body_rec, lat_rec = send_photo(args.port, photo_bytes, filename=img_file.name)
    print(f"✓ Requête valide immédiate : HTTP {status_rec} en {lat_rec}s")
    print(f"   Réponse : {body_rec}")
    proof["first_recognition"] = {"status_code": status_rec, "body": body_rec, "latency_seconds": lat_rec}

    # 5. Contrôle du premier candidat et ouverture de la fiche
    candidates = body_rec.get("candidates", [])
    if body_rec.get("status") not in {"candidate", "uncertain"} or not candidates:
        print("ÉCHEC DE LA PREUVE : aucun candidat retourné !", file=sys.stderr)
        proof["proof_verdict"] = "ÉCHEC : candidates vide"
    else:
        top_id = candidates[0].get("id")
        top_score = candidates[0].get("score")
        print(f"\n--- 5. Premier candidat : {top_id} (score: {top_score}) ---")
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/entities/{top_id}", timeout=5) as r:
            ent_body = json.loads(r.read())
            print(f"✓ Fiche {top_id} lue avec succès : HTTP {r.status}")
            print(f"   Nom : {ent_body.get('name')}")
            proof["top_entity_read"] = {"status_code": r.status, "entity": ent_body}

        if proof["invalid_file_test"]["status_code"] != 422:
            proof["proof_verdict"] = "ÉCHEC : le fichier invalide doit être rejeté avec HTTP 422"
        elif top_id == "bab-mansour" and ent_body.get("id") == top_id:
            print("✓ BAB MANSOUR CLASSÉ EN RANG 1 !")
            proof["proof_verdict"] = "SUCCÈS : Bab Mansour reconnu et fiche lue"
        else:
            ranks = [c.get("id") for c in candidates]
            print(f"Rang bab-mansour : {ranks.index('bab-mansour') + 1 if 'bab-mansour' in ranks else 'Hors top 3'}")
            proof["proof_verdict"] = f"Candidat {top_id} en rang 1, Bab Mansour rang {ranks.index('bab-mansour') + 1 if 'bab-mansour' in ranks else 'non classé'}"

finally:
    proc.terminate()
    proc.wait(timeout=5)
    print(f"\nFastAPI (PID {proc.pid}) arrêté.")

out_proof = DATA / "final-proof.json"
out_proof.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Rapport de preuve écrit dans : {out_proof}")
sys.exit(0 if proof["proof_verdict"].startswith("SUCCÈS") else 1)
