#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                🛟 运行期状态包入口 (__init__.py)             ║
║                                                              ║
║  【一句话解释】暴露运行期玩家资源和任务状态管理器。           ║
║  【类比理解】这里像港区值班牌，记录当前这一轮程序正在做什么。 ║
║  【数据流说明】OCR/任务模块 → RuntimeStateManager → GUI。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from core.state.runtime_state import (
    RuntimePlayerStatus,
    RuntimeStateManager,
    TaskState,
    TaskStateKind,
    get_runtime_state_manager,
)


# ============================================================
# 🌐 第二部分：包导出声明
# ============================================================

__all__ = [
    "RuntimePlayerStatus",
    "RuntimeStateManager",
    "TaskState",
    "TaskStateKind",
    "get_runtime_state_manager",
]
