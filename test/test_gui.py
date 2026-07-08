#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                  🧪 GUI 骨架测试 (test_gui.py)               ║
║                                                              ║
║  【测试目标】确认 v0.5.0 P1 主窗口可在离屏环境创建并切换页面。 ║
║  【类比理解】这组测试像开灯巡检，先确认港区指挥室能正常通电。 ║
║  【数据流说明】QApplication → MainWindow → 导航 / 页面 / 接口。 ║
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

from PySide6.QtCharts import QChartView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from ui.future_hooks import FeatureHookRegistry, get_feature_hook_registry
from ui.main_window import AnimatedMascotPanel, MainWindow, get_gui_version
from ui.theme import ThemeTokens, build_stylesheet


# ============================================================
# 🧩 第二部分：pytest fixtures
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
    """主窗口应能创建用户可见导航、页面栈和底部日志抽屉。"""
    window = MainWindow()

    assert "碧蓝航线科研装备统计器" in window.windowTitle()
    assert "v0.5.0" in window.windowTitle()
    assert window.navigation_list.count() == 9
    assert window.page_stack.count() == 9
    assert set(window.pages) == {
        "dashboard",
        "user_data",
        "research_progress",
        "trend",
        "automation_lab",
        "future",
        "mini_game",
        "settings",
        "about",
    }
    assert window.log_drawer.toggle_button.text() == "展开日志"

    window.close()


def test_gui_version_reads_main_config() -> None:
    """GUI 版本号应来自 config/config.json 的 app.version，而不是写死在窗口代码里。"""
    assert get_gui_version() == "v0.5.0"


def test_navigation_switches_page_stack(qapp: QApplication) -> None:
    """点击导航时应同步切换 QStackedWidget 当前页。"""
    window = MainWindow()

    window.navigation_list.setCurrentRow(3)

    assert window.page_stack.currentIndex() == 3
    assert "历史趋势" in window.statusBar().currentMessage()

    window.close()


def test_collapsible_navigation_hides_content_and_keeps_mapping(qapp: QApplication) -> None:
    """左侧导航折叠后应隐藏内部内容，展开后恢复完整页面名称。"""
    window = MainWindow()

    assert window.nav_toggle_button.text() == "<<"

    window.toggle_navigation()
    QTest.qWait(window.nav_animation_duration_ms + 180)

    assert window.nav_collapsed is True
    assert window.nav_toggle_button.text() == ">>"
    assert window.navigation_list.isHidden() is True
    assert window.app_title.isHidden() is True
    assert window.navigation_list.item(0).text() == ""
    assert window.navigation_panel.width() == window.theme_tokens.nav_collapsed_width

    window.toggle_navigation()
    QTest.qWait(window.nav_animation_duration_ms + 180)

    assert window.nav_collapsed is False
    assert window.nav_toggle_button.text() == "<<"
    assert window.navigation_list.isHidden() is False
    assert window.app_title.isHidden() is False
    assert window.navigation_list.item(0).text() == "港区实况"

    window.close()


def test_dashboard_quick_action_switches_to_user_data(qapp: QApplication) -> None:
    """港区实况页的快捷入口应能切换到对应页面。"""
    window = MainWindow()

    window.switch_to_page("user_data")

    assert window.page_stack.currentWidget() is window.pages["user_data"]
    assert "用户数据" in window.statusBar().currentMessage()

    window.close()


def test_user_data_table_hides_internal_equipment_id(qapp: QApplication) -> None:
    """用户数据页表格不应把内部装备编号暴露给普通用户。"""
    window = MainWindow()
    page = window.pages["user_data"]

    headers = [
        page.table.horizontalHeaderItem(index).text()
        for index in range(page.table.columnCount())
    ]

    assert "equipment_id" not in headers
    assert "装备编号" not in headers
    assert headers == ["装备名称", "稀有度", "类型", "科研期", "拥有数量", "碎片数量"]
    assert page.table.cellWidget(0, 0) is not None
    assert page.table.cellWidget(0, 0).findChild(QLabel, "equipment_icon_label") is not None

    window.close()


def test_user_data_missing_equipment_icon_uses_blank_pixmap(qapp: QApplication) -> None:
    """装备图片缺失时应使用固定尺寸空白图标，避免大图或缺图破坏表格布局。"""
    window = MainWindow()
    page = window.pages["user_data"]

    pixmap = page._load_equipment_icon("")

    assert pixmap.isNull() is False
    assert pixmap.width() == page.icon_size
    assert pixmap.height() == page.icon_size

    window.close()


def test_trend_page_builds_chart_and_metric_controls(qapp: QApplication) -> None:
    """历史趋势页应创建真实折线图、指标勾选和明细表。"""
    window = MainWindow()
    trend_page = window.pages["trend"]
    headers = [
        trend_page.trend_table.horizontalHeaderItem(index).text()
        for index in range(trend_page.trend_table.columnCount())
    ]

    assert trend_page.findChild(QChartView) is not None
    assert set(trend_page.metric_checks) == {
        "equipment_count",
        "fragment_count",
        "equivalent_score",
        "luck_value",
    }
    assert headers == ["日期", "装备数量", "碎片总量", "等值分", "欧非值", "评价"]

    window.close()


def test_trend_page_refreshes_chart_series_from_rows(qapp: QApplication) -> None:
    """历史趋势页应能把趋势行刷新成多条折线。"""
    window = MainWindow()
    trend_page = window.pages["trend"]

    rows = [
        {
            "date": "2026-07-01",
            "equipment_count": 1,
            "fragment_count": 30,
            "equivalent_score": 80,
            "luck_value": 7.0,
            "luck_level": "极欧",
        },
        {
            "date": "2026-07-02",
            "equipment_count": 3,
            "fragment_count": 45,
            "equivalent_score": 170,
            "luck_value": 3.25,
            "luck_level": "较欧",
        },
    ]

    trend_page._refresh_chart(rows, ["equipment_count", "fragment_count"])

    assert len(trend_page.chart.series()) == 2
    assert "多指标" in trend_page.chart_status.text()
    assert trend_page._normalize_chart_value(15.0, 10.0, 20.0) == 50.0

    window.close()


def test_dashboard_reflects_runtime_task_state(qapp: QApplication) -> None:
    """港区实况页应能展示当前运行任务状态和进度。"""
    manager = get_runtime_state_manager()
    manager.reset()
    window = MainWindow()

    manager.set_task_state(TaskStateKind.OCR_PROCESSING, 55, "正在识别港区资源")
    dashboard = window.pages["dashboard"]
    dashboard.refresh_state()

    assert "OCR 识别中" in dashboard.task_title.text()
    assert dashboard.task_message.text() == "正在识别港区资源"
    assert dashboard.task_progress.value() == 55

    window.close()
    manager.reset()


def test_future_hook_registry_has_reserved_features() -> None:
    """未来功能注册表应预留模拟出货、欧非预测、OCR 和小游戏入口。"""
    registry = get_feature_hook_registry()
    keys = {feature.key for feature in registry.get_all()}

    assert "research_simulation" in keys
    assert "luck_prediction" in keys
    assert "ocr_recognition" in keys
    assert "mini_games" in keys
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
    assert "QPlainTextEdit#log_text" in stylesheet
    assert panel.load_animation("resources/animations/not_exist.gif") is False

    panel.close()
