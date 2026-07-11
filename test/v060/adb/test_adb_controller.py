#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 ADB 控制器测试                            ║
║                                                              ║
║  【测试目标】用 mock 覆盖路径、设备、截图、输入和导航逻辑。    ║
║  【类比理解】像在试车台上模拟线路，不依赖真实模拟器。          ║
║  【数据流说明】fake subprocess → AdbController → 结构化结果。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from core.automation import adb_controller as adb_controller_module
from core.automation.adb_controller import AdbController, PNG_SIGNATURE
from core.contracts import RecognitionScene, TaskCancelledError, TaskExecutionContext


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


def _completed(command: list[str], returncode: int = 0, stdout: Any = "", stderr: Any = "") -> subprocess.CompletedProcess[Any]:
    """创建 subprocess.CompletedProcess。"""
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def _controller(
    runner: FakeRunner | None = None,
    *,
    width: int = 1920,
    height: int = 1080,
    serial: str | None = "127.0.0.1:7555",
) -> AdbController:
    """创建不访问真实 PATH 的控制器。"""
    adb_config: dict[str, Any] = {
        "path": "C:/fake/adb.exe",
        "connect_timeout": 1,
        "base_resolution": {"width": 1920, "height": 1080},
    }
    if serial is not None:
        adb_config["serial"] = serial
    return AdbController(
        {"adb": adb_config, "screen": {"width": width, "height": height}},
        runner=runner,
        path_exists=lambda path: path == "C:/fake/adb.exe",
        which=lambda name: None,
        sleeper=lambda seconds: None,
    )


# ============================================================
# 🧪 第三部分：路径与设备测试
# ============================================================

def test_adb_path_priority_uses_valid_explicit_before_path() -> None:
    """有效显式配置应优先于 PATH。"""
    controller = AdbController(
        {"adb": {"path": "C:/explicit/adb.exe"}},
        path_exists=lambda path: path == "C:/explicit/adb.exe",
        which=lambda name: "C:/path/adb.exe",
    )

    resolution = controller.find_adb()

    assert resolution.adb_path is not None
    assert resolution.adb_path.replace("\\", "/") == "C:/explicit/adb.exe"
    assert resolution.source == "config"


def test_adb_path_falls_back_to_path_and_reports_missing() -> None:
    """显式路径不可用时应继续查 PATH，全部缺失时返回 missing。"""
    path_controller = AdbController(
        {"adb": {"path": "C:/missing/adb.exe"}},
        path_exists=lambda path: False,
        which=lambda name: "D:/tools/adb.exe",
    )
    missing_controller = AdbController(
        {"adb": {"path": "C:/missing/adb.exe", "common_paths": []}},
        path_exists=lambda path: False,
        which=lambda name: None,
    )

    assert path_controller.find_adb().source == "path"
    missing = missing_controller.find_adb()
    assert missing.adb_path is None
    assert missing.source == "missing"
    assert missing.warnings == ("显式 ADB 路径不可用: C:/missing/adb.exe",)


def test_parse_devices_distinguishes_states_and_multiple_devices() -> None:
    """devices 输出应保留 device/offline/unauthorized 状态，多设备不自动选择。"""
    output = """
List of devices attached
127.0.0.1:7555 device product:MuMu model:MuMu12
emulator-5554 offline transport_id:2
ABCDEF unauthorized usb:1-1
"""
    devices = AdbController.parse_devices(output)
    runner = FakeRunner(lambda command, kwargs: _completed(command, stdout=output))
    controller = _controller(runner, serial=None)

    connection = controller.check_connection(serial=None)

    assert [device.state for device in devices] == ["device", "offline", "unauthorized"]
    assert devices[0].properties["product"] == "MuMu"
    assert connection.success is False
    assert connection.status == "multiple_devices"
    assert [device.serial for device in connection.candidates] == ["127.0.0.1:7555", "emulator-5554", "ABCDEF"]


def test_check_connection_auto_selects_single_device_without_configured_serial() -> None:
    """未显式配置 serial 且只有单设备时，可以安全自动选择。"""
    output = "List of devices attached\nemulator-5554 device\n"
    runner = FakeRunner(lambda command, kwargs: _completed(command, stdout=output))

    result = _controller(runner, serial=None).check_connection()

    assert result.success is True
    assert result.status == "ready"
    assert result.selected_device is not None
    assert result.selected_device.serial == "emulator-5554"


@pytest.mark.parametrize(
    ("state", "expected_status"),
    [
        ("offline", "offline"),
        ("unauthorized", "unauthorized"),
    ],
)
def test_check_connection_reports_unusable_single_device(state: str, expected_status: str) -> None:
    """单设备 offline/unauthorized 应返回对应错误状态。"""
    output = f"List of devices attached\n127.0.0.1:7555 {state}\n"
    runner = FakeRunner(lambda command, kwargs: _completed(command, stdout=output))

    result = _controller(runner).check_connection()

    assert result.success is False
    assert result.status == expected_status


