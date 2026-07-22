#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
 Equipment icon neural-network dataset builder
 ------------------------------------------------------------
 Read-only sources: reviewed/accepted icon galleries and the
 four rarity final-review CSV files.
 Output: a reproducible class-folder dataset plus manifests.
 A machine suggestion is metadata only and never becomes a label.
============================================================
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PIL import Image


RARITY_NAMES = {"1": "common", "2": "rare", "3": "elite", "4": "super_rare", "5": "ultra_rare"}
RARITY_DISPLAY = {"rare": "blue", "elite": "purple", "super_rare": "gold", "ultra_rare": "rainbow"}
GALLERY_FILES = (
    "archive/equipment_icon_matcher_v2/reviewed_icon_gallery/reviewed_icon_gallery_manifest.csv",
    "archive/equipment_icon_matcher_v2/accepted_icon_gallery/accepted_icon_gallery_manifest.csv",
)
FINAL_REVIEW_ROOT = "nn_training_lab/archive/equipment_icon_matcher_v2/review_iterations/iter_20260722_old_v2_rarity_review_20260722"


@dataclass(frozen=True)
class Sample:
    """One trusted icon sample and its provenance."""

    sample_id: str
    equipment_id: str
    equipment_name: str
    rarity: str
    rarity_id: str
    source_image: str
    source_filename: str
    card_no: str
    label_source: str
    review_source: str
    source_status: str


def find_project_root(start: Path) -> Path:
    """Find the project root without relying on the current directory."""
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "data" / "equipment_library.csv").exists():
            return candidate
    raise RuntimeError("Cannot find project root (data/equipment_library.csv missing).")


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read a UTF-8-SIG CSV file."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> None:
    """Write a UTF-8-SIG CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: object) -> None:
    """Write UTF-8 JSON with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_final_review_lookup(root: Path) -> Dict[Tuple[str, str], Tuple[str, str, str]]:
    """Return (source filename, card number) -> (name, id, source)."""
    lookup: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    review_root = root / FINAL_REVIEW_ROOT
    for rarity in ("elite", "rare", "super_rare", "ultra_rare"):
        applied = review_root / rarity / "final_review_pack_applied" / "review_all_cards_for_user.applied.csv"
        raw = review_root / rarity / "review_all_cards_for_user.csv"
        path = applied if applied.exists() else raw
        if not path.exists():
            continue
        for row in read_csv(path):
            filename = str(row.get("filename", "")).strip()
            card_no = str(row.get("card_no", "")).strip()
            name = str(row.get("final_equipment_name", "") or row.get("current_equipment_name", "")).strip()
            equipment_id = str(row.get("final_equipment_id", "") or row.get("proposed_equipment_id", "")).strip()
            if filename and card_no and name:
                lookup[(filename, card_no)] = (name, equipment_id, f"final_review:{rarity}")
    return lookup


def read_gallery_rows(root: Path) -> Iterable[Tuple[Dict[str, str], Path]]:
    """Yield gallery metadata and absolute image path."""
    for relative_manifest in GALLERY_FILES:
        manifest = root / "nn_training_lab" / relative_manifest
        if not manifest.exists():
            continue
        for row in read_csv(manifest):
            image_value = str(row.get("image_path", "")).strip()
            image_path = Path(image_value)
            if not image_path.is_absolute():
                image_path = root / image_path
            yield row, image_path


def validate_icon(path: Path) -> Optional[Tuple[int, int]]:
    """Accept only readable square icon images; reject partial cards."""
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width != height or width < 64 or height < 64:
                return None
            image.load()
            return width, height
    except (OSError, ValueError):
        return None


def make_sample(row: Mapping[str, str], image_path: Path, final_lookup: Mapping[Tuple[str, str], Tuple[str, str, str]], root: Path) -> Optional[Sample]:
    """Create a trusted sample, applying only final-review overrides."""
    status = str(row.get("source_icon_status", "")).strip()
    accepted_name = str(row.get("accepted_equipment_name", "") or row.get("equipment_name", "")).strip()
    equipment_id = str(row.get("equipment_id", "")).strip()
    filename = str(row.get("source_filename", "")).strip()
    card_no = str(row.get("card_no", "")).strip()
    override = final_lookup.get((filename, card_no))
    label_source = "reviewed_gallery"
    if override and override[0]:
        accepted_name = override[0]
        equipment_id = override[1] or equipment_id
        label_source = override[2]
    if not accepted_name or not equipment_id or not image_path.exists() or validate_icon(image_path) is None:
        return None
    rarity_id = str(row.get("rarity_id", "")).strip()
    rarity = str(row.get("rarity", "")).strip() or RARITY_NAMES.get(rarity_id, "unknown")
    relative_image = image_path.resolve().relative_to(root.resolve())
    sample_id = str(row.get("sample_id", "")).strip() or f"{equipment_id}:{filename}:{card_no}"
    return Sample(
        sample_id=sample_id,
        equipment_id=equipment_id,
        equipment_name=accepted_name,
        rarity=rarity,
        rarity_id=rarity_id,
        source_image=str(relative_image),
        source_filename=filename,
        card_no=card_no,
        label_source=label_source,
        review_source=str(override[2] if override else "gallery_manifest"),
        source_status=status,
    )


def stable_sample_key(sample: Sample) -> str:
    """Use content hash to deduplicate copied files without changing sources."""
    return hashlib.sha1(f"{sample.source_image}|{sample.sample_id}".encode("utf-8")).hexdigest()[:12]


