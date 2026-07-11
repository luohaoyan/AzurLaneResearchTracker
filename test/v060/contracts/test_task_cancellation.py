#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 协作式取消契约测试                        ║
║                                                              ║
║  【测试目标】确认取消请求能从 GUI 主线程传入后台安全检查点。   ║
║  【类比理解】像发出返航信号，任务在安全位置停下而非强制断电。  ║
║  【数据流说明】TaskManager → Event → TaskContext → cancelled。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
import time
from threading import Event
from typing import Callable, Generator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.contracts import CancellationToken, TaskCancelledError, TaskExecutionContext
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from ui.task_manager import BackgroundTaskSpec, GuiTaskManager, get_gui_task_manager


# ============================================================
# 🧰 第二部分：测试辅助与 fixtures
# ============================================================

def _wait_until(condition: Callable[[], bool], timeout_ms: int = 2000, interval_ms: int = 20) -> bool:
    """等待 Qt 事件循环推进后台线程状态。"""
    elapsed = 0
    while elapsed <= timeout_ms:
        if condition():
            return True
        QTest.qWait(interval_ms)
        elapsed += interval_ms
    return bool(condition())


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """创建离屏 QApplication，供 QThread 信号回到主线程。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def task_manager(qapp: QApplication) -> Generator[GuiTaskManager, None, None]:
    """在每个用例前后清理全局任务状态。"""
    manager = get_gui_task_manager()
    manager.reset_for_tests()
    get_runtime_state_manager().reset()
    yield manager
    assert _wait_until(lambda: not manager.is_running())
    manager.reset_for_tests()
    get_runtime_state_manager().reset()


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_cancellation_token_raises_only_after_request() -> None:
    """取消令牌应在线程安全事件被设置后才抛出专用异常。"""
    token = CancellationToken()
    token.raise_if_cancelled()

    token.request_cancel()

    assert token.is_cancelled() is True
    with pytest.raises(TaskCancelledError, match="测试取消"):
        token.raise_if_cancelled("测试取消")


def test_task_context_clamps_progress_and_forwards_detail() -> None:
    """任务上下文应统一限制进度范围并转发阶段信息。"""
    reports: list[tuple[int, str, str]] = []
    context = TaskExecutionContext(lambda progress, message, detail: reports.append((progress, message, detail)))

    context.report_progress(120, "完成", "detail")

    assert reports == [(100, "完成", "detail")]


def test_task_manager_injects_context_and_stops_at_safe_point(
    task_manager: GuiTaskManager,
) -> None:
    """可取消 QThread 任务应读取 Event 并以 cancelled 状态结束。"""
    started = Event()
    finished_results: list[object] = []
    spec = BackgroundTaskSpec(
        "v060_cancel_probe",
        "v0.6.0 取消探测",
        TaskStateKind.OCR_PROCESSING,
        "正在等待安全取消点。",
        cancel_supported=True,
    )

    def cancellable_runner(*, task_context: TaskExecutionContext) -> None:
        """模拟 OCR 分页循环，每次循环先检查取消令牌。"""
        started.set()
        while True:
            task_context.raise_if_cancelled("OCR 任务已由用户取消。")
            time.sleep(0.01)

    assert task_manager.start_task(spec, cancellable_runner, finished_results.append) is True
    assert _wait_until(started.is_set)
    assert task_manager.request_cancel() is True
    assert _wait_until(lambda: not task_manager.is_running())

    snapshot = task_manager.get_task_snapshots()[0]
    assert snapshot["cancel_requested"] is True
    assert snapshot["status"] == "cancelled"
    assert "用户取消" in snapshot["message"]
    assert len(finished_results) == 1
    finished_result = finished_results[0]
    finished_status = (
        finished_result.get("status")
        if isinstance(finished_result, dict)
        else getattr(finished_result, "status", None)
    )
    assert finished_status == "cancelled"
