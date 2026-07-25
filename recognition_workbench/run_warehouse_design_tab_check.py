#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🏷️ 仓库设计图页切换检查脚本                          ║
║                                                              ║
║  【一句话解释】把“仓库页 → 设计图页 → 标签确认”做成可一键运行。║
║  【类比理解】它像人工点一次菜单，再把结果清清楚楚打印出来。   ║
║  【数据流说明】当前仓库页 → 切到 design → 截图确认 → JSON 输出。║
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
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.automation.equipment_page import get_equipment_page_adb_api


# ============================================================
# 🌐 第二部分：运行入口
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析仓库设计图页切换检查参数。
    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        python recognition_workbench/run_warehouse_design_tab_check.py --no-confirm
    """
    parser = argparse.ArgumentParser(description="Switch warehouse page to design tab and confirm it.")
    parser.add_argument("--serial", default="", help="可选 ADB 设备串号。")
    parser.add_argument("--no-confirm", action="store_true", help="只执行切页动作，不做截图识别确认。")
    parser.add_argument("--json-out", type=Path, default=None, help="可选 JSON 结果输出路径。")
    return parser.parse_args()


def main() -> int:
    """
    执行仓库设计图页切换检查。
    输入：
        命令行参数。
    输出：
        0 表示成功，1 表示切页或确认失败。
    使用示例：
        python recognition_workbench/run_warehouse_design_tab_check.py
    """
    args = parse_args()
    api = get_equipment_page_adb_api()
    result = api.ensure_warehouse_design_page_ready(
        serial=args.serial or None,
        confirm_with_detector=not bool(args.no_confirm),
    )
    payload: dict[str, Any] = result.to_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
