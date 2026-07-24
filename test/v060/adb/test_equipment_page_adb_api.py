#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 装备页 ADB 自动化专项测试                          ║
║                                                              ║
║  【测试目标】用 mock 覆盖装备页准备、搜索、滑动和取消逻辑。   ║
║  【类比理解】像在模拟器假台架上检查每个按钮会不会按对。       ║
║  【数据流说明】fake controller → equipment_page API → 结果。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from core.automation.adb_controller import (
    AdbCommandResult,
    AdbConnectionResult,
    AdbDevice,
    AdbDisplayCheckResult,
    AdbPathResolution,
    AdbScreenshotResult,
    NavigationResult,
    PNG_SIGNATURE,
)
from core.automation.equipment_page import EquipmentPageAdbApi
from core.automation.equipment_page.equipment_page_constants import (
    BASE_RESOLUTION,
    EQUIPMENT_PAGE_POINTS,
    EQUIPMENT_TYPE_POINTS,
    RARITY_FILTER_POINTS,
)
from core.automation.equipment_page.equipment_page_adb_api import get_equipment_page_adb_api
from core.contracts import RecognitionScene, ScreenshotArtifact, TaskCancelledError, TaskExecutionContext
from core.utils.path_manager import PathManager


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class StateProbe:
    """按调用次数返回不同装备状态，方便测试 ensure_equipped_on。"""

    def __init__(self, states: tuple[str, ...]) -> None:
        """保存预设状态序列。"""
        self.states = states
        self.calls = 0

    def __call__(self, candidate: object = None) -> dict[str, object]:
        """返回当前状态。"""
        index = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return {
            "screen_state": "equipment_list",
            "scene_hint": "equipment_tab",
            "equipped_state": self.states[index],
            "confidence": 0.99,
        }


