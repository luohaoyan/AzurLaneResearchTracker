#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      equipment_icon_matcher_v2 独立测试图批测脚本            ║
║                                                              ║
║  【一句话解释】把 test_img 里的新截图跑一遍 v2 图标识别。      ║
║  【类比理解】像拿没参与训练的新卷子考试，结果单独放 test_out。 ║
║  【数据流说明】test_img → run_v2_prelabel → test_out/run_xxx。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List
from typing import Mapping


# ============================================================
# 🧱 第二部分：常量
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "test_img"
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "test_out"
PRELABEL_SCRIPT = SCRIPT_DIR / "run_v2_prelabel.py"


# ============================================================
# 🏗️ 第三部分：参数与命令构建
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        终端命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/run_test_img_detection.py
    """
    parser = argparse.ArgumentParser(description="批量检测 equipment_icon_matcher_v2/test_img 中的独立测试截图。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="测试截图目录，默认 test_img。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="测试输出根目录，默认 test_out。")
    parser.add_argument("--output-name", default="", help="本次输出子目录名；默认按时间生成。")
    parser.add_argument("--pattern", default="*.png", help="测试图片匹配模式，例如 *.png 或 *.jpg。")
    parser.add_argument("--read-quantity", action="store_true", help="启用碎片数量 OCR；默认关闭以优先测试图标识别速度。")
    parser.add_argument("--no-name-ocr", action="store_true", help="关闭装备名称 OCR 辅助；默认开启以提高设计图识别准确度。")
    parser.add_argument("--top-n", type=int, default=10, help="每张卡片保留 top-N 图标候选。")
    parser.add_argument("--review-confidence", type=float, default=0.90, help="低于该图标置信度且无强名称辅助时进入复核。")
    parser.add_argument("--name-global-assist-score", type=float, default=0.90, help="名称全局辅助最低相似度。")
    parser.add_argument("--name-override-icon-confidence", type=float, default=0.86, help="名称可接管图标结果的最高图标置信度。")
    return parser.parse_args()


def build_output_dir(output_root: Path, output_name: str) -> Path:
    """
    构建本次测试输出目录。

    输入：
        output_root/output_name。
    输出：
        test_out/run_yyyyMMdd_HHmmss。
    使用示例：
        output_dir = build_output_dir(Path("test_out"), "")
    """
    name = output_name.strip() or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return output_root / name


def build_command(args: argparse.Namespace, output_dir: Path) -> List[str]:
    """
    构建调用 run_v2_prelabel.py 的命令。

    输入：
        用户参数和输出目录。
    输出：
        可直接 subprocess.run 的命令列表。
    使用示例：
        command = build_command(args, output_dir)
    """
    command = [
        sys.executable,
        "-X",
        "utf8",
        str(PRELABEL_SCRIPT),
        "--input-dir",
        str(args.input_dir),
        "--output-dir",
        str(output_dir),
        "--pattern",
        str(args.pattern),
        "--top-n",
        str(args.top_n),
        "--review-confidence",
        str(args.review_confidence),
        "--name-global-assist-score",
        str(args.name_global_assist_score),
        "--name-override-icon-confidence",
        str(args.name_override_icon_confidence),
        "--pattern-prefix",
        "test_img",
    ]
    if not args.read_quantity:
        command.append("--skip-ocr")
    if not args.no_name_ocr:
        command.append("--enable-name-ocr")
    return command


# ============================================================
# 🚀 第四部分：命令入口
# ============================================================

def export_all_cards_csv(output_dir: Path) -> Path:
    """
    从 v2_prelabel_results.json 导出完整卡片 CSV，方便人工验 test_img。

    输入：
        本次 test_out/run_xxx 输出目录。
    输出：
        test_img_all_cards.csv 路径。
    使用示例：
        csv_path = export_all_cards_csv(output_dir)
    """
    results_path = output_dir / "v2_prelabel_results.json"
    output_csv = output_dir / "test_img_all_cards.csv"
    if not results_path.exists():
        return output_csv
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    rows: List[Mapping[str, object]] = []
    for image_result in payload:
        for row in image_result.get("cards", []):
            if row.get("selected") is not True:
                continue
            rows.append(
                {
                    "filename": row.get("filename", image_result.get("filename", "")),
                    "card_no": row.get("card_no", ""),
                    "suggested_equipment_id": row.get("suggested_equipment_id", ""),
                    "suggested_equipment_name": row.get("suggested_equipment_name", ""),
                    "icon_status": row.get("icon_status", ""),
                    "icon_confidence": row.get("icon_confidence", ""),
                    "name_ocr_text": row.get("name_ocr_text", ""),
                    "name_resolve_equipment_name": row.get("name_resolve_equipment_name", ""),
                    "name_resolve_score": row.get("name_resolve_score", ""),
                    "high_value_card": row.get("high_value_card", ""),
                    "high_value_guard_active": row.get("high_value_guard_active", ""),
                    "high_value_name_weak": row.get("high_value_name_weak", ""),
                    "high_value_strong_name": row.get("high_value_strong_name", ""),
                    "machine_prefill": row.get("machine_prefill", ""),
                    "auto_accept": row.get("auto_accept", ""),
                    "needs_review": row.get("needs_review", ""),
                    "review_reason": row.get("review_reason", ""),
                    "icon_top_candidates": row.get("icon_top_candidates", ""),
                    "accepted_equipment_name": row.get("accepted_equipment_name", ""),
                }
            )
    fieldnames = [
        "filename",
        "card_no",
        "suggested_equipment_id",
        "suggested_equipment_name",
        "icon_status",
        "icon_confidence",
        "name_ocr_text",
        "name_resolve_equipment_name",
        "name_resolve_score",
        "high_value_card",
        "high_value_guard_active",
        "high_value_name_weak",
        "high_value_strong_name",
        "machine_prefill",
        "auto_accept",
        "needs_review",
        "review_reason",
        "icon_top_candidates",
        "accepted_equipment_name",
    ]
    with output_csv.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_csv

def main() -> int:
    """
    执行独立测试图检测。

    输入：
        test_img 中的截图。
    输出：
        test_out/run_xxx 中的标注图、CSV、JSON 和 exp。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/run_test_img_detection.py
    """
    args = parse_args()
    input_dir = args.input_dir.resolve()
    if not input_dir.exists():
        print(f"测试截图目录不存在: {input_dir}")
        return 1
    images = sorted(path for path in input_dir.glob(str(args.pattern)) if path.is_file())
    if not images:
        print(f"测试截图目录没有匹配图片: {input_dir} / {args.pattern}")
        return 1

    output_dir = build_output_dir(args.output_root.resolve(), args.output_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(args, output_dir)
    print(f"测试图片数量: {len(images)}")
    print(f"输出目录: {output_dir}")
    print("开始运行 v2 识别...")
    result = subprocess.run(command, cwd=SCRIPT_DIR.parents[1])
    if result.returncode != 0:
        print(f"测试图识别失败，退出码: {result.returncode}")
        return int(result.returncode)

    (SCRIPT_DIR / "CURRENT_TEST_OUT.txt").write_text(str(output_dir) + "\n", encoding="utf-8")
    all_cards_csv = export_all_cards_csv(output_dir)
    print("测试图识别完成。重点查看：")
    print(f"- 标注图目录: {output_dir / 'annotated'}")
    print(f"- 全部完整卡 CSV: {all_cards_csv}")
    print(f"- CSV: {output_dir / 'v2_prelabel_review.csv'}")
    print(f"- JSON: {output_dir / 'v2_prelabel_results.json'}")
    print(f"- Summary: {output_dir / 'v2_prelabel_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
