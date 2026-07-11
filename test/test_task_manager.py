#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🧵 GUI 后台任务管理器测试 (test_task_manager.py)║
║                                                              ║
║  【测试目标】确认 GUI 长任务一次只允许一个运行，并保留取消预留。║
║  【类比理解】这组测试像检查港区远征队，同一时间只派一队出港。 ║
║  【数据流说明】GuiTaskManager → QThread Worker → 任务清单。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
import sys
import time
from typing import Callable, Generator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from ui.automation_bridge import AutomationBridgeResult
from ui.task_manager import BackgroundTaskSpec, get_gui_task_manager


def _wait_until(condition: Callable[[], bool], timeout_ms: int = 2000, interval_ms: int = 25) -> bool:
    """等待 Qt 后台线程把任务推进到目标状态。"""
    elapsed = 0
    while elapsed <= timeout_ms:
        if condition():
            return True
        QTest.qWait(interval_ms)
        elapsed += interval_ms
    return condition()


# ============================================================
# 🧩 第二部分：pytest fixtures
# ============================================================

@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """创建测试用 QApplication，供 QThread 信号回到主线程。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def task_manager(qapp: QApplication) -> Generator[object, None, None]:
    """重置全局任务管理器，避免任务历史污染用例。"""
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

def test_gui_task_manager_allows_only_one_long_task(task_manager: object) -> None:
    """已有长任务运行时，新任务应被拒绝并写入任务清单。"""
    spec = BackgroundTaskSpec(
        "crawler_update",
        "资料爬取更新",
        TaskStateKind.EQUIPMENT_UPDATING,
        "正在更新资料。",
    )

    def slow_runner() -> AutomationBridgeResult:
        """模拟稍慢的爬虫任务，确保第二个任务会撞上运行锁。"""
        time.sleep(0.2)
        return AutomationBridgeResult(True, "success", "资料更新完成", "装备: 2")

    assert task_manager.start_task(spec, slow_runner) is True
    assert task_manager.start_task(spec, slow_runner) is False
    assert _wait_until(lambda: not task_manager.is_running())

    snapshots = task_manager.get_task_snapshots()
    success_snapshot = next(snapshot for snapshot in snapshots if snapshot["status"] == "success")
    assert success_snapshot["title"] == "资料爬取更新"
    assert any(snapshot["status"] == "rejected" for snapshot in snapshots)


def test_gui_task_manager_updates_realtime_progress(task_manager: object) -> None:
    """任务函数上报进度后，任务清单应实时刷新百分比和阶段文案。"""
    spec = BackgroundTaskSpec(
        "crawler_progress_probe",
        "爬虫进度探测",
        TaskStateKind.EQUIPMENT_UPDATING,
        "正在启动爬虫。",
    )

    def progress_runner(progress_reporter: Callable[[int, str, str], bool]) -> AutomationBridgeResult:
        """模拟 crawler 在执行过程中主动上报阶段进度。"""
        progress_reporter(42, "正在下载装备图片 42/100。", "试作型装备")
        time.sleep(0.15)
        return AutomationBridgeResult(True, "success", "爬虫进度探测完成", "图片: 100")

    assert task_manager.start_task(spec, progress_runner) is True
    assert _wait_until(
        lambda: task_manager.get_task_snapshots()[0]["progress"] == 42
        and "下载装备图片" in task_manager.get_task_snapshots()[0]["message"]
    )
    assert _wait_until(lambda: not task_manager.is_running())

    snapshot = task_manager.get_task_snapshots()[0]
    assert snapshot["progress"] == 100
    assert snapshot["status"] == "success"
    assert snapshot["message"].startswith("已执行：")


def test_gui_task_manager_records_cancel_request(task_manager: object) -> None:
    """可取消任务应先记录取消请求，后续 OCR 可在安全点读取该标记。"""
    spec = BackgroundTaskSpec(
        "ocr_preview",
        "OCR 识别预览",
        TaskStateKind.OCR_PROCESSING,
        "正在识别截图。",
        cancel_supported=True,
    )

    def slow_runner() -> AutomationBridgeResult:
        """模拟 OCR 长任务，给取消请求留出时间窗口。"""
        time.sleep(0.2)
        return AutomationBridgeResult(True, "success", "OCR 识别完成", "")

    assert task_manager.start_task(spec, slow_runner) is True
    assert task_manager.request_cancel() is True

    running_snapshot = task_manager.get_task_snapshots()[0]
    assert running_snapshot["cancel_requested"] is True
    assert "取消请求" in running_snapshot["message"]
    assert _wait_until(lambda: not task_manager.is_running())


def test_gui_task_manager_can_run_process_task(task_manager: object) -> None:
    """进程任务入口应能执行外部命令，为后续 OCR 独立进程预留通道。"""
    spec = BackgroundTaskSpec(
        "ocr_process_probe",
        "OCR 进程探测",
        TaskStateKind.OCR_PROCESSING,
        "正在启动 OCR 子进程。",
        cancel_supported=True,
    )

    assert task_manager.start_process_task(spec, sys.executable, ["-c", "print('ocr-process-ok')"]) is True
    assert _wait_until(lambda: not task_manager.is_running(), timeout_ms=3000)

    snapshots = task_manager.get_task_snapshots()
    success_snapshot = next(snapshot for snapshot in snapshots if snapshot["task_id"] == "ocr_process_probe")
    assert success_snapshot["status"] == "success"
    assert "ocr-process-ok" in success_snapshot["detail"]


def test_gui_task_manager_process_start_failure_releases_lock(task_manager: object) -> None:
    """进程启动失败时应释放长任务锁，避免 OCR 路径错误后无法再次操作。"""
    spec = BackgroundTaskSpec(
        "ocr_process_missing",
        "OCR 缺失进程",
        TaskStateKind.OCR_PROCESSING,
        "正在启动 OCR 子进程。",
    )

    assert task_manager.start_process_task(spec, "definitely-missing-ocr-worker.exe", []) is True
    assert _wait_until(lambda: not task_manager.is_running(), timeout_ms=3000)

    snapshot = next(item for item in task_manager.get_task_snapshots() if item["task_id"] == "ocr_process_missing")
    assert snapshot["status"] == "error"
    assert "启动失败" in snapshot["message"]
