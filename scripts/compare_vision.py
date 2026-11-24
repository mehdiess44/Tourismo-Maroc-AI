"""Prepare, select and test the Lot 4 CPU models on frozen group splits."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote

import numpy as np
import onnxruntime
from PIL import Image, ImageOps

from tourismo.store import DATA, read_json
from tourismo.vision import preprocess, rank, scores

PARTITIONS = {"train", "validation", "test"}
MODELS = ("clip", "resnet50")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def inspect(manifest):
    catalog = {row["id"]: row["kind"] for row in read_json(DATA / "catalog.json")}
    pilot = read_json(DATA / "pilot-manifest.json")
    def source_key(source):
        return unquote(source).replace("_", " ").removeprefix("https://").removeprefix("http://").casefold()

    reserved = {row[field] for row in pilot for field in ("group", "sha256")}
    reserved_sources = {source_key(row["source"]) for row in pilot}
    rows = read_json(manifest)
    groups, hashes, identifiers = {}, {}, set()
    classes = defaultdict(list)
    unknowns = defaultdict(set)
    for row in rows:
        identifier, part, kind, label = (row[key] for key in ("id", "partition", "kind", "label"))
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", identifier) or identifier in identifiers:
            raise ValueError(f"Identifiant invalide ou dupliqué : {identifier}")
        identifiers.add(identifier)
        if row["status"] != "approved" or part not in PARTITIONS or kind not in set(catalog.values()) or not all(
            row.get(key) for key in ("group", "sha256", "author", "license", "source")
        ) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise ValueError(f"Métadonnées de campagne incomplètes : {identifier}")
        if part == "test" and (
            row["group"] in reserved or row["sha256"] in reserved or source_key(row["source"]) in reserved_sources
        ):
            raise ValueError(f"Photo ou groupe du pilote au test : {identifier}")
        if groups.setdefault(row["group"], part) != part:
            raise ValueError(f"Groupe dans plusieurs partitions : {row['group']}")
        if row["sha256"] in hashes:
            raise ValueError(f"JPEG dupliqué : {identifier} et {hashes[row['sha256']]}")
        hashes[row["sha256"]] = identifier
        if label is None:
            if part == "train":
                raise ValueError("Les inconnues sont réservées à la validation et au test.")
            unknowns[kind].add(part)
        elif catalog.get(label) != kind:
            raise ValueError(f"Label ou type incompatible avec le catalogue : {identifier}")
        else:
            classes[label].append(row)
    for label, members in classes.items():
        if (len(members) < 20 or len({m["group"] for m in members}) < 6
                or len({m["group"] for m in members if m["partition"] == "test"}) < 2
                or {m["partition"] for m in members} != PARTITIONS):
            raise ValueError(f"Classe insuffisamment documentée : {label}")
    if not classes:
        raise ValueError("Aucune classe admissible.")
    kinds = {catalog[label] for label in classes}
    if set(unknowns) != kinds or any(parts != {"validation", "test"} for parts in unknowns.values()):
        raise ValueError("Prévoir des inconnues en validation et test pour chaque type évalué.")
    return rows, {kind: {label for label in classes if catalog[label] == kind} for kind in kinds}


def image(directory, row):
    path = directory / (row["id"] + ".jpg")
    if digest(path) != row["sha256"]:
        raise ValueError(f"Empreinte inattendue : {path}")
    with Image.open(path) as raw:
        if raw.format != "JPEG":
            raise ValueError(f"Fichier JPEG attendu : {path}")
        return ImageOps.exif_transpose(raw).convert("RGB")


def session(path):
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    return onnxruntime.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def predictions(rows, directory, config, runtime, eligible):
    result = []
    for row in rows:
        kind = row["kind"]
        first = rank(scores(image(directory, row), config, runtime), config, kind, eligible[kind])["candidates"][0]
        if not math.isfinite(first["score"]):
            raise ValueError(f"Score non fini : {row['id']}")
        result.append(dict(id=row["id"], group=row["group"], kind=kind,
                           expected=row["label"], candidate=first["id"], score=first["score"]))
    return result


def evaluate(rows, cutoff, labels):
    counts = [[0] * len(labels) for _ in labels]
    decided = []
    for row in rows:
        accepted = row["score"] >= cutoff
        prediction = row["candidate"] if accepted else None
        counts[labels.index(row["expected"])][labels.index(prediction)] += 1
        decided.append(dict(row, threshold=cutoff, prediction=prediction, status="candidate" if accepted else "uncertain"))
    known = [row for row in rows if row["expected"] is not None]
    unknown = [row for row in decided if row["expected"] is None]
    f1 = []
    for index, line in enumerate(counts):
        denominator = sum(line) + sum(other[index] for other in counts)
        f1.append(2 * line[index] / denominator if denominator else 0)
    return dict(count=len(rows), groups=len({row["group"] for row in rows}),
                known_total=len(known), top1_correct=sum(row["expected"] == row["candidate"] for row in known),
                macro_f1=sum(f1) / len(f1), unknown_total=len(unknown),
                unknown_accepted=sum(row["prediction"] is not None for row in unknown),
                labels=labels, confusion=counts, predictions=decided)


def report(rows, directory, config, runtime, eligible, calibrate=False):
    predicted = predictions(rows, directory, config, runtime, eligible)
    result = {}
    for kind, identifiers in sorted(eligible.items()):
        subset = [row for row in predicted if row["kind"] == kind]
        labels = sorted(identifiers) + [None]
        if calibrate:
            cutoffs = {row["score"] for row in subset}
            cutoffs.add(math.nextafter(max(cutoffs), math.inf))

            def quality(cutoff):
                values = evaluate(subset, cutoff, labels)
                return values["macro_f1"], -values["unknown_accepted"], cutoff

            config["thresholds"][kind] = max(cutoffs, key=quality)
        result[kind] = evaluate(subset, config["thresholds"][kind], labels)
        metrics = result[kind]
        metrics["top1_known"] = metrics["top1_correct"] / metrics["known_total"]
    return result


def clip_gallery(train, directory, runtime):
    cfg = {"method": "clip", "size": 224, "mean": [.48145466, .4578275, .40821073],
           "std": [.26862954, .26130258, .27577711], "thresholds": {},
           "labels": [row["label"] for row in train], "reference_ids": [row["id"] for row in train], "gallery": []}
    for row in train:
        pixels = preprocess(image(directory, row), cfg)
        vector = runtime.run(["image_embeds"], {runtime.get_inputs()[0].name: pixels})[0].ravel()
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError(f"Vecteur CLIP invalide : {row['id']}")
        cfg["gallery"].append((vector / norm).tolist())
    return cfg

def train_resnet(train, directory, resnet_path, validation, eligible):
    import torch
    from torchvision.models import ResNet50_Weights, resnet50

    labels = sorted({row["label"] for row in train})
    torch.manual_seed(42)
    torch.set_num_threads(2)

    config = {"method": "resnet50", "labels": labels, "size": 224, "mean": [.485,.456,.406],
              "std": [.229,.224,.225], "thresholds": {}}
    model = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2).eval()
    features = []
    with torch.no_grad():
        head = model.fc
        model.fc = torch.nn.Identity()
        for row in train:
            features.append(model(torch.from_numpy(preprocess(image(directory, row), config))))
    x = torch.cat(features)
    y = torch.tensor([labels.index(row["label"]) for row in train])
    model.fc = torch.nn.Linear(head.in_features, len(labels))
    optimizer = torch.optim.AdamW(model.fc.parameters(), lr=.005)
    for _ in range(60):
        optimizer.zero_grad()
        torch.nn.functional.cross_entropy(model.fc(x), y).backward()
        optimizer.step()

    torch.onnx.export(model.eval(), (torch.zeros(1,3,224,224),), str(resnet_path),
                      input_names=["pixel_values"], dynamo=False, opset_version=17)

    runtime = session(resnet_path)
    errors = []
    mismatches = []
    with torch.no_grad():
        for row in validation:
            pixels = preprocess(image(directory, row), config)
            expected = model(torch.from_numpy(pixels)).numpy().ravel()
            actual = runtime.run(None, {runtime.get_inputs()[0].name: pixels})[0]
            if actual.shape != (1, len(labels)) or not np.all(np.isfinite(actual)):
                raise ValueError(f"Sortie ONNX invalide : {row['id']}")
            actual = actual.ravel()
            errors.append(float(np.max(np.abs(expected - actual))))
            kind = row["kind"]
            first = lambda values: rank(values, config, kind, eligible[kind])["candidates"][0]["id"]
            if first(expected) != first(actual):
                mismatches.append(row["id"])
    if mismatches:
        raise ValueError(f"Classement PyTorch/ONNX différent : {mismatches}")
    config["export_validation"] = dict(max_logit_error=max(errors), count=len(errors), mismatches=mismatches)
    config["training"] = dict(weights="IMAGENET1K_V2", seed=42, epochs=60, torch_version=torch.__version__)
    return config



def check(args):
    rows, eligible = inspect(args.manifest)
    counts = {}
    for kind, labels in sorted(eligible.items()):
        counts[kind] = {}
        for label in sorted(labels) + [None]:
            splits = {}
            for partition in sorted(PARTITIONS):
                members = [row for row in rows if row["kind"] == kind and row["label"] == label
                           and row["partition"] == partition]
                for row in members:
                    image(args.images, row)
                splits[partition] = dict(images=len(members), groups=len({row["group"] for row in members}))
            counts[kind][label or "inconnu"] = splits
    print(json.dumps(dict(manifest_sha256=digest(args.manifest), counts=counts), indent=2))


def prepare(args):
    import shutil
    import tempfile

    rows, eligible = inspect(args.manifest)
    train = [row for row in rows if row["partition"] == "train"]
    validation = [row for row in rows if row["partition"] == "validation"]
    if args.output.exists():
        raise ValueError("Utiliser un nouveau dossier pour la préparation.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temporary:
        bundle = Path(temporary) / "prepared"
        bundle.mkdir()
        manifest_hash = digest(args.manifest)
        metadata = {"manifest_sha256": manifest_hash, "files": {}}
        for method in getattr(args, "methods", MODELS):
            model = bundle / f"{method}.onnx"
            if method == "clip" and getattr(args, "clip_prepared", None):
                verify_bundle(args.manifest, args.clip_prepared, methods=("clip",))
                for suffix in (".onnx", ".json", "-validation.json"):
                    name = f"clip{suffix}"
                    shutil.copyfile(args.clip_prepared / name, bundle / name)
                continue
            if method == "clip":
                shutil.copyfile(args.clip, model)
                runtime = session(model)
                config = clip_gallery(train, args.images, runtime)
            else:
                config = train_resnet(train, args.images, model, validation, eligible)
                runtime = session(model)
            metrics = report(validation, args.images, config, runtime, eligible, calibrate=True)
            save(bundle / f"{method}.json", config)
            save(bundle / f"{method}-validation.json", metrics)
            del runtime
        if digest(args.manifest) != manifest_hash:
            raise ValueError("Le manifeste a changé pendant la préparation.")
        metadata["files"] = {path.name: digest(path) for path in sorted(bundle.iterdir())}
        save(bundle / "prepared.json", metadata)
        bundle.rename(args.output)


def verify_bundle(manifest, bundle, methods=MODELS):
    metadata = read_json(bundle / "prepared.json")
    expected = {f"{method}{suffix}" for method in methods for suffix in (".onnx", ".json", "-validation.json")}
    if set(metadata["files"]) != expected or any(digest(bundle / name) != value for name, value in metadata["files"].items()):
        raise ValueError("Les fichiers préparés ont changé.")
    if digest(manifest) != metadata["manifest_sha256"]:
        raise ValueError("Le manifeste a changé depuis la préparation.")
    return metadata


def measure(args):
    import platform

    from scripts.measure_requests import measure_warm

    model = args.artifacts / "vision.onnx"
    config = args.artifacts / "vision.json"
    hashes = [digest(path) for path in (model, config)]
    photo = args.image.read_bytes()
    summary = measure_warm(args.port, photo, args.image.name, args.pid)
    if hashes != [digest(path) for path in (model, config)]:
        raise ValueError("Les artefacts actifs ont changé pendant la mesure.")
    summary.update(model_sha256=hashes[0], config_sha256=hashes[1], image_sha256=hashlib.sha256(photo).hexdigest(),
                   machine_sha256=hashlib.sha256(platform.node().encode()).hexdigest(),
                   system=platform.system(), processor=platform.processor())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False, allow_nan=False)


def choose(args):
    from datetime import datetime, timezone

    metadata = verify_bundle(args.manifest, args.prepared)
    results, comparison = {}, set()
    for method, path in zip(MODELS, (args.clip_measure, args.resnet_measure), strict=True):
        measured = read_json(path)
        if any(measured[f"{field}_sha256"] != metadata["files"][f"{method}{suffix}"]
               for field, suffix in (("model", ".onnx"), ("config", ".json"))):
            raise ValueError(f"Mesure associée aux mauvais artefacts : {method}")
        comparison.add((measured["machine_sha256"], measured["image_sha256"]))
        elapsed = sorted(row["elapsed_seconds"] for row in measured["requests"])
        peak = measured["fastapi_peak_working_set_mib"]
        if len(elapsed) != 20 or peak is None or not math.isfinite(peak) or peak < 0 or any(
            not math.isfinite(value) or value < 0 for value in elapsed
        ):
            raise ValueError(f"Mesures CPU incomplètes : {method}")
        metrics = read_json(args.prepared / f"{method}-validation.json")
        results[method] = dict(
            eligible=measured["biz_successes"] == 20 and peak <= 400 and elapsed[-1] < 30,
            macro_f1=sum(row["macro_f1"] for row in metrics.values()) / len(metrics),
            unknown_rate=sum(row["unknown_accepted"] for row in metrics.values()) /
                         sum(row["unknown_total"] for row in metrics.values()),
            p95_seconds=elapsed[18], max_seconds=elapsed[-1], peak_mib=peak, measures_sha256=digest(path),
        )
    if len(comparison) != 1:
        raise ValueError("Les mesures doivent utiliser le même ordinateur et la même image.")
    eligible = [method for method in MODELS if results[method]["eligible"]]
    if not eligible:
        raise ValueError(f"Aucun modèle ne respecte les critères CPU : {results}")

    def priority(method):
        row = results[method]
        return (row["macro_f1"], -row["unknown_rate"], -row["p95_seconds"])
    selected = max(eligible, key=priority)  # CLIP reste le modèle de référence en cas d'égalité complète.
    decision = dict(selected=selected, utc=datetime.now(timezone.utc).isoformat(), models=results,
                    prepared_sha256=digest(args.prepared / "prepared.json"))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(decision, stream, indent=2, ensure_ascii=False, allow_nan=False)


def test(args):
    verify_bundle(args.manifest, args.prepared)
    decision = read_json(args.decision)
    if (decision["prepared_sha256"] != digest(args.prepared / "prepared.json")
            or decision["selected"] not in MODELS or not decision["models"][decision["selected"]]["eligible"]):
        raise ValueError("Décision invalide ou liée à une autre préparation.")
    rows, eligible = inspect(args.manifest)
    final = [row for row in rows if row["partition"] == "test"]
    results = {}
    for method in MODELS:
        config = read_json(args.prepared / f"{method}.json")
        results[method] = report(final, args.images, config, session(args.prepared / f"{method}.onnx"), eligible)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(dict(decision_sha256=digest(args.decision), models=results), stream,
                  indent=2, ensure_ascii=False, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="phase", required=True)
    for handler, fields in (
        (check, ("manifest", "images")),
        (prepare, ("manifest", "images", "clip", "output")),
        (measure, ("image", "artifacts", "output")),
        (choose, ("manifest", "prepared", "clip_measure", "resnet_measure", "output")),
        (test, ("manifest", "images", "prepared", "decision", "output")),
    ):
        command = commands.add_parser(handler.__name__)
        for field in fields:
            command.add_argument(field, type=Path)
        if handler is prepare:
            clip_options = command.add_mutually_exclusive_group()
            clip_options.add_argument("--clip-only", dest="methods", action="store_const", const=("clip",), default=MODELS)
            clip_options.add_argument("--clip-prepared", type=Path, help="Réutiliser le dossier CLIP validé par A.")
        if handler is measure:
            command.add_argument("--port", type=int, required=True)
            command.add_argument("--pid", type=int, required=True)
        command.set_defaults(handler=handler)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
