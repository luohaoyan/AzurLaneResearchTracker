#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       🧪 ADB 应用发现、模拟器识别与游戏登录测试             ║
║                                                              ║
║  【测试目标】验证包列表回退、模拟器指纹和可注入登录状态机。   ║
║  【类比理解】像先盘点设备上的程序，再确认游戏是否进港区。     ║
║  【数据流说明】fake ADB → AdbController → 结构化结果。       ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import subprocess
from typing import Any, Callable

import pytest

from core.automation.adb_controller import (
    AdbLoginResult,
    AdbPackageInfo,
    AdbPackageListResult,
    AdbSimulatorListResult,
    AdbSimulatorProfile,
    AdbController,
    PNG_SIGNATURE,
)
from core.automation.adb_task_api import get_adb_task_api
from core.contracts import RecognitionScene, TaskCancelledError, TaskExecutionContext


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeClock:
    """让登录超时测试无需真实等待。"""

    def __init__(self) -> None:
        """初始化虚拟时间。"""
        self.value = 0.0

    def now(self) -> float:
        """返回虚拟单调时间。"""
        return self.value

    def sleep(self, seconds: float) -> None:
        """推进虚拟时间。"""
        self.value += max(0.1, float(seconds))


class FakeRunner:
    """记录命令并按回调返回 CompletedProcess。"""

    def __init__(self, handler: Callable[[list[str]], subprocess.CompletedProcess[Any]]) -> None:
        """保存命令处理器。"""
        self.handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        """模拟 subprocess.run。"""
        self.calls.append(command)
        return self.handler(command)


def _completed(command: list[str], stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[Any]:
    """构造文本命令结果。"""
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def _controller(
    runner: FakeRunner,
    *,
    sleeper: Callable[[float], object] | None = None,
    time_provider: Callable[[], float] | None = None,
) -> AdbController:
    """创建不访问真实 PATH 的控制器。"""
    return AdbController(
        {
            "adb": {
                "path": "C:/fake/adb.exe",
                "serial": "127.0.0.1:7555",
                "connect_timeout": 1,
                "base_resolution": {"width": 1280, "height": 720},
            },
            "screen": {"width": 1280, "height": 720},
        },
        runner=runner,
        path_exists=lambda path: True,
        which=lambda name: None,
        sleeper=sleeper or (lambda seconds: None),
        time_provider=time_provider,
    )


# ============================================================
# 🧪 第三部分：应用包和前台程序测试
# ============================================================

def test_parse_packages_supports_pm_and_dumpsys_formats() -> None:
    """包解析应支持 pm 行和 dumpsys 包块，并标记系统应用。"""
    output = """
Package [com.android.settings]:
    codePath=/system/priv-app/Settings
    pkgFlags=[ SYSTEM HAS_CODE ]
Package [com.bilibili.azurlane]:
    codePath=/data/app/com.bilibili.azurlane
"""

    packages = AdbController.parse_packages(output, source="dumpsys")

    assert [item.package_name for item in packages] == ["com.android.settings", "com.bilibili.azurlane"]
    assert packages[0].is_system is True
    assert packages[1].is_system is False
    assert AdbController.parse_packages("package:com.example.demo", source="pm")[0].package_name == "com.example.demo"


def test_list_packages_falls_back_from_pm_to_dumpsys() -> None:
    """用户应用列表应在 pm 失败时回退到 dumpsys。"""
    devices = "List of devices attached\n127.0.0.1:7555 device product:MuMu model:MuMu12\n"
    dumpsys = """
Package [com.android.settings]:
    codePath=/system/priv-app/Settings
    pkgFlags=[ SYSTEM HAS_CODE ]
Package [com.bilibili.azurlane]:
    codePath=/data/app/com.bilibili.azurlane
"""

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, devices)
        if command[-4:] == ["shell", "pm", "list", "packages", "-3"]:
            return _completed(command, returncode=1, stderr="pm failed")
        if command[-2:] == ["dumpsys", "package"]:
            return _completed(command, dumpsys)
        return _completed(command)

    runner = FakeRunner(handler)
    result = _controller(runner).list_packages()

    assert result.success is True
    assert result.source == "dumpsys"
    assert result.package_names == ("com.bilibili.azurlane",)
    assert any("pm_user" in warning for warning in result.warnings)


