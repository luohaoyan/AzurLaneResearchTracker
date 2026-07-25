"""Tests for the full screenshot OpenCV/OCR/NN pipeline."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np

from nn_training_lab.scripts.run_screenshot_pipeline import choose_final_result, infer_rarity, write_outputs


def test_rarity_is_read_from_filename_tokens() -> None:
    """User naming is reflected in machine-readable output."""
    assert infer_rarity("design_super_rare_001.png") == "super_rare"
    assert infer_rarity("design_gold_001.png") == "super_rare"
    assert infer_rarity("unknown_capture.png") == "unknown"


def test_write_outputs_keeps_empty_runs_serializable(tmp_path: Path) -> None:
    """A missing or rejected batch still produces JSON/CSV summary files."""
    summary = write_outputs(tmp_path, [])
    assert summary["images"] == 0
    assert json.loads((tmp_path / "screenshot_pipeline_results.json").read_text(encoding="utf-8")) == []
    with (tmp_path / "screenshot_pipeline_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.DictReader(handle)) == []


def test_partial_cards_are_not_silently_promoted() -> None:
    """The pipeline's output contract reserves rejected_partial for partial cards."""
    row = {"visibility": "partial_bottom", "final_status": "rejected_partial"}
    assert row["final_status"] == "rejected_partial"


def test_high_confidence_name_ocr_resolves_ambiguous_icon() -> None:
    """名称 OCR 明确命中候选时可以消除 OpenCV 平分，但弱文本不能接管。"""
    equipment_id, name, source, status, warnings = choose_final_result(
        {
            "status": "ambiguous",
            "equipment_id": "unknown",
            "confidence": 0.81,
            "candidates": [{"equipment_id": "G0228"}, {"equipment_id": "G0120"}],
        },
        None,
        {"G0228": "九三式纯氧鱼雷#T2"},
        0.60,
        0.55,
        0.08,
        name_result={
            "success": True,
            "status": "icon_candidates_contains_base",
            "equipment_id": "G0228",
            "equipment_name": "九三式纯氧鱼雷#T2",
            "score": 0.93,
            "ocr_confidence": 0.92,
        },
    )

    assert (equipment_id, name, source, status) == (
        "G0228",
        "九三式纯氧鱼雷#T2",
        "name_ocr",
        "success",
    )
    assert warnings
