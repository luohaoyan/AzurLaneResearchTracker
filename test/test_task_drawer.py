#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🧾 悬浮任务清单抽屉测试 (test_task_drawer.py)   ║
║                                                              ║
║  【测试目标】确认右侧任务抽屉能悬浮覆盖、实时刷新和清理记录。 ║
║  【类比理解】像检查港区右侧任务板，展开查看不应挤动主界面。   ║
║  【数据流说明】GuiTaskManager → TaskDrawer → QListWidget。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
import time
from typing import Callable, Generator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from core.state.runtime_state import TaskStateKind
from ui.automation_bridge import AutomationBridgeResult
from ui.task_manager import BackgroundTaskSpec, get_gui_task_manager
from ui.widgets.task_drawer import TaskDrawer


def _wait_until(condition: Callable[[], bool], timeout_ms: int = 1800, interval_ms: int = 25) -> bool:
    """在离屏 Qt 测试环境中等待线程信号和动画状态稳定。"""
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
    """创建测试用 QApplication，所有任务抽屉测试共享同一个实例。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def task_drawer(qapp: QApplication) -> Generator[TaskDrawer, None, None]:
    """创建带父容器的任务抽屉，并在结束后重置任务管理器。"""
    get_gui_task_manager().reset_for_tests()
    parent = QWidget()
    parent.resize(1000, 640)
    drawer = TaskDrawer(parent)
    drawer.fit_to_parent()
    parent.show()
    qapp.processEvents()
    yield drawer
    drawer.close()
    parent.close()
    get_gui_task_manager().reset_for_tests()


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_task_drawer_overlays_parent_without_resizing_content(task_drawer: TaskDrawer) -> None:
    """任务抽屉展开时应贴住右侧覆盖内容，而不是挤压父容器。"""
    parent = task_drawer.parentWidget()
    assert parent is not None
    content = QWidget(parent)
    content.setGeometry(parent.rect())
    original_geometry = content.geometry()

    task_drawer.fit_to_parent()

    assert task_drawer.width() == task_drawer.collapsed_width
    assert task_drawer.height() == task_drawer.collapsed_height
    assert task_drawer.geometry().right() == parent.rect().right()
    assert task_drawer.geometry().top() == task_drawer.collapsed_top_offset

    task_drawer.set_expanded(True, animate=False)

    assert task_drawer.width() == task_drawer.expanded_width
    assert task_drawer.geometry().right() == parent.rect().right()
    assert content.geometry() == original_geometry
    assert task_drawer.task_list.isHidden() is False

    task_drawer.set_expanded(False, animate=False)

    assert task_drawer.width() == task_drawer.collapsed_width
    assert task_drawer.height() == task_drawer.collapsed_height
    assert task_drawer.geometry().right() == parent.rect().right()
    assert task_drawer.geometry().top() == task_drawer.collapsed_top_offset
    assert content.geometry() == original_geometry
    assert task_drawer.task_list.isHidden() is True


def test_task_drawer_realtime_progress_updates(task_drawer: TaskDrawer) -> None:
    """后台任务进度回调应实时刷新任务清单，不只在结束时跳到 100%。"""
    manager = get_gui_task_manager()
    spec = BackgroundTaskSpec(
        "crawler_progress",
        "爬虫资料更新",
        TaskStateKind.EQUIPMENT_UPDATING,
        "准备更新资料。",
    )

    def runner(progress_reporter: Callable[[int, str, str], bool]) -> AutomationBridgeResult:
        """模拟爬虫下载过程中的分段进度上报。"""
        progress_reporter(35, "装备图片下载中", "10/30")
        time.sleep(0.16)
        progress_reporter(66, "科研数据整理中", "2/3")
        time.sleep(0.08)
        return AutomationBridgeResult(True, "success", "资料更新完成", "装备: 2")

    assert manager.start_task(spec, runner) is True
    assert _wait_until(lambda: "35%" in task_drawer.task_list.item(0).text())
    assert "装备图片下载中" in task_drawer.task_list.item(0).text()
    assert _wait_until(lambda: not manager.is_running())
    assert _wait_until(lambda: "✅ 已执行" in task_drawer.task_list.item(0).text())

    item_text = task_drawer.task_list.item(0).text()
    assert "100%" in item_text
    assert "已执行：资料更新完成" in item_text


def test_task_drawer_can_delete_finished_tasks(task_drawer: TaskDrawer) -> None:
    """已执行任务应允许单条删除，避免任务清单越堆越长。"""
    manager = get_gui_task_manager()
    spec = BackgroundTaskSpec(
        "finished_task",
        "已完成任务",
        TaskStateKind.AUTO_TESTING,
        "正在执行测试任务。",
    )

    def runner() -> AutomationBridgeResult:
        """模拟立即完成的后台任务。"""
        return AutomationBridgeResult(True, "success", "测试任务完成", "")

    assert manager.start_task(spec, runner) is True
    assert _wait_until(lambda: not manager.is_running())
    task_drawer.refresh_task_list()

    item_text = task_drawer.task_list.item(0).text()
    assert "✅ 已执行" in item_text
    assert "[██████████]" in item_text

    task_drawer.task_list.setCurrentRow(0)
    assert task_drawer.delete_task_button.isEnabled() is True
    task_drawer.delete_task_button.click()

    assert manager.get_task_snapshots() == []
    assert "暂无后台任务" in task_drawer.task_list.item(0).text()


def test_task_drawer_can_clear_all_finished_tasks(task_drawer: TaskDrawer) -> None:
    """清理已完成应一次移除所有非运行任务，保留任务清单可读。"""
    manager = get_gui_task_manager()
    spec = BackgroundTaskSpec(
        "clearable_task",
        "可清理任务",
        TaskStateKind.AUTO_TESTING,
        "正在执行测试任务。",
    )

    def runner() -> AutomationBridgeResult:
        """模拟立即完成的后台任务。"""
        return AutomationBridgeResult(True, "success", "测试任务完成", "")

    assert manager.start_task(spec, runner) is True
    assert _wait_until(lambda: not manager.is_running())
    task_drawer.refresh_task_list()

    assert task_drawer.clear_finished_button.isEnabled() is True
    task_drawer.clear_finished_button.click()

    assert manager.get_task_snapshots() == []
    assert "暂无后台任务" in task_drawer.task_list.item(0).text()
