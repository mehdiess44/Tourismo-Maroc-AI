"""Run the documented Lot 4 HTTP measures on the real Tourismo FastAPI app.

The database URL is inherited only from the calling process. Production
artifacts stay untouched; each worker sees a separate staged artifact folder.
Only one explicitly selected validation JPEG is opened.
"""

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import onnxruntime as ort
import psutil

from scripts.compare_vision import verify_bundle
from scripts.measure_requests import recognition_ok, send_one


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/lot-4/manifest.json"
IMAGES = ROOT / "workspace-data/lot-4/images"
PREPARED = ROOT / "workspace-data/lot-4/prepared-b-common"
STAGED = ROOT / "workspace-data/lot-4/official-benchmark-stage"
RESULTS = ROOT / "data/lot-4"
PHOTO_ID = "commons-152724069"
PORT = 18005
OUTPUTS = {mode: RESULTS / f"b-{mode}-measure-v2.json" for mode in ("clip", "resnet50")}
CONDITIONS = RESULTS / "b-official-benchmark-conditions-v2.json"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def get_json(url, timeout=2):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, json.load(response)


def wait_health(process):
    deadline = time.monotonic() + 60
    last_error = None
    while process.poll() is None and time.monotonic() < deadline:
        try:
            code, body = get_json(f"http://127.0.0.1:{PORT}/health")
            if code == 200 and body.get("status") == "ok" and body.get("vision_configured"):
                return body
            last_error = f"health HTTP {code}: {body}"
        except (OSError, ValueError) as error:
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(0.1)
    raise RuntimeError(f"Tourismo FastAPI did not become healthy: {last_error}; exit={process.poll()}")


