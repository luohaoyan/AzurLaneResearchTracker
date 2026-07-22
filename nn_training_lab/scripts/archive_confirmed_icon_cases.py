#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║             人工确认 icon 样本归档器                             ║
║  【一句话解释】保存完整截图、card crop、icon crop 和人工真值。     ║
║  【类比理解】像把验收通过的试卷装入档案袋，旧档案不会被覆盖。     ║
║  【数据流】incoming JSON → confirmed_cases + reviewed gallery。   ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from PIL import Image


MANIFEST_FIELDS = (
    "sample_id", "equipment_id", "equipment_name", "accepted_equipment_name", "resolve_status",
    "image_path", "relative_image_path", "source_filename", "source_path", "card_no", "rarity",
    "rarity_id", "visibility", "icon_roi", "width", "height", "suggested_equipment_id",
    "suggested_equipment_name", "source_icon_status", "source_icon_confidence",
    "accepted_fragment_owned", "accepted_fragment_required",
)
RARITY_NAMES = {"1": "common", "2": "rare", "3": "elite", "4": "super_rare", "5": "ultra_rare"}


# ============================================================
# 🧱 第二部分：数据对象与输入
# ============================================================

@dataclass(frozen=True)
class ConfirmedCase:
    """一条人工确认样本的来源和真值。"""

    case_id: str
    equipment_id: str
    equipment_name: str
    source_screenshot: str
    source_icon_crop: str
    card_no: int
    bbox: Tuple[int, int, int, int]
    icon_roi: Tuple[int, int, int, int]
    rarity: str
    rarity_id: str


def project_root() -> Path:
    """返回项目根目录。"""
    return Path(__file__).resolve().parents[2]


def load_cases(path: Path) -> List[ConfirmedCase]:
    """读取 JSON 样本清单并进行基本字段校验。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload) if isinstance(payload, Mapping) else payload
    cases: List[ConfirmedCase] = []
    for raw in raw_cases:
        cases.append(
            ConfirmedCase(
                case_id=str(raw["case_id"]),
                equipment_id=str(raw["equipment_id"]),
                equipment_name=str(raw["equipment_name"]),
                source_screenshot=str(raw["source_screenshot"]),
                source_icon_crop=str(raw.get("source_icon_crop", "")),
                card_no=int(raw["card_no"]),
                bbox=tuple(int(value) for value in raw["bbox"]),
                icon_roi=tuple(int(value) for value in raw["icon_roi"]),
                rarity=str(raw["rarity"]),
                rarity_id=str(raw["rarity_id"]),
            )
        )
    return cases


def resolve_path(root: Path, raw_path: str) -> Path:
    """解析相对项目路径，同时允许传入绝对路径。"""
    path = Path(raw_path)
    return path if path.is_absolute() else root / path


def load_equipment_library(path: Path) -> Dict[str, Dict[str, str]]:
    """加载装备库，用于阻止名称或稀有度填错进入训练集。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {str(row.get("equipment_id", "")): dict(row) for row in csv.DictReader(handle)}


def validate_case(root: Path, case: ConfirmedCase, library: Mapping[str, Mapping[str, str]]) -> None:
    """校验 ID、名称、稀有度、截图和 108×108 icon。"""
    row = library.get(case.equipment_id)
    if row is None:
        raise ValueError(f"装备库中不存在 equipment_id={case.equipment_id}")
    if str(row.get("name", "")).strip() != case.equipment_name:
        raise ValueError(f"{case.equipment_id} 名称不匹配：{case.equipment_name!r} != {row.get('name')!r}")
    if str(row.get("rarity_id", "")).strip() != case.rarity_id:
        raise ValueError(f"{case.equipment_id} 稀有度不匹配：{case.rarity_id!r} != {row.get('rarity_id')!r}")
    if RARITY_NAMES.get(case.rarity_id) != case.rarity:
        raise ValueError(f"稀有度名称与 rarity_id 不匹配：{case.rarity}/{case.rarity_id}")
    screenshot = resolve_path(root, case.source_screenshot)
    icon = resolve_path(root, case.source_icon_crop) if case.source_icon_crop else None
    if not screenshot.is_file():
        raise FileNotFoundError(f"找不到来源截图：{screenshot}")
    if icon is not None:
        if not icon.is_file():
            raise FileNotFoundError(f"找不到来源 icon：{icon}")
        with Image.open(icon) as image:
            if image.size != (108, 108):
                raise ValueError(f"icon 必须是 108x108：{icon} -> {image.size}")
    else:
        with Image.open(screenshot) as image:
            x, y, width, height = case.icon_roi
            if x < 0 or y < 0 or width != 108 or height != 108 or x + width > image.width or y + height > image.height:
                raise ValueError(f"自动 icon ROI 非法或越界：{case.case_id} {case.icon_roi} image={image.size}")
    if len(case.bbox) != 4 or len(case.icon_roi) != 4:
        raise ValueError(f"ROI 必须是 [x,y,w,h]：{case.case_id}")


# ============================================================
# 🛠️ 第三部分：归档与 manifest
# ============================================================

