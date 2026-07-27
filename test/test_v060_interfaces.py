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
from pathlib import Path
from typing import Generator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.automation.adb_task_api import get_adb_task_api
from core.recognition.ocr_task_api import get_ocr_task_api
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.path_manager import PathManager
from ui.automation_bridge import AutomationBridge, AutomationBridgeResult
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
    assert "adb_auto_connect" in keys
    assert "game_auto_login" in keys
    assert "game_enter_home" in keys
    assert "adb_screenshot_capture" in keys
    assert "ocr_equipment_scan" in keys
    assert "ocr_resource_scan" in keys
    assert "design_chart_flow_test" in keys
    assert "design_chart_flow_start" not in keys
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


def test_automation_bridge_exposes_v060_entry_points(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AutomationBridge 应把 v0.6.0 预留接口统一转换成 GUI 结果。"""
    bridge = AutomationBridge()

    work_dir = tmp_path / "workdir"
    summary_path = work_dir / "automation" / "equipment_page" / "design_rarity_runs" / "run_demo" / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("{\"resume_cursor\": 1, \"next_resume_cursor\": 3}", encoding="utf-8")

    class FakeDesignReadyResult:
        success = True
        status = "ready"
        message = "已切到设计图页"
        detail = "page_type=design"
        warnings = ("design-tab-check",)

        def __init__(self) -> None:
            self.payload = {"design_tab_confirmed": True}

        def to_dict(self) -> dict[str, object]:
            return {
                "success": self.success,
                "status": self.status,
                "message": self.message,
                "detail": self.detail,
                "payload": self.payload,
                "warnings": list(self.warnings),
            }

    class FakeDesignSessionResult:
        success = True
        status = "ready"
        message = "设计图稀有度流程完成"
        detail = "run ok"
        warnings = ("sweep-ok",)

        def __init__(self) -> None:
            self.run_dir = str(tmp_path / "run")
            self.summary_path = str(tmp_path / "run" / "summary.json")

        def to_dict(self) -> dict[str, object]:
            return {
                "success": self.success,
                "status": self.status,
                "message": self.message,
                "detail": self.detail,
                "payload": {"frames": []},
                "warnings": list(self.warnings),
                "run_dir": self.run_dir,
                "summary_path": self.summary_path,
            }

    class FakeEquipmentPageApi:
        def ensure_warehouse_design_page_ready(self, task_context=None):
            return FakeDesignReadyResult()

        def capture_design_rarity_sequence(self, *, rarities=None, resume_cursor=0, task_context=None):
            assert resume_cursor == 3
            assert tuple(rarities or ())[:3] == ("common", "rare", "elite")
            return FakeDesignSessionResult()

        def load_design_rarity_resume_cursor(self, summary_path: str | Path) -> int:
            assert Path(summary_path) == summary_path.resolve()
            return 3

    class FakeAdbTaskApi:
        def check_connection(self, **kwargs):
            payload = {
                "adb_path_exists": True,
                "device_count": 1,
                "selected_device_serial": "127.0.0.1:5555",
            }
            return AutomationBridgeResult(True, "ready", "ADB 连接预检完成", "fake adb ready", payload)

        def capture_screenshot(self, **kwargs):
            return AutomationBridgeResult(True, "reserved", "ADB 截图预检完成", "fake screenshot", {"real_capture_enabled": False})

        def run_environment_check(self, **kwargs):
            return AutomationBridgeResult(True, "ready", "ADB 环境预检完成", "fake env", {"dependencies": {"opencv_cv2": True}})

    monkeypatch.setattr(PathManager, "get_work_dir", lambda: work_dir)
    monkeypatch.setattr("ui.automation_bridge.get_adb_task_api", lambda: FakeAdbTaskApi())
    monkeypatch.setattr("ui.automation_bridge.get_equipment_page_adb_api", lambda: FakeEquipmentPageApi())

    adb_result = bridge.run_adb_connection_check()
    adb_state = get_runtime_state_manager().get_full_state()["task"]
    ocr_result = bridge.run_ocr_resource_scan()
    ocr_state = get_runtime_state_manager().get_full_state()["task"]
    design_result = bridge.run_design_chart_flow()
    design_state = get_runtime_state_manager().get_full_state()["task"]

    assert adb_result.success is True
    assert adb_result.status == "ready"
    assert adb_state["kind"] == "idle"
    assert adb_state["current_task"] == "ADB 连接预检"
    assert ocr_result.success is True
    assert ocr_result.status == "reserved"
    assert ocr_state["kind"] == "idle"
    assert ocr_state["current_task"] == "资源 OCR 预检"
    assert design_result.success is True
    assert design_result.status in {"ready", "reserved"}
    assert design_state["kind"] == "idle"
    assert design_state["current_task"] == "设计图功能测试"


def test_automation_lab_page_exposes_v060_buttons_and_runs_tasks(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """自动化实验室应展示新的预检按钮，并能通过统一任务管理器执行。"""
    class FakeBridge:
        def run_adb_connection_check(self, task_context=None) -> AutomationBridgeResult:
            return AutomationBridgeResult(True, "ready", "ADB 连接预检完成", "模拟器=雷电模拟器；端口=5555", {"simulator_name": "雷电模拟器"})

        def run_ocr_resource_scan(self, task_context=None) -> AutomationBridgeResult:
            return AutomationBridgeResult(True, "reserved", "资源 OCR 接口预检完成", "player_name/oil/coins/gems", {"result_schema": []})

        def run_design_chart_flow(self, task_context=None, rarities=None, resume_cursor=None) -> AutomationBridgeResult:
            return AutomationBridgeResult(
                True,
                "ready",
                "design flow done",
                f"resume_cursor={resume_cursor}; rarities={rarities}",
                {"resume_cursor_loaded": resume_cursor, "rarities_requested": list(rarities or [])},
            )

        def run_game_enter_home(
            self,
            task_context=None,
            client_key=None,
            server_key=None,
            simulator_key=None,
            serial=None,
            port=None,
        ) -> AutomationBridgeResult:
            return AutomationBridgeResult(
                True,
                "ready",
                "已确认进入港区主页。",
                f"client={client_key}; server={server_key}; simulator={simulator_key}; serial={serial}; port={port}",
                {
                    "client_display": "国服官服（B站）",
                    "server_display": "自动进入当前/上次服务器",
                    "screen_state": "harbor",
                    "package_name": "com.bilibili.azurlane",
                },
            )

    window = MainWindow(registry=get_feature_hook_registry())
    page = window.pages["automation_lab"]
    page.automation_bridge = FakeBridge()
    monkeypatch.setattr(
        page.task_manager,
        "start_task",
        lambda spec, runner, callback: (callback(runner(None)), True)[1],
    )
    emitted_keys: list[str] = []
    page.featureRequested.connect(emitted_keys.append)

    assert "adb_connection_check" in page.automation_task_buttons
    assert "ocr_resource_scan" in page.automation_task_buttons
    assert "environment_check" in page.automation_task_buttons
    assert "game_auto_login" in page.automation_task_buttons
    assert "game_enter_home" in page.automation_task_buttons
    assert "design_chart_flow_test" in page.automation_task_buttons
    assert "design_chart_flow_start" in page.automation_task_buttons
    assert page.design_flow_button.text() == "设计图功能测试"
    assert page.design_flow_start_button.text() == "测试筛选"
    assert page.design_flow_rarities_edit.text().startswith("common")
    assert page.design_flow_resume_cursor_edit.text() == "0"

    page.automation_task_buttons["ocr_resource_scan"].click()
    assert emitted_keys[-1] == "ocr_resource_scan"
    assert "资源 OCR 接口预检完成" in page.automation_task_status_label.text()

    page.design_flow_rarities_edit.setText("rare elite ultra_rare")
    page.design_flow_resume_cursor_edit.setText("1")
    page.design_flow_start_button.click()
    assert emitted_keys[-1] == "design_chart_flow_test"
    assert "design flow done" in page.design_flow_status_label.text()
    assert "resume_cursor=1" in page.design_flow_status_label.text()

    page.game_enter_home_button.click()
    assert "已进入主页" in page.game_login_status_label.text()

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
