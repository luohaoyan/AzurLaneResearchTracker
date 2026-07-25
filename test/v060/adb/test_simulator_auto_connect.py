#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 模拟器自动连接测试                        ║
║                                                              ║
║  【测试目标】覆盖模拟器 serial 候选、ADB 自动连接和 API 包装。 ║
║  【类比理解】像在通讯试验台上模拟端口拨号，不依赖真实模拟器。  ║
║  【数据流说明】registry → AdbController → AdbTaskApi。        ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import subprocess
from typing import Any, Callable

from core.automation.adb_controller import (
    AdbAutoConnectResult,
    AdbCommandResult,
    AdbConnectionResult,
    AdbController,
    AdbDevice,
    AdbDisplayCheckResult,
    AdbPathResolution,
)
from core.automation.adb_task_api import get_adb_task_api
from core.automation.simulator_registry import build_auto_connect_candidates, normalize_serial


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeRunner:
    """记录 ADB 命令并按规则返回 fake CompletedProcess。"""

    def __init__(self, handler: Callable[[list[str], dict[str, Any]], subprocess.CompletedProcess[Any]]) -> None:
        """保存命令处理器。"""
        self.handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        """模拟 subprocess.run。"""
        self.calls.append(command)
        return self.handler(command, kwargs)


class FakeAutoConnectController:
    """模拟自动连接成功、显示环境正常和前台游戏包可读。"""

    def __init__(self, simulator_config: dict[str, Any]) -> None:
        """保存模拟器配置。"""
        self.simulator_config = simulator_config

    def auto_connect_simulator(self, *args: Any, **kwargs: Any) -> AdbAutoConnectResult:
        """返回已连接的 MuMu 设备。"""
        device = AdbDevice("127.0.0.1:7555", "device")
        return AdbAutoConnectResult(
            True,
            "ready",
            "模拟器自动连接成功：127.0.0.1:7555",
            selected_device=device,
            candidates=(device,),
            attempted_serials=("127.0.0.1:7555",),
            adb_path="C:/fake/adb.exe",
            adb_source="config",
            command_results=(AdbCommandResult(True, "ok", "ADB 命令执行成功。"),),
        )

    def check_display_environment(self, **kwargs: Any) -> AdbDisplayCheckResult:
        """模拟显示环境符合推荐设置。"""
        return AdbDisplayCheckResult(True, "ready", "显示环境正常。", resolution=(1280, 720), density=240, characteristics="tablet")

    def get_foreground_package(self, **kwargs: Any) -> AdbCommandResult:
        """模拟当前前台为碧蓝航线游戏包。"""
        return AdbCommandResult(True, "ok", "已读取前台应用包名。", stdout="com.bilibili.azurlane")


def _completed(command: list[str], returncode: int = 0, stdout: Any = "", stderr: Any = "") -> subprocess.CompletedProcess[Any]:
    """创建 subprocess.CompletedProcess。"""
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_simulator_registry_normalizes_serial_and_limits_candidates() -> None:
    """注册表应能归一化用户输入，并优先返回当前模拟器候选。"""
    config = {"adb": {"port": 7555, "candidate_serials": ["16384", "127。0。0。1：16416"]}}

    candidates = build_auto_connect_candidates("mumu", config)

    assert normalize_serial("7555") == "127.0.0.1:7555"
    assert candidates[:3] == ("127.0.0.1:7555", "127.0.0.1:16384", "127.0.0.1:16416")


def test_adb_controller_auto_connect_attempts_configured_serial_first() -> None:
    """自动连接应先尝试配置 serial，成功后返回 ready 和尝试列表。"""
    devices_after_connect = "List of devices attached\n127.0.0.1:7555 device product:MuMu\n"
    devices_seen = 0

    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        nonlocal devices_seen
        if "devices" in command:
            devices_seen += 1
            stdout = "" if devices_seen == 1 else devices_after_connect
            return _completed(command, stdout=f"List of devices attached\n{stdout}")
        if "connect" in command:
            return _completed(command, stdout="connected to 127.0.0.1:7555\n")
        if "getprop" in command:
            return _completed(command, stdout="[ro.product.model]: [MuMu]\n[nemud.player_version]: [4.0.0]\n")
        return _completed(command)

    runner = FakeRunner(handler)
    controller = AdbController(
        {
            "type": "mumu",
            "adb": {
                "path": "C:/fake/adb.exe",
                "port": 7555,
                "connect_timeout": 1,
                "auto_connect_timeout": 1,
            },
        },
        runner=runner,
        path_exists=lambda path: path == "C:/fake/adb.exe",
        which=lambda name: None,
        sleeper=lambda seconds: None,
    )

    result = controller.auto_connect_simulator("mumu", max_candidates=1)

    assert result.success is True
    assert result.status == "ready"
    assert result.selected_device is not None
    assert result.selected_device.serial == "127.0.0.1:7555"
    assert result.attempted_serials == ("127.0.0.1:7555",)
    assert any(command[-2:] == ["connect", "127.0.0.1:7555"] for command in runner.calls)


def test_adb_controller_auto_connect_keeps_multiple_devices_for_user_choice() -> None:
    """多设备且没有明确配置时，不应偷偷选择设备。"""
    output = "List of devices attached\n127.0.0.1:7555 device\n127.0.0.1:5555 device\n"
    runner = FakeRunner(lambda command, kwargs: _completed(command, stdout=output))
    controller = AdbController(
        {"type": "mumu", "adb": {"path": "C:/fake/adb.exe", "connect_timeout": 1}},
        runner=runner,
        path_exists=lambda path: path == "C:/fake/adb.exe",
        which=lambda name: None,
    )

    result = controller.auto_connect_simulator("mumu", max_candidates=1)

    assert result.success is False
    assert result.status == "multiple_devices"
    assert "多台" in result.message
    assert len(result.candidates) == 2


def test_adb_controller_identifies_ldplayer_from_ldinit_property() -> None:
    """雷电实例应能通过 Android 属性中的 ldinit 指纹识别。"""
    simulator_type, confidence, evidence = AdbController._simulator_type_for(
        "127.0.0.1:5555",
        {"init.svc.ldinit": "running", "ro.product.model": "GM1910"},
    )

    assert simulator_type == "leidian"
    assert confidence == 0.95
    assert any("雷电" in item for item in evidence)


def test_adb_task_api_auto_connect_payload_includes_display_and_foreground() -> None:
    """ADB API 自动连接 payload 应包含 UI 需要展示的显示环境与前台包。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    api._controller_factory = FakeAutoConnectController
    try:
        result = api.auto_connect_simulator()
    finally:
        api._controller_factory = original_factory

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    assert result.payload["connection_status"] == "ready"
    assert result.payload["display_environment"]["resolution"] == [1280, 720]
    assert result.payload["foreground_app"]["package_name"] == "com.bilibili.azurlane"
