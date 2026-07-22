"""Contracts for the isolated PyTorch name-label experiment."""
from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PYTORCH_ROOT = ROOT / "nn_training_lab" / "pytorch_icon_training"
RUN = PYTORCH_ROOT / "models" / "run_20260722_181933"


def test_pytorch_manifest_uses_equipment_name_labels() -> None:
    """The separate manifest and label map use names as model identities."""
    label_map = json.loads((PYTORCH_ROOT / "data" / "label_map.json").read_text(encoding="utf-8"))
    with (PYTORCH_ROOT / "data" / "manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert label_map["label_key"] == "equipment_name"
    assert set(row["equipment_name"] for row in rows) == set(label_map["name_to_index"])


def test_pytorch_checkpoint_summary_keeps_name_output() -> None:
    """The completed GPU experiment records name labels and the actual device."""
    summary = json.loads((RUN / "training_summary.json").read_text(encoding="utf-8"))
    assert summary["label_key"] == "equipment_name"
    assert summary["cuda_available"] is True
    assert "5070 Ti" in summary["cuda_device"]
    assert summary["best_validation_top1"] > 0.70


def test_pytorch_epoch_test_output_has_name_candidates() -> None:
    """Per-epoch test output exposes equipment_name instead of only IDs."""
    payload = json.loads((PYTORCH_ROOT / "test_out" / RUN.name / "epoch_080.json").read_text(encoding="utf-8"))
    assert payload["label_key"] == "equipment_name"
    assert payload["cases"]
    assert all("equipment_name" in case for case in payload["cases"])
    assert all("equipment_name" in candidate for case in payload["cases"] for candidate in case.get("top_candidates", []))
