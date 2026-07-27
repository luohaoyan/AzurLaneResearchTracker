#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 研究页 ADB 分帧采集专项测试                        ║
║                                                              ║
║  【测试目标】覆盖分辨率校验、滚动采集、重试、取消与续跑。    ║
║  【类比理解】像把科研页采集整条轨道先空跑一遍。              ║
║  【数据流说明】fake ADB → research_page API → run files。   ║
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
from PIL import Image, ImageDraw

from core.automation.adb_controller import (
    AdbCommandResult,
    AdbConnectionResult,
    AdbDevice,
    AdbDisplayCheckResult,
    AdbPathResolution,
    AdbScreenshotResult,
    PNG_SIGNATURE,
)
from core.automation.research_page import ResearchPageAdbApi
from core.automation.research_page.research_page_constants import BASE_RESOLUTION
from core.contracts import RecognitionScene, ScreenshotArtifact, TaskCancelledError, TaskExecutionContext
from core.utils.path_manager import PathManager


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeResearchController:
    """用内存记录科研页 ADB 命令，不触碰真实模拟器。"""

    def __init__(
        self,
        *,
        screenshot_bytes: tuple[bytes, ...] | None = None,
        capture_failures: int = 0,
        swipe_failures: int = 0,
        display_resolution: tuple[int, int] = BASE_RESOLUTION,
        display_characteristics: str = "tablet",
        simulator_type: str = "leidian",
    ) -> None:
        """初始化 fake 控制器。"""
        self.screenshot_bytes = screenshot_bytes or (
            PNG_SIGNATURE + b"frame-a",
            PNG_SIGNATURE + b"frame-a",
            PNG_SIGNATURE + b"frame-b",
            PNG_SIGNATURE + b"frame-c",
        )
        self.capture_failures_remaining = int(capture_failures)
        self.swipe_failures_remaining = int(swipe_failures)
        self.display_resolution = display_resolution
        self.display_characteristics = display_characteristics
        self.simulator_type = simulator_type
        self.screen_size = BASE_RESOLUTION
        self.connection_serial = "127.0.0.1:7555"
        self.notifications: list[str] = []
        self.run_sequence_calls: list[str] = []
        self.capture_calls: list[dict[str, Any]] = []
        self.swipe_calls: list[dict[str, Any]] = []
        self.check_connection_calls = 0
        self.display_check_calls = 0
        self.cancel_after_first_capture = False

    def find_adb(self) -> AdbPathResolution:
        """模拟找到 ADB。"""
        return AdbPathResolution("C:/fake/adb.exe", "config")

    def check_connection(self, **kwargs: Any) -> AdbConnectionResult:
        """模拟 ready 设备。"""
        self.check_connection_calls += 1
        device = AdbDevice(self.connection_serial, "device", "model:Fake")
        return AdbConnectionResult(
            True,
            "ready",
            "ADB 设备连接正常。",
            selected_device=device,
            candidates=(device,),
            adb_path="C:/fake/adb.exe",
            adb_source="config",
        )

    def check_display_environment(self, **kwargs: Any) -> AdbDisplayCheckResult:
        """模拟显示环境检查。"""
        self.display_check_calls += 1
        warnings: tuple[str, ...] = ()
        suggestions: tuple[str, ...] = ()
        status = "ready"
        message = "模拟器显示环境符合 OCR 推荐设置。"
        if self.display_resolution != BASE_RESOLUTION:
            status = "warning"
            warnings = ("分辨率不符合 1280x720。",)
            suggestions = ("请将模拟器分辨率设置为 1280x720。",)
            message = "模拟器显示环境需要调整。"
        elif self.simulator_type == "mumu" and "tablet" not in self.display_characteristics.lower():
            status = "warning"
            warnings = ("MuMu 不是平板模式。",)
            suggestions = ("MuMu 模拟器请切换到平板模式，并保持 1280x720。",)
            message = "模拟器显示环境需要调整。"
        return AdbDisplayCheckResult(
            True,
            status,
            message,
            resolution=self.display_resolution,
            density=240,
            characteristics=self.display_characteristics,
            warnings=warnings,
            suggestions=suggestions,
        )

    def run_sequence(self, sequence_name: str, scene_probe: Callable[..., object], **kwargs: Any) -> object:
        """模拟配置化导航成功。"""
        self.run_sequence_calls.append(sequence_name)
        try:
            scene_probe(RecognitionScene.RESEARCH)
        except TypeError:
            scene_probe()
        return type(
            "NavResult",
            (),
            {
                "success": True,
                "status": "ready",
                "message": "导航成功。",
                "sequence_name": sequence_name,
                "target_scene": RecognitionScene.RESEARCH,
                "target_screen_state": "research_design_chart",
                "screen_state": "research_design_chart",
                "scene_hint": "research_design_chart",
                "screenshot_path": str((Path.cwd() / "nav.png").resolve()),
                "resolution": BASE_RESOLUTION,
                "timestamp": "2026-07-24T12:00:00",
                "confidence": 0.99,
                "attempts": 1,
                "warnings": (),
                "detail": "导航成功。",
                "to_dict": lambda self: {
                    "success": True,
                    "status": "ready",
                    "message": "导航成功。",
                    "sequence_name": sequence_name,
                    "target_scene": RecognitionScene.RESEARCH.value,
                    "target_screen_state": "research_design_chart",
                    "screen_state": "research_design_chart",
                    "scene_hint": "research_design_chart",
                    "screenshot_path": str((Path.cwd() / "nav.png").resolve()),
                    "resolution": list(BASE_RESOLUTION),
                    "timestamp": "2026-07-24T12:00:00",
                    "confidence": 0.99,
                    "attempts": 1,
                    "warnings": [],
                },
            },
        )()

    def capture_screenshot(self, scene: RecognitionScene, **kwargs: Any) -> AdbScreenshotResult:
        """模拟截图成功或失败。"""
        output_dir = Path(kwargs.get("output_dir") or Path.cwd())
        output_dir.mkdir(parents=True, exist_ok=True)
        capture_index = len(self.capture_calls)
        self.capture_calls.append(
            {
                "scene": scene.value,
                "output_dir": str(output_dir),
                "screen_state": kwargs.get("screen_state"),
                "scene_hint": kwargs.get("scene_hint"),
            }
        )
        if self.capture_failures_remaining > 0:
            self.capture_failures_remaining -= 1
            return AdbScreenshotResult(
                False,
                "timeout",
                "科研页截图失败。",
                adb_path="C:/fake/adb.exe",
                adb_source="config",
                resolution=BASE_RESOLUTION,
                timestamp="2026-07-24T12:00:00",
                screen_state=str(kwargs.get("screen_state") or scene.value),
                scene_hint=str(kwargs.get("scene_hint") or scene.value),
            )
        image_path = output_dir / f"research_{capture_index:03d}.png"
        image_path.write_bytes(self.screenshot_bytes[min(capture_index, len(self.screenshot_bytes) - 1)])
        if self.cancel_after_first_capture and capture_index == 0:
            task_context = kwargs.get("task_context")
            if task_context is not None:
                task_context.cancellation_token.request_cancel()
        artifact = ScreenshotArtifact(str(image_path.resolve()), scene, self.connection_serial)
        return AdbScreenshotResult(
            True,
            "ready",
            "科研页截图完成。",
            artifact=artifact,
            method="exec-out",
            adb_path="C:/fake/adb.exe",
            adb_source="config",
            resolution=BASE_RESOLUTION,
            timestamp="2026-07-24T12:00:00",
            screen_state=str(kwargs.get("screen_state") or scene.value),
            scene_hint=str(kwargs.get("scene_hint") or scene.value),
        )

    def swipe(self, start_x: int | float, start_y: int | float, end_x: int | float, end_y: int | float, duration_ms: int = 300, **kwargs: Any) -> AdbCommandResult:
        """记录滚动命令，并可模拟失败。"""
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
        if self.swipe_failures_remaining > 0:
            self.swipe_failures_remaining -= 1
            return AdbCommandResult(False, "timeout", "滑动失败。", command=("swipe", str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)))
        return AdbCommandResult(True, "ready", "滑动完成。", command=("swipe", str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)))

    def show_notification(self, message: str, **kwargs: Any) -> AdbCommandResult:
        """记录模拟器提示。"""
        self.notifications.append(message)
        return AdbCommandResult(True, "ready", "通知已显示。", command=("notification", message))


