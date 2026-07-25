"""Regression checks for the audited icon NN dataset."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from nn_training_lab.scripts.build_equipment_icon_nn_dataset import validate_icon


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset"


def test_dataset_manifest_contains_only_readable_square_icons() -> None:
    """Every generated row points to a readable icon, not a partial card."""
    manifest = DATASET / "dataset_manifest.csv"
    assert manifest.exists()
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(row["split"] in {"train", "validation"} for row in rows)
    assert all(validate_icon(DATASET / row["path"]) is not None for row in rows)


def test_dataset_labels_have_stable_name_mapping() -> None:
    """All model labels use equipment names; ID aliases remain metadata only."""
    payload = json.loads((DATASET / "label_map.json").read_text(encoding="utf-8"))
    labels = payload["name_to_index"]
    with (DATASET / "dataset_manifest.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert payload["label_key"] == "equipment_name"
    assert set(row["equipment_name"] for row in rows) == set(labels)


def test_singleton_classes_are_explicitly_train_only() -> None:
    """The summary must expose sparse-class risk instead of hiding it."""
    summary = json.loads((DATASET / "dataset_summary.json").read_text(encoding="utf-8"))
    assert summary["singleton_classes_train_only"] > 0
    assert "warning" in summary
