#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      equipment_icon_matcher_v2 当前测试工作台入口             ║
║                                                              ║
║  【一句话解释】把 img_input 里的截图跑当前最新版装备识别流程。 ║
║  【类比理解】像固定的一台测试机：放图、运行、看 img_out。       ║
║  【数据流说明】img_input → run_v2_prelabel → img_out/review。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Mapping

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    # Pytest 或 IDE 中可能注入不支持 reconfigure 的流；忽略即可。
    pass


# ============================================================
# 🧱 第二部分：路径常量
# ============================================================

THIS_DIR = Path(__file__).resolve().parent
V2_DIR = THIS_DIR.parent
PROJECT_ROOT = V2_DIR.parents[1]
DEFAULT_INPUT_DIR = THIS_DIR / "img_input"
DEFAULT_OUTPUT_ROOT = THIS_DIR / "img_out"
DEFAULT_REVIEW_ROOT = THIS_DIR / "review"
PRELABEL_SCRIPT = V2_DIR / "run_v2_prelabel.py"
SELF_LABEL_SCRIPT = V2_DIR / "collection_next" / "auto_self_label_collection.py"
ACCEPTED_GALLERY_CSV = V2_DIR / "accepted_icon_gallery" / "accepted_icon_gallery_manifest.csv"
REVIEWED_GALLERY_CSV = V2_DIR / "reviewed_icon_gallery" / "reviewed_icon_gallery_manifest.csv"
CURRENT_OUT_FILE = THIS_DIR / "CURRENT_OUT.txt"
CURRENT_REVIEW_FILE = THIS_DIR / "CURRENT_REVIEW_OUT.txt"
CURRENT_STATUS_FILE = THIS_DIR / "CURRENT_STATUS.txt"
UPDATE_LOG_FILE = THIS_DIR / "UPDATE_LOG.txt"


# ============================================================
# 🏗️ 第三部分：参数与命令构建
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析当前测试工作台参数。

    输入：
        终端命令。
    输出：
        argparse.Namespace。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/current_test_workbench/run_current_test.py
    """
    parser = argparse.ArgumentParser(description="当前测试工作台：放图到 img_input 后一键跑 v2 装备识别。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="测试截图目录，默认 current_test_workbench/img_input。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="识别输出根目录，默认 current_test_workbench/img_out。")
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT, help="自标注输出根目录，默认 current_test_workbench/review。")
    parser.add_argument("--output-name", default="", help="本次输出目录名；默认 run_yyyyMMdd_HHmmss。")
    parser.add_argument("--pattern", default="*.png", help="图片匹配模式，例如 *.png。")
    parser.add_argument("--read-quantity", action="store_true", help="启用碎片数量 OCR；默认关闭以优先测试装备识别。")
    parser.add_argument("--no-name-ocr", action="store_true", help="关闭装备名称 OCR 辅助；默认开启。")
    parser.add_argument("--no-self-label", action="store_true", help="只跑机器识别，不生成 Codex 自标注合并结果。")
    parser.add_argument("--top-n", type=int, default=10, help="每张卡保留 top-N 图标候选。")
    parser.add_argument("--review-confidence", type=float, default=0.90, help="复核阈值；当前测试默认较保守。")
    parser.add_argument("--auto-accept-confidence", type=float, default=0.92, help="机器 auto_accept 阈值。")
    return parser.parse_args()


def build_output_dir(output_root: Path, output_name: str) -> Path:
    """
    构造本次识别输出目录。

    输入：
        输出根目录和可选名称。
    输出：
        img_out/run_xxx。
    使用示例：
        output_dir = build_output_dir(Path("img_out"), "")
    """
    name = output_name.strip() or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return output_root / name


def build_prelabel_command(args: argparse.Namespace, output_dir: Path) -> List[str]:
    """
    构造 run_v2_prelabel.py 调用命令。

    输入：
        参数和输出目录。
    输出：
        subprocess.run 参数列表。
    使用示例：
        command = build_prelabel_command(args, output_dir)
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
        "--accepted-gallery-csv",
        str(ACCEPTED_GALLERY_CSV),
        "--reviewed-gallery-csv",
        str(REVIEWED_GALLERY_CSV),
        "--pattern",
        str(args.pattern),
        "--top-n",
        str(args.top_n),
        "--review-confidence",
        str(args.review_confidence),
        "--auto-accept-confidence",
        str(args.auto_accept_confidence),
        "--pattern-prefix",
        "current_test",
    ]
    if not args.read_quantity:
        command.append("--skip-ocr")
    if not args.no_name_ocr:
        command.append("--enable-name-ocr")
    return command


def build_self_label_command(output_dir: Path, review_root: Path) -> List[str]:
    """
    构造自标注合并器命令。

    输入：
        本次识别输出目录和 review 根目录。
    输出：
        subprocess.run 参数列表。
    使用示例：
        command = build_self_label_command(output_dir, review_root)
    """
    return [
        sys.executable,
        "-X",
        "utf8",
        str(SELF_LABEL_SCRIPT),
        "--source-dir",
        str(output_dir),
        "--output-root",
        str(review_root),
        "--output-name",
        f"self_label_{output_dir.name}",
        "--disable-visual-overrides",
        "--ignore-human-archive",
    ]


