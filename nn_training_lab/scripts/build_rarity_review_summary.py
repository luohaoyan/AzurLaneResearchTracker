#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 Four-rarity review and training summary exporter
 ------------------------------------------------------------
 Produce small CSV/JSON indexes for the blue/purple/gold/rainbow
 review packages. This is an audit index only; it never edits the
 formal equipment CSV or user data.
============================================================
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Mapping, Sequence


RARITIES = (
    ("rare", "blue", "2"),
    ("elite", "purple", "3"),
    ("super_rare", "gold", "4"),
    ("ultra_rare", "rainbow", "5"),
)


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read UTF-8-SIG CSV."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> None:
    """Write UTF-8-SIG CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: object) -> None:
    """Write UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_summary(root: Path) -> List[Dict[str, object]]:
    """Collect review and dataset counts for all four rarities."""
    review_root = root / "nn_training_lab" / "archive" / "equipment_icon_matcher_v2" / "review_iterations" / "iter_20260722_old_v2_rarity_review_20260722"
    dataset_manifest = root / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset" / "dataset_manifest.csv"
    dataset_rows = read_csv(dataset_manifest) if dataset_manifest.exists() else []
    rows: List[Dict[str, object]] = []
    for key, display, rarity_id in RARITIES:
        source_dir = review_root / key
        raw_path = source_dir / "review_all_cards_for_user.csv"
        applied_path = source_dir / "final_review_pack_applied" / "review_all_cards_for_user.applied.csv"
        selected = applied_path if applied_path.exists() else raw_path
        review_rows = read_csv(selected) if selected.exists() else []
        corrected = sum(str(row.get("correction_applied", "")).lower() == "true" or bool(str(row.get("correct_equipment_name", "")).strip()) for row in review_rows)
        pages = len(list((source_dir / "final_review_pack_applied" / "full_contact_sheets").glob("page_*.png")))
        if pages == 0:
            pages = len(list((source_dir / "full_contact_sheets").glob("page_*.png")))
        samples = [row for row in dataset_rows if str(row.get("rarity_id", "")) == rarity_id]
        rows.append({
            "rarity": key,
            "display": display,
            "rarity_id": rarity_id,
            "review_rows": len(review_rows),
            "review_corrections": corrected,
            "preview_pages": pages,
            "training_samples": len(samples),
            "training_classes": len({row.get("equipment_id", "") for row in samples if row.get("equipment_id", "")}),
            "review_csv": str(selected),
            "preview_dir": str(source_dir / "final_review_pack_applied" / "full_contact_sheets"),
            "status": "included_in_nn_dataset" if samples else "review_only",
        })
    return rows


def main() -> int:
    """Export CSV and JSON summaries."""
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Export four-rarity review summary.")
    parser.add_argument("--output", type=Path, default=root / "nn_training_lab" / "exports")
    args = parser.parse_args()
    rows = build_summary(root)
    fields = list(rows[0].keys()) if rows else []
    write_csv(args.output.resolve() / "equipment_rarity_review_summary.csv", rows, fields)
    write_json(args.output.resolve() / "equipment_rarity_review_summary.json", {"rarities": rows, "warning": "Counts describe this reviewed snapshot; they are not accuracy measurements."})
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
