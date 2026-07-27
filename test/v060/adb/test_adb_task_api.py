#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 ADB API 包装测试                          ║
║                                                              ║
║  【测试目标】确认 adb_task_api 能透传真实 controller 结果。    ║
║  【类比理解】像核对驾驶台仪表是否把底层设备状态显示出来。      ║
║  【数据流说明】fake controller → AdbTaskApi → AdbTaskResult。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Any

from core.automation.adb_controller import (
    AdbConnectionResult,
    AdbDevice,
    AdbDisplayCheckResult,
    AdbLoginResult,
    AdbCommandResult,
    AdbPackageInfo,
    AdbPackageListResult,
    AdbPathResolution,
    AdbScreenshotResult,
    AdbStateWaitResult,
    NavigationResult,
)
from core.automation.adb_task_api import get_adb_task_api
from core.contracts import RecognitionScene, ScreenshotArtifact


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeController:
    """返回固定真实状态的 fake controller。"""

    def __init__(self, simulator_config: dict[str, Any]) -> None:
        """保存模拟器配置，匹配真实工厂签名。"""
        self.simulator_config = simulator_config

    def check_connection(self, **kwargs: Any) -> AdbConnectionResult:
        """模拟 ready 设备。"""
        device = AdbDevice("127.0.0.1:7555", "device")
        return AdbConnectionResult(
            True,
            "ready",
            "ADB 设备连接正常。",
            selected_device=device,
            candidates=(device,),
            adb_path="C:/fake/adb.exe",
            adb_source="config",
        )

    def find_adb(self) -> AdbPathResolution:
        """模拟 ADB 已找到。"""
        return AdbPathResolution("C:/fake/adb.exe", "config")

    def check_display_environment(self, **kwargs: Any) -> AdbDisplayCheckResult:
        """模拟推荐显示环境已满足。"""
        return AdbDisplayCheckResult(
            True,
            "ready",
            "显示环境正常。",
            resolution=(1280, 720),
            density=240,
            characteristics="tablet",
        )

    def capture_screenshot(self, scene: RecognitionScene, **kwargs: Any) -> AdbScreenshotResult:
        """模拟真实截图成功。"""
        artifact = ScreenshotArtifact(str((Path.cwd() / "fake.png").resolve()), scene, "127.0.0.1:7555")
        return AdbScreenshotResult(True, "ready", "ADB 截图完成。", artifact=artifact, method="exec-out")

    def launch_game(self, package_name: str, **kwargs: Any) -> AdbCommandResult:
        """模拟游戏启动成功。"""
        return AdbCommandResult(True, "ok", "游戏已启动。")

    def list_packages(self, **kwargs: Any) -> AdbPackageListResult:
        """模拟已安装国服官服客户端。"""
        return AdbPackageListResult(
            True,
            "ready",
            "应用列表读取完成。",
            packages=(AdbPackageInfo("com.bilibili.azurlane"),),
            source="fake",
        )

    def login_game(self, package_name: str, **kwargs: Any) -> AdbLoginResult:
        """模拟登录流程已经到达港区主页。"""
        return AdbLoginResult(
            True,
            "ready",
            "游戏已启动并确认进入港区主页。",
            package_name,
            serial="127.0.0.1:7555",
            attempts=1,
            foreground_package=package_name,
            screen_state="harbor",
            scene_hint="harbor",
            screenshot_path=str((Path.cwd() / "harbor.png").resolve()),
            resolution=(1280, 720),
            timestamp="2026-07-27T20:29:16",
            confidence=0.95,
        )

    def wait_for_state(self, expected_state: object, state_probe: object, **kwargs: Any) -> AdbStateWaitResult:
        """模拟状态等待成功。"""
        scene = RecognitionScene.EQUIPMENT_LIST
        return AdbStateWaitResult(
            True,
            "ready",
            "状态已稳定。",
            str(expected_state),
            screen_state="warehouse_material",
            scene=scene,
            scene_hint="material_tab",
            screenshot_path=str((Path.cwd() / "state.png").resolve()),
            resolution=(1280, 720),
            timestamp="2026-07-23T12:00:00",
            confidence=0.91,
            attempts=2,
            stable_frames=2,
        )

    def run_sequence(self, sequence_name: str, scene_probe: object, **kwargs: Any) -> NavigationResult:
        """模拟导航成功。"""
        return NavigationResult(True, "ready", "导航成功。", sequence_name, RecognitionScene.HARBOR, attempts=1)


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_adb_task_api_strict_mode_exposes_real_connection_status() -> None:
    """strict_status=True 时 API 顶层状态应使用真实连接状态。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    api._controller_factory = FakeController
    try:
        result = api.check_connection(strict_status=True)
    finally:
        api._controller_factory = original_factory

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    assert result.payload["connection_status"] == "ready"
    assert result.payload["adb_source"] == "config"


def test_adb_task_api_real_capture_returns_absolute_screenshot_path() -> None:
    """real_capture=True 时 API 应返回可交给 OCR 的绝对截图路径。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    api._controller_factory = FakeController
    try:
        result = api.capture_screenshot(RecognitionScene.RESEARCH, real_capture=True)
    finally:
        api._controller_factory = original_factory

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    assert Path(result.payload["screenshot_path"]).is_absolute()
    assert result.payload["scene"] == "research"
    assert result.payload["capture_method"] == "exec-out"


def test_adb_task_api_environment_check_includes_display_contract() -> None:
    """环境检查 payload 应包含 1280x720 和平板模式检查结果。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    api._controller_factory = FakeController
    try:
        result = api.run_environment_check(strict_status=True)
    finally:
        api._controller_factory = original_factory

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    display = result.payload["display_environment"]
    assert display["resolution"] == [1280, 720]
    assert display["recommended_resolution"] == [1280, 720]
    assert display["required_mode"] == "tablet"


def test_adb_task_api_launch_game_and_wait_for_state_payloads() -> None:
    """新 API 包装应透传 launch_game 和 wait_for_state 的结构化字段。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    api._controller_factory = FakeController
    try:
        launch = api.launch_game()
        wait = api.wait_for_state("warehouse_material", lambda scene: True)
    finally:
        api._controller_factory = original_factory

    assert launch.success is True
    assert launch.payload is not None
    assert launch.payload["package_name"] == "com.bilibili.azurlane"
    assert wait.success is True
    assert wait.payload is not None
    assert wait.payload["screen_state"] == "warehouse_material"
    assert wait.payload["scene"] == "equipment_list"


def test_adb_task_api_enter_home_requires_harbor_confirmation() -> None:
    """进入游戏主页任务只有确认 harbor 后才返回 ready。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    api._controller_factory = FakeController
    try:
        result = api.run_azur_lane_enter_home()
    finally:
        api._controller_factory = original_factory

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    assert result.payload["screen_state"] == "harbor"
    assert result.payload["enter_home_required"] is True
    assert "已确认进入港区主页" in result.message
