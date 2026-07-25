#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 游戏自动登录测试                         ║
║                                                              ║
║  【测试目标】验证多版本碧蓝航线包名匹配和 ADB 启动封装。       ║
║  【类比理解】像先找手机里装了哪个客户端，再按用户选择打开。    ║
║  【数据流说明】包列表 → game_login_registry → AdbTaskApi。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Any

from core.automation.adb_controller import AdbLoginResult, AdbPackageInfo, AdbPackageListResult
from core.automation.adb_task_api import get_adb_task_api
from core.automation.game_login_preferences import GameLoginPreferences
from core.automation.game_login_registry import (
    get_azur_lane_client_profile,
    list_azur_lane_servers,
    select_azur_lane_client,
)


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeGameLoginController:
    """记录 API 选择的包名和 Activity，不访问真实 ADB。"""

    packages: tuple[str, ...] = ("com.YoStarJP.AzurLane",)
    login_calls: list[dict[str, Any]] = []

    def __init__(self, config: dict[str, Any]) -> None:
        """保存控制器配置，匹配 AdbController 工厂签名。"""
        self.config = config

    def list_packages(self, **_: Any) -> AdbPackageListResult:
        """返回可控的已安装应用列表。"""
        return AdbPackageListResult(
            True,
            "ready",
            "应用列表完成。",
            packages=tuple(AdbPackageInfo(package, source="pm_user") for package in self.packages),
            source="pm_user",
        )

    def login_game(self, package_name: str, **kwargs: Any) -> AdbLoginResult:
        """记录启动参数并返回已启动结果。"""
        self.login_calls.append({"package_name": package_name, **kwargs})
        return AdbLoginResult(
            True,
            "started",
            "已启动。",
            package_name,
            serial=kwargs.get("serial") or "127.0.0.1:7555",
            attempts=1,
            foreground_package=package_name,
            screen_state="app_launch",
            scene_hint="app_launch",
        )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_registry_matches_alas_style_packages_and_servers() -> None:
    """客户端目录应覆盖 ALAS 中常见的包名和服务器列表。"""
    official = get_azur_lane_client_profile("official_cn")
    selected = select_azur_lane_client(["com.YoStarJP.AzurLane"], "auto")

    assert official is not None
    assert official.package_name == "com.bilibili.azurlane"
    assert official.activity_name == "com.manjuu.azurlane.MainActivity"
    assert selected is not None
    assert selected.key == "official_jp"
    assert "莱茵演习" in list_azur_lane_servers("cn_android")
    assert "横須賀" in list_azur_lane_servers("jp")


def test_adb_task_api_scans_packages_and_launches_selected_client(tmp_path: Path) -> None:
    """API 应先扫描已安装包，再启动用户选择的客户端。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    original_preferences = api.game_login_preferences
    FakeGameLoginController.packages = ("com.YoStarJP.AzurLane",)
    FakeGameLoginController.login_calls = []
    api._controller_factory = FakeGameLoginController
    api.game_login_preferences = GameLoginPreferences(tmp_path / "config.json")
    try:
        result = api.run_azur_lane_auto_login(
            client_key="official_jp",
            server_key="横須賀",
            simulator_key="mumu",
            serial="127.0.0.1:7555",
        )
    finally:
        api._controller_factory = original_factory
        api.game_login_preferences = original_preferences

    assert result.success is True
    assert result.payload is not None
    assert result.payload["client_key"] == "official_jp"
    assert result.payload["server_display"] == "横須賀"
    assert FakeGameLoginController.login_calls[0]["package_name"] == "com.YoStarJP.AzurLane"
    assert FakeGameLoginController.login_calls[0]["activity_name"] == "com.manjuu.azurlane.PrePermissionActivity"
    saved = GameLoginPreferences(tmp_path / "config.json").get_selection()
    assert saved["client"] == "official_jp"
    assert saved["server"] == "横須賀"
    assert saved["last_package"] == "com.YoStarJP.AzurLane"


def test_adb_task_api_reports_selected_client_not_installed(tmp_path: Path) -> None:
    """未安装所选客户端时应返回友好错误，不能启动错误版本。"""
    api = get_adb_task_api()
    original_factory = api._controller_factory
    original_preferences = api.game_login_preferences
    FakeGameLoginController.packages = ("com.android.settings",)
    FakeGameLoginController.login_calls = []
    api._controller_factory = FakeGameLoginController
    api.game_login_preferences = GameLoginPreferences(tmp_path / "config.json")
    try:
        result = api.run_azur_lane_auto_login(client_key="official_cn", server_key="auto")
    finally:
        api._controller_factory = original_factory
        api.game_login_preferences = original_preferences

    assert result.success is False
    assert result.status == "package_not_installed"
    assert result.payload is not None
    assert result.payload["installed_clients"] == []
    assert FakeGameLoginController.login_calls == []
