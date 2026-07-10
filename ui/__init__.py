#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║                    🧩 UI 包入口 (__init__.py)                    ║
║                                                                  ║
║   【一句话解释】暴露 GUI 主窗口和启动函数，方便测试和后续入口接入。║
║   【类比理解】这里像港区门牌，告诉外部主窗口在哪里。             ║
║   【数据流说明】外部导入 ui → MainWindow / run_gui。             ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from typing import Any


# ============================================================
# 🌐 第二部分：包导出声明
# ============================================================

__all__ = ["MainWindow", "run_gui"]


def __getattr__(name: str) -> Any:
    """
    延迟暴露主窗口对象，避免 python -m ui.main_window 时提前导入自身。
    输入：
        name: 外部访问的导出名称。
    输出：
        MainWindow 类或 run_gui 函数。
    使用示例：
        from ui import MainWindow
    """
    if name in __all__:
        from ui.main_window import MainWindow, run_gui

        exports = {"MainWindow": MainWindow, "run_gui": run_gui}
        return exports[name]
    raise AttributeError(f"module 'ui' has no attribute {name!r}")
