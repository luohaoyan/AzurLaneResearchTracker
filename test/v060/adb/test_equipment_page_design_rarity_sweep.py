#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       🧪 设计图稀有度切换会话专项测试                         ║
║                                                              ║
║  【测试目标】验证白/蓝/紫/金/彩切换会话、断点和输出落盘。      ║
║  【类比理解】像在假台架上把五个稀有度按钮逐个按一遍。          ║
║  【数据流说明】fake controller → sweep session → manifest。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from core.automation.adb_controller import (
    AdbCommandResult,
    AdbConnectionResult,
    AdbDevice,
    AdbPathResolution,
    AdbScreenshotResult,
    PNG_SIGNATURE,
)
from core.automation.equipment_page import EquipmentPageAdbApi
from core.automation.equipment_page.equipment_page_constants import DESIGN_FILTER_POINTS
from core.contracts import RecognitionScene, ScreenshotArtifact
from core.recognition.filter_state_detector import FilterStateElement, FilterStateOption, FilterStateResult
from core.utils.path_manager import PathManager


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeDesignRarityController:
    """不触碰真实模拟器的设计图稀有度切换 fake 控制器。"""

    def __init__(self) -> None:
        self.screen_size = (1280, 720)
        self.connection_serial = "127.0.0.1:5555"
        self.tap_calls: list[dict[str, Any]] = []
        self.capture_calls: list[dict[str, Any]] = []
        self.capture_count = 0
        self.screenshot_bytes = (
            PNG_SIGNATURE + b"frame-a",
            PNG_SIGNATURE + b"frame-b",
            PNG_SIGNATURE + b"frame-b",
            PNG_SIGNATURE + b"frame-c",
            PNG_SIGNATURE + b"frame-d",
        )

    def find_adb(self) -> AdbPathResolution:
        """模拟已找到 ADB。"""
        return AdbPathResolution("C:/fake/adb.exe", "config")

    def check_connection(self, **kwargs: Any) -> AdbConnectionResult:
        """模拟设备已连接。"""
        device = AdbDevice(self.connection_serial, "device", "model:LDPlayer")
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
        """返回基础分辨率。"""
        return {"resolution": self.screen_size, "density": 240}

    def tap(self, x: int | float, y: int | float, **kwargs: Any) -> AdbCommandResult:
        """记录点击行为。"""
        self.tap_calls.append({"x": x, "y": y, **kwargs})
        return AdbCommandResult(True, "ok", "点击完成。", command=("tap", str(x), str(y)))

    def capture_screenshot(self, *args: Any, **kwargs: Any) -> AdbScreenshotResult:
        """按顺序写出假截图。"""
        output_dir = Path(kwargs.get("output_dir") or Path.cwd())
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"rarity_{self.capture_count:03d}.png"
        image_path.write_bytes(self.screenshot_bytes[min(self.capture_count, len(self.screenshot_bytes) - 1)])
        self.capture_calls.append({"output_dir": str(output_dir), "screen_state": kwargs.get("screen_state")})
        self.capture_count += 1
        screenshot_artifact = ScreenshotArtifact(str(image_path.resolve()), RecognitionScene.EQUIPMENT_LIST, self.connection_serial)
        return AdbScreenshotResult(
            True,
            "ready",
            "ADB 截图完成。",
            artifact=screenshot_artifact,
            method="exec-out",
            adb_path="C:/fake/adb.exe",
            adb_source="config",
            resolution=self.screen_size,
            timestamp="2026-07-25T12:00:00",
            screen_state=str(kwargs.get("screen_state") or "equipment_list"),
            scene_hint=str(kwargs.get("scene_hint") or "equipment_viewport"),
        )


class FakeFilterStateDetector:
    """按预设序列返回筛选状态，验证稀有度选择/恢复流程。"""

    def __init__(self, api: EquipmentPageAdbApi) -> None:
        self.api = api

    def detect(self, screenshot: str | Path, sort_templates: Any = None) -> FilterStateResult:
        rarity = str(getattr(self.api, "_last_rarity_filter", "unknown") or "unknown")
        options = []
        for name in ("all", "common", "rare", "elite", "super_rare", "ultra_rare"):
            options.append(
                FilterStateOption(
                    group="rarity",
                    name=name,
                    text=name,
                    bbox=(0, 0, 1, 1),
                    visible=True,
                    selected=name == rarity,
                    enabled=True,
                    confidence=0.99,
                    state="selected" if name == rarity else "unselected",
                    image_size=(1280, 720),
                    clickable=True,
                )
            )
        elements = (
            FilterStateElement("filter_panel", (0, 0, 1, 1), True, True, "open", 0.99, 0.99, "overlay"),
        )
        return FilterStateResult(
            True,
            "success",
            "筛选状态识别完成。",
            screenshot_path=str(Path(screenshot).resolve()),
            image_size=(1280, 720),
            base_resolution=(1280, 720),
            page="fragment",
            tab="design",
            filter_panel_open=True,
            filter_button_active=True,
            current_type_filter="unknown",
            current_camp_filter="unknown",
            current_rarity_filter=rarity,
            current_sort="buildable",
            rarity_inference_source="panel_selected_option",
            elements=elements,
            options=tuple(options),
            warnings=(),
        )

