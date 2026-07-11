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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QFrame, QLabel, QMessageBox, QScrollArea, QSizePolicy
from matplotlib.colors import to_hex

from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from ui.automation_bridge import AutomationBridgeResult
from ui.future_hooks import FeatureHookRegistry, FutureFeatureSpec, get_feature_hook_registry
from ui.main_window import (
    AnimatedMascotPanel,
    FutureDockPage,
    MainWindow,
    get_gui_version,
    get_selectable_research_progress_phases,
)
from ui.theme import ThemeTokens, build_stylesheet, get_theme_skin, list_theme_skins
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
    assert window.task_drawer.width() == window.task_drawer.collapsed_width
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


def test_main_window_task_drawer_overlays_without_layout_shift(qapp: QApplication) -> None:
    """右侧任务抽屉展开时应覆盖在主界面上，不改变导航栏和页面栈布局。"""
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    qapp.processEvents()

    original_page_geometry = window.page_stack.geometry()
    original_navigation_width = window.navigation_panel.width()
    central_right = window.centralWidget().rect().right()

    window.task_drawer.set_expanded(True, animate=False)
    qapp.processEvents()

    assert window.page_stack.geometry() == original_page_geometry
    assert window.navigation_panel.width() == original_navigation_width
    assert window.task_drawer.geometry().right() == central_right
    assert window.task_drawer.width() == window.task_drawer.expanded_width

    window.task_drawer.set_expanded(False, animate=False)
    qapp.processEvents()

    assert window.page_stack.geometry() == original_page_geometry
    assert window.task_drawer.geometry().right() == central_right
    assert window.task_drawer.width() == window.task_drawer.collapsed_width
    assert window.task_drawer.height() == window.task_drawer.collapsed_height

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
    window.resize(1280, 820)
    window.show()
    qapp.processEvents()
    QTest.qWait(80)

    assert window.nav_toggle_button.text() == "<"
    expanded_button_pos = window.nav_toggle_button.mapTo(window, window.nav_toggle_button.rect().topLeft())

    window.toggle_navigation()
    QTest.qWait(window.nav_animation_duration_ms + 180)
    qapp.processEvents()

    assert window.nav_collapsed is True
    assert window.nav_toggle_button.text() == ">"
    assert window.navigation_list.isHidden() is True
    assert window.app_title.isHidden() is True
    assert window.navigation_list.item(0).text() == ""
    assert window.navigation_panel.width() == window.theme_tokens.nav_collapsed_width
    assert window.theme_tokens.nav_collapsed_width <= 60
    assert window.nav_toggle_button.mapTo(window, window.nav_toggle_button.rect().topLeft()) == expanded_button_pos

    window.toggle_navigation()
    QTest.qWait(window.nav_animation_duration_ms + 180)
    qapp.processEvents()

    assert window.nav_collapsed is False
    assert window.nav_toggle_button.text() == "<"
    assert window.navigation_list.isHidden() is False
    assert window.app_title.isHidden() is False
    assert window.navigation_list.item(0).text() == "港区实况"
    assert window.nav_toggle_button.mapTo(window, window.nav_toggle_button.rect().topLeft()) == expanded_button_pos

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
    assert 88 <= page.target_combo.width() <= 124
    assert page.target_combo.itemData(0) == 1
    assert page.target_combo.itemData(19) == 20
    assert page.secretary_avatar_label.objectName() == "secretary_avatar"
    assert page.secretary_avatar_label.height() >= 108
    assert page.secretary_dialog_frame.objectName() == "secretary_dialog"
    assert page.secretary_dialog_frame.height() >= 108
    assert "duration" in page.summary_cards
    assert page.progress_table.columnCount() == 5
    assert [
        page.progress_table.horizontalHeaderItem(index).text()
        for index in range(page.progress_table.columnCount())
    ] == ["装备", "稀有度", "当前图纸", "整装", "总碎片"]
    assert "位置" not in [
        page.progress_table.horizontalHeaderItem(index).text()
        for index in range(page.progress_table.columnCount())
    ]
    assert page.progress_table.rowCount() == 6
    assert page.progress_table.item(0, 0).icon().isNull() is False
    assert page.progress_table.item(0, 0).toolTip() == "彩装位"
    assert "最新科研期" in page.notice_label.text()
    assert page.score_value_label.text() != ""
    assert page.luck_value_label.objectName() == "luck_badge"

    selectable_phase_numbers = {
        int(phase.get("phase_number", 0))
        for phase in get_selectable_research_progress_phases()
    }
    combo_phase_numbers = {
        int(page.phase_combo.itemData(index) or 0)
        for index in range(page.phase_combo.count())
    }
    assert combo_phase_numbers == selectable_phase_numbers
    assert int(page.phase_combo.currentData() or 0) == max(selectable_phase_numbers)
    assert "待加载" not in page.phase_combo.currentText()
    assert "异常" not in page.phase_combo.currentText()

    assert page.phase_combo.findData(1) == -1
    history_index = page.phase_combo.findData(2)
    assert history_index >= 0
    page.phase_combo.setCurrentIndex(history_index)
    page.target_combo.setCurrentIndex(11)
    page.refresh_progress()

    assert "历史科研期" in page.notice_label.text()
    assert page._last_target_context in {"history", "history_completed"}
    assert page._last_target_comment != ""

    window.close()


