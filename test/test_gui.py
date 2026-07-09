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

from PySide6.QtCore import QDate, Qt
from PySide6.QtCharts import QChartView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from ui.future_hooks import FeatureHookRegistry, get_feature_hook_registry
from ui.main_window import AnimatedMascotPanel, MainWindow, get_gui_version
from ui.theme import ThemeTokens, build_stylesheet
from ui.ui_config import get_ui_config_manager


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

    assert window.nav_toggle_button.text() == "<"
    expanded_button_pos = window.nav_toggle_button.geometry().topLeft()

    window.toggle_navigation()
    QTest.qWait(window.nav_animation_duration_ms + 180)

    assert window.nav_collapsed is True
    assert window.nav_toggle_button.text() == ">"
    assert window.navigation_list.isHidden() is True
    assert window.app_title.isHidden() is True
    assert window.navigation_list.item(0).text() == ""
    assert window.navigation_panel.width() == window.theme_tokens.nav_collapsed_width
    assert window.theme_tokens.nav_collapsed_width <= 60
    assert window.nav_toggle_button.geometry().topLeft() == expanded_button_pos

    window.toggle_navigation()
    QTest.qWait(window.nav_animation_duration_ms + 180)

    assert window.nav_collapsed is False
    assert window.nav_toggle_button.text() == "<"
    assert window.navigation_list.isHidden() is False
    assert window.app_title.isHidden() is False
    assert window.navigation_list.item(0).text() == "港区实况"
    assert window.nav_toggle_button.geometry().topLeft() == expanded_button_pos

    window.close()


def test_dashboard_quick_action_switches_to_user_data(qapp: QApplication) -> None:
    """港区实况页的快捷入口应能切换到对应页面。"""
    window = MainWindow()

    window.switch_to_page("user_data")

    assert window.page_stack.currentWidget() is window.pages["user_data"]
    assert "用户数据" in window.statusBar().currentMessage()

    window.close()


def test_research_progress_page_shows_real_progress_widgets(qapp: QApplication) -> None:
    """科研进度页应展示真实进度汇总、最新标记和装备明细表。"""
    window = MainWindow()
    page = window.pages["research_progress"]

    assert page.overall_progress_bar.maximum() == 10000
    assert page.overall_progress_bar.orientation() == Qt.Orientation.Vertical
    assert page.target_combo.count() == 20
    assert page.target_combo.width() <= 140
    assert page.target_combo.width() >= page.target_combo.fontMetrics().horizontalAdvance("20 件") + 42
    assert page.target_combo.itemData(0) == 1
    assert page.target_combo.itemData(19) == 20
    assert page.secretary_avatar_label.objectName() == "secretary_avatar"
    assert page.secretary_dialog_frame.objectName() == "secretary_dialog"
    assert "duration" in page.summary_cards
    assert page.progress_table.columnCount() == 4
    assert [
        page.progress_table.horizontalHeaderItem(index).text()
        for index in range(page.progress_table.columnCount())
    ] == ["装备", "需求图纸", "当前图纸", "整装"]
    assert page.progress_table.rowCount() >= 1
    assert "最新科研期" in page.notice_label.text()
    assert page.score_value_label.text() != ""
    assert page.luck_value_label.objectName() == "luck_badge"

    history_index = page.phase_combo.findData(1)
    page.phase_combo.setCurrentIndex(history_index)
    page.target_combo.setCurrentIndex(11)
    page.refresh_progress()

    assert "历史科研期" in page.notice_label.text()
    assert "过期科研" in page.target_comment_label.text()

    window.close()


def test_research_progress_target_and_secretary_share_one_row(qapp: QApplication) -> None:
    """目标彩装选择和秘书舰对话应保持同一行，避免卡片出现大块空白。"""
    window = MainWindow()
    window.resize(1280, 820)
    window.switch_to_page("research_progress")
    window.show()
    qapp.processEvents()
    QTest.qWait(120)
    page = window.pages["research_progress"]
    target_card = page.summary_cards["target"]
    duration_card = page.summary_cards["duration"]

    target_combo_center = page.target_combo.mapTo(target_card, page.target_combo.rect().center())
    avatar_center = page.secretary_avatar_label.mapTo(target_card, page.secretary_avatar_label.rect().center())
    dialog_center = page.secretary_dialog_frame.mapTo(target_card, page.secretary_dialog_frame.rect().center())

    assert target_card.geometry().x() > duration_card.geometry().x()
    assert 120 <= page.target_combo.width() <= 140
    assert abs(target_combo_center.y() - avatar_center.y()) <= 36
    assert avatar_center.x() > target_combo_center.x()
    assert dialog_center.x() > avatar_center.x()
    assert page.secretary_dialog_frame.width() >= 220

    window.close()


