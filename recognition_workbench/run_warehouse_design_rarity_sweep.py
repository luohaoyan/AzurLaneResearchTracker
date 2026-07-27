#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🎨 设计图稀有度切换工作台 (run_warehouse_design_rarity_sweep.py) ║
║                                                              ║
║  【一句话解释】把设计图页里的白/蓝/紫/金/彩筛选切换做成一键运行。 ║
║  【类比理解】它像人工依次点五个稀有度标签，再把每一步拍照留档。   ║
║  【数据流说明】当前设计图页 → 稀有度切换 → frames/manifest/summary。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.automation.equipment_page import get_equipment_page_adb_api


# ============================================================
# 🌐 第二部分：运行入口
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析设计图稀有度切换工作台参数。
    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python recognition_workbench/run_warehouse_design_rarity_sweep.py --json-out out.json
    """
    parser = argparse.ArgumentParser(description="Sweep design-page rarity filters and save structured evidence.")
    parser.add_argument("--session-id", default="", help="可选会话 ID；不填则自动生成。")
    parser.add_argument("--output-root", type=Path, default=None, help="可选输出根目录。")
    parser.add_argument("--frame-count", type=int, default=5, help="最多采集多少个稀有度步骤。")
    parser.add_argument(
        "--rarities",
        nargs="+",
        default=["common", "rare", "elite", "super_rare", "ultra_rare"],
        help="稀有度顺序，默认白/蓝/紫/金/彩。",
    )
    parser.add_argument("--resume-cursor", type=int, default=0, help="断点续跑游标，从第几个稀有度开始。")
    parser.add_argument("--json-out", type=Path, default=None, help="可选 JSON 结果输出路径。")
    return parser.parse_args()


def run_design_rarity_sweep(args: argparse.Namespace) -> dict[str, Any]:
    """
    执行设计图稀有度切换会话。
    输入：
        args: 命令行参数。
    输出：
        session.to_dict() 结构化结果。
    使用示例：
        payload = run_design_rarity_sweep(args)
    """
    api = get_equipment_page_adb_api()
    session = api.capture_design_rarity_sequence(
        frame_count=int(args.frame_count),
        rarities=tuple(str(rarity).strip() for rarity in args.rarities),
        resume_cursor=int(args.resume_cursor),
        session_id=str(args.session_id or ""),
        output_root=args.output_root,
    )
    return session.to_dict()


def main() -> int:
    """执行设计图稀有度切换工作台。"""
    args = parse_args()
    payload = run_design_rarity_sweep(args)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0 if bool(payload.get("success", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