class FakeEquipmentController:
    """用内存记录所有装备页 ADB 命令，不触碰真实模拟器。"""

    def __init__(
        self,
        *,
        screenshot_bytes: tuple[bytes, ...] | None = None,
        clipboard_success: bool = True,
    ) -> None:
        """初始化 fake 控制器。"""
        self.screenshot_bytes = screenshot_bytes or (
            PNG_SIGNATURE + b"frame-a",
            PNG_SIGNATURE + b"frame-a",
            PNG_SIGNATURE + b"frame-b",
        )
        self.clipboard_success = clipboard_success
        self.screen_size = (1280, 720)
        self.connection_serial = "127.0.0.1:7555"
        self.tap_calls: list[dict[str, Any]] = []
        self.swipe_calls: list[dict[str, Any]] = []
        self.keyevent_calls: list[str] = []
        self.input_text_calls: list[str] = []
        self.run_adb_calls: list[list[str]] = []
        self.capture_calls: list[dict[str, Any]] = []
        self.run_sequence_calls: list[str] = []
        self.select_tab_calls: list[str] = []
        self.foreground_calls: list[dict[str, Any]] = []
        self.check_connection_calls = 0
        self.get_screen_info_calls = 0
        self.capture_count = 0
        self.cancel_after_first_capture = False
        self.package_name = "com.bilibili.azurlane"

    def find_adb(self) -> AdbPathResolution:
        """模拟找到 ADB。"""
        return AdbPathResolution("C:/fake/adb.exe", "config")

    def check_connection(self, **kwargs: Any) -> AdbConnectionResult:
        """模拟 ready 设备。"""
        self.check_connection_calls += 1
        device = AdbDevice(self.connection_serial, "device", "model:MuMu12")
        return AdbConnectionResult(
            True,
            "ready",
            "ADB 设备连接正常。",
            selected_device=device,
            candidates=(device,),
            adb_path="C:/fake/adb.exe",
            adb_source="config",
        )

    def get_screen_info(self, **kwargs: Any) -> dict[str, Any]:
        """返回 1280x720 和密度信息。"""
        self.get_screen_info_calls += 1
        return {"resolution": self.screen_size, "density": 240}

    def get_foreground_package(self, **kwargs: Any) -> AdbCommandResult:
        """模拟当前前台包名。"""
        self.foreground_calls.append(dict(kwargs))
        return AdbCommandResult(True, "ok", "已读取前台应用包名。", stdout=self.package_name)

    def run_sequence(self, sequence_name: str, scene_probe: Callable[..., object], **kwargs: Any) -> NavigationResult:
        """模拟配置化导航成功。"""
        self.run_sequence_calls.append(sequence_name)
        try:
            scene_probe(RecognitionScene.EQUIPMENT_LIST)
        except TypeError:
            scene_probe()
        return NavigationResult(
            True,
            "ready",
            "导航成功。",
            sequence_name,
            RecognitionScene.EQUIPMENT_LIST,
            target_screen_state="warehouse_design",
            screen_state="warehouse_design",
            scene_hint="equipment_tab",
            screenshot_path=str((Path.cwd() / "nav.png").resolve()),
            resolution=self.screen_size,
            attempts=1,
        )

    def select_warehouse_tab(self, tab: str, state_probe: Callable[..., object], **kwargs: Any) -> NavigationResult:
        """模拟仓库标签切换成功。"""
        self.select_tab_calls.append(tab)
        try:
            state_probe({"screen_state": f"warehouse_{tab}", "scene_hint": f"{tab}_tab"})
        except TypeError:
            state_probe()
        return NavigationResult(
            True,
            "ready",
            "仓库标签切换完成。",
            f"warehouse_{tab}",
            RecognitionScene.EQUIPMENT_LIST,
            target_screen_state=f"warehouse_{tab}",
            screen_state=f"warehouse_{tab}",
            scene_hint=f"{tab}_tab",
            screenshot_path=str((Path.cwd() / f"{tab}.png").resolve()),
            resolution=self.screen_size,
            attempts=1,
        )

    def _write_screenshot(self, output_dir: Path, index: int) -> Path:
        """写出假 PNG 文件。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"equipment_{index:03d}.png"
        image_path.write_bytes(self.screenshot_bytes[min(index, len(self.screenshot_bytes) - 1)])
        return image_path

    def capture_screenshot(self, scene: RecognitionScene, **kwargs: Any) -> AdbScreenshotResult:
        """模拟截图成功。"""
        output_dir = Path(kwargs.get("output_dir") or Path.cwd())
        image_path = self._write_screenshot(output_dir, self.capture_count)
        self.capture_calls.append(
            {
                "scene": scene.value,
                "output_dir": str(output_dir),
                "screen_state": kwargs.get("screen_state"),
                "scene_hint": kwargs.get("scene_hint"),
            }
        )
        self.capture_count += 1
        if self.cancel_after_first_capture:
            task_context = kwargs.get("task_context")
            if task_context is not None:
                task_context.cancellation_token.request_cancel()
        artifact = ScreenshotArtifact(str(image_path.resolve()), scene, self.connection_serial)
        return AdbScreenshotResult(
            True,
            "ready",
            "ADB 截图完成。",
            artifact=artifact,
            method="exec-out",
            adb_path="C:/fake/adb.exe",
            adb_source="config",
            resolution=self.screen_size,
            timestamp="2026-07-24T12:00:00",
            screen_state=str(kwargs.get("screen_state") or scene.value),
            scene_hint=str(kwargs.get("scene_hint") or scene.value),
        )

    def tap(self, x: int | float, y: int | float, **kwargs: Any) -> AdbCommandResult:
        """记录点击命令。"""
        self.tap_calls.append({"x": x, "y": y, **kwargs})
        return AdbCommandResult(True, "ok", "点击完成。", command=("tap", str(x), str(y)))

    def swipe(self, start_x: int | float, start_y: int | float, end_x: int | float, end_y: int | float, duration_ms: int = 300, **kwargs: Any) -> AdbCommandResult:
        """记录滑动命令。"""
        self.swipe_calls.append(
            {
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "duration_ms": duration_ms,
                **kwargs,
            }
        )
        return AdbCommandResult(True, "ok", "滑动完成。", command=("swipe", str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)))

    def keyevent(self, keycode: int | str, **kwargs: Any) -> AdbCommandResult:
        """记录按键命令。"""
        self.keyevent_calls.append(str(keycode))
        return AdbCommandResult(True, "ok", "按键完成。", command=("keyevent", str(keycode)))

    def input_text(self, text: str, **kwargs: Any) -> AdbCommandResult:
        """记录直接输入文本命令。"""
        self.input_text_calls.append(text)
        return AdbCommandResult(True, "ok", "输入文本完成。", command=("input_text", text))

    def run_adb(self, args: list[str], **kwargs: Any) -> AdbCommandResult:
        """记录底层 ADB 命令。"""
        self.run_adb_calls.append(list(args))
        if args[:5] == ["shell", "cmd", "clipboard", "set", "text"] and not self.clipboard_success:
            return AdbCommandResult(False, "error", "系统剪贴板写入失败。", stderr="clipboard unavailable", command=tuple(args))
        if "clipper.set" in args and not self.clipboard_success:
            return AdbCommandResult(False, "error", "Clipper 广播写入失败。", stderr="clipper unavailable", command=tuple(args))
        return AdbCommandResult(True, "ok", "命令执行完成。", stdout="ok", command=tuple(args))


@pytest.fixture()
def equipment_page_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[EquipmentPageAdbApi, FakeEquipmentController]:
    """创建装备页 API 和 fake 控制器。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.equipment_page.equipment_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = EquipmentPageAdbApi()
    api.configure_probes()
    api._last_rarity_filter = "all"
    api._last_equipment_type = "全部"
    api._last_equipped_state = "unknown"
    api._last_search_text = ""
    fake_controller = FakeEquipmentController()
    api._controller_factory = lambda config: fake_controller
    return api, fake_controller


