#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 模拟器自动连接契约测试                    ║
║                                                              ║
║  【测试目标】验证从 INT worktree 迁移的自动连接行为。         ║
║  【类比理解】像通讯试验台，检查候选端口、设备选择和 API 包装。 ║
║  【数据流说明】模拟器注册表 → AdbController → AdbTaskApi。    ║
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
)
from core.automation.adb_task_api import get_adb_task_api
from core.automation.simulator_registry import build_auto_connect_candidates, normalize_serial


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeRunner:
    """记录 ADB 命令并返回可控的 CompletedProcess。"""

    def __init__(self, handler: Callable[[list[str], dict[str, Any]], subprocess.CompletedProcess[Any]]) -> None:
        """保存命令处理器。"""
        self.handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        """模拟 subprocess.run。"""
        self.calls.append(command)
        return self.handler(command, kwargs)


def _completed(
    command: list[str],
    returncode: int = 0,
    stdout: Any = "",
    stderr: Any = "",
) -> subprocess.CompletedProcess[Any]:
    """创建 subprocess.CompletedProcess。"""
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


class FakeAutoConnectController:
    """提供成功连接、显示环境和前台应用结果，隔离真实设备。"""

    def __init__(self, simulator_config: dict[str, Any]) -> None:
        """保存模拟器配置。"""
        self.simulator_config = simulator_config

    def auto_connect_simulator(self, *args: Any, **kwargs: Any) -> AdbAutoConnectResult:
        """返回符合 INT 结果契约的已连接设备。"""
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
        """返回推荐的 1280x720 平板环境。"""
        return AdbDisplayCheckResult(
            True,
            "ready",
            "显示环境正常。",
            resolution=(1280, 720),
            density=240,
            characteristics="tablet",
        )

    def get_foreground_package(self, **kwargs: Any) -> AdbCommandResult:
        """返回碧蓝航线前台包名。"""
        return AdbCommandResult(True, "ok", "已读取前台应用包名。", stdout="com.bilibili.azurlane")


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_registry_normalizes_serial_and_prioritizes_configured_port() -> None:
    """注册表应将端口规范化，并把当前模拟器端口放在候选首位。"""
    config = {"adb": {"port": 7555, "candidate_serials": ["16384", "127。0。0。1：16416"]}}

    candidates = build_auto_connect_candidates("mumu", config)

    assert normalize_serial("7555") == "127.0.0.1:7555"
    assert candidates[:3] == ("127.0.0.1:7555", "127.0.0.1:16384", "127.0.0.1:16416")


def test_controller_auto_connect_attempts_tcp_candidate() -> None:
    """没有现成设备时，控制器应执行 adb connect 并返回已选设备。"""
    devices_seen = 0

    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        nonlocal devices_seen
        if "devices" in command:
            devices_seen += 1
            stdout = "" if devices_seen == 1 else "127.0.0.1:7555 device product:MuMu\n"
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


def test_task_api_auto_connect_exposes_display_and_foreground() -> None:
    """任务 API payload 应继续提供 UI 所需的显示环境和前台应用。"""
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
