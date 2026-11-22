"""Generate an audit report after the binôme has grouped and labelled the images."""
import argparse
from collections import Counter
import json
from pathlib import Path

from tourismo.store import read_json


def audit(manifest):
    rows = read_json(manifest)
    labels = sorted({row["label"] for row in rows if row.get("label")})
    report = {}
    for label in labels:
        members = [r for r in rows if r.get("label") == label]
        approved = [r for r in members if r.get("status") == "approved"]
        partitions = Counter(r["partition"] for r in approved)
        groups = {r["group"] for r in approved}
        test_groups = {r["group"] for r in approved if r["partition"] == "test"}
        report[label] = {"candidates": len(members), "approved": len(approved),
                         "groups": len(groups), "test_groups": len(test_groups),
                         "partitions": partitions,
                         "eligible": len(approved) >= 20 and len(groups) >= 6
                         and len(test_groups) >= 2 and all(partitions[p] for p in ("train","validation","test"))}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.manifest), indent=2, ensure_ascii=False))