# ============================================================
# 🧪 第三部分：基础原语与设备检查
# ============================================================

def test_equipment_page_primitive_commands_return_structured_payloads(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """tap/swipe/keyevent/wait/run_adb 应返回结构化结果和 payload。"""
    api, fake = equipment_page_api

    tap = api.tap(640, 360)
    swipe = api.swipe(640, 590, 640, 170, 650)
    keyevent = api.keyevent("KEYCODE_BACK")
    wait = api.wait(250)
    run_adb = api.run_adb(["shell", "wm", "size"])

    assert tap.success is True
    assert swipe.success is True
    assert keyevent.success is True
    assert wait.success is True
    assert run_adb.success is True
    assert fake.tap_calls[0]["x"] == 640
    assert fake.swipe_calls[0]["duration_ms"] == 650
    assert fake.keyevent_calls[0] == "KEYCODE_BACK"
    assert wait.payload is not None and wait.payload["duration_ms"] == 250
    assert run_adb.payload is not None and run_adb.payload["command"]["command"] == ["shell", "wm", "size"]


def test_get_device_info_reports_orientation_and_simulator_key(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """设备信息应包含方向、前台包名和模拟器 key。"""
    api, fake = equipment_page_api

    result = api.get_device_info()

    assert result.success is True
    assert result.payload is not None
    assert result.payload["current_simulator_key"] == "mumu"
    assert result.payload["orientation"] == "landscape"
    assert result.payload["foreground_package"] == "com.bilibili.azurlane"
    assert result.payload["resolution"] == [1280, 720]
    assert fake.check_connection_calls >= 1
    assert fake.get_screen_info_calls >= 1


def test_check_connection_returns_unavailable_when_adb_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """找不到 ADB 时应返回 unavailable，不向 GUI 抛异常。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.equipment_page.equipment_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = EquipmentPageAdbApi()

    class MissingAdbController(FakeEquipmentController):
        def find_adb(self) -> AdbPathResolution:
            return AdbPathResolution(None, "missing", ("PATH:adb",), ("未找到 adb",))

    api._controller_factory = lambda config: MissingAdbController()
    result = api.check_connection()

    assert result.success is False
    assert result.status == "unavailable"
    assert result.payload is not None
    assert result.payload["adb_ready"] is False
    assert result.payload["adb_path"] is None


# ============================================================
# 🧪 第四部分：装备页准备、筛选和搜索
# ============================================================

def test_ensure_equipped_on_uses_state_probe_and_leaves_evidence(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """装备中 ON 应优先读取探针，必要时执行点击并保留截图证据。"""
    api, fake = equipment_page_api
    probe = StateProbe(("off", "on"))

    result = api.ensure_equipped_on(state_probe=probe)

    assert result.success is True
    assert result.payload is not None
    assert result.payload["equipped_state"] == "on"
    assert Path(result.payload["screenshot_path"]).is_absolute()
    assert fake.tap_calls[0]["x"] == EQUIPMENT_PAGE_POINTS["equipped_on"][0]
    assert probe.calls >= 2


def test_ensure_equipment_page_ready_runs_navigation_and_filters(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """装备页准备流程应进入仓库、切页、开启装备中并应用筛选。"""
    api, fake = equipment_page_api
    probe = StateProbe(("off", "on"))

    result = api.ensure_equipment_page_ready(
        rarity="super_rare",
        equipment_type="战列炮",
        keep_on=True,
        scene_probe=lambda scene: True,
        state_probe=probe,
    )

    assert result.success is True
    assert result.payload is not None
    assert result.payload["rarity_filter"] == "super_rare"
    assert result.payload["equipment_type"] == "战列炮"
    assert result.payload["equipped_state"] == "on"
    assert fake.run_sequence_calls == ["enter_warehouse"]
    assert fake.select_tab_calls == ["equipment"]
    assert any(call["x"] == RARITY_FILTER_POINTS["super_rare"][0] for call in fake.tap_calls)
    assert any(call["x"] == EQUIPMENT_TYPE_POINTS["战列炮"][0] for call in fake.tap_calls)


def test_input_search_text_prefers_clipboard_and_clear_button(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """搜索中文装备名时应优先走剪贴板，并先清空旧文本。"""
    api, fake = equipment_page_api

    result = api.input_search_text("试作型三联装406mm主炮", clear_before_input=True, input_mode="clipboard")

    assert result.success is True
    assert result.payload is not None
    assert result.payload["search_text"] == "试作型三联装406mm主炮"
    assert any(
        call[:5] == ["shell", "cmd", "clipboard", "set", "text"] and call[-1] == "试作型三联装406mm主炮"
        for call in fake.run_adb_calls
    )
    assert "KEYCODE_PASTE" in fake.keyevent_calls
    assert fake.input_text_calls == []
    assert any(call["x"] == EQUIPMENT_PAGE_POINTS["search_clear"][0] for call in fake.tap_calls)
    assert any(call["x"] == EQUIPMENT_PAGE_POINTS["search_input"][0] for call in fake.tap_calls)


def test_confirm_search_and_capture_viewport_return_absolute_artifacts(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """确认搜索和单帧截图都应返回绝对路径证据。"""
    api, fake = equipment_page_api

    confirm = api.confirm_search()
    viewport = api.capture_viewport(session_id="alpha", frame_index=3)
    screenshot = api.screenshot(Path(PathManager.get_work_dir()) / "explicit_equipment.png")

    assert confirm.success is True
    assert viewport.success is True
    assert screenshot.success is True
    assert Path(viewport.screenshot_path).is_absolute()
    assert Path(screenshot.screenshot_path).is_absolute()
    assert any(call["x"] == EQUIPMENT_PAGE_POINTS["search_confirm"][0] for call in fake.tap_calls)
    assert viewport.sha1


def test_input_search_text_falls_back_to_input_text_when_clipboard_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """剪贴板不可用时应回退到 input_text，并保留 warning。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.equipment_page.equipment_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = EquipmentPageAdbApi()
    fake = FakeEquipmentController(clipboard_success=False)
    api._controller_factory = lambda config: fake

    result = api.input_search_text("彩云", clear_before_input=False, input_mode="auto")

    assert result.success is True
    assert result.warnings
    assert fake.input_text_calls == ["彩云"]
    assert any("clipboard" in " ".join(w.lower() for w in result.warnings) or "中文" in warning for warning in result.warnings)


def test_reset_filter_to_all_and_return_to_equipment_list(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """重置筛选和返回列表应发送预期按钮和按键。"""
    api, fake = equipment_page_api

    reset = api.reset_filter_to_all()
    back = api.return_to_equipment_list()

    assert reset.success is True
    assert back.success is True
    assert fake.keyevent_calls.count("KEYCODE_BACK") >= 2
    assert any(call["x"] == EQUIPMENT_PAGE_POINTS["filter_button"][0] for call in fake.tap_calls)
    assert any(call["x"] == EQUIPMENT_PAGE_POINTS["filter_reset"][0] for call in fake.tap_calls)


# ============================================================
# 🧪 第五部分：滑动采集、manifest 和取消
# ============================================================

def test_scroll_list_uses_expected_coordinates(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """单次滑动应按 1280x720 基准坐标执行。"""
    api, fake = equipment_page_api

    result = api.scroll_list("down", distance_px=300, duration_ms=700)

    assert result.success is True
    assert fake.swipe_calls[0]["start_x"] == 640
    assert fake.swipe_calls[0]["start_y"] == 590
    assert fake.swipe_calls[0]["end_y"] == 290
    assert fake.swipe_calls[0]["duration_ms"] == 700


def test_wait_for_stable_screen_reports_stable_after_repeated_sha1(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """连续相同帧应被视为画面稳定。"""
    api, _fake = equipment_page_api

    result = api.wait_for_stable_screen(stable_frames=2)

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    assert result.payload["stable_frames"] >= 2
    assert Path(result.payload["screenshot_path"]).is_absolute()


def test_capture_scroll_sequence_writes_manifests_and_detects_repeat(
    equipment_page_api: tuple[EquipmentPageAdbApi, FakeEquipmentController],
) -> None:
    """连续采集应写出 CSV/JSON manifest，并在重复帧时停止。"""
    api, fake = equipment_page_api

    session = api.capture_scroll_sequence(frame_count=4, overlap_hint=0.35, stop_on_repeat=True)

    assert session.success is True
    assert session.end_of_list_suspected is True
    assert len(session.frames) == 2
    assert fake.swipe_calls and len(fake.swipe_calls) == 1
    assert Path(session.manifest_path).exists()
    assert Path(session.json_manifest_path).exists()
    assert Path(session.scroll_session_path).exists()
    assert all(Path(frame.screenshot_path).is_absolute() for frame in session.frames)
    csv_lines = Path(session.manifest_path).read_text(encoding="utf-8-sig").splitlines()
    json_payload = json.loads(Path(session.json_manifest_path).read_text(encoding="utf-8"))
    scroll_payload = json.loads(Path(session.scroll_session_path).read_text(encoding="utf-8"))
    assert len(csv_lines) >= 3
    assert json_payload["session_id"] == session.session_id
    assert len(json_payload["artifacts"]) == 2
    assert scroll_payload["resume_cursor"] == 2


def test_capture_scroll_sequence_honors_cancellation_before_second_swipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务取消后不应继续执行后续滑动。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.equipment_page.equipment_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = EquipmentPageAdbApi()
    fake = FakeEquipmentController()
    fake.cancel_after_first_capture = True
    api._controller_factory = lambda config: fake
    context = TaskExecutionContext()

    with pytest.raises(TaskCancelledError):
        api.capture_scroll_sequence(frame_count=3, task_context=context)

    assert len(fake.capture_calls) >= 1
    assert fake.swipe_calls == []


def test_equipment_page_api_singleton_accessor_matches_class_instance() -> None:
    """全局 accessor 应返回同一个装备页 API 实例。"""
    assert get_equipment_page_adb_api() is EquipmentPageAdbApi()