@pytest.fixture()
def research_page_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ResearchPageAdbApi, FakeResearchController]:
    """创建研究页 API 和 fake 控制器。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.research_page.research_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = ResearchPageAdbApi()
    api.configure_probes()
    fake_controller = FakeResearchController()
    api._controller_factory = lambda config: fake_controller
    return api, fake_controller


def _scene_probe(scene: object = None) -> bool:
    """乐观的页面探针。"""
    return True


def _state_probe(candidate: object = None) -> dict[str, object]:
    """返回稳定的科研页状态。"""
    return {
        "screen_state": "research_design_chart",
        "scene_hint": "research_design_chart",
        "confidence": 0.95,
    }


# ============================================================
# 🧪 第三部分：环境校验测试
# ============================================================

def test_check_connection_accepts_1280x720_and_records_display_environment(
    research_page_api: tuple[ResearchPageAdbApi, FakeResearchController],
) -> None:
    """1280x720 环境应判定为 ready。"""
    api, fake = research_page_api

    result = api.check_connection()

    assert result.success is True
    assert result.status == "ready"
    assert result.payload is not None
    assert result.payload["real_capture_enabled"] is True
    assert result.payload["display_environment"]["resolution"] == [1280, 720]
    assert fake.check_connection_calls >= 1
    assert fake.display_check_calls >= 1


def test_check_connection_rejects_wrong_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 1280x720 分辨率应直接返回不支持。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.research_page.research_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = ResearchPageAdbApi()
    fake = FakeResearchController(display_resolution=(1920, 1080))
    api._controller_factory = lambda config: fake

    result = api.check_connection()

    assert result.success is False
    assert result.status == "unsupported_resolution"
    assert "1280x720" in result.message
    assert result.payload is not None
    assert result.payload["real_capture_enabled"] is False


def test_check_connection_rejects_mumu_without_tablet_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MuMu 非平板模式应给出明确不支持提示。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.research_page.research_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = ResearchPageAdbApi()
    fake = FakeResearchController(display_characteristics="phone", simulator_type="mumu")
    api._controller_factory = lambda config: fake
    monkeypatch.setattr(
        api,
        "_get_simulator_context",
        lambda: {
            "key": "mumu",
            "name": "MuMu模拟器",
            "adb": {"path": "C:/fake/adb.exe", "port": 7555},
            "config": {"type": "mumu"},
            "device_serial": "127.0.0.1:7555",
            "default_device_serial": "127.0.0.1:7555",
        },
    )

    result = api.check_connection()

    assert result.success is False
    assert result.status == "unsupported_mode"
    assert "平板模式" in result.message


# ============================================================
# 🧪 第四部分：分帧采集、manifest、续跑与提示
# ============================================================

def test_capture_design_chart_sequence_writes_manifest_actions_device_info_and_summary(
    research_page_api: tuple[ResearchPageAdbApi, FakeResearchController],
) -> None:
    """连续采集应写出完整目录结构，并在重复帧时标记到底。"""
    api, fake = research_page_api
    fake.screenshot_bytes = (
        PNG_SIGNATURE + b"frame-a",
        PNG_SIGNATURE + b"frame-a",
        PNG_SIGNATURE + b"frame-a",
        PNG_SIGNATURE + b"frame-b",
    )

    session = api.capture_design_chart_sequence(
        frame_count=4,
        overlap_ratio=0.35,
        scene_probe=_scene_probe,
        state_probe=_state_probe,
    )

    assert session.success is True
    assert session.bottom_reached is True
    assert len(session.frames) == 3
    assert session.resume_cursor == 3
    assert session.scroll_step_px == 280
    assert Path(session.run_dir).is_dir()
    assert Path(session.frames_dir).is_dir()
    assert Path(session.manifest_path).exists()
    assert Path(session.actions_log_path).exists()
    assert Path(session.device_info_path).exists()
    assert Path(session.summary_path).exists()
    assert all(Path(frame.screenshot_path).is_absolute() for frame in session.frames)
    assert all(Path(frame.screenshot_path).exists() for frame in session.frames)
    assert fake.run_sequence_calls == ["enter_research"]
    assert len(fake.swipe_calls) == 2

    manifest = json.loads(Path(session.manifest_path).read_text(encoding="utf-8"))
    summary = json.loads(Path(session.summary_path).read_text(encoding="utf-8"))
    actions = [json.loads(line) for line in Path(session.actions_log_path).read_text(encoding="utf-8").splitlines()]

    assert manifest["page_name"] == "research_design_chart"
    assert manifest["frames"][0]["scroll_offset_px"] == 0
    assert manifest["frames"][1]["scroll_offset_px"] == 280
    assert manifest["next_resume_cursor"] == 3
    assert summary["frame_count"] == 3
    assert summary["duplicate_frame_count"] == 2
    assert summary["bottom_reached"] is True
    assert summary["next_resume_cursor"] == 3
    assert any(entry["action_name"] == "capture_viewport" for entry in actions)
    assert any(entry["action_name"] == "scroll_down" for entry in actions)


def test_capture_design_chart_sequence_supports_scroll_retry_resume_and_notifications(
    research_page_api: tuple[ResearchPageAdbApi, FakeResearchController],
) -> None:
    """滚动失败应重试，且支持 resume_cursor 和模拟器提示。"""
    api, fake = research_page_api
    fake.screenshot_bytes = (
        PNG_SIGNATURE + b"frame-a",
        PNG_SIGNATURE + b"frame-b",
        PNG_SIGNATURE + b"frame-c",
        PNG_SIGNATURE + b"frame-d",
    )
    fake.swipe_failures_remaining = 1

    session = api.capture_design_chart_sequence(
        frame_count=3,
        resume_cursor=5,
        scene_probe=_scene_probe,
        state_probe=_state_probe,
        notify_actions=True,
        device_message_mode="notification",
    )

    assert session.success is True
    assert session.resume_cursor == 8
    assert session.bottom_reached is False
    assert len(session.frames) == 3
    assert session.frames[0].scroll_index == 5
    assert session.frames[0].scroll_offset_px == 5 * session.scroll_step_px
    assert fake.swipe_calls  # 包含一次失败和一次重试
    assert fake.notifications
    assert any("采集中第 1/3 帧" in message for message in fake.notifications)
    assert api.load_resume_cursor(session.summary_path) == 8


def test_capture_design_chart_sequence_can_rewind_to_top_before_capturing(
    research_page_api: tuple[ResearchPageAdbApi, FakeResearchController],
) -> None:
    """开启 ensure_top 后应先回到顶部，再开始按逻辑游标采集。"""
    api, fake = research_page_api
    fake.screenshot_bytes = (
        PNG_SIGNATURE + b"middle-0",
        PNG_SIGNATURE + b"middle-1",
        PNG_SIGNATURE + b"top-0",
        PNG_SIGNATURE + b"top-0",
        PNG_SIGNATURE + b"frame-0",
        PNG_SIGNATURE + b"frame-1",
        PNG_SIGNATURE + b"frame-2",
    )

    session = api.capture_design_chart_sequence(
        frame_count=2,
        overlap_ratio=0.35,
        scroll_step_px=512,
        ensure_top=True,
        scene_probe=_scene_probe,
        state_probe=_state_probe,
    )

    assert session.success is True
    assert session.bottom_reached is False
    assert session.frames[0].scroll_index == 0
    assert session.frames[0].scroll_offset_px == 0
    assert len(fake.swipe_calls) >= 3
    assert fake.swipe_calls[0]["start_y"] == 170
    assert fake.swipe_calls[0]["end_y"] > fake.swipe_calls[0]["start_y"]
    assert Path(session.frames[0].screenshot_path).read_bytes() == PNG_SIGNATURE + b"frame-0"
    assert Path(session.frames[1].screenshot_path).read_bytes() == PNG_SIGNATURE + b"frame-1"


def test_capture_design_chart_sequence_honors_cancellation_before_second_scroll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取消请求后不应继续执行后续滚动。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.research_page.research_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = ResearchPageAdbApi()
    fake = FakeResearchController()
    fake.cancel_after_first_capture = True
    api._controller_factory = lambda config: fake
    context = TaskExecutionContext()

    with pytest.raises(TaskCancelledError):
        api.capture_design_chart_sequence(
            frame_count=3,
            task_context=context,
            scene_probe=_scene_probe,
            state_probe=_state_probe,
        )

    assert len(fake.capture_calls) >= 1
    assert fake.swipe_calls == []


def test_capture_design_chart_sequence_can_continue_until_bottom_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开启 until_bottom 后，帧数上限应放宽，直到检测到底部才停止。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.research_page.research_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = ResearchPageAdbApi()
    fake = FakeResearchController(
        screenshot_bytes=(
            PNG_SIGNATURE + b"frame-0",
            PNG_SIGNATURE + b"frame-1",
            PNG_SIGNATURE + b"frame-2",
            PNG_SIGNATURE + b"frame-3",
            PNG_SIGNATURE + b"frame-4",
        )
    )
    api._controller_factory = lambda config: fake

    session = api.capture_design_chart_sequence(
        frame_count=2,
        capture_until_bottom=True,
        scene_probe=_scene_probe,
        state_probe=_state_probe,
    )

    assert session.success is True
    assert len(session.frames) >= 2
    assert session.bottom_reached is True
    assert len(fake.capture_calls) >= 2


def test_analyze_scrollbar_state_reports_top_and_bottom(tmp_path: Path) -> None:
    """滚动条探针应能识别顶部与底部位置。"""
    top_path = tmp_path / "scroll_top.png"
    bottom_path = tmp_path / "scroll_bottom.png"

    for path, top_y in ((top_path, 70), (bottom_path, 540)):
        image = Image.new("RGB", BASE_RESOLUTION, (20, 20, 30))
        draw = ImageDraw.Draw(image)
        draw.rectangle((1258, top_y, 1264, top_y + 76), fill=(235, 185, 40))
        image.save(path)

    top_state = ResearchPageAdbApi._analyze_scrollbar_state(top_path)
    bottom_state = ResearchPageAdbApi._analyze_scrollbar_state(bottom_path)

    assert top_state["detected"] is True
    assert top_state["state"] == "top"
    assert bottom_state["detected"] is True
    assert bottom_state["state"] == "bottom"


def test_analyze_scrollbar_state_reports_single_page(tmp_path: Path) -> None:
    """滚动条占满轨道时应标记为 single_page，避免误判为 top 后反复滑动。"""
    single_path = tmp_path / "scroll_single_page.png"
    image = Image.new("RGB", BASE_RESOLUTION, (20, 20, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((1258, 65, 1264, 625), fill=(235, 185, 40))
    image.save(single_path)

    state = ResearchPageAdbApi._analyze_scrollbar_state(single_path)

    assert state["detected"] is True
    assert state["state"] == "single_page"


def test_capture_requires_two_post_scroll_checks_for_single_page_scrollbar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """滑块占满轨道时仍要完成两次拖动确认，避免截掉底部卡片。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.research_page.research_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    image = Image.new("RGB", BASE_RESOLUTION, (20, 20, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((1258, 65, 1264, 625), fill=(235, 185, 40))
    from io import BytesIO

    output = BytesIO()
    image.save(output, format="PNG")
    fake = FakeResearchController(screenshot_bytes=(output.getvalue(),))
    api = ResearchPageAdbApi()
    api._controller_factory = lambda config: fake

    session = api.capture_design_chart_sequence(
        frame_count=2,
        capture_until_bottom=True,
        prepare_page=False,
        ensure_top=False,
    )

    assert session.success is True
    assert session.bottom_reached is True
    assert len(session.frames) == 3
    assert len(fake.swipe_calls) == 2


def test_capture_requires_two_bottom_scrollbar_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单帧 bottom 颜色误检不能直接结束，必须连续两帧确认。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.research_page.research_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)

    def scrollbar_png(top_y: int) -> bytes:
        image = Image.new("RGB", BASE_RESOLUTION, (20, 20, 30))
        draw = ImageDraw.Draw(image)
        draw.rectangle((1258, top_y, 1264, top_y + 76), fill=(235, 185, 40))
        from io import BytesIO

        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    api = ResearchPageAdbApi()
    fake = FakeResearchController(
        screenshot_bytes=(
            scrollbar_png(70),   # top
            scrollbar_png(540),  # 第一次 bottom 候选
            scrollbar_png(540),  # 第二次 bottom，才允许结束
        )
    )
    api._controller_factory = lambda config: fake

    session = api.capture_design_chart_sequence(
        frame_count=1,
        capture_until_bottom=True,
        prepare_page=False,
        ensure_top=False,
    )

    assert session.success is True
    assert session.bottom_reached is True
    assert len(session.frames) == 3
    assert session.frames[1].bottom_reached is False
    assert session.frames[2].bottom_reached is True
    assert session.frames[1].scrollbar_state == "bottom"
    assert session.frames[2].scrollbar_state == "bottom"


def test_capture_current_screen_returns_absolute_path_and_resume_helper(
    research_page_api: tuple[ResearchPageAdbApi, FakeResearchController],
) -> None:
    """单帧截图也应返回绝对路径，并能从 summary 读取续跑游标。"""
    api, _fake = research_page_api

    artifact = api.capture_current_screen()

    assert artifact.success is True
    assert Path(artifact.screenshot_path).is_absolute()
    assert Path(artifact.screenshot_path).exists()
    assert artifact.session_id


def test_research_page_api_singleton_accessor_matches_class_instance() -> None:
    """全局 accessor 应返回同一个研究页 API 实例。"""
    assert ResearchPageAdbApi() is ResearchPageAdbApi()
