#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🛟 运行期状态测试 (test_runtime_state.py)        ║
║                                                              ║
║  【测试目标】确认玩家资源与任务状态只保存在本次运行内存中。   ║
║  【类比理解】这组测试像检查港区白板，开局空白，写入后可读。   ║
║  【数据流说明】RuntimePlayerStatus / RuntimeStateManager → 断言。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from core.state.runtime_state import (
    RuntimePlayerStatus,
    RuntimeStateManager,
    TaskStateKind,
    get_runtime_state_manager,
)


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_runtime_player_status_starts_empty() -> None:
    """玩家资源状态默认应为空，避免把 OCR 结果落成本地持久数据。"""
    status = RuntimePlayerStatus()
    snapshot = status.get_status()

    assert snapshot["player_name"] == "等待识别"
    assert snapshot["oil"] is None
    assert snapshot["coins"] is None
    assert snapshot["gems"] is None
    assert snapshot["available"] is False


def test_runtime_player_status_updates_from_ocr() -> None:
    """OCR 识别结果应能更新玩家名称、石油、物资和钻石。"""
    status = RuntimePlayerStatus()

    status.update_from_ocr({
        "player_name": "测试指挥官",
        "oil": "1200",
        "coins": 3456,
        "gems": 78,
    })
    snapshot = status.get_status()

    assert snapshot["player_name"] == "测试指挥官"
    assert snapshot["oil"] == 1200
    assert snapshot["coins"] == 3456
    assert snapshot["gems"] == 78
    assert snapshot["last_ocr_time"] is not None
    assert snapshot["available"] is True


def test_runtime_state_manager_clamps_progress_and_marks_running() -> None:
    """任务状态应把进度限制在 0-100，并正确标记运行中状态。"""
    manager = RuntimeStateManager()
    manager.reset()

    manager.set_task_state(TaskStateKind.OCR_PROCESSING, 150, current_task="OCR 测试")
    state = manager.get_full_state()

    assert state["task"]["kind"] == "ocr_processing"
    assert state["task"]["kind_name"] == "OCR 识别中"
    assert state["task"]["current_task"] == "OCR 测试"
    assert state["task"]["progress"] == 100
    assert state["task"]["is_running"] is True


def test_runtime_state_manager_error_is_not_running() -> None:
    """异常状态应展示错误信息，但不继续标记为运行中。"""
    manager = RuntimeStateManager()
    manager.reset()

    manager.set_task_state(TaskStateKind.ERROR, -20, last_error="模拟器未连接")
    state = manager.get_full_state()

    assert state["task"]["kind_name"] == "异常"
    assert state["task"]["progress"] == 0
    assert state["task"]["is_running"] is False
    assert state["task"]["last_error"] == "模拟器未连接"


def test_global_runtime_state_manager_can_reset() -> None:
    """全局管理器应能回到默认空闲状态，方便 GUI 测试和程序重启语义。"""
    manager = get_runtime_state_manager()
    manager.update_player_from_ocr({"player_name": "临时数据", "oil": 1, "coins": 2, "gems": 3})
    manager.set_task_state(TaskStateKind.EXPORTING, 66)

    manager.reset()
    state = manager.get_full_state()

    assert state["player"]["player_name"] == "等待识别"
    assert state["player"]["available"] is False
    assert state["task"]["kind"] == "idle"
    assert state["task"]["kind_name"] == "空闲"
    assert state["task"]["is_running"] is False