def test_research_progress_equipment_table_uses_fixed_rainbow_gold_slots(qapp: QApplication) -> None:
    """科研装备明细应固定展示 1 彩 + 5 金槽位，不再把彩装目标数放进表格。"""
    window = MainWindow()
    page = window.pages["research_progress"]
    rows = [
        {"equipment_id": "S2-002", "equipment_name": "金装 B", "rarity_id": 4, "rarity_name": "超稀有", "fragment_count": 12, "equipment_count": 0, "equivalent": 25},
        {"equipment_id": "S2-001", "equipment_name": "彩装 A", "rarity_id": 5, "rarity_name": "海上传奇", "fragment_count": 35, "equipment_count": 1, "equivalent": 50},
        {"equipment_id": "S2-003", "equipment_name": "金装 A", "rarity_id": 4, "rarity_name": "超稀有", "fragment_count": 7, "equipment_count": 0, "equivalent": 25},
    ]

    page._update_table(rows)

    assert page.progress_table.rowCount() == 6
    assert page.progress_table.item(0, 0).toolTip() == "彩装位"
    assert page.progress_table.item(0, 0).text() == "彩装 A"
    assert page.progress_table.item(0, 0).icon().isNull() is False
    assert page.progress_table.item(0, 4).text() == "85"
    assert page.progress_table.item(1, 0).toolTip() == "金装位 1"
    assert page.progress_table.item(1, 0).text() == "金装 A"
    assert page.progress_table.item(1, 4).text() == "7"
    assert page.progress_table.item(2, 0).toolTip() == "金装位 2"
    assert page.progress_table.item(2, 0).text() == "金装 B"
    assert page.progress_table.item(3, 0).text() == "待资料同步"
    assert page.progress_table.item(3, 3).text() == "—"

    window.close()


def test_research_progress_completed_count_follows_target_selection(qapp: QApplication) -> None:
    """目标彩装数量改变后，完成装备的分母应跟随用户选择，而不是固定为 6 个装备槽。"""
    window = MainWindow()
    page = window.pages["research_progress"]

    for target_count in (1, 3, 8):
        target_index = page.target_combo.findData(target_count)
        assert target_index >= 0
        page.target_combo.setCurrentIndex(target_index)
        page.refresh_progress()

        assert page.completed_value_label.text().endswith(f"/ {target_count}")

    window.close()


