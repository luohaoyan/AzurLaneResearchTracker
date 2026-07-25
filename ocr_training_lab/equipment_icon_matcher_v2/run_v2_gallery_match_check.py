#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      装备图标 v2 Accepted 图库自检脚本                       ║
║                                                              ║
║  【一句话解释】用 accepted 图库回测已人工确认的图标样本。     ║
║  【类比理解】把剪好的小图鉴拿回来认原题，先确认链路可用。    ║
║  【数据流说明】accepted manifest + results.json → 自检结果。  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.recognition.equipment_icon_matcher import EquipmentIconMatcher  # noqa: E402

from build_accepted_icon_gallery import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_RESULTS,
    MANIFEST_CSV_NAME,
    iter_accepted_cards,
    load_results,
    read_image,
)


# ============================================================
# 🧱 第二部分：常量与参数
# ============================================================

DEFAULT_CHECK_OUT = Path(__file__).resolve().parent / "img_out"
RoiRegion = Tuple[int, int, int, int]


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    输入：
        终端命令行。
    输出：
        argparse.Namespace。
    使用示例：
        python run_v2_gallery_match_check.py
    """
    parser = argparse.ArgumentParser(description="使用 accepted 图标图库回测 accepted 样本。")
    parser.add_argument("--source-results", type=Path, default=DEFAULT_SOURCE_RESULTS, help="rarity_bucket_results.json 路径。")
    parser.add_argument("--gallery-csv", type=Path, default=DEFAULT_OUTPUT_DIR / MANIFEST_CSV_NAME, help="accepted 图库 manifest CSV。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CHECK_OUT, help="自检结果输出目录。")
    parser.add_argument("--threshold", type=float, default=0.90, help="v2 自检阈值；accepted 图库回测默认应较高。")
    parser.add_argument("--ambiguous-margin", type=float, default=0.01, help="Top1/Top2 最小分差。")
    parser.add_argument("--top-n", type=int, default=5, help="保留 top-n 候选。")
    return parser.parse_args()


# ============================================================
# 🧪 第三部分：回测逻辑
# ============================================================

def run_match_check(
    source_results: Path,
    gallery_csv: Path,
    output_dir: Path,
    threshold: float = 0.90,
    ambiguous_margin: float = 0.01,
    top_n: int = 5,
) -> Dict[str, Any]:
    """
    对 accepted 样本执行图库回测。
    输入：
        source_results/gallery_csv/output_dir/threshold/ambiguous_margin/top_n。
    输出：
        summary 字典。
    使用示例：
        summary = run_match_check(DEFAULT_SOURCE_RESULTS, DEFAULT_OUTPUT_DIR / MANIFEST_CSV_NAME, Path("img_out"))
    """
    if not gallery_csv.exists():
        raise FileNotFoundError(f"accepted 图库 manifest 不存在，请先运行 build_accepted_icon_gallery.py: {gallery_csv}")

    matcher = EquipmentIconMatcher(
        config={
            "gallery_csv_path": str(gallery_csv),
            "threshold": float(threshold),
            "ambiguous_margin": float(ambiguous_margin),
            "top_n": int(top_n),
            "structure_weight": 0.70,
            "color_weight": 0.20,
            "edge_weight": 0.10,
            "hash_weight": 0.00,
        },
        gallery_csv_path=gallery_csv,
        project_root=PROJECT_ROOT,
    )
    status = matcher.check_status()
    if not status.get("available"):
        raise RuntimeError(f"EquipmentIconMatcher 不可用: {json.dumps(status, ensure_ascii=False)}")

    results = load_results(source_results)
    output_rows: List[Dict[str, Any]] = []
    for result, card in iter_accepted_cards(results):
        screenshot_path = Path(str(result.get("screenshot_path", "") or ""))
        if not screenshot_path.is_absolute():
            screenshot_path = PROJECT_ROOT / screenshot_path
        image = read_image(screenshot_path)
        expected_id = str(card.get("accepted_equipment_id", "") or "").strip()
        roi = tuple(int(value) for value in card.get("icon_match_roi") or card.get("icon_roi"))  # type: ignore[arg-type]
        match_result = matcher.match_icon(image, icon_roi=roi, top_n=top_n)
        candidates = match_result.to_dict().get("candidates", [])
        output_rows.append(
            {
                "filename": result.get("filename", card.get("filename", "")),
                "card_no": card.get("card_no", ""),
                "expected_equipment_id": expected_id,
                "matched_equipment_id": match_result.equipment_id,
                "status": match_result.status,
                "confidence": f"{match_result.confidence:.6f}",
                "is_expected": match_result.equipment_id == expected_id,
                "top_candidates": " | ".join(
                    f"{item.get('equipment_id')}:{float(item.get('confidence', 0.0)):.3f}"
                    for item in candidates
                ),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_check_csv(output_dir / "v2_gallery_match_check.csv", output_rows)
    (output_dir / "v2_gallery_match_check.json").write_text(json.dumps(output_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = summarize_rows(source_results, gallery_csv, output_rows)
    (output_dir / "v2_gallery_match_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def write_check_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """
    写出自检 CSV。
    输入：
        path/rows。
    输出：
        CSV 文件。
    使用示例：
        write_check_csv(Path("check.csv"), rows)
    """
    fieldnames = [
        "filename",
        "card_no",
        "expected_equipment_id",
        "matched_equipment_id",
        "status",
        "confidence",
        "is_expected",
        "top_candidates",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def summarize_rows(source_results: Path, gallery_csv: Path, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    汇总自检结果；不把回测结果宣称为真实准确率。
    输入：
        source_results/gallery_csv/rows。
    输出：
        summary 字典。
    使用示例：
        summary = summarize_rows(src, gallery, rows)
    """
    total = len(rows)
    matched = sum(1 for row in rows if str(row.get("is_expected", "")).lower() == "true")
    success = sum(1 for row in rows if row.get("status") == "success")
    return {
        "source_results": str(source_results),
        "gallery_csv": str(gallery_csv),
        "accepted_queries": total,
        "status_success": success,
        "matched_expected": matched,
        "mismatch_or_unknown": total - matched,
        "note": "该结果是 accepted 图库链路自检，包含同源样本，不能作为最终泛化准确率。真正准确率需要 test_img 中独立截图验证。",
    }


# ============================================================
# 🚀 第四部分：主入口
# ============================================================

def main() -> int:
    """
    脚本入口。
    输入：
        命令行参数。
    输出：
        进程退出码。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/run_v2_gallery_match_check.py
    """
    args = parse_args()
    try:
        summary = run_match_check(
            source_results=args.source_results,
            gallery_csv=args.gallery_csv,
            output_dir=args.output_dir,
            threshold=args.threshold,
            ambiguous_margin=args.ambiguous_margin,
            top_n=args.top_n,
        )
    except Exception as exc:
        print(f"v2 accepted 图库自检失败: {exc}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
