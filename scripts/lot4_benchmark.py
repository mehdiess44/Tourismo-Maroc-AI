"""Isolated, single-worker HTTP benchmark for frozen Lot 4 CLIP and ResNet-50.

Run only after A's CLIP gallery and B's ResNet validation thresholds are frozen.
The same approved validation photos are sent in the same order to each model.
This does not change production artifacts or connect to PostGIS.
"""

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from statistics import median

import numpy as np
import onnxruntime as ort
import psutil
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image

from tourismo.vision import decode, preprocess as clip_preprocess, rank


app = FastAPI(title="Lot 4 isolated CPU benchmark")
STATE = {}
ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resnet_preprocess(image):
    """PIL/NumPy equivalent of torchvision IMAGENET1K_V2 PIL transform."""
    width, height = image.size
    if width <= height:
        size = (232, int(232 * height / width))
    else:
        size = (int(232 * width / height), 232)
    scaled = image.resize(size, Image.Resampling.BILINEAR)
    left = round((size[0] - 224) / 2)
    top = round((size[1] - 224) / 2)
    cropped = scaled.crop((left, top, left + 224, top + 224))
    pixels = np.asarray(cropped, dtype=np.float32) / np.float32(255.0)
    mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
    return ((pixels - mean) / std).transpose(2, 0, 1)[None].astype(np.float32)


def load_state():
    if STATE:
        return STATE
    mode = os.environ["LOT4_BENCHMARK_MODEL"]
    config = json.loads(Path(os.environ["LOT4_BENCHMARK_CONFIG"]).read_text(encoding="utf-8"))
    model_path = Path(os.environ["LOT4_BENCHMARK_ONNX"])
    kinds = json.loads(os.environ["LOT4_BENCHMARK_KINDS"])
    if config.get("method", "resnet50") != mode:
        raise ValueError("Model method and benchmark mode disagree")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model_path), sess_options=options,
                                   providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("CPUExecutionProvider is required")
    STATE.update(mode=mode, config=config, model_path=model_path,
                 kinds=kinds, session=session)
    return STATE


@app.get("/health")
def health():
    state = load_state()
    return {"status": "ok", "model": state["mode"],
            "providers": state["session"].get_providers(),
            "onnx_sha256": sha256(state["model_path"])}


@app.post("/recognitions")
def recognition(kind: str = Form(), photo: UploadFile = File()):
    state = load_state()
    if kind not in set(state["kinds"].values()):
        raise HTTPException(422, "Unknown kind")
    try:
        image = decode(photo.file.read())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    config, session = state["config"], state["session"]
    tensor = clip_preprocess(image, config) if state["mode"] == "clip" else resnet_preprocess(image)
    output = session.run(None, {session.get_inputs()[0].name: tensor})[0].ravel()
    if not np.isfinite(output).all():
        raise HTTPException(500, "Non-finite model output")
    if state["mode"] == "clip":
        vector = output / max(float(np.linalg.norm(output)), 1e-12)
        values = np.asarray(config["gallery"], dtype=np.float32) @ vector
    else:
        values = output
    eligible = {label for label, label_kind in state["kinds"].items() if label_kind == kind}
    return rank(values, config, kind, eligible)


def photo_path(row, images_dir):
    root = images_dir.resolve()
    relative = row.get("file") or row["id"] + ".jpg"
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Photo outside image directory: {relative}")
    if sha256(path).lower() != row["sha256"].lower():
        raise ValueError(f"Photo SHA-256 mismatch: {relative}")
    return path


def request(port, row, content):
    boundary = b"----TourismoLot4Benchmark"
    payload = (b"--" + boundary + b"\r\n"
               + b'Content-Disposition: form-data; name="kind"\r\n\r\n'
               + row["kind"].encode("utf-8") + b"\r\n"
               + b"--" + boundary + b"\r\n"
               + b'Content-Disposition: form-data; name="photo"; filename="photo.jpg"\r\n'
               + b"Content-Type: image/jpeg\r\n\r\n" + content
               + b"\r\n--" + boundary + b"--\r\n")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/recognitions", data=payload,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary.decode()},
                                 method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            result = json.load(response)
            status = response.status
            error = None
    except urllib.error.HTTPError as problem:
        status = problem.code
        result = problem.read().decode("utf-8", errors="replace")
        error = str(problem)
    except (OSError, ValueError) as problem:
        status, result, error = None, None, str(problem)
    return {"id": row["id"], "kind": row["kind"], "status_code": status,
            "body": result, "seconds": time.perf_counter() - started, "error": error}


def wait_health(process, port):
    deadline = time.monotonic() + 60
    while process.poll() is None and time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                return json.load(response)
        except (OSError, ValueError):
            time.sleep(0.1)
    raise RuntimeError("Benchmark worker did not become healthy")


