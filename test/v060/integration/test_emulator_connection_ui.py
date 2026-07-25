#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 模拟器连接 UI 测试                        ║
║                                                              ║
║  【测试目标】确认自动化实验室能展示 ADB 连接、显示环境和前台包。║
║  【类比理解】像看仪表盘，后台连接结果必须清楚显示给指挥官。    ║
║  【数据流说明】AutomationBridgeResult → AutomationLabPage。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
from pathlib import Path
from typing import Generator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.automation_bridge import AutomationBridgeResult
from ui.main_window import MainWindow
from core.automation.simulator_preferences import SimulatorPreferences


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """创建离屏 QApplication。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_automation_lab_updates_emulator_connection_status(qapp: QApplication) -> None:
    """自动化实验室应把自动连接结果展示为常驻连接状态。"""
    window = MainWindow()
    page = window.pages["automation_lab"]
    result = AutomationBridgeResult(
        True,
        "ready",
        "模拟器自动连接成功：127.0.0.1:7555",
        "模拟器=MuMu模拟器；设备=127.0.0.1:7555",
        {
            "simulator_name": "MuMu模拟器",
            "connection_status": "ready",
            "device_serial": "127.0.0.1:7555",
            "adb_path": "C:/fake/adb.exe",
            "adb_source": "config",
            "display_environment": {
                "status": "ready",
                "resolution": [1280, 720],
                "density": 240,
                "characteristics": "tablet",
            },
            "foreground_app": {
                "success": True,
                "package_name": "com.bilibili.azurlane",
            },
            "detected_simulators": [
                {"serial": "127.0.0.1:7555", "state": "device", "simulator_type": "mumu"}
            ],
            "attempted_serials": ["127.0.0.1:7555"],
        },
    )

    page._on_automation_task_finished("adb_auto_connect", result, page.emulator_status_label)

    assert "已连接" in page.emulator_status_badge.text()
    assert "127.0.0.1:7555" in page.emulator_detail_label.text()
    assert "端口：7555" in page.emulator_detail_label.text()
    assert "ADB路径" not in page.emulator_detail_label.text()
    assert "com.bilibili.azurlane" not in page.emulator_detail_label.text()
    assert page.emulator_candidates_label.isVisible() is False

    window.close()


def test_automation_lab_exposes_simulator_selector_and_manual_endpoint(qapp: QApplication) -> None:
    """自动化实验室应提供自动选择、模拟器下拉框和手动端点输入。"""
    window = MainWindow()
    page = window.pages["automation_lab"]

    assert page.emulator_selector.findData("auto") >= 0
    assert page.emulator_selector.findData("mumu") >= 0
    assert page.emulator_selector.findData("leidian") >= 0
    page.emulator_selector.setCurrentIndex(page.emulator_selector.findData("leidian"))
    page.emulator_serial_edit.setText("")
    page.emulator_port_edit.setText("5566")

    options = page._selected_simulator_options()
    assert options == {"simulator_key": "leidian", "serial": "", "port": "5566"}
    window.close()


def test_automation_lab_startup_connection_uses_background_task(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """启动检测应交给任务管理器，不在 Qt 主线程直接调用 ADB。"""
    window = MainWindow()
    page = window.pages["automation_lab"]
    started: list[object] = []
    monkeypatch.setattr(
        "ui.main_window.get_simulator_preferences",
        lambda: SimulatorPreferences(tmp_path / "config.json"),
    )

    monkeypatch.setattr(
        page.automation_bridge,
        "run_adb_auto_connect",
        lambda **_: "fake-result",
    )

    def fake_start_task(spec: object, runner: object, finished_handler: object) -> bool:
        started.extend([spec, runner, finished_handler])
        return True

    monkeypatch.setattr(page.task_manager, "start_task", fake_start_task)
    page._startup_connection_queued = False
    page._start_startup_connection_check()

    assert started
    assert getattr(started[0], "task_id") == "adb_auto_connect"
    assert callable(started[1])
    assert started[1](task_context=None) == "fake-result"
    window.close()
