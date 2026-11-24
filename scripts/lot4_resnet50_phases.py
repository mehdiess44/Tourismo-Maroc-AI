"""Lot 4 CPU ResNet-50: train, validate, then evaluate frozen test artifacts.

The only provisional part is adapt_manifest(). Confirm its schema with member A
before any definitive run. No command here is run automatically.
"""

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from PIL import Image, ImageOps

from scripts.lot4_resnet50_prototype import SEED, WEIGHTS, sha256


PREPROCESSING = {
    "source": "torchvision ResNet50_Weights.IMAGENET1K_V2.transforms()",
    "resize": 232, "center_crop": 224, "interpolation": "bilinear",
    "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
    "color": "RGB", "exif_transpose": True,
}


def adapt_manifest(document):
    """Provisional adapter boundary; update only this function for A's schema.

    Expects {"photos": [...], "class_decisions": [...]}. Photo fields match
    scripts.compare_vision, with optional `file` relative to --images. Each
    decision has `label`, `kind`, and boolean `admissible`. No decision is
    inferred from counts or from a photo's presence.
    """
    if not isinstance(document, dict) or not isinstance(document.get("photos"), list) \
            or not isinstance(document.get("class_decisions"), list):
        raise ValueError("Manifest schema unconfirmed: adapt_manifest() needs photos and class_decisions")
    rows = document["photos"]
    decisions = document["class_decisions"]
    if not rows or not decisions:
        raise ValueError("Manifest photos and class decisions must be nonempty")
    return rows, decisions


def manifest_rows(path, expected_sha):
    if len(expected_sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_sha):
        raise ValueError("Expected manifest SHA-256 must be 64 hex characters")
    actual_sha = sha256(path)
    if actual_sha.lower() != expected_sha.lower():
        raise ValueError(f"Manifest SHA-256 mismatch: {actual_sha}")
    rows, decisions = adapt_manifest(json.loads(path.read_text(encoding="utf-8")))

    decision_map = {}
    for decision in decisions:
        label = decision.get("label")
        kind = decision.get("kind")
        admissible = decision.get("admissible")
        if not isinstance(label, str) or not label or not isinstance(kind, str) or not kind \
                or not isinstance(admissible, bool):
            raise ValueError(f"Incomplete class decision: {label}")
        if label in decision_map:
            raise ValueError(f"Duplicate class decision: {label}")
        decision_map[label] = {"kind": kind, "admissible": admissible}

    ids, groups, hashes = set(), {}, {}
    approved = []
    for row in rows:
        if row.get("status") != "approved":
            continue
        if not all(isinstance(row.get(key), str) and row[key] for key in
                   ("id", "partition", "group", "sha256", "kind")):
            raise ValueError(f"Incomplete approved photo: {row.get('id')}")
        if row["partition"] not in ("train", "validation", "test"):
            raise ValueError(f"Invalid partition: {row['id']}")
        if len(row["sha256"]) != 64 or any(c not in "0123456789abcdefABCDEF" for c in row["sha256"]):
            raise ValueError(f"Invalid photo SHA-256: {row['id']}")
        if row["id"] in ids:
            raise ValueError(f"Duplicate photo id: {row['id']}")
        ids.add(row["id"])
        for mapping, key in ((groups, row["group"]), (hashes, row["sha256"])):
            if mapping.setdefault(key, row["partition"]) != row["partition"]:
                raise ValueError(f"Cross-partition leakage: {key}")
        label = row.get("label")
        if label is not None:
            if label not in decision_map:
                raise ValueError(f"Missing class decision: {label}")
            if decision_map[label]["kind"] != row["kind"]:
                raise ValueError(f"Class kind mismatch: {row['id']}")
        elif row["partition"] == "train":
            raise ValueError(f"Unknown photo in train: {row['id']}")
        approved.append(row)
    if not approved:
        raise ValueError("No approved photos")

    eligible = {label: item["kind"] for label, item in decision_map.items()
                if item["admissible"]}
    if not eligible:
        raise ValueError("No admissible class")
    active = [row for row in approved if row.get("label") is None and row["kind"] in eligible.values()
              or row.get("label") in eligible]
    excluded = [row["id"] for row in approved if row not in active]
    for label in eligible:
        if not any(row["partition"] == "train" and row.get("label") == label for row in active):
            raise ValueError(f"Admissible class has no train photo: {label}")
    return active, eligible, actual_sha, excluded


