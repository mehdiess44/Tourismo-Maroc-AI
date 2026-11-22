import hashlib
import json
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import numpy as np
import onnxruntime
from PIL import Image, ImageOps

from tourismo.store import ARTIFACTS, DATA, ROOT, read_json
from tourismo.vision import preprocess


MODEL = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx"


def fetch(url, location):
    if not location.exists():
        temporary = location.with_suffix(".partial")
        with urlopen(Request(url, headers={"User-Agent": "TourismoMarocAI/0.1 educational pilot"}), timeout=90) as stream:
            with temporary.open("wb") as output:
                while chunk := stream.read(1024 * 1024):
                    output.write(chunk)
        temporary.replace(location)


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    photos = ROOT / "workspace-data" / "images"
    photos.mkdir(parents=True, exist_ok=True)
    config = {
        "method": "clip", "size": 224, "mean": [0.48145466, 0.4578275, 0.40821073],
        "std": [0.26862954, 0.26130258, 0.27577711], "labels": [],
        "gallery": [], "thresholds": {}, "source": MODEL,
    }
    manifest = [
        row for row in read_json(DATA / "photo-candidates.json")
        if row["role"] != "candidate"
    ]
    missing = []
    for row in manifest:
        file = row["file"]
        prefix = hashlib.md5(file.encode("utf-8"), usedforsecurity=False).hexdigest()
        target = photos / (row["id"] + ".jpg")
        try:
            fetch(f"https://upload.wikimedia.org/wikipedia/commons/{prefix[0]}/{prefix[:2]}/{quote(file)}", target)
        except HTTPError as error:
            missing.append(row["id"])
            print(f"{row['id']}: téléchargement indisponible (HTTP {error.code})")
            if error.code == 429:
                break
            continue
        row["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    if missing:
        raise SystemExit("Déposez les originaux manquants dans workspace-data/images, puis relancez.")
    (DATA / "pilot-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    model = ARTIFACTS / "vision.onnx"
    fetch(MODEL, model)
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    session = onnxruntime.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    for row in manifest:
        if row["role"] != "reference":
            continue
        with Image.open(photos / (row["id"] + ".jpg")) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
        embedding = session.run(["image_embeds"], {session.get_inputs()[0].name: preprocess(image, config)})[0].ravel()
        config["gallery"].append((embedding / np.linalg.norm(embedding)).tolist())
        config["labels"].append(row["label"])
    (ARTIFACTS / "vision.json").write_text(json.dumps(config), encoding="utf-8")


if __name__ == "__main__":
    main()
