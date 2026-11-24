"""Final local CLIP recipe on one Tourismo FastAPI worker and PostGIS."""

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psutil

from scripts.measure_requests import recognition_ok, send_one


ROOT = Path(__file__).resolve().parents[1]
PREPARED = ROOT / "workspace-data/lot-4/prepared-b-common"
ARTIFACTS = ROOT / "artifacts"
ARCHIVE = ROOT / "workspace-data/lot-4/archive-vision-before-final-b126d4e"
IMAGES = ROOT / "workspace-data/lot-4/images"
MANIFEST = ROOT / "data/lot-4/manifest.json"
RECIPE = ROOT / "data/lot-4/b-clip-recipe.json"
WARM = ROOT / "data/lot-4/b-clip-warm.json"
LOG = ROOT / "data/lot-4/b-clip-recipe-worker.log"
PORT = 18006


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def get(path):
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return {"status_code": response.status, "body": json.load(response),
                    "elapsed_seconds": time.perf_counter() - started, "error": None}
    except urllib.error.HTTPError as error:
        return {"status_code": error.code,
                "body": error.read().decode("utf-8", errors="replace"),
                "elapsed_seconds": time.perf_counter() - started, "error": str(error)}


def wait_health(process):
    deadline = time.monotonic() + 60
    last_error = None
    while process.poll() is None and time.monotonic() < deadline:
        try:
            response = get("/health")
            if response["status_code"] == 200 and isinstance(response["body"], dict) \
                    and response["body"].get("status") == "ok" \
                    and response["body"].get("vision_configured"):
                return response
            last_error = response
        except (OSError, ValueError) as error:
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(0.1)
    raise RuntimeError(f"FastAPI did not become healthy: {last_error}; exit={process.poll()}")


def photo(identifier, expected_partition):
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    matched = [row for row in rows if row.get("id") == identifier]
    if len(matched) != 1 or matched[0].get("partition") != expected_partition:
        raise ValueError(f"Unexpected photo partition: {identifier}")
    path = IMAGES / f"{identifier}.jpg"
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != matched[0]["sha256"]:
        raise ValueError(f"Photo SHA-256 mismatch: {identifier}")
    return path, content


