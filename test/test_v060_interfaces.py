#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║           🧪 v0.6.0 自动化接口测试 (test_v060_interfaces.py) ║
║                                                              ║
║  【测试目标】确认 ADB / OCR 预留接口和 GUI 挂接点可以安全运行。 ║
║  【类比理解】像先验收船坞插槽，再把真正的船慢慢开进来。        ║
║  【数据流说明】API 契约 → AutomationBridge → AutomationLabPage。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
from typing import Generator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.automation.adb_task_api import get_adb_task_api
from core.recognition.ocr_task_api import get_ocr_task_api
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from ui.automation_bridge import AutomationBridge
from ui.future_hooks import get_feature_hook_registry
from ui.main_window import MainWindow
from ui.automation_task_specs import get_automation_task_definition, list_automation_task_definitions
from ui.task_manager import get_gui_task_manager


# ============================================================
# 🧩 第二部分：pytest fixtures
# ============================================================

@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """创建离屏 QApplication 供 GUI 测试复用。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def reset_runtime_state() -> None:
    """每个测试前后重置运行期状态，避免任务状态串味。"""
    manager = get_runtime_state_manager()
    manager.reset()
    get_gui_task_manager().reset_for_tests()
    yield
    manager.reset()
    get_gui_task_manager().reset_for_tests()


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_automation_task_spec_registry_contains_v060_tasks() -> None:
    """自动化任务规格表应包含 v0.6.0 预留入口。"""
    keys = [item.key for item in list_automation_task_definitions()]

    assert "crawler_update" in keys
    assert "adb_connection_check" in keys
    assert "adb_screenshot_capture" in keys
    assert "ocr_equipment_scan" in keys
    assert "ocr_resource_scan" in keys
    assert "environment_check" in keys
    assert get_automation_task_definition("ocr_resource_scan") is not None


def test_adb_task_api_reports_reserved_prechecks() -> None:
    """ADB 预检接口应返回可测试的占位结果和结构化 payload。"""
    api = get_adb_task_api()

    connection_result = api.check_connection()
    screenshot_result = api.capture_screenshot()
    environment_result = api.run_environment_check()

    assert connection_result.success is True
    assert connection_result.status == "reserved"
    assert connection_result.payload is not None
    assert "adb_path_exists" in connection_result.payload
    assert screenshot_result.status == "reserved"
    assert screenshot_result.payload is not None
    assert screenshot_result.payload["real_capture_enabled"] is False
    assert environment_result.payload is not None
    assert "opencv_cv2" in environment_result.payload["dependencies"]


def test_ocr_task_api_reports_reserved_scan_contracts() -> None:
    """OCR 预检接口应固定装备和资源的结构契约。"""
    api = get_ocr_task_api()

    equipment_result = api.scan_equipment_counts()
    resource_result = api.scan_resource_status()
    engine_result = api.check_engine()

    assert equipment_result.success is True
    assert equipment_result.status == "reserved"
    assert equipment_result.payload is not None
    assert equipment_result.payload["result_schema"][0]["name"] == "equipment_id"
    assert resource_result.payload is not None
    assert resource_result.payload["result_schema"][0]["name"] == "player_name"
    assert engine_result.payload is not None
    assert "paddleocr" in engine_result.payload["dependencies"]


def test_automation_bridge_exposes_v060_entry_points() -> None:
    """AutomationBridge 应把 v0.6.0 预留接口统一转换成 GUI 结果。"""
    bridge = AutomationBridge()

    adb_result = bridge.run_adb_connection_check()
    adb_state = get_runtime_state_manager().get_full_state()["task"]
    ocr_result = bridge.run_ocr_resource_scan()
    ocr_state = get_runtime_state_manager().get_full_state()["task"]

    assert adb_result.success is True
    assert adb_result.status == "reserved"
    assert adb_state["kind"] == "idle"
    assert adb_state["current_task"] == "ADB 连接预检"
    assert ocr_result.success is True
    assert ocr_result.status == "reserved"
    assert ocr_state["kind"] == "idle"
    assert ocr_state["current_task"] == "资源 OCR 预检"


def test_automation_lab_page_exposes_v060_buttons_and_runs_tasks(qapp: QApplication) -> None:
    """自动化实验室应展示新的预检按钮，并能通过统一任务管理器执行。"""
    window = MainWindow(registry=get_feature_hook_registry())
    page = window.pages["automation_lab"]

    assert "adb_connection_check" in page.automation_task_buttons
    assert "ocr_resource_scan" in page.automation_task_buttons
    assert "environment_check" in page.automation_task_buttons

    page.automation_task_buttons["adb_connection_check"].click()
    assert _wait_until(lambda: "ADB 连接预检完成" in page.automation_task_status_label.text())
    assert _wait_until(lambda: not page.task_manager.is_running())

    page.automation_task_buttons["ocr_resource_scan"].click()
    assert _wait_until(lambda: "资源 OCR 接口预检完成" in page.automation_task_status_label.text())
    assert _wait_until(lambda: not page.task_manager.is_running())

    window.close()


def _wait_until(condition, timeout_ms: int = 2500, interval_ms: int = 25) -> bool:
    """等待 GUI 事件循环把后台任务推进到目标状态。"""
    elapsed = 0
    while elapsed <= timeout_ms:
        if condition():
            return True
        QTest.qWait(interval_ms)
        elapsed += interval_ms
    return bool(condition())