def copy_case_assets(root: Path, archive_root: Path, case: ConfirmedCase) -> Dict[str, str]:
    """复制完整截图、card crop、icon crop，并写出单样本 label.json。"""
    destination = archive_root / "human_label_archive" / "confirmed_cases" / case.case_id
    destination.mkdir(parents=True, exist_ok=True)
    screenshot_source = resolve_path(root, case.source_screenshot)
    icon_source = resolve_path(root, case.source_icon_crop) if case.source_icon_crop else None
    screenshot_target = destination / "source_screenshot.png"
    icon_target = destination / "source_icon_crop.png"
    shutil.copy2(screenshot_source, screenshot_target)
    if icon_source is not None:
        shutil.copy2(icon_source, icon_target)
    else:
        with Image.open(screenshot_source) as image:
            x, y, width, height = case.icon_roi
            image.crop((x, y, x + width, y + height)).save(icon_target, format="PNG")
    with Image.open(screenshot_source) as image:
        x, y, width, height = case.bbox
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > image.width or y + height > image.height:
            raise ValueError(f"card ROI 越界：{case.case_id} bbox={case.bbox} image={image.size}")
        image.crop((x, y, x + width, y + height)).save(destination / "card_crop.png", format="PNG")
    label = {**asdict(case), "bbox": list(case.bbox), "icon_roi": list(case.icon_roi), "label_source": "human_confirmed"}
    (destination / "label.json").write_text(json.dumps(label, ensure_ascii=False, indent=2), encoding="utf-8")
    gallery_path = archive_root / "reviewed_icon_gallery" / case.equipment_id / (
        f"confirmed_{case.case_id}_{case.equipment_id}_icon.png"
    )
    gallery_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_target, gallery_path)
    return {
        "archive_dir": str(destination.relative_to(root)),
        "gallery_path": str(gallery_path.relative_to(root)),
        "source_screenshot": str(screenshot_source),
        "source_icon_crop": str(icon_source or icon_target),
    }


def read_manifest(path: Path) -> List[Dict[str, str]]:
    """读取现有 reviewed gallery manifest。"""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def update_gallery_manifest(root: Path, archive_root: Path, cases: Sequence[ConfirmedCase]) -> int:
    """追加人工确认行；以 sample_id 去重，重复执行不会增加重复样本。"""
    manifest = archive_root / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
    rows = read_manifest(manifest)
    known = {str(row.get("sample_id", "")) for row in rows}
    added = 0
    for case in cases:
        sample_id = f"confirmed:{case.case_id}:01"
        if sample_id in known:
            continue
        gallery_path = archive_root / "reviewed_icon_gallery" / case.equipment_id / (
            f"confirmed_{case.case_id}_{case.equipment_id}_icon.png"
        )
        rows.append({
            "sample_id": sample_id,
            "equipment_id": case.equipment_id,
            "equipment_name": case.equipment_name,
            "accepted_equipment_name": case.equipment_name,
            "resolve_status": "exact",
            "image_path": str(gallery_path.relative_to(root)),
            "relative_image_path": str(gallery_path.relative_to(archive_root / "reviewed_icon_gallery")),
            "source_filename": Path(case.source_screenshot).name,
            "source_path": str(resolve_path(root, case.source_screenshot)),
            "card_no": str(case.card_no),
            "rarity": case.rarity,
            "rarity_id": case.rarity_id,
            "visibility": "full",
            "icon_roi": json.dumps(list(case.icon_roi), ensure_ascii=False),
            "width": "108",
            "height": "108",
            "suggested_equipment_id": "",
            "suggested_equipment_name": "",
            "source_icon_status": "human_confirmed",
            "source_icon_confidence": "1.0",
            "accepted_fragment_owned": "",
            "accepted_fragment_required": "",
        })
        known.add(sample_id)
        added += 1
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANIFEST_FIELDS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in MANIFEST_FIELDS} for row in rows)
    json_manifest = manifest.with_suffix(".json")
    json_manifest.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return added


def archive_cases(root: Path, cases_path: Path, archive_root: Path) -> Dict[str, Any]:
    """执行整批归档并返回可审计摘要。"""
    cases = load_cases(cases_path)
    library = load_equipment_library(root / "data" / "equipment_library.csv")
    for case in cases:
        validate_case(root, case, library)
    assets = [copy_case_assets(root, archive_root, case) for case in cases]
    added = update_gallery_manifest(root, archive_root, cases)
    summary = {
        "status": "completed",
        "cases": [asdict(case) for case in cases],
        "assets": assets,
        "manifest_rows_added": added,
        "manifest": str((archive_root / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv").relative_to(root)),
        "label_source": "human_confirmed",
        "note": "人工确认名称优先；本脚本不会把机器候选写成标签。",
    }
    output = archive_root / "human_label_archive" / "confirmed_cases" / "archive_summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


# ============================================================
# 🚀 第四部分：命令入口
# ============================================================

def main() -> int:
    """命令行入口。"""
    root = project_root()
    parser = argparse.ArgumentParser(description="归档人工确认 equipment icon 样本。")
    parser.add_argument("--cases", type=Path, default=root / "nn_training_lab" / "incoming" / "confirmed_icon_cases_20260722.json")
    parser.add_argument("--archive-root", type=Path, default=root / "nn_training_lab" / "archive" / "equipment_icon_matcher_v2")
    args = parser.parse_args()
    summary = archive_cases(root, args.cases.resolve(), args.archive_root.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
