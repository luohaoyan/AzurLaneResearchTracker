#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 v0.6.0 ADB 操作方法测试                          ║
║                                                              ║
║  【测试目标】覆盖点击、长按、文本、文件传输和应用控制方法。    ║
║  【类比理解】像把每个模拟器遥控按钮逐个按一遍。                ║
║  【数据流说明】操作方法 → fake ADB runner → 命令断言。         ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import subprocess
from pathlib import Path
from typing import Any, Callable

from core.automation.adb_controller import AdbController
from core.contracts import TaskCancelledError, TaskExecutionContext


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeRunner:
    """记录命令并返回成功。"""

    def __init__(
        self,
        handler: Callable[[list[str], dict[str, Any]], subprocess.CompletedProcess[Any]] | None = None,
    ) -> None:
        """初始化 fake runner。"""
        self.calls: list[list[str]] = []
        self.handler = handler

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        """模拟 subprocess.run。"""
        self.calls.append(command)
        if self.handler is not None:
            return self.handler(command, kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def _controller(runner: FakeRunner) -> AdbController:
    """创建固定 1280x720 的测试控制器。"""
    return AdbController(
        {
            "adb": {
                "path": "C:/fake/adb.exe",
                "serial": "emulator-5554",
                "base_resolution": {"width": 1280, "height": 720},
            },
            "screen": {"width": 1280, "height": 720},
        },
        runner=runner,
        path_exists=lambda path: True,
        which=lambda name: None,
        sleeper=lambda seconds: None,
    )


# ============================================================
# 🧪 第三部分：输入操作测试
# ============================================================

def test_long_press_uses_same_point_swipe() -> None:
    """长按应转换成同点位 swipe。"""
    runner = FakeRunner()

    result = _controller(runner).long_press(100, 200, 1200)

    assert result.success is True
    assert runner.calls[-1][-6:] == ["swipe", "100", "200", "100", "200", "1200"]


def test_double_tap_sends_two_tap_commands() -> None:
    """双击应发送两次 tap。"""
    runner = FakeRunner()

    result = _controller(runner).double_tap(300, 400)

    assert result.success is True
    tap_calls = [command for command in runner.calls if command[-3] == "tap"]
    assert len(tap_calls) == 2
    assert tap_calls[0][-2:] == ["300", "400"]


def test_drag_reuses_swipe_with_duration() -> None:
    """拖拽应使用 swipe 并保留较长 duration。"""
    runner = FakeRunner()

    result = _controller(runner).drag(10, 20, 300, 400, 1500)

    assert result.success is True
    assert runner.calls[-1][-6:] == ["swipe", "10", "20", "300", "400", "1500"]


def test_input_text_escapes_spaces_and_shell_sensitive_chars() -> None:
    """文本输入应转义空格和常见 shell 敏感字符。"""
    runner = FakeRunner()

    result = _controller(runner).input_text("Azur Lane & OCR")

    assert result.success is True
    assert runner.calls[-1][-2:] == ["text", "Azur%sLane%s\\&%sOCR"]


def test_key_shortcuts_send_expected_keyevents() -> None:
    """快捷按键方法应发送固定 keyevent。"""
    runner = FakeRunner()
    controller = _controller(runner)

    controller.press_back()
    controller.press_home()
    controller.press_menu()

    assert runner.calls[-3][-1] == "KEYCODE_BACK"
    assert runner.calls[-2][-1] == "KEYCODE_HOME"
    assert runner.calls[-1][-1] == "KEYCODE_MENU"


# ============================================================
# 🧪 第四部分：文件与应用操作测试
# ============================================================

def test_transfer_to_device_validates_local_file_and_pushes(tmp_path: Path) -> None:
    """push 前应检查本地文件存在。"""
    runner = FakeRunner()
    local_file = tmp_path / "shot.png"
    local_file.write_bytes(b"png")

    missing = _controller(runner).transfer_to_device(tmp_path / "missing.png", "/sdcard/missing.png")
    result = _controller(runner).transfer_to_device(local_file, "/sdcard/shot.png")

    assert missing.status == "invalid_path"
    assert result.success is True
    assert runner.calls[-1][-3:] == ["push", str(local_file), "/sdcard/shot.png"]


def test_transfer_from_device_creates_parent_and_pulls(tmp_path: Path) -> None:
    """pull 应创建本地父目录并执行 adb pull。"""
    runner = FakeRunner()
    target = tmp_path / "nested" / "shot.png"

    result = _controller(runner).transfer_from_device("/sdcard/shot.png", target)

    assert result.success is True
    assert target.parent.exists()
    assert runner.calls[-1][-3:] == ["pull", "/sdcard/shot.png", str(target)]


def test_remove_remote_file_uses_rm_force() -> None:
    """远端删除应使用 rm -f。"""
    runner = FakeRunner()

    result = _controller(runner).remove_remote_file("/sdcard/tmp.png")

    assert result.success is True
    assert runner.calls[-1][-4:] == ["shell", "rm", "-f", "/sdcard/tmp.png"]


def test_start_and_stop_app_commands() -> None:
    """应用启动/停止应发送 monkey/am force-stop 或 am start。"""
    runner = FakeRunner()
    controller = _controller(runner)

    monkey_result = controller.start_app("com.bilibili.azurlane")
    activity_result = controller.start_app("com.bilibili.azurlane", "com.unity3d.player.UnityPlayerActivity")
    stop_result = controller.stop_app("com.bilibili.azurlane")

    assert monkey_result.success is True
    assert runner.calls[-3][-6:] == ["monkey", "-p", "com.bilibili.azurlane", "-c", "android.intent.category.LAUNCHER", "1"]
    assert activity_result.success is True
    assert runner.calls[-2][-3:] == ["start", "-n", "com.bilibili.azurlane/com.unity3d.player.UnityPlayerActivity"]
    assert stop_result.success is True
    assert runner.calls[-1][-3:] == ["am", "force-stop", "com.bilibili.azurlane"]


def test_foreground_activity_and_screen_info_queries() -> None:
    """前台窗口和屏幕信息应使用 dumpsys/wm 查询。"""
    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        if command[-2:] == ["wm", "size"]:
            return subprocess.CompletedProcess(command, 0, stdout="Physical size: 1280x720", stderr="")
        if command[-2:] == ["wm", "density"]:
            return subprocess.CompletedProcess(command, 0, stdout="Physical density: 240", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    runner = FakeRunner(handler)
    controller = _controller(runner)

    foreground = controller.get_foreground_activity()
    screen_info = controller.get_screen_info()

    assert foreground.success is True
    assert runner.calls[0][-3:] == ["dumpsys", "window", "windows"]
    assert screen_info["resolution"] == (1280, 720)
    assert screen_info["density"] == 240


# ============================================================
# 🧪 第五部分：连续操作接口测试
# ============================================================

def test_run_operations_executes_ordered_steps_and_collects_payload() -> None:
    """连续操作应按顺序执行并记录每一步结果。"""
    runner = FakeRunner()
    controller = _controller(runner)

    result = controller.run_operations(
        [
            {"action": "notify", "title": "测试", "message": "准备点击", "expand": False},
            {"action": "tap", "x": 100, "y": 200},
            {"action": "wait", "seconds": 0},
            {"action": "swipe", "start_x": 100, "start_y": 600, "end_x": 1000, "end_y": 120, "duration_ms": 1200},
            {"action": "screen_info"},
        ],
        default_delay=0,
    )

    assert result.success is True
    assert result.status == "ready"
    assert [step.action for step in result.steps] == ["notify", "tap", "wait", "swipe", "screen_info"]
    notify_command = result.steps[0].payload["command"]["command"]
    assert "notification" in notify_command
    assert notify_command[-3:] == ["测试", "azurlane_adb_notice", "准备点击"]
    assert any(command[-3:] == ["tap", "100", "200"] for command in runner.calls)


def test_run_operations_stops_on_first_failure_by_default() -> None:
    """默认遇到失败应停止后续步骤。"""
    runner = FakeRunner()
    controller = _controller(runner)

    result = controller.run_operations(
        [
            {"action": "tap", "x": 9999, "y": 1},
            {"action": "tap", "x": 100, "y": 100},
        ]
    )

    assert result.success is False
    assert result.failure_index == 1
    assert len(result.steps) == 1
    assert result.steps[0].status == "invalid_coordinate"
    assert runner.calls == []


def test_run_operations_can_continue_after_failure() -> None:
    """continue_on_error=True 时失败后应继续执行后续步骤。"""
    runner = FakeRunner()
    controller = _controller(runner)

    result = controller.run_operations(
        [
            {"action": "tap", "x": 9999, "y": 1},
            {"action": "tap", "x": 100, "y": 100},
        ],
        continue_on_error=True,
    )

    assert result.success is False
    assert result.status == "warning"
    assert result.failure_index is None
    assert len(result.steps) == 2
    assert runner.calls[-1][-3:] == ["tap", "100", "100"]


def test_run_operations_respects_task_cancellation_between_steps() -> None:
    """连续操作应在步骤之间响应 TaskExecutionContext 取消。"""
    context = TaskExecutionContext()

    def handler(command: list[str], kwargs: dict[str, Any]) -> subprocess.CompletedProcess[Any]:
        context.cancellation_token.request_cancel()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runner = FakeRunner(handler)
    controller = _controller(runner)

    try:
        controller.run_operations(
            [
                {"action": "tap", "x": 100, "y": 100},
                {"action": "tap", "x": 200, "y": 200},
            ],
            task_context=context,
        )
    except TaskCancelledError:
        pass
    else:
        raise AssertionError("连续操作未响应取消。")

    assert len(runner.calls) == 1


def test_run_operations_rejects_unknown_action() -> None:
    """未知 action 应返回结构化失败。"""
    result = _controller(FakeRunner()).run_operations([{"action": "bad_action"}])

    assert result.success is False
    assert result.failure_index == 1
    assert result.steps[0].status == "error"
