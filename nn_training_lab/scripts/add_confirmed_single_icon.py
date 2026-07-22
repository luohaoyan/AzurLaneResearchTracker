#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              单张人工确认 icon 导入器                        ║
║  【一句话解释】把用户确认过的 108×108 icon 加入训练图库。       ║
║  【类比理解】像把一张确认无误的装备头像贴进标准样本册。         ║
║  【数据流说明】单 icon + equipment_name → OCR/NN reviewed图库。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from PIL import Image


# ============================================================
# 🧱 第二部分：常量与基础工具
# ============================================================

MANIFEST_FIELDS = (
    "sample_id", "equipment_id", "equipment_name", "accepted_equipment_name", "resolve_status",
    "image_path", "relative_image_path", "source_filename", "source_path", "card_no", "rarity",
    "rarity_id", "visibility", "icon_roi", "width", "height", "suggested_equipment_id",
    "suggested_equipment_name", "source_icon_status", "source_icon_confidence",
    "accepted_fragment_owned", "accepted_fragment_required",
)
RARITY_NAMES = {"1": "common", "2": "rare", "3": "elite", "4": "super_rare", "5": "ultra_rare"}


def project_root() -> Path:
    """返回项目根目录，避免依赖当前终端所在目录。"""
    return Path(__file__).resolve().parents[2]


def read_csv(path: Path) -> List[Dict[str, str]]:
    """读取 UTF-8-SIG CSV；文件不存在时返回空列表。"""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    """按图库 manifest 固定字段写回 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANIFEST_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})


def load_equipment_by_name(root: Path) -> Dict[str, Dict[str, str]]:
    """按 equipment_name 加载当前装备库。"""
    rows = read_csv(root / "data" / "equipment_library.csv")
    return {str(row.get("name", "")).strip(): row for row in rows if str(row.get("name", "")).strip()}


def load_equipment_by_id(root: Path) -> Dict[str, Dict[str, str]]:
    """按 equipment_id 加载当前装备库，避免命令行中文编码问题。"""
    rows = read_csv(root / "data" / "equipment_library.csv")
    return {
        str(row.get("equipment_id", "")).strip(): row
        for row in rows
        if str(row.get("equipment_id", "")).strip()
    }


def validate_icon(icon_path: Path) -> tuple[int, int]:
    """确认输入图片是可读取的完整正方形 icon。"""
    if not icon_path.is_file():
        raise FileNotFoundError(f"icon 文件不存在: {icon_path}")
    with Image.open(icon_path) as image:
        width, height = image.size
        if width != height or width < 64:
            raise ValueError(f"icon 必须是完整正方形，当前尺寸为 {width}x{height}: {icon_path}")
        image.load()
        return width, height


def copy_icon(source: Path, target: Path) -> None:
    """复制 icon 并统一保存成 RGB PNG，避免不同截图来源带来的格式差异。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGB").save(target, format="PNG")


# ============================================================
# 🏗️ 第三部分：图库导入逻辑
# ============================================================

def build_manifest_row(
    root: Path,
    manifest_root: Path,
    gallery_path: Path,
    source_icon: Path,
    sample_id: str,
    equipment_id: str,
    equipment_name: str,
    rarity_id: str,
    width: int,
    height: int,
) -> Dict[str, str]:
    """构建一行人工确认 manifest。"""
    rarity = RARITY_NAMES.get(rarity_id, "unknown")
    return {
        "sample_id": sample_id,
        "equipment_id": equipment_id,
        "equipment_name": equipment_name,
        "accepted_equipment_name": equipment_name,
        "resolve_status": "exact",
        "image_path": str(gallery_path.relative_to(root)),
        "relative_image_path": str(gallery_path.relative_to(manifest_root / "reviewed_icon_gallery")),
        "source_filename": source_icon.name,
        "source_path": str(source_icon),
        "card_no": "0",
        "rarity": rarity,
        "rarity_id": rarity_id,
        "visibility": "full",
        "icon_roi": json.dumps([0, 0, width, height], ensure_ascii=False),
        "width": str(width),
        "height": str(height),
        "suggested_equipment_id": equipment_id,
        "suggested_equipment_name": equipment_name,
        "source_icon_status": "human_confirmed",
        "source_icon_confidence": "1.0",
        "accepted_fragment_owned": "",
        "accepted_fragment_required": "",
    }