def test_foreground_package_parser_handles_window_and_activity_formats() -> None:
    """前台包解析应兼容 Android 窗口和 activity 两种输出。"""
    window = "mCurrentFocus=Window{1 u0 com.bilibili.azurlane/com.manjuu.azurlane.MainActivity}"
    activity = "ACTIVITY com.bilibili.azurlane/com.manjuu.azurlane.MainActivity 123 pid=42"

    assert AdbController.parse_foreground_package(window) == "com.bilibili.azurlane"
    assert AdbController.parse_foreground_package(activity) == "com.bilibili.azurlane"
    assert AdbController.parse_foreground_package("no focus") is None


# ============================================================
# 🧪 第四部分：模拟器指纹测试
# ============================================================

def test_detect_simulators_keeps_all_devices_and_reports_fingerprint() -> None:
    """多设备识别只返回候选，不擅自选择。"""
    devices = (
        "List of devices attached\n"
        "127.0.0.1:7555 device product:MuMu model:MuMu12\n"
        "emulator-5554 offline product:sdk_gphone model:sdk\n"
    )
    mumu_props = "[ro.product.model]: [MuMu12]\n[ro.product.brand]: [Netease]\n"

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, devices)
        if command[-2:] == ["shell", "getprop"]:
            return _completed(command, mumu_props)
        return _completed(command)

    result = _controller(FakeRunner(handler)).detect_simulators()

    assert result.success is True
    assert len(result.simulators) == 2
    assert result.simulators[0].simulator_type == "mumu"
    assert result.simulators[1].state == "offline"


def test_simulator_port_heuristics_keep_ambiguous_ldplayer_bluestacks_label() -> None:
    """仅凭 5555 端口时应标记歧义，等待用户或属性确认。"""
    simulator_type, confidence, evidence = AdbController._simulator_type_for("127.0.0.1:5555")

    assert simulator_type == "leidian_or_bluestacks"
    assert confidence < 0.6
    assert evidence


# ============================================================
# 🧪 第五部分：游戏启动和登录测试
# ============================================================

def test_login_game_starts_app_and_succeeds_when_scene_probe_confirms() -> None:
    """登录流程应启动应用并由注入探针确认港区。"""
    devices = "List of devices attached\n127.0.0.1:7555 device\n"
    probe_calls = 0

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, devices)
        if command[-5:] == ["shell", "pm", "list", "packages", "-3"]:
            return _completed(command, "package:com.bilibili.azurlane\n")
        if "am" in command and "start" in command and "-n" in command:
            return _completed(command, "Starting: Intent {}")
        if command[:4] == ["shell", "monkey", "-p", "com.bilibili.azurlane"]:
            return _completed(command, "Events injected: 1")
        if command[-3:] == ["dumpsys", "window", "windows"]:
            return _completed(command, "mCurrentFocus=Window{1 u0 com.bilibili.azurlane/com.manjuu.azurlane.MainActivity}")
        if "exec-out" in command:
            return _completed(command, PNG_SIGNATURE + b"login")
        return _completed(command)

    def scene_probe(scene: RecognitionScene) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return scene is RecognitionScene.HARBOR and probe_calls >= 2

    clock = FakeClock()
    result = _controller(FakeRunner(handler), sleeper=clock.sleep, time_provider=clock.now).login_game(
        "com.bilibili.azurlane",
        activity_name="com.manjuu.azurlane.MainActivity",
        scene_probe=scene_probe,
        timeout_seconds=2,
        max_retries=0,
        login_steps=[],
    )

    assert result.success is True
    assert result.status == "ready"
    assert result.foreground_package == "com.bilibili.azurlane"
    assert probe_calls >= 2


def test_login_game_falls_back_to_monkey_when_activity_launch_fails() -> None:
    """指定 Activity 无法拉起时，应回退到 monkey 主入口，避免按钮看起来没反应。"""
    devices = "List of devices attached\n127.0.0.1:7555 device\n"
    commands: list[list[str]] = []

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        commands.append(list(command))
        if "devices" in command:
            return _completed(command, devices)
        if command[-5:] == ["shell", "pm", "list", "packages", "-3"]:
            return _completed(command, "package:com.bilibili.azurlane\n")
        if "am" in command and "start" in command and "-n" in command:
            return _completed(command, "", returncode=0, stderr="Error type 3: Activity not found")
        if command[:4] == ["shell", "monkey", "-p", "com.bilibili.azurlane"]:
            return _completed(command, "Events injected: 1")
        if command[-3:] == ["dumpsys", "window", "windows"]:
            return _completed(command, "mCurrentFocus=Window{1 u0 com.bilibili.azurlane/com.manjuu.azurlane.MainActivity}")
        return _completed(command)

    clock = FakeClock()
    result = _controller(FakeRunner(handler), sleeper=clock.sleep, time_provider=clock.now).login_game(
        "com.bilibili.azurlane",
        activity_name="com.manjuu.azurlane.MainActivity",
        scene_probe=None,
        timeout_seconds=0.5,
        max_retries=0,
        login_steps=[],
    )

    assert result.success is True
    assert result.status in {"started", "ready"}
    assert any(
        "monkey" in command and "-p" in command and "com.bilibili.azurlane" in command
        for command in commands
    )


