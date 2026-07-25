#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the read-only local recognition audit."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from nn_training_lab.scripts.audit_recognition_pipeline import audit_gallery, audit_run, latest_model_dir


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    """Write a tiny fixture CSV for the audit test."""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_audit_gallery_reports_missing_and_valid_image_rows(tmp_path: Path) -> None:
    """Gallery audit distinguishes readable image paths from missing files."""
    image = tmp_path / "icon.png"
    image.write_bytes(b"fixture")
    gallery = tmp_path / "gallery.csv"
    _write_csv(
        gallery,
        ["equipment_id", "image_path"],
        [
            {"equipment_id": "G0001", "image_path": "icon.png"},
            {"equipment_id": "G0002", "image_path": "missing.png"},
        ],
    )

    result = audit_gallery(tmp_path, [gallery])

    assert result["union_equipment_ids"] == 2
    assert result["union_valid_equipment_ids"] == 1
    assert result["union_missing_equipment_ids"] == ["G0002"]
    assert result["union_valid_image_rows"] == 1
    assert result["sources"][0]["valid_image_rows"] == 1
    assert result["sources"][0]["missing_image_rows"][0]["equipment_id"] == "G0002"


def test_audit_run_compares_only_nonempty_manual_names(tmp_path: Path) -> None:
    """Blank manual fields remain ungraded; accepted names compare exactly."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_csv(
        run_dir / "screenshot_pipeline_results.csv",
        ["filename", "card_no", "visibility", "final_status", "final_equipment_name", "opencv_status", "ocr_status", "name_ocr_status", "nn_status"],
        [{"filename": "one.png", "card_no": "1", "visibility": "full", "final_status": "success", "final_equipment_name": "装备A", "opencv_status": "success", "ocr_status": "success", "name_ocr_status": "success", "nn_status": "skipped"}],
    )
    manual = tmp_path / "manual.csv"
    _write_csv(
        manual,
        ["filename", "card_no", "accepted_equipment_name"],
        [{"filename": "one.png", "card_no": "1", "accepted_equipment_name": "装备A"}, {"filename": "two.png", "card_no": "1", "accepted_equipment_name": ""}],
    )
    library = tmp_path / "library.csv"
    _write_csv(library, ["name"], [{"name": "装备A"}])

    result = audit_run(run_dir, manual, library)

    assert result["status_counts"]["success"] == 1
    assert result["manual_comparison"]["compared"] == 1
    assert result["manual_comparison"]["exact"] == 1


def test_latest_model_dir_ignores_incomplete_newer_runs(tmp_path: Path) -> None:
    """The audit selects the newest checkpoint that has both required files."""
    checkpoint_root = tmp_path / "nn_training_lab" / "models" / "checkpoints"
    complete = checkpoint_root / "run_20260722_100000"
    incomplete = checkpoint_root / "run_20260722_200000"
    complete.mkdir(parents=True)
    incomplete.mkdir(parents=True)
    (complete / "best.pdparams").write_bytes(b"weights")
    (complete / "label_map.json").write_text("{}", encoding="utf-8")
    (incomplete / "best.pdparams").write_bytes(b"weights")

    selected = latest_model_dir(tmp_path)

    assert selected == complete


def test_latest_model_dir_prefers_validation_score_over_newer_timestamp(tmp_path: Path) -> None:
    """A newer but weaker experiment must not replace the best checkpoint."""
    checkpoint_root = tmp_path / "nn_training_lab" / "models" / "checkpoints"
    stronger = checkpoint_root / "run_20260722_100000"
    newer = checkpoint_root / "run_20260722_200000"
    stronger.mkdir(parents=True)
    newer.mkdir(parents=True)
    for run, score in ((stronger, 0.48), (newer, 0.31)):
        (run / "best.pdparams").write_bytes(b"weights")
        (run / "label_map.json").write_text("{}", encoding="utf-8")
        (run / "training_summary.json").write_text(json.dumps({"best_validation_top1": score}), encoding="utf-8")

    selected = latest_model_dir(tmp_path)

    assert selected == stronger