def save_recipe(report):
    RECIPE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    if not os.environ.get("TOURISMO_DATABASE_URL"):
        raise RuntimeError("Local PostgreSQL connection is required")
    if RECIPE.exists() or WARM.exists() or LOG.exists():
        raise FileExistsError("CLIP recipe output already exists; preserve existing results")
    prepared = json.loads((PREPARED / "prepared.json").read_text(encoding="utf-8"))
    hashes = prepared["files"]
    for source, target in (("clip.onnx", "vision.onnx"), ("clip.json", "vision.json")):
        if sha256(PREPARED / source) != hashes[source] or sha256(ARTIFACTS / target) != hashes[source]:
            raise ValueError(f"Installed CLIP SHA-256 mismatch: {target}")
        if not (ARCHIVE / target).is_file():
            raise FileNotFoundError(f"Archived artifact missing: {target}")
    config = json.loads((ARTIFACTS / "vision.json").read_text(encoding="utf-8"))
    if config.get("method") != "clip" or config.get("thresholds") != {"monument": 0.8774516582489014}:
        raise ValueError("Installed CLIP method or frozen threshold changed")
    known_path, known_bytes = photo("commons-152724069", "validation")
    unknown_path, unknown_bytes = photo("commons-49023822", "test")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError(f"Port {PORT} is already in use")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                     text=True).strip()
    report = {
        "utc_started": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit, "manifest_sha256": prepared["manifest_sha256"],
        "model_sha256": hashes["clip.onnx"], "config_sha256": hashes["clip.json"],
        "archive": str(ARCHIVE.relative_to(ROOT)),
        "backend": "tourismo.api:app", "postgis": True, "worker_count": 1,
        "python": sys.version.split()[0], "platform": platform.platform(),
        "processor": platform.processor(), "port": PORT,
        "known_photo": {"id": known_path.stem, "partition": "validation",
                        "sha256": hashlib.sha256(known_bytes).hexdigest()},
        "unknown_photo": {"id": unknown_path.stem, "partition": "test",
                          "sha256": hashlib.sha256(unknown_bytes).hexdigest()},
        "thresholds": config["thresholds"], "errors": [],
    }
    worker_code = (
        "import os; from tourismo.api import app; from tourismo.vision import load_model; import uvicorn; "
        "app.add_api_route('/lot4-worker-pid',lambda:{'pid':os.getpid()}); "
        "app.add_api_route('/lot4-providers',lambda:{'providers':load_model()[1].get_providers()}); "
        f"uvicorn.run(app,host='127.0.0.1',port={PORT},workers=1)"
    )
    with LOG.open("x", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", worker_code], cwd=ROOT,
                                   env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
        report["launcher_pid"] = process.pid
        try:
            report["health"] = wait_health(process)
            pid_response = get("/lot4-worker-pid")
            worker_pid = pid_response["body"].get("pid")
            if pid_response["status_code"] != 200 or not isinstance(worker_pid, int) \
                    or not psutil.pid_exists(worker_pid) or worker_pid == process.pid:
                raise RuntimeError(f"Cannot identify true FastAPI worker: {pid_response}")
            report["worker_pid"] = worker_pid
            report["onnx_providers"] = get("/lot4-providers")
            if report["onnx_providers"]["status_code"] != 200 \
                    or report["onnx_providers"]["body"].get("providers") != ["CPUExecutionProvider"]:
                raise RuntimeError(f"Unexpected ONNX providers: {report['onnx_providers']}")
            report["invalid_file"] = send_one(PORT, b"not-an-image", "invalid.txt")
            if report["invalid_file"]["status_code"] != 422:
                raise RuntimeError(f"Invalid photo was not rejected: {report['invalid_file']}")

            report["known_recognition"] = send_one(PORT, known_bytes, known_path.name)
            known = report["known_recognition"]
            if not recognition_ok(known) or known["body"]["status"] != "candidate" \
                    or known["body"]["candidates"][0]["id"] != "bab-mansour":
                raise RuntimeError(f"Known recognition failed: {known}")
            identifier = known["body"]["candidates"][0]["id"]
            report["returned_identifier"] = identifier
            report["postgis_entity"] = get("/entities/" + urllib.parse.quote(identifier))
            if report["postgis_entity"]["status_code"] != 200 \
                    or report["postgis_entity"]["body"].get("id") != identifier:
                raise RuntimeError(f"PostGIS entity lookup failed: {report['postgis_entity']}")

            report["unknown_recognition"] = send_one(PORT, unknown_bytes, unknown_path.name)
            if not recognition_ok(report["unknown_recognition"]) \
                    or report["unknown_recognition"]["body"]["status"] != "uncertain":
                raise RuntimeError(f"Unknown photo was not uncertain: {report['unknown_recognition']}")
            query = urllib.parse.urlencode({"q": "Bab Mansour", "kind": "monument"})
            report["manual_search"] = get("/catalog?" + query)
            if report["manual_search"]["status_code"] != 200 \
                    or not any(item.get("id") == "bab-mansour"
                               for item in report["manual_search"]["body"]):
                raise RuntimeError(f"Manual search failed: {report['manual_search']}")

            report["warmup"] = send_one(PORT, known_bytes, known_path.name)
            if not recognition_ok(report["warmup"]):
                raise RuntimeError(f"Warm-up failed: {report['warmup']}")
            command = [sys.executable, "-m", "scripts.compare_vision", "measure",
                       str(known_path), str(ARTIFACTS), str(WARM),
                       "--port", str(PORT), "--pid", str(worker_pid)]
            completed = subprocess.run(command, cwd=ROOT, env=os.environ.copy(),
                                       capture_output=True, text=True)
            if completed.returncode:
                raise RuntimeError(f"Twenty warm requests failed: {completed.stdout}{completed.stderr}")
            warm = json.loads(WARM.read_text(encoding="utf-8"))
            if warm["fastapi_pid"] != worker_pid or len(warm["requests"]) != 20 \
                    or warm["model_sha256"] != hashes["clip.onnx"] \
                    or warm["config_sha256"] != hashes["clip.json"] \
                    or warm["fastapi_peak_working_set_mib"] < 100:
                raise RuntimeError("Warm measure integrity check failed")
            warm.update(git_commit=commit, photo_id=known_path.stem,
                        onnx_providers=["CPUExecutionProvider"],
                        worker_pid=worker_pid)
            WARM.write_text(json.dumps(warm, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            report["warm_file"] = str(WARM.relative_to(ROOT))
            report["warm_sha256"] = sha256(WARM)
            report["warm_summary"] = {key: warm[key] for key in (
                "http_successes", "biz_successes", "median_seconds", "p95_seconds",
                "max_seconds", "fastapi_peak_working_set_mib", "fastapi_pid")}
            report["memory_limit_met"] = warm["fastapi_peak_working_set_mib"] <= 400
            report["warm_latency_limit_met"] = warm["max_seconds"] < 30
            report["utc_completed"] = datetime.now(timezone.utc).isoformat()
        except Exception as error:
            report["errors"].append(f"{type(error).__name__}: {error}")
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            save_recipe(report)


if __name__ == "__main__":
    main()
