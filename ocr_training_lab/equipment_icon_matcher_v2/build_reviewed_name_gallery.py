#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      装备图标 v2 Reviewed 名称样本构建器                     ║
║                                                              ║
║  【一句话解释】把人工确认装备名对应的游戏内名称区域裁成样本。 ║
║  【类比理解】图标是“脸”，名称区域是“铭牌”，两者一起训练。    ║
║  【数据流说明】review_exp + prelabel_results → name_gallery。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import cv2
except Exception:  # pragma: no cover - 无 OpenCV 环境时 main 返回友好错误。
    cv2 = None

from build_reviewed_icon_gallery import (  # noqa: E402
    EquipmentNameResolver,
    parse_review_exp,
    safe_stem,
)


# ============================================================
# 🧱 第二部分：常量
# ============================================================

DEFAULT_REVIEW_EXP = SCRIPT_DIR / "review_iterations" / "iter_20260718_192618" / "completed" / "v2_review_completed_exp.txt"
DEFAULT_PRELABEL_RESULTS = (
    SCRIPT_DIR
    / "img_out"
    / "name_weight_experiments"
    / "top10_o086_scope_tierguard"
    / "v2_prelabel_results.json"
)
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "reviewed_name_gallery"
MANIFEST_CSV_NAME = "reviewed_name_gallery_manifest.csv"
MANIFEST_JSON_NAME = "reviewed_name_gallery_manifest.json"
RESOLVE_REPORT_CSV_NAME = "reviewed_name_gallery_resolve_report.csv"


