import json
from argparse import Namespace
from types import SimpleNamespace

import pytest
from PIL import Image

from scripts import compare_vision as comparison


def campaign(tmp_path):
    rows = []
    for partition, groups, count in (("train", ("a", "b", "c"), 12),
                                      ("validation", ("d",), 4), ("test", ("e", "f"), 4)):
        for index in range(count):
            rows.append(dict(id=f"{partition}-{index}", label="bab-mansour", partition=partition,
                             group=groups[index % len(groups)]))
    rows += [dict(id=f"unknown-{part}", label=None, partition=part, group=f"unknown-{part}")
             for part in ("validation", "test")]
    images = tmp_path / "images"
    images.mkdir()
    for index, row in enumerate(rows):
        path = images / f"{row['id']}.jpg"
        Image.new("RGB", (16, 16), (index * 10, index, 100)).save(path)
        row.update(kind="monument", status="approved", author="Test", license="Test",
                   source=f"https://example.org/{row['id']}", sha256=comparison.digest(path))
    manifest = tmp_path / "manifest.json"
    comparison.save(manifest, rows)
    return manifest, images, rows


def test_prepare_has_no_test_images_and_test_rejects_modified_artifacts(tmp_path, monkeypatch):
    manifest, images, rows = campaign(tmp_path)
    test_paths = {images / f"{row['id']}.jpg": (images / f"{row['id']}.jpg").read_bytes()
                  for row in rows if row["partition"] == "test"}
    for path in test_paths:
        path.unlink()
    model = tmp_path / "original.onnx"
    model.write_bytes(b"fixture")
    prepared = tmp_path / "prepared"
    def configuration(method):
        return dict(method=method, labels=["bab-mansour"], thresholds={})
    def fake_train(train, directory, path, validation, eligible):
        assert {r["partition"] for r in train} == {"train"}
        assert {r["partition"] for r in validation} == {"validation"}
        path.write_bytes(b"fake resnet")
        return configuration("resnet50")
    monkeypatch.setattr(comparison, "session", lambda model: SimpleNamespace())
    monkeypatch.setattr(comparison, "clip_gallery", lambda *args: configuration("clip"))
    monkeypatch.setattr(comparison, "train_resnet", fake_train)
    monkeypatch.setattr(comparison, "scores", lambda *args: [1.0])
    comparison.prepare(Namespace(manifest=manifest, images=images, clip=model, output=prepared))
    result = json.loads((prepared / "clip-validation.json").read_text())["monument"]
    assert all(not r["id"].startswith("test-") for r in result["predictions"])
    for path, data in test_paths.items():
        path.write_bytes(data)
    measures = []
    for method in comparison.MODELS:
        path = tmp_path / f"{method}-measure.json"
        comparison.save(path, dict(model_sha256=comparison.digest(prepared / f"{method}.onnx"),
            config_sha256=comparison.digest(prepared / f"{method}.json"), machine_sha256="pc",
            image_sha256="same", fastapi_peak_working_set_mib=400, biz_successes=20,
            requests=[dict(elapsed_seconds=1)] * 20))
        measures.append(path)
    decision = tmp_path / "decision.json"
    comparison.choose(Namespace(manifest=manifest, prepared=prepared, clip_measure=measures[0],
                                resnet_measure=measures[1], output=decision))
    batch = Namespace(manifest=manifest, images=images, prepared=prepared, decision=decision,
                      output=tmp_path / "results.json")
    comparison.test(batch)
    results = json.loads(batch.output.read_text())["models"]["clip"]["monument"]
    assert results["count"] == 5 and sum(map(sum, results["confusion"])) == 5
    (prepared / "clip.json").write_text("{}")
    with pytest.raises(ValueError, match="ont changé"):
        comparison.test(batch)


def test_manifest_rejects_pilot_group_in_test(tmp_path):
    manifest, _, rows = campaign(tmp_path)
    next(row for row in rows if row["partition"] == "test")["group"] = "lek-2018"
    comparison.save(manifest, rows)
    with pytest.raises(ValueError, match="pilote"):
        comparison.inspect(manifest)
