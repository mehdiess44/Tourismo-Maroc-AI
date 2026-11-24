"""Software-only checks with synthetic metadata and pixels, not Lot 4 results."""

import hashlib
import json

import numpy as np
import pytest
from PIL import Image
from torchvision.models import ResNet50_Weights

from scripts.lot4_benchmark import resnet_preprocess
from scripts.lot4_resnet50_phases import calibrate, manifest_rows


def write_manifest(tmp_path, *, leak=False, missing_decision=False):
    photos = [
        {"id": "train", "status": "approved", "partition": "train", "group": "g-train",
         "sha256": "a" * 64, "kind": "monument", "label": "known", "file": "train.jpg"},
        {"id": "known-val", "status": "approved", "partition": "validation",
         "group": "g-train" if leak else "g-val", "sha256": "b" * 64,
         "kind": "monument", "label": "known", "file": "known-val.jpg"},
        {"id": "unknown-val", "status": "approved", "partition": "validation",
         "group": "g-unknown", "sha256": "c" * 64,
         "kind": "monument", "label": None, "file": "unknown-val.jpg"},
        {"id": "excluded", "status": "approved", "partition": "train", "group": "g-excluded",
         "sha256": "d" * 64, "kind": "monument", "label": "manual-only",
         "file": "excluded.jpg"},
        {"id": "test", "status": "approved", "partition": "test", "group": "g-test",
         "sha256": "e" * 64, "kind": "monument", "label": "known", "file": "test.jpg"},
    ]
    decisions = [{"label": "known", "kind": "monument", "admissible": True}]
    if not missing_decision:
        decisions.append({"label": "manual-only", "kind": "monument", "admissible": False})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"photos": photos, "class_decisions": decisions}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_filters_inadmissible_class_without_opening_photos(tmp_path):
    path, digest = write_manifest(tmp_path)
    rows, kinds, actual, excluded = manifest_rows(path, digest)
    assert actual == digest
    assert kinds == {"known": "monument"}
    assert {row["id"] for row in rows} == {"train", "known-val", "unknown-val", "test"}
    assert excluded == ["excluded"]


def test_manifest_requires_a_decision_and_rejects_leakage(tmp_path):
    path, digest = write_manifest(tmp_path, missing_decision=True)
    with pytest.raises(ValueError, match="Missing class decision"):
        manifest_rows(path, digest)
    path, digest = write_manifest(tmp_path, leak=True)
    with pytest.raises(ValueError, match="Cross-partition leakage"):
        manifest_rows(path, digest)


def test_manifest_rejects_unconfirmed_schema_and_wrong_hash(tmp_path):
    path, digest = write_manifest(tmp_path)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        manifest_rows(path, "0" * 64)
    path.write_text(json.dumps([{"id": "train"}]), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="schema unconfirmed"):
        manifest_rows(path, digest)


def test_calibration_uses_validation_onnx_scores_and_unknowns():
    records = [
        {"id": "known", "partition": "validation", "kind": "monument",
         "expected": "known", "onnx_top1": "known", "onnx_score": 2.0},
        {"id": "unknown", "partition": "validation", "kind": "monument",
         "expected": None, "onnx_top1": "known", "onnx_score": 0.5},
    ]
    assert calibrate(records, {"known": "monument"}) == {"monument": 2.0}
    with pytest.raises(ValueError, match="validation records only"):
        calibrate([{**records[0], "partition": "test"}], {"known": "monument"})
    with pytest.raises(ValueError, match="requires unknowns"):
        calibrate(records[:1], {"known": "monument"})


@pytest.mark.parametrize("size", [(301, 257), (400, 600), (224, 224), (225, 233)])
def test_cpu_backend_preprocessing_matches_torchvision(size):
    width, height = size
    pixels = np.random.default_rng(width + height).integers(
        0, 256, size=(height, width, 3), dtype=np.uint8)
    image = Image.fromarray(pixels, "RGB")
    expected = ResNet50_Weights.IMAGENET1K_V2.transforms()(image).unsqueeze(0).numpy()
    actual = resnet_preprocess(image)
    assert actual.shape == (1, 3, 224, 224)
    np.testing.assert_array_equal(actual, expected)