# ============================================================
# 🏗️ 第三部分：参数与数据读取
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python build_reviewed_name_gallery.py --review-exp review_iterations/iter_x/completed/v2_review_completed_exp.txt
    """
    parser = argparse.ArgumentParser(description="从人工确认装备名构建名称 OCR 裁剪样本。")
    parser.add_argument("--review-exp", type=Path, default=DEFAULT_REVIEW_EXP, help="人工确认后的 exp 文件。")
    parser.add_argument("--prelabel-results", type=Path, default=DEFAULT_PRELABEL_RESULTS, help="对应的 v2_prelabel_results.json。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="名称样本输出目录。")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同名裁剪文件。")
    parser.add_argument("--pattern-prefix", default="reviewed_name", help="输出图片文件名前缀。")
    return parser.parse_args()


def load_prelabel_cards(prelabel_results_path: Path) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """
    加载预标注结果并按 filename/card_no 建索引。

    输入：
        v2_prelabel_results.json。
    输出：
        (filename, card_no) → card payload。
    使用示例：
        cards = load_prelabel_cards(Path("v2_prelabel_results.json"))
    """
    payload = json.loads(prelabel_results_path.read_text(encoding="utf-8"))
    cards: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for image_result in payload:
        screenshot_path = str(image_result.get("screenshot_path", "") or "")
        for card in image_result.get("cards", []):
            filename = str(card.get("filename", "") or image_result.get("filename", "") or "")
            card_no = int(card.get("card_no", 0) or 0)
            if not filename or card_no <= 0:
                continue
            enriched = dict(card)
            enriched["screenshot_path"] = screenshot_path
            cards[(filename, card_no)] = enriched
    return cards


# ============================================================
# 🖼️ 第四部分：裁剪与输出
# ============================================================

def crop_roi(image: Any, roi: Sequence[int]) -> Any:
    """
    从图片中安全裁剪 ROI。

    输入：
        OpenCV BGR 图片和 [x, y, w, h]。
    输出：
        裁剪图片。
    使用示例：
        crop = crop_roi(image, [10, 20, 100, 30])
    """
    if len(roi) != 4:
        raise ValueError(f"ROI 必须是 [x,y,w,h]: {roi}")
    x, y, width, height = [int(value) for value in roi]
    image_height, image_width = image.shape[:2]
    x = max(0, min(x, image_width - 1))
    y = max(0, min(y, image_height - 1))
    width = max(1, min(width, image_width - x))
    height = max(1, min(height, image_height - y))
    return image[y : y + height, x : x + width]


def build_name_gallery(
    review_exp: Path,
    prelabel_results: Path,
    output_dir: Path,
    overwrite: bool = False,
    pattern_prefix: str = "reviewed_name",
) -> Dict[str, Any]:
    """
    构建名称 OCR 裁剪样本库。

    输入：
        review_exp/prelabel_results/output_dir。
    输出：
        summary 字典。
    使用示例：
        build_name_gallery(review_exp, results_json, output_dir)
    """
    if cv2 is None:
        return {"available": False, "status": "unavailable", "message": "OpenCV/cv2 不可用，无法裁剪名称样本。"}
    annotations = parse_review_exp(review_exp)
    cards = load_prelabel_cards(prelabel_results)
    resolver = EquipmentNameResolver(PROJECT_ROOT)

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    resolve_rows: List[Dict[str, Any]] = []
    skipped = 0
    image_cache: Dict[str, Any] = {}

    for (filename, card_no), annotation in sorted(annotations.items()):
        card = cards.get((filename, card_no))
        resolve_result = resolver.resolve(annotation.accepted_equipment_name, annotation.accepted_equipment_id)
        resolve_rows.append(
            {
                "filename": filename,
                "card_no": card_no,
                "accepted_equipment_name": annotation.accepted_equipment_name,
                "resolve_status": resolve_result.status,
                "equipment_id": resolve_result.equipment_id,
                "equipment_name": resolve_result.equipment_name,
                "message": resolve_result.message,
            }
        )
        if card is None or resolve_result.status not in {"exact", "normalized", "id_fallback", "accepted_id", "name_with_accepted_id"}:
            skipped += 1
            continue

        screenshot_path = str(card.get("screenshot_path", "") or "")
        name_roi = card.get("name_roi") or []
        if not screenshot_path or len(name_roi) != 4:
            skipped += 1
            continue
        if screenshot_path not in image_cache:
            image_cache[screenshot_path] = cv2.imread(screenshot_path)
        image = image_cache[screenshot_path]
        if image is None:
            skipped += 1
            continue

        crop = crop_roi(image, name_roi)
        equipment_id = resolve_result.equipment_id
        equipment_name = resolve_result.equipment_name
        equipment_dir = output_dir / equipment_id
        equipment_dir.mkdir(parents=True, exist_ok=True)
        output_name = (
            f"{safe_stem(equipment_id)}_"
            f"{safe_stem(pattern_prefix + '_' + Path(filename).stem + f'_card{card_no:02d}')}.png"
        )
        output_path = equipment_dir / output_name
        if output_path.exists() and not overwrite:
            skipped += 1
            continue
        cv2.imwrite(str(output_path), crop)
        rows.append(
            {
                "sample_id": f"{equipment_id}:{Path(filename).stem}:card{card_no:02d}:name",
                "equipment_id": equipment_id,
                "equipment_name": equipment_name,
                "accepted_equipment_name": annotation.accepted_equipment_name,
                "image_path": str(output_path),
                "relative_image_path": str(output_path.relative_to(output_dir)),
                "source_filename": filename,
                "source_path": screenshot_path,
                "card_no": card_no,
                "name_roi": json.dumps(list(name_roi), ensure_ascii=False),
                "name_ocr_text": card.get("name_ocr_text", ""),
                "name_ocr_confidence": card.get("name_ocr_confidence", ""),
                "name_resolve_status": card.get("name_resolve_status", ""),
                "name_resolve_equipment_name": card.get("name_resolve_equipment_name", ""),
                "review_reason": card.get("review_reason", ""),
            }
        )

    cumulative_rows = merge_manifest_rows(load_existing_manifest(output_dir / MANIFEST_CSV_NAME), rows)
    write_csv(output_dir / MANIFEST_CSV_NAME, cumulative_rows)
    (output_dir / MANIFEST_JSON_NAME).write_text(json.dumps(cumulative_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(output_dir / RESOLVE_REPORT_CSV_NAME, resolve_rows)
    summary = {
        "review_exp": str(review_exp),
        "prelabel_results": str(prelabel_results),
        "output_dir": str(output_dir),
        "reviewed_name_samples": len(cumulative_rows),
        "new_reviewed_name_samples": len(rows),
        "report_rows": len(resolve_rows),
        "skipped": skipped,
        "manifest_csv": str(output_dir / MANIFEST_CSV_NAME),
        "resolve_report_csv": str(output_dir / RESOLVE_REPORT_CSV_NAME),
        "note": "名称样本用于后续 OCR/名称解析调参；不是正式用户数据。",
    }
    (output_dir / "reviewed_name_gallery_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def load_existing_manifest(manifest_path: Path) -> List[Dict[str, Any]]:
    """
    读取已有 reviewed name manifest，支持多轮名称样本累计。

    输入：
        reviewed_name_gallery_manifest.csv。
    输出：
        已有 manifest 行；文件不存在时返回空列表。
    使用示例：
        rows = load_existing_manifest(output_dir / MANIFEST_CSV_NAME)
    """
    if not manifest_path.exists():
        return []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def merge_manifest_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """
    合并名称图库 manifest，避免新一轮覆盖旧训练样本。

    输入：
        existing_rows/new_rows。
    输出：
        按 source_filename + card_no 累计去重后的行。
    使用示例：
        merged = merge_manifest_rows(old_rows, current_rows)
    """
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    for row in [*existing_rows, *new_rows]:
        key = (str(row.get("source_filename", "") or ""), str(row.get("card_no", "") or ""))
        if not key[0] or not key[1]:
            key = (str(row.get("sample_id", "") or ""), str(row.get("image_path", "") or ""))
        if key not in merged:
            order.append(key)
        merged[key] = dict(row)
    return [merged[key] for key in order]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """写出 CSV；空行时仍生成文件。"""
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# 🚀 第五部分：命令入口
# ============================================================

def main() -> int:
    """
    命令入口。

    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python build_reviewed_name_gallery.py
    """
    args = parse_args()
    summary = build_name_gallery(
        review_exp=args.review_exp,
        prelabel_results=args.prelabel_results,
        output_dir=args.output_dir,
        overwrite=bool(args.overwrite),
        pattern_prefix=str(args.pattern_prefix),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("status") != "unavailable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
