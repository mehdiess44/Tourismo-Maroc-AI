"""Measure twenty requests against an already warmed FastAPI worker."""
import argparse
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from statistics import median

import psutil
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def send_one(port, image_bytes, filename="photo.jpg"):
    boundary = b"----TourismoMeasure"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="kind"\r\n\r\nmonument\r\n'
        b"--" + boundary + b"\r\n"
        + f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode()
        + b"Content-Type: image/jpeg\r\n\r\n"
        + image_bytes
        + b"\r\n--" + boundary + b"--\r\n"
    )
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/recognitions",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
            elapsed = round(time.perf_counter() - t0, 3)
            return {"status_code": r.status, "body": resp, "elapsed_seconds": elapsed, "error": None}
    except urllib.error.HTTPError as error:
        elapsed = round(time.perf_counter() - t0, 3)
        try:
            body = json.load(error)
        except ValueError:
            body = None
        return {"status_code": error.code, "body": body, "elapsed_seconds": elapsed, "error": str(error)}
    except (OSError, ValueError) as e:
        elapsed = round(time.perf_counter() - t0, 3)
        return {"status_code": None, "body": None, "elapsed_seconds": elapsed, "error": str(e)}


def recognition_ok(result):
    body = result.get("body")
    return (
        result.get("status_code") == 200
        and isinstance(body, dict)
        and body.get("status") in {"candidate", "uncertain"}
        and bool(body.get("candidates"))
    )


def measure_warm(port, image, filename, pid):
    measures = [send_one(port, image, filename) for _ in range(20)]
    elapsed = sorted(row["elapsed_seconds"] for row in measures)
    memory = psutil.Process(pid).memory_info() if pid is not None else None
    peak = getattr(memory, "peak_wset", None)
    return {
        "requests": measures,
        "http_successes": sum(row["status_code"] == 200 for row in measures),
        "biz_successes": sum(recognition_ok(row) for row in measures),
        "median_seconds": median(elapsed),
        "p95_seconds": elapsed[18],
        "max_seconds": elapsed[-1],
        "fastapi_pid": pid,
        "fastapi_peak_working_set_mib": round(peak / 1048576, 1) if peak is not None else None,
        "fastapi_final_rss_mib": round(memory.rss / 1048576, 1) if memory is not None else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "workspace-data" / "warm-measures.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path)
    source.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    if args.image:
        if not args.image.is_file():
            parser.error(f"Fichier introuvable : {args.image}")
        image, filename = args.image.read_bytes(), args.image.name
    else:
        buffer = io.BytesIO()
        Image.new("RGB", (640, 480), "gray").save(buffer, format="JPEG")
        image, filename = buffer.getvalue(), "synthetic.jpg"

    summary = measure_warm(args.port, image, filename, args.pid)
    summary["image"] = filename
    summary["image_mode"] = "real" if args.image else "synthetic"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Mesures à chaud enregistrées dans {args.output}")


if __name__ == "__main__":
    main()