# ============================================================
# 🧾 第四部分：状态文件
# ============================================================

def load_json(path: Path) -> Mapping[str, object]:
    """
    读取 JSON 文件；缺失时返回空字典。

    输入：
        JSON 路径。
    输出：
        dict。
    使用示例：
        summary = load_json(output_dir / "v2_prelabel_summary.json")
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_current_status(output_dir: Path, review_dir: Path | None, image_count: int) -> None:
    """
    写出当前工作台状态，方便用户只看一个文件。

    输入：
        识别输出目录、自标注目录和输入图片数量。
    输出：
        CURRENT_STATUS.txt / UPDATE_LOG.txt。
    使用示例：
        write_current_status(output_dir, review_dir, 18)
    """
    summary = load_json(output_dir / "v2_prelabel_summary.json")
    review_summary = load_json(review_dir / "self_label_summary.json") if review_dir is not None else {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "equipment_icon_matcher_v2 当前测试工作台状态",
        "==========================================",
        "",
        f"更新时间: {now}",
        f"输入图片数量: {image_count}",
        f"最新识别输出: {output_dir}",
        f"最新自标注输出: {review_dir or '未运行'}",
        "",
        "识别摘要:",
        f"  images: {summary.get('images', '')}",
        f"  full_cards: {summary.get('full_cards', '')}",
        f"  machine_prefill_cards: {summary.get('machine_prefill_cards', '')}",
        f"  auto_accept_cards: {summary.get('auto_accept_cards', '')}",
        f"  needs_review_cards: {summary.get('needs_review_cards', '')}",
        f"  icon_needs_review_cards: {summary.get('icon_needs_review_cards', '')}",
        "",
        "自标注摘要:",
        f"  self_labeled_cards: {review_summary.get('self_labeled_cards', '')}",
        f"  excluded_cards: {review_summary.get('excluded_cards', '')}",
        f"  unresolved_cards: {review_summary.get('unresolved_cards', '')}",
        "",
        "重点查看:",
        f"  标注图目录: {output_dir / 'annotated'}",
        f"  全量CSV: {output_dir / 'v2_prelabel_results.csv'}",
        f"  复核CSV: {output_dir / 'v2_prelabel_review.csv'}",
        f"  自标注CSV: {(review_dir / 'self_labeled_cards.csv') if review_dir is not None else '未运行'}",
        "",
        "说明:",
        "  needs_review_cards 为 0 时，这一轮通常不用人工处理。",
        "  该工作台只用于 OCR 测试，不写正式用户数据或正式 CSV。",
    ]
    CURRENT_STATUS_FILE.write_text("\n".join(lines), encoding="utf-8")
    with UPDATE_LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(f"[{now}] output={output_dir} review={review_dir or 'none'} images={image_count} needs_review={summary.get('needs_review_cards', '')}\n")


# ============================================================
# 🚀 第五部分：命令入口
# ============================================================

def main() -> int:
    """
    执行当前测试工作台。

    输入：
        img_input 中的测试截图。
    输出：
        img_out/run_xxx、review/self_label_xxx 和 CURRENT_STATUS.txt。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/current_test_workbench/run_current_test.py
    """
    args = parse_args()
    input_dir = args.input_dir.resolve()
    if not input_dir.exists():
        print(f"输入目录不存在: {input_dir}")
        return 1

    images = sorted(path for path in input_dir.glob(str(args.pattern)) if path.is_file())
    if not images:
        print(f"没有找到测试图片: {input_dir} / {args.pattern}")
        print("请先把 1280x720 截图放进 current_test_workbench/img_input。")
        return 1

    output_dir = build_output_dir(args.output_root.resolve(), args.output_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"输入目录: {input_dir}")
    print(f"图片数量: {len(images)}")
    print(f"识别输出: {output_dir}")
    print("开始运行当前 v2 识别流程...")
    prelabel_result = subprocess.run(build_prelabel_command(args, output_dir), cwd=PROJECT_ROOT)
    if prelabel_result.returncode != 0:
        print(f"识别流程失败，退出码: {prelabel_result.returncode}")
        return int(prelabel_result.returncode)

    review_dir: Path | None = None
    if not args.no_self_label:
        review_dir = args.review_root.resolve() / f"self_label_{output_dir.name}"
        print("开始运行 Codex 自标注合并，避免把大表丢给人工...")
        self_label_result = subprocess.run(build_self_label_command(output_dir, args.review_root.resolve()), cwd=PROJECT_ROOT)
        if self_label_result.returncode != 0:
            print(f"自标注合并失败，退出码: {self_label_result.returncode}")
            return int(self_label_result.returncode)

    CURRENT_OUT_FILE.write_text(str(output_dir) + "\n", encoding="utf-8")
    if review_dir is not None:
        CURRENT_REVIEW_FILE.write_text(str(review_dir) + "\n", encoding="utf-8")
    write_current_status(output_dir, review_dir, len(images))
    print("当前测试完成。只需要看：")
    print(f"- 当前状态: {CURRENT_STATUS_FILE}")
    print(f"- 标注图: {output_dir / 'annotated'}")
    print(f"- 全量 CSV: {output_dir / 'v2_prelabel_results.csv'}")
    if review_dir is not None:
        print(f"- 自标注 CSV: {review_dir / 'self_labeled_cards.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
