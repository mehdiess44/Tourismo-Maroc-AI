"""Measure three cold starts, then twenty warm recognitions on the last worker."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from statistics import median
from urllib.error import URLError
from urllib.request import urlopen

import psutil
from PIL import Image

from scripts.measure_requests import measure_warm, recognition_ok, send_one
from tourismo.store import ARTIFACTS, ROOT


def wait_health(proc, port):
    deadline = time.perf_counter() + 60
    while proc.poll() is None and time.perf_counter() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                return json.load(response)
        except (URLError, OSError):
            time.sleep(0.1)
    raise RuntimeError("FastAPI n’a pas répondu à /health après le démarrage.")


def stop_worker(proc):
    if proc.poll() is None:
        for child in psutil.Process(proc.pid).children(recursive=True):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def measure(port, image_path):
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Le port {port} est déjà utilisé.")

    image = image_path.read_bytes()
    runs = []
    warm = None
    for trial in range(1, 4):
        started = time.perf_counter()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tourismo.api:app",
             "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        run = {"run": trial, "pid": proc.pid}
        runs.append(run)
        try:
            run["health"] = wait_health(proc, port)
            run["startup_seconds"] = time.perf_counter() - started
            children = psutil.Process(proc.pid).children()
            worker_pid = children[0].pid if len(children) == 1 else proc.pid
            run["pid"] = worker_pid
            if not run["health"].get("vision_configured"):
                raise RuntimeError("Les artefacts ne sont pas disponibles dans FastAPI.")
            cold = send_one(port, image, image_path.name)
            run["cold_recognition"] = cold
            peak = getattr(psutil.Process(worker_pid).memory_info(), "peak_wset", None)
            run["fastapi_peak_working_set_mib"] = round(peak / 1048576, 1) if peak is not None else None
            if trial == 3 and recognition_ok(cold):
                warm = measure_warm(port, image, image_path.name, worker_pid)
        except RuntimeError as error:
            run["error"] = str(error)
        finally:
            stop_worker(proc)

    startups = [run["startup_seconds"] for run in runs if "startup_seconds" in run]
    cold_successes = [
        run["cold_recognition"]["elapsed_seconds"] for run in runs
        if recognition_ok(run.get("cold_recognition", {}))
    ]
    with Image.open(image_path) as picture:
        dimensions = picture.size
    config = json.loads((ARTIFACTS / "vision.json").read_text(encoding="utf-8"))
    hashes = {}
    for name in ("vision.onnx", "vision.json"):
        with (ARTIFACTS / name).open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "image": image_path.name,
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "image_dimensions": dimensions,
        "reference_count": len(config.get("gallery", [])),
        "artifact_sha256": hashes,
        "runs": runs,
        "median_startup_seconds": median(startups) if startups else None,
        "cold_successes": len(cold_successes),
        "median_cold_seconds": median(cold_successes) if len(cold_successes) == 3 else None,
        "warm": warm,
        "postgis_used": True,  # /health calls catalog() with the required database URL.
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "workspace-data" / "lot-3-measures.json")
    args = parser.parse_args()
    if not os.getenv("TOURISMO_DATABASE_URL"):
        parser.error("TOURISMO_DATABASE_URL est requise pour la mesure avec PostGIS.")
    for path in (args.image, ARTIFACTS / "vision.json", ARTIFACTS / "vision.onnx"):
        if not path.is_file():
            parser.error(f"Fichier introuvable : {path}")

    try:
        summary = measure(args.port, args.image)
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Mesures enregistrées dans {args.output}")
    warm = summary["warm"]
    if summary["cold_successes"] != 3 or warm is None or warm["biz_successes"] != 20:
        print("Série incomplète : consulter les réponses et les erreurs dans le rapport.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
