#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare a separate PyTorch manifest while reusing reviewed icon files read-only."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset"
DEST = ROOT / "nn_training_lab" / "pytorch_icon_training" / "data"
TEST_CASES = ROOT / "nn_training_lab" / "pytorch_icon_training" / "test_cases.json"


def main() -> int:
    """Copy metadata only and create a small non-independent smoke test manifest."""
    DEST.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, str]] = []
    with (SOURCE / "dataset_manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row["path"] = str((SOURCE / row["path"]).resolve())
            rows.append(row)
    fields = list(rows[0].keys())
    with (DEST / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    label_map = json.loads((SOURCE / "label_map.json").read_text(encoding="utf-8"))
    (DEST / "label_map.json").write_text(json.dumps(label_map, ensure_ascii=False, indent=2), encoding="utf-8")
    test_cases = [
        {
            "equipment_name": "试作型三联装305mmSKC39主炮#T0",
            "image_path": str((ROOT / "nn_training_lab/archive/equipment_icon_matcher_v2/reviewed_icon_gallery/S3-005/confirmed_20260722_s3_005_screenshot_154906_card01_S3-005_icon.png").resolve()),
            "independent": False,
        },
        {
            "equipment_name": "五联装533mm鱼雷Mk17#T0",
            "image_path": str((ROOT / "nn_training_lab/archive/equipment_icon_matcher_v2/reviewed_icon_gallery/G0103/confirmed_20260722_g0103_screenshot_154916_card06_G0103_icon.png").resolve()),
            "independent": False,
        },
    ]
    TEST_CASES.write_text(json.dumps(test_cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"samples": len(rows), "output": str(DEST), "test_cases": len(test_cases)}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
