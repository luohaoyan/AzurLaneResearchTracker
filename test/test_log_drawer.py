#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                📜 运行日志抽屉测试 (test_log_drawer.py)       ║
║                                                              ║
║  【测试目标】确认 GUI 日志抽屉能收起、展开、筛选、复制与清空。 ║
║  【类比理解】这组测试像检查港区通讯记录，用户能一键反馈问题。 ║
║  【数据流说明】LogDrawer → QPlainTextEdit / Clipboard → 断言。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
from typing import Generator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from ui.widgets.log_drawer import LogDrawer


# ============================================================
# 🧩 第二部分：pytest fixtures
# ============================================================

@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """创建测试用 QApplication，所有日志抽屉测试共享同一个实例。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def log_drawer(qapp: QApplication) -> Generator[LogDrawer, None, None]:
    """创建单个日志抽屉，并在测试结束后关闭窗口释放 Qt 对象。"""
    drawer = LogDrawer()
    yield drawer
    drawer.close()


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_log_drawer_starts_collapsed_and_can_toggle(log_drawer: LogDrawer) -> None:
    """日志抽屉默认应收起，并支持展开/收起切换。"""
    assert log_drawer.log_text.isHidden() is True
    assert log_drawer.toggle_button.text() == ">>"

    log_drawer.set_expanded(True)

    assert log_drawer.log_text.isHidden() is False
    assert log_drawer.toggle_button.text() == "<<"


def test_log_drawer_appends_and_filters_messages(log_drawer: LogDrawer) -> None:
    """日志抽屉应能追加日志，并按级别筛选显示。"""
    log_drawer.set_expanded(True)
    log_drawer.append_message("INFO", "启动完成")
    log_drawer.append_message("ERROR", "识别失败")

    assert "启动完成" in log_drawer.log_text.toPlainText()
    assert "识别失败" in log_drawer.log_text.toPlainText()

    log_drawer.filter_combo.setCurrentText("ERROR")

    visible_text = log_drawer.log_text.toPlainText()
    assert "识别失败" in visible_text
    assert "启动完成" not in visible_text


def test_log_drawer_copy_all_and_clear(log_drawer: LogDrawer) -> None:
    """复制全部应写入剪贴板，清空后界面和内存条目都应为空。"""
    log_drawer.append_message("WARNING", "资源即将达到上限")

    log_drawer.copy_all()

    assert "资源即将达到上限" in QGuiApplication.clipboard().text()

    log_drawer.clear()

    assert log_drawer.log_text.toPlainText() == ""
    assert log_drawer._entries == []


def test_log_drawer_copy_diagnostic_info(log_drawer: LogDrawer) -> None:
    """复制诊断信息应包含版本、任务状态和最近日志，方便用户反馈异常。"""
    manager = get_runtime_state_manager()
    manager.reset()
    manager.set_task_state(TaskStateKind.AUTO_TESTING, 40, last_error="无")
    log_drawer.append_message("INFO", "自动化检测开始")

    log_drawer.copy_diagnostic_info()

    copied = QGuiApplication.clipboard().text()
    assert "碧蓝航线科研装备统计器诊断信息" in copied
    assert "当前任务: 自动化测试中" in copied
    assert "任务进度: 40%" in copied
    assert "自动化检测开始" in copied