def image_tensor(row, images_dir, transform):
    root = images_dir.resolve()
    relative = row.get("file") or row["id"] + ".jpg"
    if not isinstance(relative, str):
        raise ValueError(f"Invalid image path: {row['id']}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Photo outside image directory: {relative}")
    if sha256(path).lower() != row["sha256"].lower():
        raise ValueError(f"Photo SHA-256 mismatch: {relative}")
    with Image.open(path) as source:
        tensor = transform(ImageOps.exif_transpose(source).convert("RGB"))
    if tuple(tensor.shape) != (3, 224, 224) or not bool(np.isfinite(tensor.numpy()).all()):
        raise ValueError(f"Invalid input tensor: {relative}")
    return tensor.unsqueeze(0).numpy()


def cpu_session(path):
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(path), sess_options=options,
                                   providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError(f"Unexpected ONNX providers: {session.get_providers()}")
    return session


def candidate(kind, values, labels, kinds):
    eligible = [(label, float(value)) for label, value in zip(labels, values, strict=True)
                if kinds[label] == kind]
    if not eligible:
        raise ValueError(f"No admissible class for kind: {kind}")
    return min(eligible, key=lambda pair: (-pair[1], pair[0]))


def infer_rows(rows, images_dir, transform, session, labels, kinds, torch_model=None):
    records = []
    for row in rows:
        tensor = image_tensor(row, images_dir, transform)
        logits = session.run(["logits"], {"pixel_values": tensor})[0]
        if logits.shape != (1, len(labels)) or not np.isfinite(logits).all():
            raise ValueError(f"Invalid ONNX output: {row['id']}")
        first, score = candidate(row["kind"], logits[0], labels, kinds)
        record = {"id": row["id"], "partition": row["partition"],
                  "kind": row["kind"], "expected": row.get("label"),
                  "onnx_top1": first, "onnx_score": score}
        if torch_model is not None:
            import torch
            with torch.inference_mode():
                torch_logits = torch_model(torch.from_numpy(tensor)).cpu().numpy()
            if torch_logits.shape != logits.shape or not np.isfinite(torch_logits).all():
                raise ValueError(f"Invalid PyTorch output: {row['id']}")
            torch_first, torch_score = candidate(row["kind"], torch_logits[0], labels, kinds)
            record.update({"pytorch_top1": torch_first, "pytorch_score": torch_score,
                           "top1_agrees": torch_first == first,
                           "max_abs_logit_difference": float(np.max(np.abs(torch_logits - logits)))})
        records.append(record)
    return records


def calibrate(records, kinds):
    """Choose abstention thresholds only from validation ONNX logits."""
    if not records or any(row["partition"] != "validation" for row in records):
        raise ValueError("Calibration accepts validation records only")
    by_kind = defaultdict(list)
    for row in records:
        if not math.isfinite(row["onnx_score"]):
            raise ValueError(f"Non-finite score: {row['id']}")
        by_kind[row["kind"]].append(row)
    thresholds = {}
    for kind in sorted(set(kinds.values())):
        group = by_kind[kind]
        if not group or not any(row["expected"] is None for row in group):
            raise ValueError(f"Validation requires unknowns for kind: {kind}")
        candidates = {row["onnx_score"] for row in group}
        candidates.add(max(candidates) + 1.0)
        thresholds[kind] = max(candidates, key=lambda cutoff: (
            sum((row["onnx_top1"] if row["onnx_score"] >= cutoff else None) == row["expected"]
                for row in group), cutoff))
    return thresholds