def test_research_progress_prompts_update_when_all_phases_invalid(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """如果所有科研期都不符合 1 彩 + 5 金结构，页面应提示用户重新更新数据。"""
    import ui.main_window as main_window_module

    monkeypatch.setattr(main_window_module, "get_selectable_research_progress_phases", lambda: [])
    window = MainWindow()
    page = window.pages["research_progress"]

    page.refresh_progress()

    assert page.phase_combo.currentData() == 0
    assert "异常" in page.phase_combo.currentText()
    assert "更新装备表" in page.notice_label.text()

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
    assert 88 <= page.target_combo.width() <= 124
    assert avatar_center.y() > target_combo_center.y()
    assert avatar_center.x() > target_combo_center.x()
    assert dialog_center.x() > avatar_center.x()
    assert page.secretary_dialog_frame.width() >= 300

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
    assert page.secretary_dialog_frame.property("quiet") is False
    assert page.target_comment_label.text() in page._secretary_lines(page._last_target_context)

    page._reset_secretary_dialog()

    assert page.secretary_dialog_frame.property("quiet") is True
    assert page.target_comment_label.text() == ""

    window.close()


def test_research_progress_secretary_dialog_timer_restarts_on_new_dialog(qapp: QApplication) -> None:
    """连续切换目标时，新秘书舰对话不应被上一轮旧计时器提前清空。"""
    window = MainWindow()
    page = window.pages["research_progress"]
    page.secretary_lines_config["dialog_duration_ms"] = 800
    page.ui_config.setdefault("secretary", {})["dialog_duration_ms"] = 800

    page._show_secretary_dialog("第一次目标提示")
    QTest.qWait(100)
    page._show_secretary_dialog("第二次目标提示")
    QTest.qWait(950)

    assert page._secretary_dialog_timer.interval() >= 3600
    assert page.secretary_dialog_frame.property("quiet") is False
    assert page.target_comment_label.text() == "第二次目标提示"

    page._reset_secretary_dialog()
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
        if phase_number == 9:
            assert official_date == QDate(2026, 7, 9)
        page.start_date_edit.setDate(today.addDays(-1))
        page._reset_start_date_to_official()

        assert page.start_date_edit.date() == official_date
        assert f"第 {phase_number} 期科研官方开始时间" in page.reset_start_date_button.toolTip()
        assert "官方开始时间" in page.notice_label.text()
    finally:
        manager.config_loader.save_config("ui", "research_progress", original_config)
        window.close()


def test_research_progress_persists_target_per_phase(qapp: QApplication) -> None:
    """科研进度页应按 PR 期数分别保存目标彩装数量，不同期数互不覆盖。"""
    manager = get_ui_config_manager()
    original_config = manager.get_research_progress_config()
    window = MainWindow()
    page = window.pages["research_progress"]

    try:
        phase_two_index = page.phase_combo.findData(2)
        phase_six_index = page.phase_combo.findData(6)
        assert phase_two_index >= 0
        assert phase_six_index >= 0
        page.phase_combo.setCurrentIndex(phase_two_index)
        page.target_combo.setCurrentIndex(page.target_combo.findData(3))
        page.phase_combo.setCurrentIndex(phase_six_index)
        page.target_combo.setCurrentIndex(page.target_combo.findData(5))

        config = manager.get_research_progress_config()

        assert config["phase_settings"]["PR2"]["target"] == 3
        assert config["phase_settings"]["PR6"]["target"] == 5

        page.phase_combo.setCurrentIndex(phase_two_index)

        assert page.target_combo.currentData() == 3
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
    assert "类型" not in headers
    assert headers == ["装备名称", "稀有度", "科研期", "装备数", "碎片数"]
    assert page.table.cellWidget(0, 0) is None
    assert page.table.item(0, 0) is not None
    assert page.table.item(0, 0).icon().isNull() is False
    assert page.table.item(0, 0).data(Qt.ItemDataRole.UserRole)
    assert page.table.item(0, 3) is not None
    assert page.table.item(0, 4) is not None
    assert page.refresh_user_table_button.text() == "刷新表"
    assert page.table.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    window.close()


def test_user_data_main_table_refreshes_from_local_sources(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户数据主表应能主动重新读取本地装备表和今日用户记录。"""
    window = MainWindow()
    page = window.pages["user_data"]
    reload_calls: list[str] = []

    refreshed_rows = [
        {
            "equipment_id": "S8-901",
            "name": "刷新测试装备",
            "rarity_id": 5,
            "rarity_name": "海上传奇",
            "image_path": "",
        }
    ]

    monkeypatch.setattr(page.equipment_manager, "reload", lambda: reload_calls.append("equipment"))
    monkeypatch.setattr(page.research_manager, "reload", lambda: reload_calls.append("research"))
    monkeypatch.setattr(page.equipment_manager, "get_equipment_with_image", lambda: refreshed_rows)

    page.refresh_user_table_button.click()
    QTest.qWait(120)

    assert reload_calls == ["equipment", "research"]
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "刷新测试装备"
    assert page.table.item(0, 0).data(Qt.ItemDataRole.UserRole) == "S8-901"
    assert page.table.item(0, 3).text() == "0"
    assert page.table.item(0, 4).text() == "0"
    assert page.refresh_user_table_button.isEnabled() is True
    assert "已刷新用户数据表" in page.user_data_status_label.text()

    window.close()


def test_user_data_can_open_downloaded_equipment_library_view(qapp: QApplication) -> None:
    """用户数据页应提供基础装备库表子界面，且只展示公开装备库列。"""
    window = MainWindow()
    page = window.pages["user_data"]

    page.open_library_button.click()

    assert page.view_stack.currentWidget() is page.library_view
    headers = [
        page.library_table.horizontalHeaderItem(index).text()
        for index in range(page.library_table.columnCount())
    ]
    assert headers == ["装备名称", "稀有度", "科研期"]
    assert "equipment_id" not in headers
    assert "装备数" not in headers
    assert "碎片数" not in headers
    assert page.library_table.cellWidget(0, 0) is None
    assert page.library_table.item(0, 0) is not None
    assert page.library_table.item(0, 0).icon().isNull() is False
    assert "equipment_library" not in page.open_library_button.toolTip()
    assert page.refresh_library_button.text() == "刷新装备表"
    assert page.update_library_button.text() == "更新装备表"

    page.library_search_input.setText("457")
    assert page.library_table.rowCount() >= 1
    assert all("457" in page.library_table.item(row, 0).text() for row in range(page.library_table.rowCount()))

    page.library_search_input.setText("")
    page.library_rarity_combo.setCurrentIndex(page.library_rarity_combo.findData(5))
    page.library_phase_combo.setCurrentIndex(page.library_phase_combo.findData(2))
    assert page.library_table.rowCount() >= 1
    assert all(page.library_table.item(row, 1).text() == "海上传奇" for row in range(page.library_table.rowCount()))
    assert all(page.library_table.item(row, 2).text() == "科研 2 期" for row in range(page.library_table.rowCount()))

    page.back_to_player_data_button.click()
    assert page.view_stack.currentWidget() is page.player_data_view

    window.close()


def test_user_data_displays_s0_as_research_common_equipment(qapp: QApplication) -> None:
    """S0 科研通用装备不应显示成“科研 0 期”。"""
    window = MainWindow()
    page = window.pages["user_data"]

    assert page._phase_from_public_data("S0-001") == "科研通用装备"
    assert page.phase_combo.findText("科研 0 期") == -1
    assert page.library_phase_combo.findText("科研 0 期") == -1
    assert page.phase_combo.itemText(0) == "全部"
    assert page.phase_combo.itemText(1) == "科研通用装备"
    assert page.library_phase_combo.itemText(0) == "全部"
    assert page.library_phase_combo.itemText(1) == "科研通用装备"
    assert page.phase_combo.findText("科研通用装备") >= 0
    assert page.library_phase_combo.findText("科研通用装备") >= 0
    phase_values = [
        int(page.phase_combo.itemData(index))
        for index in range(2, page.phase_combo.count())
    ]
    assert phase_values == sorted(phase_values, reverse=True)
    rarity_values = [
        int(page.rarity_combo.itemData(index))
        for index in range(1, page.rarity_combo.count())
    ]
    assert rarity_values == sorted(rarity_values, reverse=True)

    page.phase_combo.setCurrentIndex(page.phase_combo.findData(0))
    assert page.table.rowCount() >= 1
    assert all(page.table.item(row, 2).text() == "科研通用装备" for row in range(page.table.rowCount()))

    window.close()


def test_user_data_filters_by_name_rarity_and_phase(qapp: QApplication) -> None:
    """用户数据页应支持名称、稀有度和科研期三种基础筛选。"""
    window = MainWindow()
    page = window.pages["user_data"]

    page.search_input.setText("406")
    assert page.table.rowCount() >= 1
    assert all("406" in page.table.item(row, 0).text() for row in range(page.table.rowCount()))

    page.search_input.setText("")
    rarity_index = page.rarity_combo.findData(5)
    page.rarity_combo.setCurrentIndex(rarity_index)
    assert page.table.rowCount() >= 1
    assert all(page.table.item(row, 1).text() == "海上传奇" for row in range(page.table.rowCount()))

    first_research_phase = next(
        page._phase_number_from_id(str(row.get("equipment_id", "")))
        for row in page.all_equipment_rows
        if page._phase_number_from_id(str(row.get("equipment_id", ""))) not in (None, 0)
    )
    page.rarity_combo.setCurrentIndex(0)
    phase_index = page.phase_combo.findData(first_research_phase)
    page.phase_combo.setCurrentIndex(phase_index)
    assert page.table.rowCount() >= 1
    assert all(page.table.item(row, 2).text() == f"科研 {first_research_phase} 期" for row in range(page.table.rowCount()))

    window.close()


def test_user_data_table_merges_today_user_records_for_fragments(qapp: QApplication) -> None:
    """用户数据主表应展示当天 user_records 中的装备数和碎片数，而不是装备库默认 0 值。"""
    window = MainWindow()
    page = window.pages["user_data"]

    s8_rows = [
        row for row in page.all_equipment_rows
        if str(row.get("equipment_id", "")).startswith("S8-")
    ]
    assert len(s8_rows) >= 2
    first_equipment = s8_rows[0]
    second_equipment = s8_rows[1]

    class DummyUserDataManager:
        """给 GUI 测试注入固定的当天用户记录。"""

        def get_today_data(self) -> dict[str, dict[str, int]]:
            return {
                str(first_equipment["equipment_id"]): {"equipment_count": 0, "fragment_count": 3},
                str(second_equipment["equipment_id"]): {"equipment_count": 2, "fragment_count": 10},
            }

    page.user_data_manager = DummyUserDataManager()
    page.search_input.setText("")
    page.rarity_combo.setCurrentIndex(0)
    page.phase_combo.setCurrentIndex(page.phase_combo.findData(8))
    page.refresh_equipment_table()

    displayed = {
        page.table.item(row, 0).text(): (
            page.table.item(row, 3).text(),
            page.table.item(row, 4).text(),
        )
        for row in range(page.table.rowCount())
    }

    assert displayed[str(first_equipment["name"])] == ("0", "3")
    assert displayed[str(second_equipment["name"])] == ("2", "10")

    window.close()


def test_user_data_missing_equipment_icon_uses_blank_pixmap(qapp: QApplication) -> None:
    """装备图片缺失时应使用固定尺寸空白图标，避免大图或缺图破坏表格布局。"""
    window = MainWindow()
    page = window.pages["user_data"]

    icon = page._load_equipment_icon("")

    assert icon.isNull() is False
    pixmap = icon.pixmap(page.icon_size, page.icon_size)
    assert pixmap.width() == page.icon_size
    assert pixmap.height() == page.icon_size

    window.close()


def test_user_data_equipment_library_buttons_use_separate_update_steps(qapp: QApplication) -> None:
    """装备库子页应区分“本地刷新 UI”和“爬虫更新正式表”两个动作。"""
    class FakeBridge:
        def __init__(self) -> None:
            self.called = False

        def run_crawler_update(self) -> AutomationBridgeResult:
            self.called = True
            return AutomationBridgeResult(
                True,
                "success",
                "资料更新完成",
                "装备: 2；图片表: data/equipment_images.csv；告警: 0",
                {"equipment_count": 2, "warnings": []},
            )

    window = MainWindow()
    page = window.pages["user_data"]
    fake_bridge = FakeBridge()
    page.automation_bridge = fake_bridge
    page.open_library_button.click()

    page.update_library_button.click()
    for _ in range(30):
        if "资料更新完成" in page.library_status_label.text():
            break
        QTest.qWait(100)

    assert fake_bridge.called is True
    assert "资料更新完成" in page.library_status_label.text()
    assert "刷新装备表" in page.library_status_label.text()

    page.refresh_library_button.click()
    QTest.qWait(100)

    assert "已从正式装备表载入" in page.library_status_label.text()
    assert page.library_table.rowCount() == len(page._filtered_library_rows())

    window.close()


def test_user_data_library_can_add_equipment_to_trend_lines(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """装备库表应能通过右键确认流程把装备加入历史趋势的划线列表。"""
    window = MainWindow()
    user_page = window.pages["user_data"]
    trend_page = window.pages["trend"]

    user_page.open_library_button.click()
    assert user_page.library_table.rowCount() >= 1
    item = user_page.library_table.item(0, 0)
    assert item is not None
    equipment_id = str(item.data(Qt.ItemDataRole.UserRole))
    equipment_name = item.text()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    user_page._confirm_add_equipment_to_trend(equipment_id, equipment_name)

    assert trend_page.trend_tabs.currentIndex() == 1
    assert trend_page._selected_equipment_lines[equipment_id] == equipment_name
    assert trend_page.selected_equipment_list.count() >= 1
    assert window.page_stack.currentWidget() is trend_page

    window.close()


def test_user_data_main_table_can_add_equipment_to_trend_lines(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户数据主表也应能把当前装备加入历史趋势折线。"""
    window = MainWindow()
    user_page = window.pages["user_data"]
    trend_page = window.pages["trend"]

    assert user_page.table.rowCount() >= 1
    item = user_page.table.item(0, 0)
    assert item is not None
    equipment_id = str(item.data(Qt.ItemDataRole.UserRole))
    equipment_name = item.text()
    assert equipment_id
    assert equipment_id not in equipment_name

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    user_page._confirm_add_equipment_to_trend(equipment_id, equipment_name)

    assert trend_page.trend_tabs.currentIndex() == 1
    assert trend_page._selected_equipment_lines[equipment_id] == equipment_name
    assert trend_page.selected_equipment_list.count() >= 1
    assert window.page_stack.currentWidget() is trend_page

    window.close()


def test_trend_page_builds_single_matplotlib_panel_with_function_tabs(qapp: QApplication) -> None:
    """历史趋势页应重构为两个 matplotlib 折线图区域，不再展示表格。"""
    window = MainWindow()
    trend_page = window.pages["trend"]

    assert trend_page.trend_tabs.count() == 2
    assert trend_page.trend_tabs.tabText(0) == "科研金彩比"
    assert trend_page.trend_tabs.tabText(1) == "装备碎片趋势"
    assert hasattr(trend_page, "trend_panel")
    assert not hasattr(trend_page, "trend_table")
    assert not hasattr(trend_page.trend_panel, "toolbar")
    assert trend_page.trend_panel.canvas.objectName() == "matplotlib_trend_canvas"
    assert trend_page.trend_panel.minimumHeight() >= 420
    assert trend_page.trend_tabs.maximumHeight() <= 190
    assert trend_page.trend_tabs.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert trend_page.equipment_select_combo.objectName() == "trend_equipment_select"
    assert trend_page.phase_checks
    assert 1 not in trend_page.phase_checks
    assert 2 in trend_page.phase_checks
    phase_order = list(trend_page.phase_checks)
    assert phase_order == sorted(phase_order, reverse=True)
    assert all(not checkbox.isChecked() for checkbox in trend_page.phase_checks.values())
    assert trend_page._selected_phase_numbers() == []
    assert "未选择科研期" in trend_page.phase_selection_summary_label.text()
    assert trend_page.phase_drawer_table.objectName() == "phase_drawer_table"
    assert trend_page.phase_drawer_table.isHidden() is True
    assert trend_page.phase_drawer_table.rowCount() == len(trend_page.phase_checks)
    trend_page.phase_drawer_button.click()
    assert trend_page.phase_drawer_table.isHidden() is False
    assert trend_page.phase_drawer_button.text() == "收起科研期"
    assert trend_page.trend_tabs.maximumHeight() >= 300
    assert trend_page.import_history_button.objectName() == "import_history_button"
    assert trend_page.root.indexOf(trend_page.trend_tabs) < trend_page.root.indexOf(trend_page.common_trend_panel)
    assert trend_page.root.indexOf(trend_page.common_trend_panel) < trend_page.root.indexOf(trend_page.trend_panel)

    window.close()


def test_trend_page_gives_chart_more_vertical_space_than_controls(qapp: QApplication) -> None:
    """趋势页默认应让图表区域明显大于中间选项区，避免折线图被挤到很小。"""
    window = MainWindow()
    window.resize(1280, 820)
    window.switch_to_page("trend")
    window.show()
    qapp.processEvents()
    QTest.qWait(120)
    trend_page = window.pages["trend"]

    assert trend_page.trend_tabs.height() <= 210
    assert trend_page.trend_panel.height() > trend_page.trend_tabs.height()

    window.close()


def test_trend_equipment_selector_keeps_readable_layout(qapp: QApplication) -> None:
    """装备碎片趋势页应给装备选择和已选列表足够空间，避免控件挤成一团。"""
    window = MainWindow()
    window.resize(1280, 820)
    window.switch_to_page("trend")
    window.show()
    qapp.processEvents()
    trend_page = window.pages["trend"]

    trend_page.trend_tabs.setCurrentIndex(1)
    qapp.processEvents()
    QTest.qWait(120)

    assert 220 <= trend_page.trend_tabs.height() <= 280
    assert trend_page.equipment_search_input.width() >= 170
    assert trend_page.equipment_select_combo.width() >= 250
    assert trend_page.selected_equipment_list.height() >= 70
    assert trend_page.trend_panel.height() > trend_page.trend_tabs.height()

    window.close()


def test_trend_selected_equipment_list_uses_skin_tokens(qapp: QApplication) -> None:
    """已选划线装备列表应跟随皮肤配色，避免露出 Qt 默认白底。"""
    manager = get_ui_config_manager()
    original_config = manager.get_appearance_config()
    window = MainWindow()
    trend_page = window.pages["trend"]

    try:
        window.apply_theme_skin("iron_blood")
        stylesheet = window.styleSheet()
        skin = get_theme_skin("iron_blood")

        assert trend_page.selected_equipment_list.objectName() == "selected_equipment_line_list"
        assert "QListWidget#selected_equipment_line_list" in stylesheet
        assert f"background: {skin.tokens.table_row};" in stylesheet
        assert f"selection-background-color: {skin.tokens.table_selection};" in stylesheet
        assert f"selection-color: {skin.tokens.table_selection_text};" in stylesheet
    finally:
        manager.config_loader.save_config("ui", "appearance", original_config)
        window.close()


def test_trend_page_builds_phase_ratio_and_equipment_fragment_series(qapp: QApplication) -> None:
    """趋势页应能构建金彩比多线和指定装备碎片折线数据。"""
    window = MainWindow()
    trend_page = window.pages["trend"]

    class FakeUserDataManager:
        def list_available_dates(self) -> list[str]:
            return ["2026-07-01", "2026-07-02"]

        def get_data_by_date(self, _date: str) -> dict[str, dict[str, int]]:
            return {}

        def get_history(self, _equipment_id: str) -> list[dict[str, int | str]]:
            return [
                {"date": "2026-07-01", "equipment_count": 0, "fragment_count": 12},
                {"date": "2026-07-02", "equipment_count": 1, "fragment_count": 35},
            ]

    class FakeLuckCalculator:
        def calculate_phase_luck(self, phase_number: int, _day_data: dict[str, dict[str, int]]) -> dict[str, int]:
            return {"rainbow_total": 50 * phase_number, "gold_total": 25 * phase_number}

    trend_page.user_data_manager = FakeUserDataManager()
    trend_page.luck_calculator = FakeLuckCalculator()
    trend_page.start_date.setDate(QDate(2026, 7, 1))
    trend_page.end_date.setDate(QDate(2026, 7, 2))
    for phase, checkbox in trend_page.phase_checks.items():
        checkbox.setChecked(phase in {2, 3})

    ratio_series = trend_page._build_phase_ratio_series_map()
    fragment_series = trend_page._build_equipment_fragment_series("S1-001", "测试装备")

    assert "PR1" not in ratio_series
    assert set(ratio_series) == {"PR2", "PR3"}
    assert ratio_series["PR2"][0]["value"] == 0.5
    assert fragment_series[-1]["value"] == 35

    window.close()


def test_trend_date_range_is_clamped_to_today_and_ordered(qapp: QApplication) -> None:
    """历史趋势日期不能超过今天，且开始日期不能晚于结束日期。"""
    window = MainWindow()
    trend_page = window.pages["trend"]
    today = QDate.currentDate()

    trend_page.start_date.setMaximumDate(today.addDays(3))
    trend_page.end_date.setMaximumDate(today.addDays(3))
    trend_page.start_date.setDate(today.addDays(1))
    qapp.processEvents()

    assert trend_page.start_date.date() == today

    trend_page.start_date.setDate(today)
    trend_page.end_date.setDate(today.addDays(-2))
    qapp.processEvents()

    assert trend_page.start_date.date() == trend_page.end_date.date()
    assert trend_page.start_date.date() <= trend_page.end_date.date()

    window.close()


def test_trend_page_searches_equipment_and_draws_lines(qapp: QApplication) -> None:
    """趋势页装备碎片图应只能从查询结果中选择装备，并能绘制折线。"""
    window = MainWindow()
    trend_page = window.pages["trend"]

    class FakeUserDataManager:
        def get_history(self, _equipment_id: str) -> list[dict[str, int | str]]:
            return [
                {"date": "2026-07-01", "equipment_count": 0, "fragment_count": 12},
                {"date": "2026-07-02", "equipment_count": 1, "fragment_count": 35},
            ]

        def list_available_dates(self) -> list[str]:
            return ["2026-07-01", "2026-07-02"]

    trend_page.user_data_manager = FakeUserDataManager()
    trend_page.start_date.setDate(QDate(2026, 7, 1))
    trend_page.end_date.setDate(QDate(2026, 7, 2))

    trend_page.trend_tabs.setCurrentIndex(1)
    trend_page.equipment_search_input.setText("406")
    trend_page.search_equipment_options()

    assert trend_page.equipment_select_combo.count() >= 1
    assert "406" in trend_page.equipment_select_combo.itemText(0)
    assert str(trend_page.equipment_select_combo.itemData(0)).startswith("S")
    trend_page._add_selected_equipment_line()

    trend_page.equipment_search_input.setText("457")
    trend_page.search_equipment_options()
    assert "457" in trend_page.equipment_select_combo.itemText(0)
    trend_page._add_selected_equipment_line()

    assert trend_page.selected_equipment_list.count() == 2
    assert len(trend_page._selected_equipment_lines) == 2
    trend_page.refresh_equipment_fragment_chart()
    assert len(trend_page.trend_panel.axes.lines) == 2

    window.close()


def test_trend_page_chart_colors_follow_selected_skin(qapp: QApplication) -> None:
    """matplotlib 趋势图背景和坐标轴应跟随当前皮肤。"""
    manager = get_ui_config_manager()
    original_config = manager.get_appearance_config()
    window = MainWindow()
    trend_page = window.pages["trend"]

    try:
        window.apply_theme_skin("dragon_empery")

        skin = get_theme_skin("dragon_empery")
        assert to_hex(trend_page.trend_panel.figure.get_facecolor()).upper() == skin.tokens.surface.upper()
        assert to_hex(trend_page.trend_panel.axes.get_facecolor()).upper() == skin.tokens.table_row.upper()
    finally:
        manager.config_loader.save_config("ui", "appearance", original_config)
        window.close()


def test_trend_chart_uses_sparse_x_ticks_and_y_padding(qapp: QApplication) -> None:
    """趋势图应抽样显示长日期范围的 X 轴，并给 Y 轴留出可读空间。"""
    window = MainWindow()
    trend_page = window.pages["trend"]
    points = [
        {"date": f"2026-07-{day:02d}", "value": float(day), "detail": ""}
        for day in range(1, 16)
    ]

    trend_page.trend_panel.plot_series({"测试线": points}, "碎片数量", "暂无数据")

    assert len(trend_page.trend_panel.axes.get_xticks()) < len(points)
    y_min, y_max = trend_page.trend_panel.axes.get_ylim()
    assert y_min < 1
    assert y_max > 15

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
    assert "crawler_update" in keys
    assert registry.get("research_simulation") is not None
    assert registry.get("crawler_update") is not None


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
    assert "alternate-background-color" in stylesheet
    assert "QTableWidget::item:selected" in stylesheet
    assert "QCalendarWidget" in stylesheet
    assert panel.load_animation("resources/animations/not_exist.gif") is False

    panel.close()


def test_date_calendar_popup_uses_active_skin_tokens(qapp: QApplication) -> None:
    """日期选择弹层应跟随当前皮肤，避免出现 Qt 默认白底日历。"""
    manager = get_ui_config_manager()
    original_config = manager.get_appearance_config()
    window = MainWindow()

    try:
        window.apply_theme_skin("iron_blood")
        skin = get_theme_skin("iron_blood")
        research_page = window.pages["research_progress"]
        trend_page = window.pages["trend"]

        research_calendar_style = research_page.start_date_edit.calendarWidget().styleSheet()
        trend_calendar_style = trend_page.start_date.calendarWidget().styleSheet()
        trend_calendar = trend_page.start_date.calendarWidget()
        today = QDate.currentDate()
        trend_calendar.setCurrentPage(today.year(), today.month())
        future_format = trend_calendar.dateTextFormat(today.addDays(1))
        adjacent_format = trend_calendar.dateTextFormat(QDate(today.year(), today.month(), 1).addDays(-1))

        assert skin.tokens.surface in research_calendar_style
        assert skin.tokens.table_row in research_calendar_style
        assert skin.tokens.azure in trend_calendar_style
        assert future_format.foreground().color().name().lower() == skin.tokens.line.lower()
        assert adjacent_format.foreground().color().name().lower() == skin.tokens.text_muted.lower()
        assert "#FFFFFF" not in research_calendar_style.upper()
    finally:
        manager.config_loader.save_config("ui", "appearance", original_config)
        window.close()


def test_theme_skin_registry_has_multiple_named_skins() -> None:
    """皮肤注册表应预留多套外观，并能对未知 key 回退到默认皮肤。"""
    skins = list_theme_skins()
    keys = {skin.key for skin in skins}

    assert {
        "harbor_night",
        "sakura_mist",
        "iron_blood",
        "dragon_empery",
        "eagle_union",
        "northern_parliament",
        "sakura_empire",
    }.issubset(keys)
    assert get_theme_skin("missing").key == "harbor_night"
    assert get_theme_skin("sakura_mist").tokens.table_row != get_theme_skin("harbor_night").tokens.table_row
    assert get_theme_skin("iron_blood").tokens.radius <= 5


def test_settings_page_exposes_skin_selector_and_preview(qapp: QApplication) -> None:
    """设置页应展示皮肤下拉和预览卡，为后续多风格 UI 做预留。"""
    window = MainWindow()
    page = window.pages["settings"]

    assert page.skin_combo.count() >= 7
    assert page.skin_combo.objectName() == "skin_combo"
    assert set(page.skin_preview_cards) >= {"harbor_night", "iron_blood", "dragon_empery"}
    assert page.skin_combo.findData("iron_blood") >= 0
    assert page.skin_combo.findData("dragon_empery") >= 0
    assert sum(not card.isHidden() for card in page.skin_preview_cards.values()) <= page.skin_preview_limit
    assert page.skin_preview_expand_button.text() == "＋"
    assert page.skin_preview_expand_button.minimumHeight() >= 104

    page.skin_preview_expand_button.click()

    assert sum(not card.isHidden() for card in page.skin_preview_cards.values()) == len(page.skin_preview_cards)
    assert page.skin_preview_expand_button.text() == "－"

    window.close()


def test_settings_skin_preview_card_click_switches_skin(qapp: QApplication) -> None:
    """点击皮肤预览卡应能直接切换皮肤，不必只依赖右侧下拉框。"""
    manager = get_ui_config_manager()
    original_config = manager.get_appearance_config()
    window = MainWindow()
    page = window.pages["settings"]
    card = page.skin_preview_cards["iron_blood"]

    try:
        if card.isHidden():
            page.skin_preview_expand_button.click()
        QTest.mouseClick(card, Qt.MouseButton.LeftButton)

        assert page.skin_combo.currentData() == "iron_blood"
        assert window.active_skin == "iron_blood"
    finally:
        manager.config_loader.save_config("ui", "appearance", original_config)
        window.close()


def test_settings_and_research_pages_scroll_when_log_drawer_expands(qapp: QApplication) -> None:
    """窗口变小且日志展开时，设置页和科研页应通过页面滚动保护内容可读性。"""
    window = MainWindow()
    window.resize(900, 620)
    window.log_drawer.set_expanded(True, animate=False)
    window.show()
    qapp.processEvents()

    try:
        for page_key in ("settings", "research_progress"):
            window.switch_to_page(page_key)
            qapp.processEvents()
            page = window.pages[page_key]

            assert page.findChild(QScrollArea, "page_scroll_area") is page.page_scroll_area
            assert page.page_scroll_area.widgetResizable() is True
            assert page.page_scroll_area.content_overflows() is True
    finally:
        window.close()


def test_settings_skin_preview_grid_keeps_expand_button_on_first_row(qapp: QApplication) -> None:
    """设置页皮肤预览收起时应保持三张卡加一个加号同排，避免日志展开后挤压文字。"""
    window = MainWindow()
    window.resize(900, 620)
    window.log_drawer.set_expanded(True, animate=False)
    window.switch_to_page("settings")
    window.show()
    qapp.processEvents()
    page = window.pages["settings"]
    visible_cards = [card for card in page.skin_preview_cards.values() if not card.isHidden()]

    assert len(visible_cards) <= page.skin_preview_limit
    assert visible_cards
    assert all(card.minimumHeight() >= 112 for card in visible_cards)
    assert all(card.minimumWidth() >= 160 for card in visible_cards)
    assert page.skin_preview_expand_button.geometry().y() == visible_cards[0].geometry().y()

    window.close()


def test_future_page_rows_keep_readable_height(qapp: QApplication) -> None:
    """等待开发页面的功能行应放入滚动区并保持足够间隔，避免标题和说明挤成一坨。"""
    window = MainWindow()
    page = window.pages["future"]
    rows = page.findChildren(QFrame, "future_feature_row")

    assert page.findChild(QScrollArea, "future_scroll_area") is page.future_scroll_area
    assert page.future_scroll_area.widgetResizable() is True
    assert page.future_scroll_layout.spacing() >= 16
    assert rows
    assert all(row.minimumHeight() >= 104 for row in rows)
    assert all(row.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed for row in rows)

    window.close()


def test_future_page_does_not_force_scroll_for_short_content(qapp: QApplication) -> None:
    """等待开发内容不足一屏时不应强行出现滚动行为。"""
    registry = FeatureHookRegistry()
    registry._features = {
        "short": FutureFeatureSpec("short", "短内容", "只有一个待开发入口时不需要滚动。", "planned", "ui.future")
    }
    page = FutureDockPage(registry)
    page.resize(900, 720)
    page.show()
    qapp.processEvents()

    assert page.future_scroll_area.content_overflows() is False
    assert page.future_scroll_area.play_edge_bounce("top") is False

    page.close()


def test_future_page_edge_bounce_runs_when_content_overflows(qapp: QApplication) -> None:
    """等待开发内容超过一屏时，到顶或到底应能触发轻量回弹动画。"""
    window = MainWindow()
    page = window.pages["future"]
    window.resize(900, 520)
    window.show()
    qapp.processEvents()

    assert page.future_scroll_area.content_overflows() is True
    assert page.future_scroll_area.play_edge_bounce("top") is True

    window.close()


def test_main_window_applies_and_persists_skin(qapp: QApplication) -> None:
    """主窗口切换皮肤时应更新 token、样式和 appearance.json。"""
    manager = get_ui_config_manager()
    original_config = manager.get_appearance_config()
    window = MainWindow()

    try:
        window.apply_theme_skin("iron_blood")

        assert window.active_skin == "iron_blood"
        assert window.theme_tokens.background == get_theme_skin("iron_blood").tokens.background
        assert "铁血机库" in window.statusBar().currentMessage()
        assert manager.get_appearance_config()["active_skin"] == "iron_blood"
        assert window._iron_blood_timer.isActive() is True

        window.apply_theme_skin("dragon_empery")

        assert window.active_skin == "dragon_empery"
        assert window._iron_blood_timer.isActive() is False
    finally:
        manager.config_loader.save_config("ui", "appearance", original_config)
        window.close()


def test_data_tables_use_readable_row_selection_behavior(qapp: QApplication) -> None:
    """用户数据表格应使用整行选择与只读模式，趋势页不再展示明细表格。"""
    window = MainWindow()
    user_page = window.pages["user_data"]
    trend_page = window.pages["trend"]

    assert user_page.table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert user_page.table.showGrid() is False
    assert not hasattr(trend_page, "trend_table")

    window.close()


def test_automation_lab_has_crawler_update_entry(qapp: QApplication) -> None:
    """自动化实验室应提供资料爬取与更新入口，并用 crawler_update 作为后续执行接口。"""
    class FakeBridge:
        def run_crawler_update(self) -> AutomationBridgeResult:
            return AutomationBridgeResult(True, "success", "formal sync done", "装备: 2；告警: 0", {"equipment_count": 2})

    manager = get_runtime_state_manager()
    manager.reset()
    window = MainWindow()
    page = window.pages["automation_lab"]
    page.automation_bridge = FakeBridge()
    emitted_keys: list[str] = []
    page.featureRequested.connect(emitted_keys.append)

    page.crawler_update_button.click()
    QTest.qWait(600)

    assert emitted_keys[-1] == "crawler_update"
    assert "formal sync done" in page.crawler_status_label.text()
    assert "装备: 2" in page.crawler_status_label.text()
    assert "GitHub" in page.crawler_notice_label.text()

    window.close()
    manager.reset()


def test_automation_lab_secretary_pack_template_check(qapp: QApplication) -> None:
    """自动化实验室应预留秘书舰资源包模板校验入口。"""
    window = MainWindow()
    page = window.pages["automation_lab"]

    page.secretary_pack_button.click()

    assert "模板格式正确" in page.secretary_pack_status_label.text()

    window.close()
