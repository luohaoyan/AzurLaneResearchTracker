#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 ADB 状态与仓库接口测试                   ║
║                                                              ║
║  【测试目标】验证 wait_for_state、仓库 tab 切换与弹窗关闭。   ║
║  【类比理解】像检查驾驶台是否会等到仪表稳定才继续开车。      ║
║  【数据流说明】fake ADB → AdbController → 状态化结果。       ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import subprocess
from pathlib import Path
from typing import Any, Callable

from core.automation.adb_controller import AdbController, PNG_SIGNATURE
from core.contracts import RecognitionScene


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeClock:
    """让状态等待测试无需真实睡眠。"""

    def __init__(self) -> None:
        """初始化虚拟单调时间。"""
        self.value = 0.0

    def now(self) -> float:
        """返回虚拟单调时间。"""
        return self.value

    def sleep(self, seconds: float) -> None:
        """推进虚拟时间。"""
        self.value += max(0.1, float(seconds))


class FakeRunner:
    """记录 ADB 命令并按回调返回 CompletedProcess。"""

    def __init__(self, handler: Callable[[list[str]], subprocess.CompletedProcess[Any]]) -> None:
        """保存命令处理器。"""
        self.handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        """模拟 subprocess.run。"""
        self.calls.append(command)
        return self.handler(command)


def _completed(command: list[str], stdout: Any = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[Any]:
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
# 🧪 第三部分：状态等待与仓库导航测试
# ============================================================

def test_wait_for_state_returns_png_metadata_and_state_hint() -> None:
    """wait_for_state 应返回稳定屏幕状态与截图元数据。"""
    devices_output = "List of devices attached\n127.0.0.1:7555 device\n"
    probe_calls = 0

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, stdout=devices_output)
        if "exec-out" in command:
            return _completed(command, stdout=PNG_SIGNATURE + b"state")
        return _completed(command)

    def state_probe(candidate: object) -> dict[str, object]:
        nonlocal probe_calls
        probe_calls += 1
        return {
            "screen_state": "warehouse_material",
            "scene_hint": "material_tab",
            "confidence": 0.91,
        }

    clock = FakeClock()
    result = _controller(FakeRunner(handler), sleeper=clock.sleep, time_provider=clock.now).wait_for_state(
        "warehouse_material",
        state_probe,
        timeout_seconds=1,
        stable_frames=1,
        screenshot_scene="equipment_list",
    )

    assert result.success is True
    assert result.screen_state == "warehouse_material"
    assert result.scene_hint == "material_tab"
    assert result.scene is RecognitionScene.EQUIPMENT_LIST
    assert result.screenshot_path is not None
    assert Path(result.screenshot_path).is_absolute()
    assert probe_calls >= 1


def test_select_warehouse_tab_material_uses_sequence_and_state_probe() -> None:
    """仓库材料页切换应执行配置动作并确认 target_screen_state。"""
    devices_output = "List of devices attached\n127.0.0.1:7555 device\n"

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, stdout=devices_output)
        if "exec-out" in command:
            return _completed(command, stdout=PNG_SIGNATURE + b"material")
        return _completed(command)

    def state_probe(candidate: object) -> dict[str, object]:
        return {
            "screen_state": "warehouse_material",
            "scene_hint": "material_tab",
            "confidence": 0.95,
        }

    controller = _controller(FakeRunner(handler))
    controller._load_sequence_config = lambda: {
        "defaults": {"step_delay": 0, "timeout_seconds": 1, "max_retries": 0, "stable_frames": 1},
        "sequences": {
            "warehouse_material": {
                "target_scene": "equipment_list",
                "target_screen_state": "warehouse_material",
                "timeout_seconds": 1,
                "steps": [{"action": "tap", "x": 1208, "y": 679, "delay": 0}],
            }
        },
    }

    result = controller.select_warehouse_tab("material", state_probe)

    assert result.success is True
    assert result.target_screen_state == "warehouse_material"
    assert result.screen_state == "warehouse_material"
    assert any(command[-2:] == ["1208", "679"] for command in controller.runner.calls)


def test_enter_warehouse_wrapper_uses_sequence_and_scene_probe() -> None:
    """进入仓库入口页的 wrapper 应透传配置序列。"""
    devices_output = "List of devices attached\n127.0.0.1:7555 device\n"

    def handler(command: list[str]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, stdout=devices_output)
        if "exec-out" in command:
            return _completed(command, stdout=PNG_SIGNATURE + b"warehouse")
        return _completed(command)

    controller = _controller(FakeRunner(handler))
    controller._load_sequence_config = lambda: {
        "defaults": {"step_delay": 0, "timeout_seconds": 1, "max_retries": 0, "stable_frames": 1},
        "sequences": {
            "enter_warehouse": {
                "target_scene": "equipment_list",
                "target_screen_state": "warehouse_design",
                "timeout_seconds": 1,
                "steps": [
                    {"action": "tap", "x": 1110, "y": 617, "delay": 0},
                    {"action": "tap", "x": 773, "y": 313, "delay": 0},
                ],
            }
        },
    }

    result = controller.enter_warehouse(lambda scene: scene is RecognitionScene.EQUIPMENT_LIST)

    assert result.success is True
    assert result.target_screen_state == "warehouse_design"
    assert any(command[-2:] == ["773", "313"] for command in controller.runner.calls)


def test_close_popup_home_policy_issues_home_key() -> None:
    """关闭弹窗的 home 策略应发送 Home 键并返回 ready。"""
    runner = FakeRunner(lambda command: _completed(command))
    controller = _controller(runner)

    result = controller.close_popup(policy="home")

    assert result.success is True
    assert result.status == "ready"
    assert any("KEYCODE_HOME" in command for command in runner.calls)