def refuse_existing(*paths):
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite frozen output: {existing}")


def train(args):
    import torch
    import torchvision
    from torchvision.models import resnet50

    rows, kinds, manifest_sha, excluded = manifest_rows(args.manifest, args.manifest_sha256)
    train_rows = [row for row in rows if row["partition"] == "train"]
    labels = sorted(kinds)
    model_path = args.output / "resnet50.onnx"
    head_path = args.output / "resnet50-head.pt"
    config_path = args.output / "resnet50-trained.json"
    refuse_existing(model_path, head_path, config_path)
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(2)
    transform = WEIGHTS.transforms()
    model = resnet50(weights=WEIGHTS).to("cpu").eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    feature_count = model.fc.in_features
    model.fc = torch.nn.Identity()
    with torch.inference_mode():
        features = [model(torch.from_numpy(image_tensor(row, args.images, transform)))
                    for row in train_rows]  # Never opens validation or test images.
    x = torch.cat(features).detach().clone()
    y = torch.tensor([labels.index(row["label"]) for row in train_rows])
    model.fc = torch.nn.Linear(feature_count, len(labels)).to("cpu")
    optimizer = torch.optim.AdamW(model.fc.parameters(), lr=0.005)
    for _ in range(60):
        optimizer.zero_grad()
        torch.nn.functional.cross_entropy(model.fc(x), y).backward()
        optimizer.step()
    model.eval()
    args.output.mkdir(parents=True, exist_ok=True)
    torch.save(model.fc.state_dict(), head_path)
    torch.onnx.export(model, torch.zeros(1, 3, 224, 224), str(model_path),
                      input_names=["pixel_values"], output_names=["logits"],
                      opset_version=17, dynamo=False,
                      dynamic_axes={"pixel_values": {0: "batch"}, "logits": {0: "batch"}})
    onnx.checker.check_model(str(model_path))
    session = cpu_session(model_path)
    if session.get_outputs()[0].shape[-1] != len(labels):
        raise ValueError("Exported output dimension differs from label count")
    weights_path = Path(torch.hub.get_dir()) / "checkpoints" / Path(WEIGHTS.url).name
    config = {"phase": "trained_on_train", "manifest_sha256": manifest_sha,
              "labels": labels, "kinds": kinds, "thresholds": None,
              "seed": SEED, "weights": WEIGHTS.name, "weights_url": WEIGHTS.url,
              "weights_sha256": sha256(weights_path), "head_sha256": sha256(head_path),
              "onnx_sha256": sha256(model_path), "preprocessing": PREPROCESSING,
              "train_count": len(train_rows), "excluded_photo_ids": excluded,
              "python": __import__("sys").version.split()[0],
              "torch": torch.__version__, "torchvision": torchvision.__version__,
              "onnx": onnx.__version__,
              "onnxruntime": ort.__version__, "onnx_providers": session.get_providers()}
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


