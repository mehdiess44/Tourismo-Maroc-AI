"""CPU-only technical smoke test of pretrained ResNet-50 and its ONNX export.

This is an ImageNet prototype. It does not train or evaluate Tourismo labels.
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
import torchvision
from PIL import Image, ImageOps
from torchvision.models import ResNet50_Weights, resnet50


SEED = 42
WEIGHTS = ResNet50_Weights.IMAGENET1K_V2


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(manifest_path, images_dir, onnx_path, report_path):
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(2)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    smoke = [row for row in manifest if row.get("role") == "smoke"]
    if not smoke:
        raise ValueError("No pilot smoke images found")

    model = resnet50(weights=WEIGHTS).to("cpu").eval()
    transform = WEIGHTS.transforms()
    samples = []
    for row in smoke:
        path = images_dir / (row["id"] + ".jpg")
        if sha256(path) != row["sha256"]:
            raise ValueError(f"Pilot image hash mismatch: {path}")
        with Image.open(path) as source:
            tensor = transform(ImageOps.exif_transpose(source).convert("RGB"))
        if tuple(tensor.shape) != (3, 224, 224) or not torch.isfinite(tensor).all():
            raise ValueError(f"Invalid input tensor: {path}")
        samples.append((path.name, row["sha256"], tensor.unsqueeze(0)))

    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        torch.onnx.export(
            model, samples[0][2], str(onnx_path), input_names=["pixel_values"],
            output_names=["logits"], opset_version=17, dynamo=False,
            dynamic_axes={"pixel_values": {0: "batch"}, "logits": {0: "batch"}},
        )
    onnx.checker.check_model(str(onnx_path))

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(onnx_path), sess_options=options,
                                   providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError(f"Unexpected ONNX providers: {session.get_providers()}")

    comparisons = []
    for name, image_hash, tensor in samples:
        with torch.inference_mode():
            pt = model(tensor).cpu().numpy()
        ox = session.run(["logits"], {"pixel_values": tensor.numpy()})[0]
        if pt.shape != ox.shape or pt.shape != (1, 1000):
            raise ValueError(f"Output shape mismatch for {name}: {pt.shape} / {ox.shape}")
        if not np.isfinite(pt).all() or not np.isfinite(ox).all():
            raise ValueError(f"Non-finite output for {name}")
        difference = np.abs(pt - ox)
        pt_top1 = int(np.argmax(pt[0]))
        ox_top1 = int(np.argmax(ox[0]))
        comparisons.append({
            "image": name, "image_sha256": image_hash,
            "input_shape": list(tensor.shape), "output_shape": list(pt.shape),
            "pytorch_top1_imagenet_index": pt_top1,
            "onnx_top1_imagenet_index": ox_top1,
            "top1_agrees": pt_top1 == ox_top1,
            "max_abs_logit_difference": float(difference.max()),
            "mean_abs_logit_difference": float(difference.mean()),
            "pytorch_finite": True, "onnx_finite": True,
        })

    weights_path = Path(torch.hub.get_dir()) / "checkpoints" / Path(WEIGHTS.url).name
    report = {
        "prototype_only": True,
        "git_commit": None,
        "seed": SEED,
        "python": __import__("sys").version.split()[0],
        "torch": torch.__version__, "torchvision": torchvision.__version__,
        "onnx": onnx.__version__, "onnxruntime": ort.__version__,
        "weights": WEIGHTS.name, "weights_url": WEIGHTS.url,
        "weights_sha256": sha256(weights_path),
        "preprocessing": {
            "source": "torchvision ResNet50_Weights.IMAGENET1K_V2.transforms()",
            "resize": 232, "center_crop": 224, "interpolation": "bilinear",
            "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
            "color": "RGB", "exif_transpose": True,
        },
        "device": "cpu", "onnx_providers": session.get_providers(),
        "onnx_opset": 17, "onnx_path": str(onnx_path),
        "onnx_sha256": sha256(onnx_path),
        "comparisons": comparisons,
    }
    import subprocess
    report["git_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/pilot-manifest.json"))
    parser.add_argument("--images", type=Path, default=Path("workspace-data/images"))
    parser.add_argument("--onnx", type=Path,
                        default=Path("artifacts/lot-4-prototype-resnet50-imagenet-v2.onnx"))
    parser.add_argument("--report", type=Path,
                        default=Path("data/lot-4/b-resnet50-prototype.json"))
    args = parser.parse_args()
    result = run(args.manifest, args.images, args.onnx, args.report)
    print(json.dumps({"onnx_providers": result["onnx_providers"],
                      "comparisons": result["comparisons"]}, ensure_ascii=False))