def split_samples(samples: Sequence[Sample], seed: int, validation_ratio: float) -> Tuple[List[Sample], List[Sample], Dict[str, str]]:
    """Split per equipment name; singleton classes remain in train and are marked."""
    grouped: Dict[str, List[Sample]] = defaultdict(list)
    for sample in samples:
        # 名称是模型稳定身份；equipment_id 只保留为当前库的运行时元数据。
        grouped[sample.equipment_name].append(sample)
    rng = random.Random(seed)
    train: List[Sample] = []
    validation: List[Sample] = []
    reasons: Dict[str, str] = {}
    for equipment_id, group in sorted(grouped.items()):
        ordered = list(group)
        rng.shuffle(ordered)
        if len(ordered) < 2:
            train.extend(ordered)
            reasons[equipment_id] = "singleton_train_only"
            continue
        val_count = max(1, round(len(ordered) * validation_ratio))
        val_count = min(val_count, len(ordered) - 1)
        validation.extend(ordered[:val_count])
        train.extend(ordered[val_count:])
        reasons[equipment_id] = "stratified_train_validation"
    return train, validation, reasons


def copy_split(root: Path, output: Path, split: str, samples: Sequence[Sample]) -> List[Dict[str, object]]:
    """Copy images into split/equipment_id and return manifest rows."""
    rows: List[Dict[str, object]] = []
    for index, sample in enumerate(samples, start=1):
        source = root / sample.source_image
        target_dir = output / split / sample.equipment_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{index:05d}_{stable_sample_key(sample)}.png"
        with Image.open(source) as image:
            image.convert("RGB").save(target, format="PNG")
        rows.append({"split": split, "path": str(target.relative_to(output)), **asdict(sample)})
    return rows


def build_dataset(root: Path, output: Path, seed: int = 20260722, validation_ratio: float = 0.2) -> Dict[str, object]:
    """Build the dataset and all machine-readable manifests."""
    final_lookup = build_final_review_lookup(root)
    candidates: List[Sample] = []
    seen: set[Tuple[str, str, str]] = set()
    for row, image_path in read_gallery_rows(root):
        sample = make_sample(row, image_path, final_lookup, root)
        if sample is None:
            continue
        dedupe_key = (sample.source_image.lower(), sample.equipment_id, sample.equipment_name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(sample)
    candidates.sort(key=lambda item: (item.rarity_id, item.equipment_id, item.source_image))
    train, validation, split_reasons = split_samples(candidates, seed, validation_ratio)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = copy_split(root, output, "train", train) + copy_split(root, output, "validation", validation)
    fields = ["split", "path", *Sample.__dataclass_fields__.keys()]
    write_csv(output / "dataset_manifest.csv", rows, fields)
    by_rarity = Counter(sample.rarity for sample in candidates)
    by_name = Counter(sample.equipment_name for sample in candidates)
    by_id = Counter(sample.equipment_id for sample in candidates)
    summary = {
        "schema_version": 1,
        "seed": seed,
        "validation_ratio": validation_ratio,
        "trusted_samples": len(candidates),
        "equipment_classes": len(by_name),
        "train_samples": len(train),
        "validation_samples": len(validation),
        "validation_classes": len({sample.equipment_id for sample in validation}),
        "singleton_classes_train_only": sum(reason == "singleton_train_only" for reason in split_reasons.values()),
        "rarity_counts": dict(sorted(by_rarity.items())),
        "label_source_counts": dict(Counter(sample.label_source for sample in candidates)),
        "source_status_counts": dict(Counter(sample.source_status for sample in candidates)),
        "class_sample_count_histogram": dict(sorted(Counter(by_name.values()).items())),
        "label_key": "equipment_name",
        "split_reasons": split_reasons,
        "manifest": str(output / "dataset_manifest.csv"),
        "warning": "The dataset is long-tailed and small per class; validation accuracy is diagnostic, not a 98% claim.",
    }
    write_json(output / "dataset_summary.json", summary)
    names = sorted(by_name)
    name_to_index = {name: index for index, name in enumerate(names)}
    index_to_name = {str(index): name for name, index in name_to_index.items()}
    # 保留当前 ID 映射作为兼容元数据；训练标签和模型输出不依赖它。
    id_to_index = {
        sample.equipment_id: name_to_index[sample.equipment_name]
        for sample in candidates
    }
    index_to_id = {
        str(index): next(sample.equipment_id for sample in candidates if sample.equipment_name == name)
        for name, index in name_to_index.items()
    }
    write_json(
        output / "label_map.json",
        {
            "label_key": "equipment_name",
            "name_to_index": name_to_index,
            "index_to_name": index_to_name,
            "name_to_ids": {
                name: sorted({sample.equipment_id for sample in candidates if sample.equipment_name == name})
                for name in names
            },
            "id_to_index": id_to_index,
            "index_to_id": index_to_id,
            "compatibility_note": "id_to_index/index_to_id 仅为旧调用方兼容；模型类别身份是 equipment_name。",
        },
    )
    return summary


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    root = find_project_root(Path(__file__))
    parser = argparse.ArgumentParser(description="Build the trusted equipment icon NN dataset.")
    parser.add_argument("--output", type=Path, default=root / "nn_training_lab" / "training_sets" / "equipment_icon_nn_dataset")
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--validation-ratio", type=float, default=0.2)
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    root = find_project_root(Path(__file__))
    summary = build_dataset(root, args.output.resolve(), args.seed, args.validation_ratio)
    # Windows 默认控制台可能是 GBK；文件本身仍以 UTF-8 保存中文名称，
    # 这里用 ASCII 转义保证直接运行脚本时不会因控制台编码中断。
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