def test_login_game_returns_package_not_installed_without_clicking() -> None:
    """未安装游戏时应在启动前返回，不发送点击或启动命令。"""
    devices = "List of devices attached\n127.0.0.1:7555 device\n"

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, devices)
        if command[-5:] == ["shell", "pm", "list", "packages", "-3"]:
            return _completed(command, "package:com.android.settings\n")
        return _completed(command)

    runner = FakeRunner(handler)
    result = _controller(runner).login_game("com.bilibili.azurlane", login_steps=[])

    assert result.success is False
    assert result.status == "package_not_installed"
    assert not any("monkey" in command or "am" in command for command in runner.calls)


def test_login_game_honors_cancellation_before_following_status_queries() -> None:
    """取消请求后不应继续执行登录状态查询。"""
    context = TaskExecutionContext()
    devices = "List of devices attached\n127.0.0.1:7555 device\n"

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, devices)
        if command[-5:] == ["shell", "pm", "list", "packages", "-3"]:
            return _completed(command, "package:com.bilibili.azurlane\n")
        if "monkey" in command or ("am" in command and "start" in command):
            context.cancellation_token.request_cancel()
        return _completed(command)

    runner = FakeRunner(handler)
    with pytest.raises(TaskCancelledError):
        _controller(runner).login_game(
            "com.bilibili.azurlane",
            scene_probe=lambda scene: False,
            timeout_seconds=2,
            login_steps=[],
            task_context=context,
        )

    assert not any("dumpsys" in command for command in runner.calls)


# ============================================================
# 🧪 第六部分：任务 API 包装测试
# ============================================================

def test_adb_task_api_exposes_package_simulator_and_login_payloads() -> None:
    """任务 API 应透传三类新增控制器结果且不改变顶层契约。"""
    class ApiController:
        """仅实现新增 API 所需的 fake 控制器。"""

        def __init__(self, config: dict[str, Any]) -> None:
            """保存配置以匹配真实工厂签名。"""
            self.config = config

        def list_packages(self, **kwargs: Any) -> Any:
            """返回 fake 应用列表。"""
            package = AdbPackageInfo("com.bilibili.azurlane", source="pm_user")
            return AdbPackageListResult(True, "ready", "应用列表完成。", packages=(package,), source="pm_user")

        def detect_simulators(self, **kwargs: Any) -> Any:
            """返回 fake 模拟器候选。"""
            profile = AdbSimulatorProfile("127.0.0.1:7555", "device", "mumu", 0.95)
            return AdbSimulatorListResult(True, "ready", "识别完成。", simulators=(profile,), adb_source="config")

        def login_game(self, package_name: str, **kwargs: Any) -> Any:
            """返回 fake 登录结果。"""
            return AdbLoginResult(True, "started", "已启动。", package_name, serial="127.0.0.1:7555", attempts=1)

    api = get_adb_task_api()
    original_factory = api._controller_factory
    api._controller_factory = ApiController
    try:
        packages = api.list_packages()
        simulators = api.detect_simulators()
        login = api.run_game_login()
        enter_home = api.run_azur_lane_enter_home()
    finally:
        api._controller_factory = original_factory

    assert packages.success is True
    assert packages.payload is not None
    assert packages.payload["package_names"] == ["com.bilibili.azurlane"]
    assert simulators.payload is not None
    assert simulators.payload["simulator_count"] == 1
    assert login.success is True
    assert login.payload is not None
    assert login.payload["package_name"] == "com.bilibili.azurlane"
    assert enter_home.success is False
    assert enter_home.status == "needs_confirmation"
    assert enter_home.payload is not None
    assert enter_home.payload["enter_home_required"] is True
