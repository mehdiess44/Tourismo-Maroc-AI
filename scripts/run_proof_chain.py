"""Record the photo-to-PostGIS acceptance test without exposing connection settings."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from scripts.measure_requests import measure_warm, recognition_ok, send_one
from scripts.measure_startup import stop_worker, wait_health
from tourismo.store import ARTIFACTS, ROOT


def read_entity(port, identifier):
    started = time.perf_counter()
    with urlopen(f"http://127.0.0.1:{port}/entities/{quote(identifier, safe='')}", timeout=10) as response:
        entity = json.load(response)
        return {
            "status_code": response.status,
            "requested_id": identifier,
            "entity": entity,
            "elapsed_seconds": time.perf_counter() - started,
        }


def check_http(port, image, proof):
    proof["invalid_file_test"] = send_one(port, b"ceci n'est pas une image", "faux.txt")
    recognition = send_one(port, image.read_bytes(), image.name)
    proof["first_recognition"] = recognition
    if not recognition_ok(recognition):
        raise RuntimeError("La photo ne produit aucun candidat exploitable.")

    identifiers = [candidate.get("id") for candidate in recognition["body"]["candidates"]]
    proof["bab_mansour_rank"] = next(
        (rank for rank, identifier in enumerate(identifiers, 1) if identifier == "bab-mansour"), None
    )
    top_id = identifiers[0]
    if not top_id:
        raise RuntimeError("Le premier candidat ne contient aucun identifiant.")
    try:
        proof["top_entity_read"] = read_entity(port, top_id)
    except HTTPError as error:
        proof["top_entity_read"] = {"status_code": error.code, "requested_id": top_id}
        raise RuntimeError("Échec HTTP lors de la lecture de la fiche.") from error
    entity = proof["top_entity_read"]["entity"]
    if entity.get("id") != top_id or not entity.get("name"):
        raise RuntimeError("La fiche reçue ne correspond pas au candidat.")
    if proof["invalid_file_test"]["status_code"] != 422:
        raise RuntimeError("Le fichier invalide doit recevoir HTTP 422.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "final-proof.json")
    parser.add_argument("--existing-server", action="store_true", help="Utiliser le conteneur déjà démarré.")
    parser.add_argument("--warm", action="store_true", help="Ajouter 20 appels sur le conteneur.")
    args = parser.parse_args()
    if args.warm and not args.existing_server:
        parser.error("--warm requiert --existing-server.")
    if not args.existing_server and not os.getenv("TOURISMO_DATABASE_URL"):
        parser.error("TOURISMO_DATABASE_URL est requise.")
    paths = (ARTIFACTS / "vision.onnx", ARTIFACTS / "vision.json", args.image)
    proof = {"technical_success": False, "image_name": args.image.name}
    for path, key in zip(paths, ("onnx_sha256", "json_sha256", "image_sha256")):
        if not path.is_file():
            parser.error(f"Fichier introuvable : {path}")
        with path.open("rb") as stream:
            proof[key] = hashlib.file_digest(stream, "sha256").hexdigest()

    proc = None
    try:
        if args.existing_server:
            with urlopen(f"http://127.0.0.1:{args.port}/health", timeout=10) as response:
                proof["health"] = json.load(response)
        else:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", args.port)) == 0:
                    raise RuntimeError(f"Le port {args.port} est déjà utilisé.")
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "tourismo.api:app", "--host", "127.0.0.1",
                 "--port", str(args.port), "--workers", "1"], cwd=ROOT
            )
            proof["fastapi_pid"] = proc.pid
            proof["health"] = wait_health(proc, args.port)
        if not proof["health"].get("vision_configured"):
            raise RuntimeError("La vision n'est pas configurée.")
        check_http(args.port, args.image, proof)
        proof["technical_success"] = True
        if args.warm:
            proof["warm"] = measure_warm(args.port, args.image.read_bytes(), args.image.name, None)
    except (OSError, ValueError, RuntimeError) as error:
        proof["error"] = str(error)
    finally:
        if proc is not None:
            stop_worker(proc)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Preuve enregistrée dans {args.output}")
    return int(not proof["technical_success"] or "error" in proof
           or (args.warm and proof["warm"]["biz_successes"] != 20))


if __name__ == "__main__":
    sys.exit(main())
