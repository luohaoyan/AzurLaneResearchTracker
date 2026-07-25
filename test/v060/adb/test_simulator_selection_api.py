#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 模拟器手动选择 API 测试                   ║
║                                                              ║
║  【测试目标】覆盖模拟器 key、手动端口、serial 和自动选择参数。 ║
║  【数据流说明】UI参数 → AdbTaskApi → AdbController 配置。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.automation.adb_controller import (
    AdbAutoConnectResult,
    AdbCommandResult,
    AdbDevice,
    AdbDisplayCheckResult,
)
from core.automation.adb_task_api import get_adb_task_api
from core.automation.simulator_preferences import SimulatorPreferences


class FakeSelectionController:
    """记录 API 传入的模拟器配置和连接 serial。"""

    last_config: dict[str, Any] = {}
    last_serial: str = ""

    def __init__(self, simulator_config: dict[str, Any]) -> None:
        """保存控制器配置供断言。"""
        self.simulator_config = simulator_config
        type(self).last_config = simulator_config

    def auto_connect_simulator(self, _key: str, *, serial: str | None = None, **_: Any) -> AdbAutoConnectResult:
        """返回固定成功结果。"""
        type(self).last_serial = str(serial or "")
        device = AdbDevice(type(self).last_serial or "127.0.0.1:5555", "device")
        return AdbAutoConnectResult(
            True,
            "ready",
            "连接成功",
            selected_device=device,
            candidates=(device,),
            adb_path="C:/fake/adb.exe",
            adb_source="config",
            command_results=(AdbCommandResult(True, "ok", "完成"),),
        )

    def check_display_environment(self, **_: Any) -> AdbDisplayCheckResult:
        """返回最小显示环境结果。"""
        return AdbDisplayCheckResult(True, "ready", "正常", resolution=(1280, 720), density=240, characteristics="tablet")

    def get_foreground_package(self, **_: Any) -> AdbCommandResult:
        """返回最小前台包结果。"""
        return AdbCommandResult(True, "ok", "正常", stdout="com.bilibili.azurlane")


def test_api_manual_port_overrides_saved_serial_and_persists_to_temp_json(tmp_path: Path) -> None:
    """手动端口应转换为本地 serial，并覆盖历史 serial。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    original_preferences = api.simulator_preferences
    api._controller_factory = FakeSelectionController
    api.simulator_preferences = SimulatorPreferences(tmp_path / "config.json")
    try:
        result = api.auto_connect_simulator(simulator_key="leidian", port="5566")
    finally:
        api._controller_factory = original_factory
        api.simulator_preferences = original_preferences

    assert result.success is True
    assert FakeSelectionController.last_config["adb"]["port"] == 5566
    assert FakeSelectionController.last_serial == "127.0.0.1:5566"
    data = SimulatorPreferences(tmp_path / "config.json").load()
    assert data["simulator_preferences"]["selection"] == "leidian"


def test_api_auto_selection_keeps_auto_mode_and_accepts_explicit_serial(tmp_path: Path) -> None:
    """自动选择模式允许用户用 serial 锁定多设备中的目标实例。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    original_preferences = api.simulator_preferences
    api._controller_factory = FakeSelectionController
    api.simulator_preferences = SimulatorPreferences(tmp_path / "config.json")
    try:
        result = api.auto_connect_simulator(simulator_key="auto", serial="127.0.0.1:7555")
    finally:
        api._controller_factory = original_factory
        api.simulator_preferences = original_preferences

    assert result.success is True
    assert result.payload is not None
    assert result.payload["selection"] == "auto"
    assert result.payload["auto_selected"] is True
    assert result.payload["device_serial"] == "127.0.0.1:7555"
