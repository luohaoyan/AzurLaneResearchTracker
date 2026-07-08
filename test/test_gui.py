#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║                 🧪 GUI 骨架测试 (test_gui.py)                   ║
║                                                                  ║
║   【测试目标】确认 v0.5.0 P1 主窗口可在离屏环境创建并切换页面。  ║
║   【类比理解】这组测试像开灯巡检，先确认港区指挥室能正常通电。  ║
║   【数据流说明】QApplication → MainWindow → 导航 / 页面 / 接口。║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
from typing import Generator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.future_hooks import FeatureHookRegistry, get_feature_hook_registry
from ui.main_window import AnimatedMascotPanel, MainWindow
from ui.theme import ThemeTokens, build_stylesheet


# ============================================================
# 🧰 第二部分：pytest fixtures
# ============================================================

@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """创建测试用 QApplication，所有 GUI 测试共享同一个实例。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_main_window_creates_navigation_and_pages(qapp: QApplication) -> None:
    """主窗口应能创建导航栏和页面栈。"""
    window = MainWindow()

    assert "碧蓝航线科研装备统计器" in window.windowTitle()
    assert window.navigation_list.count() == 9
    assert window.page_stack.count() == 9
    assert "automation_lab" in window.pages

    window.close()


def test_navigation_switches_page_stack(qapp: QApplication) -> None:
    """点击导航时应同步切换 QStackedWidget 当前页。"""
    window = MainWindow()

    window.navigation_list.setCurrentRow(3)

    assert window.page_stack.currentIndex() == 3
    assert "数据录入" in window.statusBar().currentMessage()

    window.close()


def test_future_hook_registry_has_reserved_features() -> None:
    """未来功能注册表应预留模拟出货和欧非预测入口。"""
    registry = get_feature_hook_registry()
    keys = {feature.key for feature in registry.get_all()}

    assert "research_simulation" in keys
    assert "luck_prediction" in keys
    assert "ocr_recognition" in keys
    assert registry.get("research_simulation") is not None


def test_future_feature_signal_updates_status(qapp: QApplication) -> None:
    """未来功能按钮触发时，主窗口应给出状态栏反馈。"""
    registry = FeatureHookRegistry()
    window = MainWindow(registry=registry)

    window.on_future_feature_requested("luck_prediction")

    assert "欧非走势预测" in window.statusBar().currentMessage()

    window.close()


def test_theme_stylesheet_and_animation_slot(qapp: QApplication) -> None:
    """主题样式和 GIF 动画槽位应可创建，不依赖实际资源文件。"""
    stylesheet = build_stylesheet(ThemeTokens())
    panel = AnimatedMascotPanel()

    assert "QMainWindow" in stylesheet
    assert panel.load_animation("resources/animations/not_exist.gif") is False

    panel.close()
