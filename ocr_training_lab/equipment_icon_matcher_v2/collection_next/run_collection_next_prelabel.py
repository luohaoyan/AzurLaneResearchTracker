#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      collection_next 机器预标注入口                          ║
║                                                              ║
║  【一句话解释】把 collection_next/img_input 里的新截图跑一遍。 ║
║  【类比理解】像把新试卷先交给机器批改，再只让人改错题。        ║
║  【数据流说明】img_input → run_v2_prelabel → img_out/run_xxx。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    # 某些测试注入的 stdout/stderr 不支持 reconfigure；忽略即可。
    pass


# ============================================================
# 🧱 第二部分：路径常量
# ============================================================

THIS_DIR = Path(__file__).resolve().parent
V2_DIR = THIS_DIR.parent
PROJECT_ROOT = V2_DIR.parents[1]
DEFAULT_INPUT_DIR = THIS_DIR / "img_input"
DEFAULT_OUTPUT_ROOT = THIS_DIR / "img_out"
PRELABEL_SCRIPT = V2_DIR / "run_v2_prelabel.py"
CURRENT_OUT_FILE = THIS_DIR / "CURRENT_COLLECTION_NEXT_OUT.txt"


# ============================================================
# 🏗️ 第三部分：参数与命令构建
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析 collection_next 专用命令行参数。

    输入：
        终端命令行。
    输出：
        argparse.Namespace。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/collection_next/run_collection_next_prelabel.py
    """
    parser = argparse.ArgumentParser(description="批量预标注 collection_next/img_input 中的新截图。")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="截图输入目录，默认 collection_next/img_input。")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="输出根目录，默认 collection_next/img_out。")
    parser.add_argument("--output-name", default="", help="输出子目录名；默认 run_yyyyMMdd_HHmmss。")
    parser.add_argument("--pattern", default="*.png", help="图片匹配模式，例如 *.png 或 *.jpg。")
    parser.add_argument("--read-quantity", action="store_true", help="启用碎片数量 OCR；默认关闭，先优先看图标和名称。")
    parser.add_argument("--no-name-ocr", action="store_true", help="关闭设计图名称 OCR；默认开启。")
    parser.add_argument("--enable-attribute-rerank", action="store_true", help="启用 Wiki 属性签名辅助重排；较慢，但困难装备更稳。")
    parser.add_argument("--enable-attribute-ocr", action="store_true", help="启用右侧属性文字 OCR；通常和 --enable-attribute-rerank 一起用。")
    parser.add_argument("--top-n", type=int, default=10, help="每张卡保留 top-N 图标候选。")
    parser.add_argument("--review-confidence", type=float, default=0.90, help="低于该置信度的金/彩卡片更倾向进入复核。")
    parser.add_argument("--auto-accept-confidence", type=float, default=0.92, help="达到该阈值才机器高可信接受。")
    parser.add_argument("--name-global-assist-score", type=float, default=0.90, help="名称 OCR 全局辅助最低相似度。")
    return parser.parse_args()


def build_output_dir(output_root: Path, output_name: str) -> Path:
    """
    构造本次输出目录。

    输入：
        输出根目录和可选名称。
    输出：
        img_out/run_yyyyMMdd_HHmmss。
    使用示例：
        output_dir = build_output_dir(Path("img_out"), "")
    """
    safe_name = output_name.strip() or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return output_root / safe_name


def build_command(args: argparse.Namespace, output_dir: Path) -> List[str]:
    """
    构造调用 v2 预标注脚本的命令。

    输入：
        用户参数和输出目录。
    输出：
        subprocess.run 可执行的参数列表。
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
        "--auto-accept-confidence",
        str(args.auto_accept_confidence),
        "--name-global-assist-score",
        str(args.name_global_assist_score),
        "--pattern-prefix",
        "collection_next",
    ]

    # 默认先不读碎片数量：这样跑得快，适合你第一轮看装备识别效果。
    if not args.read_quantity:
        command.append("--skip-ocr")

    # 设计图页面有装备名称文字，默认打开名称 OCR 来辅助图标消歧。
    if not args.no_name_ocr:
        command.append("--enable-name-ocr")

    if args.enable_attribute_rerank:
        command.append("--enable-attribute-rerank")
    if args.enable_attribute_ocr:
        command.append("--enable-attribute-ocr")
    return command


# ============================================================
# 🚀 第四部分：命令入口
# ============================================================

def main() -> int:
    """
    执行 collection_next 机器预标注。

    输入：
        collection_next/img_input 下的新截图。
    输出：
        collection_next/img_out/run_xxx 下的标注图、CSV、JSON 和人工复核 exp。
    使用示例：
        python ocr_training_lab/equipment_icon_matcher_v2/collection_next/run_collection_next_prelabel.py
    """
    args = parse_args()
    input_dir = args.input_dir.resolve()
    if not input_dir.exists():
        print(f"截图输入目录不存在: {input_dir}")
        return 1

    image_paths = sorted(path for path in input_dir.glob(args.pattern) if path.is_file())
    if not image_paths:
        print(f"没有找到匹配截图: {input_dir} / {args.pattern}")
        print("请先把 .png 截图放入 collection_next/img_input。")
        return 1

    output_dir = build_output_dir(args.output_root.resolve(), args.output_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(args, output_dir)

    print(f"输入截图目录: {input_dir}")
    print(f"输入截图数量: {len(image_paths)}")
    print(f"输出目录: {output_dir}")
    print("开始机器预标注；PaddleOCR 初始化时可能显示 Creating model，这是正常初始化信息。")

    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"collection_next 预标注失败，退出码: {result.returncode}")
        return int(result.returncode)

    CURRENT_OUT_FILE.write_text(str(output_dir) + "\n", encoding="utf-8")
    print("collection_next 预标注完成。请优先查看：")
    print(f"- 标注图: {output_dir / 'annotated'}")
    print(f"- 只需复核 CSV: {output_dir / 'v2_prelabel_review.csv'}")
    print(f"- 人工填写文件: {output_dir / 'v2_prelabel_review_only_exp.txt'}")
    print(f"- 汇总: {output_dir / 'v2_prelabel_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