def run_worker(mode, model_path, config_path, kinds, plan, port, log_path):
    environment = os.environ.copy()
    environment.pop("TOURISMO_DATABASE_URL", None)
    environment.pop("TOURISMO_DB_PASSWORD", None)
    environment.update(LOT4_BENCHMARK_MODEL=mode, LOT4_BENCHMARK_ONNX=str(model_path.resolve()),
                       LOT4_BENCHMARK_CONFIG=str(config_path.resolve()),
                       LOT4_BENCHMARK_KINDS=json.dumps(kinds))
    result = None
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "scripts.lot4_benchmark:app",
                                    "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
                                   cwd=ROOT, env=environment, stdout=log,
                                   stderr=subprocess.STDOUT)
        try:
            health_result = wait_health(process, port)
            if health_result["providers"] != ["CPUExecutionProvider"]:
                raise RuntimeError("Worker did not use CPUExecutionProvider")
            warmup = request(port, plan[0][0], plan[0][1])
            if warmup["status_code"] != 200:
                raise RuntimeError(f"Warm-up failed: {warmup['error']}")
            results = [request(port, row, content) for row, content in plan]
            latencies = sorted(result["seconds"] for result in results)
            memory = psutil.Process(process.pid).memory_info()
            peak = getattr(memory, "peak_wset", None)
            result = {"model": mode, "health": health_result, "pid": process.pid,
                      "warmup": warmup, "requests": results,
                      "http_successes": sum(item["status_code"] == 200 for item in results),
                      "usable_responses": sum(item["status_code"] == 200
                                              and isinstance(item["body"], dict)
                                              and item["body"].get("status") in ("candidate", "uncertain")
                                              and bool(item["body"].get("candidates")) for item in results),
                      "median_seconds": median(latencies), "p95_seconds": latencies[18],
                      "max_seconds": latencies[-1],
                      "peak_working_set_mib": peak / 1048576 if peak is not None else None,
                      "memory_limit_met": peak is not None and peak <= 400 * 1048576,
                      "warm_latency_limit_met": max(latencies) < 30,
                      "log": str(log_path)}
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    # Windows can release the subprocess log handle just after process exit.
    time.sleep(0.25)
    return result


def benchmark(args):
    from scripts.lot4_resnet50_phases import manifest_rows

    if not os.path.isfile(args.clip_onnx) or not os.path.isfile(args.clip_config):
        raise FileNotFoundError("Frozen CLIP artifacts required")
    resnet_model = args.resnet_artifacts / "resnet50.onnx"
    resnet_config = args.resnet_artifacts / "resnet50-calibrated.json"
    if not resnet_model.is_file() or not resnet_config.is_file():
        raise FileNotFoundError("Calibrated ResNet artifacts required")
    rows, kinds, manifest_sha, _ = manifest_rows(args.manifest, args.manifest_sha256)
    selected = sorted((row for row in rows if row["partition"] == "validation"),
                      key=lambda row: row["id"])
    if not selected:
        raise ValueError("No approved validation photos")
    clip = json.loads(args.clip_config.read_text(encoding="utf-8"))
    resnet = json.loads(resnet_config.read_text(encoding="utf-8"))
    if clip.get("method") != "clip" or set(clip["labels"]) != set(kinds) \
            or not all(kind in clip.get("thresholds", {}) for kind in set(kinds.values())):
        raise ValueError("CLIP classes or validation thresholds do not match the manifest")
    if resnet.get("phase") != "calibrated_on_validation" \
            or resnet["manifest_sha256"] != manifest_sha \
            or resnet["labels"] != sorted(kinds) or resnet["kinds"] != kinds \
            or not all(kind in resnet["thresholds"] for kind in set(kinds.values())) \
            or sha256(resnet_model) != resnet["onnx_sha256"]:
        raise ValueError("ResNet artifacts do not match the frozen validation")
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite benchmark: {args.output}")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            raise RuntimeError(f"Port {args.port} is already in use")
    samples = [(row, photo_path(row, args.images).read_bytes()) for row in selected]
    plan = [samples[index % len(samples)] for index in range(20)]
    report = {"scope": "validation_http_benchmark", "manifest_sha256": manifest_sha,
              "sample_ids": [row["id"] for row, _ in plan],
              "sample_sha256": [row["sha256"] for row, _ in plan],
              "worker_count": 1, "requests_per_model": 20, "port": args.port,
              "platform": platform.platform(), "processor": platform.processor(),
              "python": sys.version.split()[0], "onnxruntime": ort.__version__,
              "numpy": np.__version__, "psutil": psutil.__version__,
              "artifact_sha256": {"clip_onnx": sha256(args.clip_onnx),
                                  "clip_config": sha256(args.clip_config),
                                  "resnet_onnx": sha256(resnet_model),
                                  "resnet_config": sha256(resnet_config)},
              "models": {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for mode, onnx_path, config_path in (("clip", args.clip_onnx, args.clip_config),
                                         ("resnet50", resnet_model, resnet_config)):
        try:
            report["models"][mode] = run_worker(
                mode, onnx_path, config_path, kinds, plan, args.port,
                args.output.parent / f"{mode}-benchmark.log")
        except Exception as problem:
            report["models"][mode] = {"error": f"{type(problem).__name__}: {problem}"}
            raise
        finally:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--clip-onnx", type=Path, required=True)
    parser.add_argument("--clip-config", type=Path, required=True)
    parser.add_argument("--resnet-artifacts", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18004)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args)
    if any(item["usable_responses"] != 20 or not item["memory_limit_met"]
           or not item["warm_latency_limit_met"] for item in report["models"].values()):
        raise SystemExit("Benchmark incomplete or outside limits; inspect saved raw responses")


if __name__ == "__main__":
    main()
