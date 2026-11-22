"""Train ResNet-50 and compare it with a CLIP gallery on approved group splits."""
import argparse
from collections import defaultdict
from pathlib import Path
import hashlib
import json

import numpy as np
import onnxruntime
from PIL import Image, ImageOps
from sklearn.metrics import confusion_matrix, f1_score
import torch
from torchvision.models import ResNet50_Weights, resnet50

from tourismo.store import read_json
from tourismo.vision import preprocess, rank, scores


def inspect(manifest, directory):
    rows = [row for row in read_json(manifest) if row["status"] == "approved"]
    groups, hashes = {}, {}
    classes = defaultdict(list)
    for row in rows:
        part = row["partition"]
        if part not in {"train", "validation", "test"} or not all(
            row.get(key) for key in ("group", "sha256", "author", "license", "source", "kind")
        ):
            raise ValueError(f"Métadonnées incomplètes : {row['id']}")
        path = directory / (row["id"] + ".jpg")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Empreinte inattendue : {path}")
        for index, key in ((groups, row["group"]), (hashes, row["sha256"])):
            if index.setdefault(key, part) != part:
                raise ValueError(f"Fuite entre partitions : {key}")
        if row.get("label"):
            classes[row["label"]].append(row)
        elif part == "train":
            raise ValueError("Les inconnues sont réservées à la validation et au test.")
    for name, members in classes.items():
        if (len(members) < 20 or len({m["group"] for m in members}) < 6
                or len({m["group"] for m in members if m["partition"] == "test"}) < 2
                or {m["partition"] for m in members} != {"train", "validation", "test"}):
            raise ValueError(f"Classe insuffisamment documentée : {name}")
    if not classes:
        raise ValueError("Aucune classe approuvée.")
    return rows, classes


def image(directory, row):
    with Image.open(directory / (row["id"] + ".jpg")) as raw:
        return ImageOps.exif_transpose(raw).convert("RGB")


def run(args):
    rows, classes = inspect(args.manifest, args.images)
    labels = sorted(classes)
    torch.manual_seed(42)
    torch.set_num_threads(2)
    args.output.mkdir(parents=True, exist_ok=True)
    kinds = {label: classes[label][0]["kind"] for label in labels}
    train = [row for row in rows if row["partition"] == "train"]
    config = {"method": "resnet50", "labels": labels, "size": 224, "mean": [.485,.456,.406],
              "std": [.229,.224,.225], "thresholds": {}}
    model = resnet50(weights=ResNet50_Weights.DEFAULT).eval()
    features = []
    with torch.no_grad():
        head = model.fc
        model.fc = torch.nn.Identity()
        for row in train:
            features.append(model(torch.from_numpy(preprocess(image(args.images, row), config))))
    x = torch.cat(features)
    y = torch.tensor([labels.index(row["label"]) for row in train])
    model.fc = torch.nn.Linear(head.in_features, len(labels))
    optimizer = torch.optim.AdamW(model.fc.parameters(), lr=.005)
    for _ in range(60):
        optimizer.zero_grad()
        torch.nn.functional.cross_entropy(model.fc(x), y).backward()
        optimizer.step()
    resnet_path = args.output / "resnet50.onnx"
    torch.onnx.export(model.eval(), (torch.zeros(1,3,224,224),), str(resnet_path),
                      input_names=["pixel_values"], dynamo=False, opset_version=17)

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    clip = onnxruntime.InferenceSession(str(args.clip), sess_options=options, providers=["CPUExecutionProvider"])
    clip_config = {"method":"clip", "size":224, "mean":[.48145466,.4578275,.40821073],
                   "std":[.26862954,.26130258,.27577711], "labels":[r["label"] for r in train],
                   "gallery":[], "thresholds":{}}
    for row in train:
        vector = clip.run(["image_embeds"], {clip.get_inputs()[0].name: preprocess(image(args.images, row), clip_config)})[0].ravel()
        clip_config["gallery"].append((vector / np.linalg.norm(vector)).tolist())
    resnet = onnxruntime.InferenceSession(str(resnet_path), sess_options=options, providers=["CPUExecutionProvider"])
    results = {}
    for cfg, session in [(config, resnet), (clip_config, clip)]:
        results[cfg["method"]] = {}
        for kind in sorted(set(kinds.values())):
            eligible = {label for label in labels if kinds[label] == kind}
            parts = {"validation": [], "test": []}
            for row in rows:
                if row["kind"] != kind or row["partition"] not in parts:
                    continue
                output = rank(scores(image(args.images, row), cfg, session), cfg, kind, eligible)
                first = output["candidates"][0]
                parts[row["partition"]].append((row.get("label") or "inconnu", first["id"], first["score"]))
            validation = parts["validation"]
            if not any(expected == "inconnu" for expected, _, _ in validation):
                raise ValueError(f"Prévoir des inconnues en validation pour {kind}.")
            thresholds = {score for _, _, score in validation}
            thresholds.add(max(thresholds) + 1)
            cutoff = max(thresholds, key=lambda score: (
                sum(want == (guess if value >= score else "inconnu") for want, guess, value in validation), score))
            cfg["thresholds"][kind] = cutoff
            evaluated = parts["test"]
            truth = [want for want, _, _ in evaluated]
            predicted = [guess if value >= cutoff else "inconnu" for _, guess, value in evaluated]
            names = sorted(eligible) + ["inconnu"]
            known = [(want, guess) for want, guess, _ in evaluated if want != "inconnu"]
            results[cfg["method"]][kind] = {
                "count": len(truth), "top1_known": sum(a == b for a, b in known) / len(known),
                "macro_f1": f1_score(truth, predicted, labels=names, average="macro", zero_division=0),
                "labels": names, "confusion": confusion_matrix(truth, predicted, labels=names).tolist(),
                "unknown_total": truth.count("inconnu"),
                "unknown_accepted": sum(a == "inconnu" and b != "inconnu" for a, b in zip(truth, predicted)),
            }
        (args.output / (cfg["method"] + ".json")).write_text(json.dumps(cfg), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for field in ("manifest", "images", "clip", "output"):
        parser.add_argument(field, type=Path)
    run(parser.parse_args())