def test_research_progress_secretary_dialog_keeps_target_layout_stable(qapp: QApplication) -> None:
    """目标对话长短变化时，目标彩装一行的控件位置不应跟着漂移。"""
    window = MainWindow()
    window.resize(1280, 820)
    window.switch_to_page("research_progress")
    window.show()
    qapp.processEvents()
    QTest.qWait(120)
    page = window.pages["research_progress"]
    target_card = page.summary_cards["target"]

    def current_positions() -> tuple[int, int, int, int, int]:
        qapp.processEvents()
        return (
            page.target_combo.mapTo(target_card, page.target_combo.rect().topLeft()).x(),
            page.completed_value_label.mapTo(target_card, page.completed_value_label.rect().topLeft()).x(),
            page.secretary_avatar_label.mapTo(target_card, page.secretary_avatar_label.rect().topLeft()).x(),
            page.secretary_dialog_frame.mapTo(target_card, page.secretary_dialog_frame.rect().topLeft()).x(),
            page.secretary_dialog_frame.width(),
        )

    baseline_positions = current_positions()
    for target_count in (1, 5, 9, 20, 2):
        index = page.target_combo.findData(target_count)
        page.target_combo.setCurrentIndex(index)
        QTest.qWait(80)
        assert current_positions() == baseline_positions

    window.close()


def test_research_progress_duration_and_dialog_use_ui_config(qapp: QApplication) -> None:
    """科研天数和秘书舰对话应来自 UI JSON 配置，并按开始日为第 1 天计算。"""
    window = MainWindow()
    page = window.pages["research_progress"]
    config = get_ui_config_manager().get_research_progress_config()

    assert "phase_start_dates" in config
    assert page._calculate_research_day(QDate(2026, 3, 10), QDate(2026, 3, 10)) == 1
    assert page._calculate_research_day(QDate(2026, 3, 10), QDate(2026, 3, 11)) == 2
    assert page._duration_message(8) == config["duration_messages"][1]["text"]

    page.target_combo.setCurrentIndex(4)
    QTest.qWait(80)

    assert page.secretary_dialog_frame.isHidden() is False
    assert page.target_comment_label.text() == page._target_comment(5, float(page.overall_progress_bar.value()) / 100, True)

    window.close()


def test_research_progress_rejects_future_start_date_and_resets_official(qapp: QApplication) -> None:
    """科研开始时间不能超过今天，复位按钮应回到配置中的官方开始时间。"""
    manager = get_ui_config_manager()
    original_config = manager.get_research_progress_config()
    window = MainWindow()
    page = window.pages["research_progress"]
    phase_number = int(page.phase_combo.currentData() or 0)
    today = QDate.currentDate()
    future = today.addDays(12)

    try:
        page.start_date_edit.setMaximumDate(future)
        page._syncing_start_date = True
        page.start_date_edit.setDate(future)
        page._syncing_start_date = False
        page._on_start_date_changed()

        assert page.start_date_edit.date() == today
        assert "时间选择有误" in page.notice_label.text()

        official_date = page._official_start_date(phase_number)
        page.start_date_edit.setDate(today.addDays(-1))
        page._reset_start_date_to_official()

        assert page.start_date_edit.date() == official_date
        assert f"第 {phase_number} 期科研官方开始时间" in page.reset_start_date_button.toolTip()
        assert "官方开始时间" in page.notice_label.text()
    finally:
        manager.config_loader.save_config("ui", "research_progress", original_config)
        window.close()


def test_research_progress_target_comment_uses_current_and_history_context() -> None:
    """目标评价应区分最新科研期与历史科研期，避免把补旧期误读成欧非。"""
    window = MainWindow()
    page = window.pages["research_progress"]

    assert "歪头" in page._target_comment(1, 20.0, True)
    assert "标准指挥官" in page._target_comment(3, 20.0, True)
    assert "勇者级" in page._target_comment(6, 20.0, True)
    assert "理智值" in page._target_comment(9, 20.0, True)
    assert "新目标" in page._target_comment(3, 100.0, True)
    assert "过期科研" in page._target_comment(20, 20.0, False)

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