# ============================================================
# 🧪 第四部分：命令、截图与输入测试
# ============================================================

def test_run_adb_classifies_timeout_and_non_zero_exit() -> None:
    """subprocess 超时和非零退出码应转为结构化结果。"""
    def timeout_runner(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"", stderr=b"timeout")

    timeout = _controller(FakeRunner(timeout_runner)).run_adb(["devices", "-l"])
    unauthorized = _controller(
        FakeRunner(lambda command, kwargs: _completed(command, 1, stdout="", stderr="device unauthorized"))
    ).run_adb(["devices", "-l"])

    assert timeout.status == "timeout"
    assert timeout.timed_out is True
    assert unauthorized.status == "unauthorized"
    assert unauthorized.returncode == 1


def test_parse_wm_size_and_density_outputs() -> None:
    """wm size/density 输出应解析为基础 Python 类型。"""
    assert AdbController.parse_wm_size("Physical size: 1280x720\n") == (1280, 720)
    assert AdbController.parse_wm_size("Override size: 1920x1080") == (1920, 1080)
    assert AdbController.parse_wm_size("bad") is None
    assert AdbController.parse_wm_density("Physical density: 240\n") == 240


def test_capture_screenshot_uses_exec_out_and_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """exec-out 成功时应原子保存 PNG，并返回绝对路径。"""
    png_bytes = PNG_SIGNATURE + b"exec-out"
    devices_output = "List of devices attached\n127.0.0.1:7555 device\n"
    replacements: list[tuple[Path, Path]] = []
    original_replace = adb_controller_module.os.replace

    def spy_replace(src: str | Path, dst: str | Path) -> None:
        replacements.append((Path(src), Path(dst)))
        original_replace(src, dst)

    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, stdout=devices_output)
        if "exec-out" in command:
            return _completed(command, stdout=png_bytes)
        return _completed(command)

    monkeypatch.setattr(adb_controller_module.os, "replace", spy_replace)
    result = _controller(FakeRunner(handler)).capture_screenshot(RecognitionScene.HARBOR, output_dir=tmp_path)

    assert result.success is True
    assert result.method == "exec-out"
    assert result.artifact is not None
    assert Path(result.artifact.screenshot_path).is_absolute()
    assert Path(result.artifact.screenshot_path).read_bytes() == png_bytes
    assert replacements and replacements[0][1] == Path(result.artifact.screenshot_path)


def test_capture_screenshot_falls_back_to_pull(tmp_path: Path) -> None:
    """exec-out 失败时应执行 pull 回退并保存 PNG。"""
    png_bytes = PNG_SIGNATURE + b"pull"
    devices_output = "List of devices attached\n127.0.0.1:7555 device\n"

    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, stdout=devices_output)
        if "exec-out" in command:
            return _completed(command, 1, stderr="exec failed")
        if "screencap" in command:
            return _completed(command)
        if "pull" in command:
            Path(command[-1]).write_bytes(png_bytes)
            return _completed(command)
        return _completed(command)

    result = _controller(FakeRunner(handler)).capture_screenshot(RecognitionScene.RESEARCH, output_dir=tmp_path)

    assert result.success is True
    assert result.method == "pull"
    assert result.artifact is not None
    assert Path(result.artifact.screenshot_path).read_bytes() == png_bytes
    assert any("exec-out 截图失败" in warning for warning in result.warnings)


def test_capture_screenshot_retries_once_and_reports_failure(tmp_path: Path) -> None:
    """截图失败应重试一次并按配置尝试重连。"""
    devices_output = "List of devices attached\n127.0.0.1:7555 device\n"
    runner = FakeRunner(
        lambda command, kwargs: (
            _completed(command, stdout=devices_output)
            if "devices" in command
            else _completed(command, 1, stderr="broken")
        )
    )

    result = _controller(runner).capture_screenshot(RecognitionScene.HARBOR, output_dir=tmp_path)

    assert result.success is False
    assert result.status == "error"
    assert sum(1 for command in runner.calls if "exec-out" in command) == 2
    assert any(command[-2:] == ["connect", "127.0.0.1:7555"] for command in runner.calls)


def test_tap_and_swipe_scale_coordinates_and_validate_bounds() -> None:
    """tap/swipe 应按基准分辨率缩放坐标，并拒绝越界和非法 duration。"""
    runner = FakeRunner(lambda command, kwargs: _completed(command))
    controller = _controller(runner, width=1280, height=720)

    tap_result = controller.tap(960, 540)
    swipe_result = controller.swipe(0, 0, 960, 540, 500)
    out_of_bounds = controller.tap(2000, 100)
    bad_duration = controller.swipe(0, 0, 10, 10, -1)

    assert tap_result.success is True
    assert runner.calls[0][-2:] == ["640", "360"]
    assert swipe_result.success is True
    assert runner.calls[1][-5:] == ["0", "0", "640", "360", "500"]
    assert out_of_bounds.status == "invalid_coordinate"
    assert bad_duration.status == "invalid_duration"