@pytest.fixture()
def rarity_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[EquipmentPageAdbApi, FakeDesignRarityController]:
    """构造装备页 API 与 fake 控制器。"""
    monkeypatch.setattr(PathManager, "get_work_dir", lambda: tmp_path / "workdir")
    monkeypatch.setattr("core.automation.equipment_page.equipment_page_adb_api.time.sleep", lambda *_args, **_kwargs: None)
    api = EquipmentPageAdbApi()
    api._last_rarity_filter = "buildable"
    api._last_equipment_type = "全部"
    api._last_equipped_state = "unknown"
    api._last_search_text = ""
    fake_controller = FakeDesignRarityController()
    api._controller_factory = lambda config: fake_controller
    api._filter_state_detector = FakeFilterStateDetector(api)
    return api, fake_controller


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_capture_design_rarity_sequence_writes_run_outputs(rarity_api: tuple[EquipmentPageAdbApi, FakeDesignRarityController]) -> None:
    """完整稀有度切换应产出 run 目录、manifest、actions 和 summary。"""
    api, fake_controller = rarity_api
    session = api.capture_design_rarity_sequence()

    assert session.success is True
    assert session.status in {"ready", "warning"}
    assert [frame.rarity_state for frame in session.frames] == ["common", "rare", "elite", "super_rare", "ultra_rare"]
    assert session.resume_cursor == 0
    assert session.next_resume_cursor == 5
    assert session.duplicate_frame_count >= 1
    assert len(fake_controller.tap_calls) == 20
    assert len(fake_controller.capture_calls) == 20

    run_dir = Path(session.run_dir)
    assert run_dir.is_dir()
    assert Path(session.frames_dir).is_dir()
    assert Path(session.manifest_path).is_file()
    assert Path(session.actions_log_path).is_file()
    assert Path(session.device_info_path).is_file()
    assert Path(session.summary_path).is_file()

    summary = json.loads(Path(session.summary_path).read_text(encoding="utf-8"))
    assert summary["frame_count"] == 5
    assert summary["next_resume_cursor"] == 5
    assert summary["duplicate_frame_count"] == session.duplicate_frame_count
    assert summary["real_capture_enabled"] is True
    assert summary["filter_state"] == "buildable"
    assert summary["sort_state"] == "buildable"
    assert summary["run_dir"] == str(run_dir)

    manifest = json.loads(Path(session.manifest_path).read_text(encoding="utf-8"))
    assert len(manifest["frames"]) == 5
    assert manifest["next_resume_cursor"] == 5
    assert manifest["run_dir"] == str(run_dir)

    actions = Path(session.actions_log_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(actions) == 5


def test_open_design_filter_panel_uses_design_button_coordinates(rarity_api: tuple[EquipmentPageAdbApi, FakeDesignRarityController]) -> None:
    """设计图筛选面板必须点击设计页自己的筛选按钮，而不是复用装备页坐标。"""
    api, fake_controller = rarity_api
    result = api.open_design_filter_panel()

    assert result.success is True
    assert fake_controller.tap_calls
    assert fake_controller.tap_calls[0]["x"] == DESIGN_FILTER_POINTS["filter_button"][0]
    assert fake_controller.tap_calls[0]["y"] == DESIGN_FILTER_POINTS["filter_button"][1]
    payload = result.payload or {}
    filter_state = payload.get("filter_state_result") or {}
    assert filter_state["filter_panel_open"] is True


def test_capture_design_rarity_sequence_supports_resume_cursor(rarity_api: tuple[EquipmentPageAdbApi, FakeDesignRarityController]) -> None:
    """resume_cursor 应该让会话从指定稀有度继续，并更新 next_resume_cursor。"""
    api, fake_controller = rarity_api
    session = api.capture_design_rarity_sequence(resume_cursor=2)

    assert session.success is True
    assert [frame.rarity_state for frame in session.frames] == ["elite", "super_rare", "ultra_rare"]
    assert session.resume_cursor == 2
    assert session.next_resume_cursor == 5
    assert len(fake_controller.tap_calls) == 12
    assert len(fake_controller.capture_calls) == 12

    loaded_cursor = api.load_design_rarity_resume_cursor(session.summary_path)
    assert loaded_cursor == 5


def test_capture_design_rarity_sequence_emits_concise_logs(
    rarity_api: tuple[EquipmentPageAdbApi, FakeDesignRarityController],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """设计图稀有度切换日志应保留阶段摘要，而不是直接倾倒 JSON。"""
    api, _ = rarity_api
    caplog.set_level(logging.INFO)

    session = api.capture_design_rarity_sequence()

    assert session.success is True
    messages = [record.message for record in caplog.records if "[设计图]" in record.message]
    assert any("设计图稀有度切换开始" in message for message in messages)
    assert any("设计图稀有度步骤开始" in message for message in messages)
    assert any("设计图稀有度切换结束" in message for message in messages)
    assert not any('"frames"' in message or '"payload"' in message for message in messages)