def upsert_manifest_row(manifest_path: Path, row: Mapping[str, str]) -> int:
    """按 sample_id 幂等追加 manifest 行。"""
    rows = read_csv(manifest_path)
    sample_id = str(row["sample_id"])
    for index, existing in enumerate(rows):
        if str(existing.get("sample_id", "")) == sample_id:
            rows[index] = dict(row)
            write_csv(manifest_path, rows)
            manifest_path.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0
    rows.append(dict(row))
    write_csv(manifest_path, rows)
    manifest_path.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1


def add_confirmed_single_icon(
    root: Path,
    icon_path: Path,
    equipment_name: str,
    equipment_id: str,
    case_id: str,
) -> Dict[str, object]:
    """把单张人工确认 icon 同步到 OpenCV 图库和 NN archive。"""
    equipment = load_equipment_by_id(root).get(equipment_id) if equipment_id else None
    if equipment is None and equipment_name:
        equipment = load_equipment_by_name(root).get(equipment_name)
    if equipment is None:
        raise ValueError(f"equipment_library.csv 中找不到装备: name={equipment_name}, id={equipment_id}")
    equipment_id = str(equipment.get("equipment_id", "")).strip()
    equipment_name = str(equipment.get("name", "")).strip()
    rarity_id = str(equipment.get("rarity_id", "")).strip()
    if not equipment_id or not rarity_id:
        raise ValueError(f"装备库字段不完整: {equipment_name} -> {equipment}")
    width, height = validate_icon(icon_path)
    safe_case = case_id.strip() or f"{equipment_id.lower()}_manual_icon"
    filename = f"manual_{safe_case}_{equipment_id}_icon.png"
    sample_id = f"manual_icon:{safe_case}:01"
    targets = (
        root / "ocr_training_lab" / "equipment_icon_matcher_v2",
        root / "nn_training_lab" / "archive" / "equipment_icon_matcher_v2",
    )
    added_rows = 0
    outputs: List[str] = []
    for manifest_root in targets:
        gallery_path = manifest_root / "reviewed_icon_gallery" / equipment_id / filename
        copy_icon(icon_path, gallery_path)
        row = build_manifest_row(
            root=root,
            manifest_root=manifest_root,
            gallery_path=gallery_path,
            source_icon=icon_path,
            sample_id=sample_id,
            equipment_id=equipment_id,
            equipment_name=equipment_name,
            rarity_id=rarity_id,
            width=width,
            height=height,
        )
        manifest_path = manifest_root / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
        added_rows += upsert_manifest_row(manifest_path, row)
        outputs.append(str(gallery_path.relative_to(root)))
    return {
        "status": "completed",
        "equipment_id": equipment_id,
        "equipment_name": equipment_name,
        "rarity_id": rarity_id,
        "rarity": RARITY_NAMES.get(rarity_id, "unknown"),
        "sample_id": sample_id,
        "added_manifest_rows": added_rows,
        "outputs": outputs,
        "note": "训练标签使用 equipment_name；equipment_id 仅作为当前装备库映射元数据。",
    }


# ============================================================
# 🚀 第四部分：命令入口
# ============================================================

def main() -> int:
    """命令行入口。"""
    root = project_root()
    parser = argparse.ArgumentParser(description="导入一张人工确认的完整装备 icon。")
    parser.add_argument("--icon", type=Path, required=True, help="完整正方形 icon 路径。")
    parser.add_argument("--equipment-name", default="", help="人工确认的 equipment_name。")
    parser.add_argument("--equipment-id", default="", help="当前装备库 ID；优先使用它反查中文名称。")
    parser.add_argument("--case-id", default="", help="本次样本的稳定编号。")
    args = parser.parse_args()
    if not args.equipment_name.strip() and not args.equipment_id.strip():
        parser.error("--equipment-name 和 --equipment-id 至少提供一个。")
    summary = add_confirmed_single_icon(
        root,
        args.icon.resolve(),
        args.equipment_name.strip(),
        args.equipment_id.strip(),
        args.case_id,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