def test_display_environment_accepts_1280x720_tablet() -> None:
    """1280x720 且 tablet 模式应符合 OCR 推荐环境。"""
    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, stdout="List of devices attached\nemulator-5554 device\n")
        if command[-2:] == ["wm", "size"]:
            return _completed(command, stdout="Physical size: 1280x720\n")
        if command[-2:] == ["wm", "density"]:
            return _completed(command, stdout="Physical density: 240\n")
        if command[-2:] == ["getprop", "ro.build.characteristics"]:
            return _completed(command, stdout="tablet\n")
        return _completed(command)

    controller = AdbController(
        {"type": "mumu", "adb": {"path": "C:/fake/adb.exe"}, "screen": {"width": 1280, "height": 720}},
        runner=FakeRunner(handler),
        path_exists=lambda path: True,
        which=lambda name: None,
        sleeper=lambda seconds: None,
    )

    result = controller.check_display_environment()

    assert result.success is True
    assert result.status == "ready"
    assert result.resolution == (1280, 720)
    assert result.characteristics == "tablet"


def test_display_environment_warns_for_mumu_resolution_and_mode() -> None:
    """MuMu 不是 1280x720 或非平板模式时应给出明确 warning。"""
    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        if "devices" in command:
            return _completed(command, stdout="List of devices attached\n127.0.0.1:7555 device\n")
        if command[-2:] == ["wm", "size"]:
            return _completed(command, stdout="Physical size: 1920x1080\n")
        if command[-2:] == ["wm", "density"]:
            return _completed(command, stdout="Physical density: 320\n")
        if command[-2:] == ["getprop", "ro.build.characteristics"]:
            return _completed(command, stdout="phone\n")
        return _completed(command)

    controller = AdbController(
        {"type": "mumu", "adb": {"path": "C:/fake/adb.exe"}, "screen": {"width": 1920, "height": 1080}},
        runner=FakeRunner(handler),
        path_exists=lambda path: True,
        which=lambda name: None,
        sleeper=lambda seconds: None,
    )

    result = controller.check_display_environment()

    assert result.success is False
    assert result.status == "warning"
    assert result.resolution == (1920, 1080)
    assert any("1280x720" in warning for warning in result.warnings)
    assert any("平板模式" in warning for warning in result.warnings)


def test_display_environment_suggests_enabling_adb_when_unavailable() -> None:
    """ADB 不可用时应提示用户开启 ADB/Android 调试开关。"""
    controller = AdbController(
        {"type": "leidian", "adb": {"path": "C:/missing/adb.exe"}},
        path_exists=lambda path: False,
        which=lambda name: None,
    )

    result = controller.check_display_environment()

    assert result.success is False
    assert result.status == "unavailable"
    assert any("开启 ADB" in suggestion for suggestion in result.suggestions)


# ============================================================
# 🧪 第五部分：导航和取消测试
# ============================================================

def test_run_sequence_uses_scene_probe_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """导航应通过 scene_probe 判断到达状态，并最多重试两次。"""
    probe_calls = 0
    runner = FakeRunner(lambda command, kwargs: _completed(command))
    controller = _controller(runner)
    monkeypatch.setattr(
        controller,
        "_load_sequence_config",
        lambda: {
            "defaults": {"step_delay": 0, "timeout_seconds": 0, "max_retries": 2},
            "base_resolution": {"width": 1920, "height": 1080},
            "sequences": {
                "go_harbor": {
                    "target_scene": "harbor",
                    "steps": [{"action": "tap", "x": 100, "y": 100}],
                }
            },
        },
    )

    def scene_probe(scene: RecognitionScene) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return probe_calls >= 2 and scene is RecognitionScene.HARBOR

    result = controller.run_sequence("go_harbor", scene_probe)

    assert result.success is True
    assert result.attempts == 2
    assert sum(1 for command in runner.calls if "tap" in command) == 2
    assert result.warnings == ("第 1 次导航未到达 harbor。",)


def test_task_context_cancellation_stops_following_navigation_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """取消令牌在安全点触发后，不应继续执行后续点击。"""
    context = TaskExecutionContext()

    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        context.cancellation_token.request_cancel()
        return _completed(command)

    runner = FakeRunner(handler)
    controller = _controller(runner)
    monkeypatch.setattr(
        controller,
        "_load_sequence_config",
        lambda: {
            "defaults": {"step_delay": 0, "timeout_seconds": 0, "max_retries": 0},
            "sequences": {
                "enter_equipment": {
                    "target_scene": "equipment_list",
                    "steps": [
                        {"action": "tap", "x": 100, "y": 100},
                        {"action": "tap", "x": 200, "y": 200},
                    ],
                }
            },
        },
    )

    with pytest.raises(TaskCancelledError):
        controller.run_sequence("enter_equipment", lambda scene: False, task_context=context)

    assert sum(1 for command in runner.calls if "tap" in command) == 1