def validate(args):
    import torch
    from torchvision.models import resnet50

    trained_path = args.artifacts / "resnet50-trained.json"
    model_path = args.artifacts / "resnet50.onnx"
    head_path = args.artifacts / "resnet50-head.pt"
    calibrated_path = args.artifacts / "resnet50-calibrated.json"
    predictions_path = args.artifacts / "validation-predictions.json"
    refuse_existing(calibrated_path, predictions_path)
    config = json.loads(trained_path.read_text(encoding="utf-8"))
    if config["weights"] != WEIGHTS.name or config["preprocessing"] != PREPROCESSING:
        raise ValueError("Trained preprocessing or weights mismatch")
    rows, kinds, manifest_sha, _ = manifest_rows(args.manifest, config["manifest_sha256"])
    if kinds != config["kinds"] or sorted(kinds) != config["labels"]:
        raise ValueError("Class order or admissibility changed")
    if sha256(model_path) != config["onnx_sha256"] or sha256(head_path) != config["head_sha256"]:
        raise ValueError("Trained artifact SHA-256 mismatch")
    weights_path = Path(torch.hub.get_dir()) / "checkpoints" / Path(WEIGHTS.url).name
    if sha256(weights_path) != config["weights_sha256"]:
        raise ValueError("Pretrained weights SHA-256 mismatch")
    validation_rows = [row for row in rows if row["partition"] == "validation"]
    if not validation_rows:
        raise ValueError("No validation rows")
    torch.set_num_threads(2)
    model = resnet50(weights=WEIGHTS).to("cpu").eval()
    model.fc = torch.nn.Linear(model.fc.in_features, len(config["labels"]))
    model.fc.load_state_dict(torch.load(head_path, map_location="cpu", weights_only=True))
    model.eval()
    records = infer_rows(validation_rows, args.images, WEIGHTS.transforms(),
                         cpu_session(model_path), config["labels"], kinds, model)
    thresholds = calibrate(records, kinds)
    for record in records:
        record["decision"] = (record["onnx_top1"]
                              if record["onnx_score"] >= thresholds[record["kind"]] else None)
    calibrated = dict(config, phase="calibrated_on_validation", thresholds=thresholds,
                      validation_count=len(records),
                      pytorch_onnx_top1_agreements=sum(row["top1_agrees"] for row in records),
                      max_abs_logit_difference=max(row["max_abs_logit_difference"] for row in records))
    predictions_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    calibrated["validation_predictions_sha256"] = sha256(predictions_path)
    calibrated_path.write_text(json.dumps(calibrated, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")


def test(args):
    """Read only test photos and already calibrated ONNX artifacts."""
    config_path = args.artifacts / "resnet50-calibrated.json"
    model_path = args.artifacts / "resnet50.onnx"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config["phase"] != "calibrated_on_validation" or not config["thresholds"]:
        raise ValueError("Frozen validation thresholds required")
    if config["weights"] != WEIGHTS.name or config["preprocessing"] != PREPROCESSING:
        raise ValueError("Frozen preprocessing mismatch")
    rows, kinds, manifest_sha, _ = manifest_rows(args.manifest, config["manifest_sha256"])
    if kinds != config["kinds"] or sorted(kinds) != config["labels"]:
        raise ValueError("Frozen class order mismatch")
    if sha256(model_path) != config["onnx_sha256"]:
        raise ValueError("Frozen ONNX SHA-256 mismatch")
    test_rows = [row for row in rows if row["partition"] == "test"]
    if not test_rows:
        raise ValueError("No test rows")
    refuse_existing(args.output)
    records = infer_rows(test_rows, args.images, WEIGHTS.transforms(),
                         cpu_session(model_path), config["labels"], kinds)
    for record in records:
        cutoff = config["thresholds"][record["kind"]]
        record["decision"] = record["onnx_top1"] if record["onnx_score"] >= cutoff else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"phase": "frozen_test", "manifest_sha256": manifest_sha,
                                       "onnx_sha256": config["onnx_sha256"],
                                       "predictions": records}, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="phase", required=True)
    training = commands.add_parser("train")
    training.add_argument("--manifest", type=Path, required=True)
    training.add_argument("--manifest-sha256", required=True)
    training.add_argument("--images", type=Path, required=True)
    training.add_argument("--output", type=Path, required=True)
    validation = commands.add_parser("validate")
    validation.add_argument("--manifest", type=Path, required=True)
    validation.add_argument("--images", type=Path, required=True)
    validation.add_argument("--artifacts", type=Path, required=True)
    final = commands.add_parser("test")
    final.add_argument("--manifest", type=Path, required=True)
    final.add_argument("--images", type=Path, required=True)
    final.add_argument("--artifacts", type=Path, required=True)
    final.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"train": train, "validate": validate, "test": test}[args.phase](args)


if __name__ == "__main__":
    main()
