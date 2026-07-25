#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        active_workbench 单 icon 识别入口                     ║
║                                                              ║
║  【一句话解释】只识别 03_icon_only/img_input 里的单个 icon。  ║
║  【类比理解】像把一个装备头像拿出来单独对图鉴。               ║
║  【数据流说明】img_input → matcher → img_out/run_xxx。       ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    import cv2
except Exception:  # pragma: no cover - 缺依赖时输出 unavailable。
    cv2 = None

SCRIPT_DIR = Path(__file__).resolve().parent
WORKBENCH_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common_icon_matching import (  # noqa: E402
    annotate_single_icon,
    build_combined_gallery_csv,
    build_icon_matcher,
    format_candidates,
    load_equipment_catalog,
    resolve_name,
    write_csv,
    write_json,
)

SECTION_DIR = WORKBENCH_DIR / "03_icon_only"
DEFAULT_INPUT_DIR = SECTION_DIR / "img_input"
DEFAULT_OUTPUT_ROOT = SECTION_DIR / "img_out"
STATUS_FILE = SECTION_DIR / "STATUS.txt"
CURRENT_OUT_FILE = SECTION_DIR / "CURRENT_OUT.txt"


# ============================================================
# 🏗️ 第二部分：参数
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析单 icon 测试参数。

    输入：
        命令行。
    输出：
        argparse.Namespace。
    使用示例：
        python run_icon_only_test.py
    """
    parser = argparse.ArgumentParser(description="active_workbench 单 icon 识别。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output-name", default="")
    parser.add_argument("--pattern", default="*.png")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--rarity-id", type=int, default=0)
    parser.add_argument("--no-region-refine", action="store_true")
    return parser.parse_args()


def output_dir_for(root: Path, name: str) -> Path:
    """
    构造本轮输出目录。

    输入：
        输出根目录和可选名称。
    输出：
        img_out/run_xxx。
    使用示例：
        out = output_dir_for(Path("img_out"), "")
    """
    final_name = name.strip() or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return root / final_name


# ============================================================
# 🚀 第三部分：入口
# ============================================================

def main() -> int:
    """
    执行单 icon 识别。

    输入：
        03_icon_only/img_input。
    输出：
        03_icon_only/img_out/run_xxx。
    使用示例：
        python run_icon_only_test.py
    """
    args = parse_args()
    input_dir = args.input_dir.resolve()
    images = sorted(path for path in input_dir.glob(str(args.pattern)) if path.is_file())
    images = [path for path in images if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}]
    if not images:
        print(f"没有找到单 icon 图片: {input_dir} / {args.pattern}")
        return 1

    output_dir = output_dir_for(args.output_root.resolve(), args.output_name)
    annotated_dir = output_dir / "annotated"
    output_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_equipment_catalog()
    gallery_csv = build_combined_gallery_csv(output_dir, catalog, int(args.rarity_id))
    matcher = build_icon_matcher(gallery_csv, top_n=int(args.top_n), region_refine=not args.no_region_refine)

    rows: List[Dict[str, Any]] = []
    for image_path in images:
        if cv2 is None:
            result = {"status": "unavailable", "equipment_id": "", "confidence": 0.0, "message": "OpenCV 不可用。", "candidates": []}
        else:
            image = cv2.imread(str(image_path), getattr(cv2, "IMREAD_COLOR", 1))
            if image is None or getattr(image, "size", 0) == 0:
                result = {"status": "error", "equipment_id": "", "confidence": 0.0, "message": "图片无法读取。", "candidates": []}
            else:
                result = matcher.match_icon(image, top_n=int(args.top_n)).to_dict()
        equipment_id = str(result.get("equipment_id", "") or "")
        candidates = list(result.get("candidates", []) or [])
        row = {
            "filename": image_path.name,
            "status": str(result.get("status", "") or ""),
            "equipment_id": equipment_id,
            "equipment_name": resolve_name(catalog, equipment_id),
            "confidence": float(result.get("confidence", 0.0) or 0.0),
            "matched_image_path": str(result.get("matched_image_path", "") or ""),
            "top3": format_candidates(candidates[:3], catalog),
            "top_candidates": format_candidates(candidates, catalog),
            "message": str(result.get("message", "") or ""),
        }
        rows.append(row)
        annotate_single_icon(image_path, annotated_dir / f"{image_path.stem}_icon_only.png", row)
        print(f"{row['filename']}: {row['status']} {row['equipment_id']} {row['equipment_name']} {row['confidence']:.3f}")

    summary = {
        "images": len(rows),
        "success": sum(1 for row in rows if row["status"] == "success"),
        "ambiguous": sum(1 for row in rows if row["status"] == "ambiguous"),
        "unknown_or_error": sum(1 for row in rows if row["status"] not in {"success", "ambiguous"}),
        "output_dir": str(output_dir),
        "gallery_csv": str(gallery_csv),
    }
    fields = ["filename", "status", "equipment_id", "equipment_name", "confidence", "matched_image_path", "top3", "top_candidates", "message"]
    write_csv(output_dir / "icon_only_results.csv", rows, fields)
    write_json(output_dir / "icon_only_summary.json", {"summary": summary, "rows": rows})
    CURRENT_OUT_FILE.write_text(str(output_dir) + "\n", encoding="utf-8")
    STATUS_FILE.write_text(
        "\n".join(
            [
                "03_icon_only 当前状态",
                "====================",
                "",
                f"输出目录: {output_dir}",
                f"图片数量: {summary['images']}",
                f"success: {summary['success']}",
                f"ambiguous: {summary['ambiguous']}",
                f"unknown/error: {summary['unknown_or_error']}",
                "",
                f"标注图: {annotated_dir}",
                f"CSV: {output_dir / 'icon_only_results.csv'}",
            ]
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
