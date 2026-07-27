#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       v0.6.0 GUI 手动修改装备/碎片数量专项测试                 ║
║                                                              ║
║  【一句话解释】验证用户数据与科研进度页可右键修改单件装备数量。║
║  【数据流说明】右键弹窗 → 非负整数校验 → user_records CSV 写入。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import os
from typing import Generator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu

from ui.main_window import EquipmentCountEditDialog, MainWindow, polish_equipment_context_menu
from ui.theme import get_theme_skin


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp() -> Generator[QApplication, None, None]:
    """提供 Qt 应用实例。"""
    app = QApplication.instance() or QApplication([])
    yield app


def test_equipment_count_edit_dialog_uses_skin_and_non_negative_spinboxes(qapp: QApplication) -> None:
    """编辑弹窗应使用当前皮肤，并通过 QSpinBox 限制为非负整数。"""
    tokens = get_theme_skin("iron_blood").tokens
    dialog = EquipmentCountEditDialog("试作型彩装", 2, 35, tokens)

    assert tokens.surface in dialog.styleSheet()
    assert tokens.text in dialog.styleSheet()
    assert dialog.equipment_count_spin.minimum() == 0
    assert dialog.fragment_count_spin.minimum() == 0
    assert dialog.values() == (2, 35)

    dialog.equipment_count_spin.setValue(-9)
    dialog.fragment_count_spin.setValue(-1)

    assert dialog.values() == (0, 0)
    dialog.close()


def test_equipment_context_menu_keeps_readable_width(qapp: QApplication) -> None:
    """装备右键菜单应统一加宽，避免三项操作文字贴边或宽度突兀。"""
    tokens = get_theme_skin("iron_blood").tokens
    menu = QMenu()

    polish_equipment_context_menu(menu, tokens)

    assert menu.objectName() == "equipment_context_menu"
    assert menu.minimumWidth() >= 236
    assert "min-width: 212px" in menu.styleSheet()
    assert tokens.surface in menu.styleSheet()
    menu.close()


def test_user_data_page_applies_manual_record_update_with_active_date(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户数据页修改应写入当前展示日期，并刷新科研进度与历史趋势。"""
    window = MainWindow()
    page = window.pages["user_data"]
    page._active_user_record_date = "2026-07-12"
    update_calls: list[tuple[str, int, int, str]] = []
    refresh_calls: list[str] = []
    dependent_calls: list[str] = []

    class DummyUserDataManager:
        """记录单件装备写入参数。"""

        def update_record(
            self,
            equipment_id: str,
            equipment_count: int,
            fragment_count: int,
            target_date: str | None = None,
        ) -> bool:
            update_calls.append((equipment_id, equipment_count, fragment_count, str(target_date)))
            return True

    page.user_data_manager = DummyUserDataManager()
    monkeypatch.setattr(page, "refresh_equipment_table", lambda: refresh_calls.append("user_table"))
    monkeypatch.setattr(window, "refresh_data_dependent_pages", lambda page_key, **_kwargs: dependent_calls.append(page_key))

    assert page._apply_user_equipment_record_update("S8-001", "试作型彩装", 3, 49) is True

    assert update_calls == [("S8-001", 3, 49, "2026-07-12")]
    assert refresh_calls == ["user_table"]
    assert dependent_calls == ["research_progress", "trend"]
    assert "试作型彩装" in page.user_data_status_label.text()
    window.close()


def test_user_data_page_rejects_decimal_negative_or_bool_values(qapp: QApplication) -> None:
    """用户数据页写入前应拒绝小数、负数和 bool，避免脏数据进入 CSV。"""
    window = MainWindow()
    page = window.pages["user_data"]

    assert page._apply_user_equipment_record_update("S8-001", "试作型彩装", -1, 0) is False
    assert page._apply_user_equipment_record_update("S8-001", "试作型彩装", 1.5, 0) is False
    assert page._apply_user_equipment_record_update("S8-001", "试作型彩装", True, 0) is False
    assert "只能是 ≥ 0 的整数" in page.user_data_status_label.text()
    window.close()


def test_research_progress_page_applies_manual_record_update_and_refreshes_related_pages(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """科研进度页修改应写入当前可见用户记录日期，并刷新用户数据与趋势页。"""
    window = MainWindow()
    page = window.pages["research_progress"]
    update_calls: list[tuple[str, int, int, str]] = []
    refresh_calls: list[str] = []
    dependent_calls: list[str] = []

    class DummyUserDataManager:
        """模拟用户记录管理器。"""

        def get_today_or_latest_data(self) -> tuple[str, dict[str, dict[str, int]]]:
            return "2026-07-12", {}

        def update_record(
            self,
            equipment_id: str,
            equipment_count: int,
            fragment_count: int,
            target_date: str | None = None,
        ) -> bool:
            update_calls.append((equipment_id, equipment_count, fragment_count, str(target_date)))
            return True

    monkeypatch.setattr("ui.main_window.get_user_data_manager", lambda: DummyUserDataManager())
    monkeypatch.setattr(page, "refresh_progress", lambda: refresh_calls.append("research_progress"))
    monkeypatch.setattr(window, "refresh_data_dependent_pages", lambda page_key, **_kwargs: dependent_calls.append(page_key))

    assert page._apply_progress_equipment_record_update("S8-002", "试作型金装", 1, 22) is True

    assert update_calls == [("S8-002", 1, 22, "2026-07-12")]
    assert refresh_calls == ["research_progress"]
    assert dependent_calls == ["user_data", "trend"]
    assert "试作型金装" in page.notice_label.text()
    window.close()


def test_research_progress_table_stores_equipment_id_for_context_menu(qapp: QApplication) -> None:
    """科研进度表真实装备行应保存 equipment_id，供右键修改定位单件装备。"""
    window = MainWindow()
    page = window.pages["research_progress"]
    page._update_table([
        {
            "equipment_id": "S8-001",
            "equipment_name": "试作型彩装",
            "rarity_id": 5,
            "rarity_name": "海上传奇",
            "equipment_count": 1,
            "fragment_count": 12,
            "equivalent": 50,
            "image_path": "",
        }
    ])

    assert page.progress_table.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert page.progress_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == "S8-001"
    assert page.progress_table.item(0, 2).text() == "12"
    assert page.progress_table.item(0, 3).text() == "1"
    assert page.progress_table.item(0, 4).text() == "62"
    window.close()


def test_research_progress_page_can_add_equipment_to_trend_lines(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """科研进度页应和用户数据页一样支持把装备添加到历史趋势折线。"""
    window = MainWindow()
    page = window.pages["research_progress"]
    trend_page = window.pages["trend"]

    monkeypatch.setattr(page, "_ask_add_equipment_to_trend", lambda _name: True)

    page._confirm_add_progress_equipment_to_trend("S8-001", "试作型彩装")

    assert trend_page._selected_equipment_lines["S8-001"] == "试作型彩装"
    assert trend_page.selected_equipment_list.count() >= 1
    assert window.page_stack.currentWidget() is trend_page
    assert "试作型彩装" in page.notice_label.text()
    window.close()