def save_conditions(value):
    CONDITIONS.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_model(mode, photo, photo_path, metadata, conditions):
    stage = STAGED / mode
    stage.mkdir(parents=True, exist_ok=True)
    for suffix, target in ((".onnx", "vision.onnx"), (".json", "vision.json")):
        source = PREPARED / f"{mode}{suffix}"
        destination = stage / target
        if destination.exists():
            if digest(destination) != digest(source):
                raise ValueError(f"Staged artifact changed: {destination}")
        else:
            shutil.copyfile(source, destination)
        if digest(destination) != metadata["files"][source.name]:
            raise ValueError(f"Staged artifact SHA-256 mismatch: {destination}")

    session = ort.InferenceSession(str(stage / "vision.onnx"), providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError(f"Unexpected ONNX providers: {session.get_providers()}")
    del session

    environment = os.environ.copy()
    environment["LOT4_STAGE_ARTIFACTS"] = str(stage)
    environment["LOT4_STAGE_PORT"] = str(PORT)
    worker_code = (
        "import os; from pathlib import Path; import tourismo.store as store; "
        "store.ARTIFACTS=Path(os.environ['LOT4_STAGE_ARTIFACTS']); "
        "from tourismo.api import app; import uvicorn; "
        "app.add_api_route('/lot4-worker-pid',lambda:{'pid':os.getpid()}); "
        "uvicorn.run(app,host='127.0.0.1',port=int(os.environ['LOT4_STAGE_PORT']),workers=1)"
    )
    log_path = RESULTS / f"b-{mode}-worker-v2.log"
    with log_path.open("x", encoding="utf-8") as log:
        started = time.perf_counter()
        process = subprocess.Popen([sys.executable, "-c", worker_code], cwd=ROOT,
                                   env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            health = wait_health(process)
            startup_seconds = time.perf_counter() - started
            pid_code, pid_body = get_json(f"http://127.0.0.1:{PORT}/lot4-worker-pid")
            worker_pid = pid_body.get("pid")
            if pid_code != 200 or not isinstance(worker_pid, int) \
                    or worker_pid == process.pid or not psutil.pid_exists(worker_pid):
                raise RuntimeError(f"Cannot identify distinct FastAPI worker PID: {pid_body}")
            code, entity = get_json(f"http://127.0.0.1:{PORT}/entities/bab-mansour")
            if code != 200 or entity.get("id") != "bab-mansour":
                raise RuntimeError(f"PostGIS entity check failed: HTTP {code}: {entity}")
            warmup = send_one(PORT, photo, photo_path.name)
            if not recognition_ok(warmup) or warmup["body"]["candidates"][0]["id"] != "bab-mansour":
                raise RuntimeError(f"First recognition failed: {warmup}")

            command = [sys.executable, "-m", "scripts.compare_vision", "measure",
                       str(photo_path), str(stage), str(OUTPUTS[mode]),
                       "--port", str(PORT), "--pid", str(worker_pid)]
            completed = subprocess.run(command, cwd=ROOT, env=environment,
                                       capture_output=True, text=True)
            if completed.returncode:
                raise RuntimeError(f"compare_vision measure ({mode}) failed: "
                                   f"{completed.stdout}{completed.stderr}")
            measure = json.loads(OUTPUTS[mode].read_text(encoding="utf-8"))
            if measure["fastapi_pid"] != worker_pid or len(measure["requests"]) != 20 \
                    or measure["model_sha256"] != metadata["files"][f"{mode}.onnx"] \
                    or measure["config_sha256"] != metadata["files"][f"{mode}.json"] \
                    or measure["fastapi_peak_working_set_mib"] < 100:
                raise RuntimeError(f"Official measure integrity check failed: {mode}")
            conditions["models"][mode] = {
                "launcher_pid": process.pid, "fastapi_pid": worker_pid,
                "startup_seconds": startup_seconds,
                "health": health, "postgis_entity_http": code,
                "first_recognition": warmup,
                "onnx_providers": ["CPUExecutionProvider"],
                "measure_file": str(OUTPUTS[mode].relative_to(ROOT)),
                "measure_sha256": digest(OUTPUTS[mode]),
                "worker_log": str(log_path.relative_to(ROOT)),
                "http_successes": measure["http_successes"],
                "usable_responses": measure["biz_successes"],
                "peak_working_set_mib": measure["fastapi_peak_working_set_mib"],
            }
            save_conditions(conditions)
        except Exception as error:
            conditions["models"][mode] = {"error": f"{type(error).__name__}: {error}",
                                          "worker_log": str(log_path.relative_to(ROOT))}
            save_conditions(conditions)
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    if not os.environ.get("TOURISMO_DATABASE_URL"):
        raise RuntimeError("TOURISMO_DATABASE_URL must be supplied in the local session")
    if CONDITIONS.exists() or any(path.exists() for path in OUTPUTS.values()):
        raise FileExistsError("Official benchmark outputs already exist")
    metadata = verify_bundle(MANIFEST, PREPARED)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    matches = [row for row in manifest if row.get("id") == PHOTO_ID]
    if len(matches) != 1 or matches[0].get("partition") != "validation" \
            or matches[0].get("label") != "bab-mansour" \
            or matches[0].get("status") != "approved":
        raise ValueError("Selected photo is not an approved known validation photo")
    photo_path = IMAGES / f"{PHOTO_ID}.jpg"
    photo = photo_path.read_bytes()
    if hashlib.sha256(photo).hexdigest() != matches[0]["sha256"]:
        raise ValueError("Validation photo SHA-256 mismatch")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError(f"Port {PORT} already in use")
    conditions = {
        "utc_started": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                              text=True).strip(),
        "manifest_sha256": metadata["manifest_sha256"],
        "prepared_sha256": digest(PREPARED / "prepared.json"),
        "photo_id": PHOTO_ID, "photo_partition": "validation",
        "photo_sha256": matches[0]["sha256"],
        "platform": platform.platform(), "processor": platform.processor(),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "system_ram_mib": psutil.virtual_memory().total / 1048576,
        "python": sys.version.split()[0], "onnxruntime": ort.__version__,
        "worker_count_per_model": 1, "warm_requests_per_model": 20,
        "port": PORT, "backend": "tourismo.api:app", "postgis": True,
        "warmup_requests_per_model": 1,
        "production_artifacts_unchanged": True,
        "models": {},
    }
    for mode in ("clip", "resnet50"):
        run_model(mode, photo, photo_path, metadata, conditions)
    conditions["utc_completed"] = datetime.now(timezone.utc).isoformat()
    save_conditions(conditions)


if __name__ == "__main__":
    main()
