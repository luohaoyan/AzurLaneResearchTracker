#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 OCR 统一入口页面状态测试                         ║
║                                                              ║
║  【测试目标】验证 run_ocr_task 能消费 ADB 截图路径并返回场景。 ║
║  【类比理解】像检查前台接待是否先问“你在哪页”，再决定找谁办事。║
║  【数据流说明】截图路径 → fake 状态探针 → OCRResult/OcrTaskResult。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Callable

import pytest

from core.contracts import RecognitionScene, TaskCancelledError, TaskExecutionContext
from core.recognition.harbor_resource_detector import HarborResourceResult
from core.recognition.ocr_engine import OcrReadResult
from core.recognition.ocr_task_api import OcrTaskApi, run_ocr_task
from core.recognition.screen_state_detector import ScreenStateResult


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeScreenStateDetector:
    """模拟登录/加载/港区状态探针。"""

    def __init__(
        self,
        result: ScreenStateResult,
        on_detect: Callable[[], object] | None = None,
    ) -> None:
        self.result = result
        self.on_detect = on_detect
        self.calls: list[str] = []

    def detect(self, screenshot_path: str, task_context=None) -> ScreenStateResult:
        """记录截图路径并返回预置状态。"""
        self.calls.append(str(screenshot_path))
        if self.on_detect is not None:
            self.on_detect()
        return self.result


class FakeHarborResourceDetector:
    """模拟港区资源检测器，确认登录/加载不应触发资源 OCR。"""

    def __init__(self, result: HarborResourceResult) -> None:
        self.result = result
        self.calls: list[Path] = []

    def detect(self, screenshot_path: Path) -> HarborResourceResult:
        """记录调用并返回资源识别结果。"""
        self.calls.append(Path(screenshot_path))
        return self.result


def _touch(tmp_path: Path) -> str:
    """创建截图占位文件；fake 探针不读取图像内容。"""
    path = tmp_path / "shot.png"
    path.write_bytes(b"fake screenshot placeholder")
    return str(path)


def _state(
    screen_state: str,
    scene: RecognitionScene,
    confidence: float = 0.82,
    status: str = "success",
) -> ScreenStateResult:
    """构造页面状态结果。"""
    return ScreenStateResult(
        True,
        status,
        f"{screen_state} ok",
        screen_state,
        scene,
        confidence,
        screenshot_path="placeholder",
        detail=f"screen_state={screen_state}",
        suggested_action="建议由 ADB/Integration 层处理。" if screen_state != "harbor" else "",
    )


def _ocr_field(text: str, value: int | None = None, confidence: float = 0.95) -> OcrReadResult:
    """构造单字段 OCR 结果。"""
    return OcrReadResult(True, "success", "ok", text=text, value=value, confidence=confidence)


def _harbor_result() -> HarborResourceResult:
    """构造成功港区资源结果。"""
    fields = {
        "player_name": _ocr_field("指挥官", confidence=0.92),
        "oil": _ocr_field("1234", 1234, 0.93),
        "coins": _ocr_field("567890", 567890, 0.94),
        "gems": _ocr_field("321", 321, 0.95),
    }
    rois = {
        "player_name": (88, 15, 155, 38),
        "oil": (555, 16, 55, 42),
        "coins": (708, 16, 76, 42),
        "gems": (907, 16, 56, 42),
    }
    return HarborResourceResult(True, "success", "港区资源识别完成。", "new", "指挥官", 1234, 567890, 321, 0.94, fields, rois)


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_run_ocr_task_login_returns_unknown_and_skips_resource_ocr(tmp_path: Path) -> None:
    """登录页应返回 scene=unknown，不调用港区资源 OCR。"""
    state_detector = FakeScreenStateDetector(_state("login", RecognitionScene.UNKNOWN))
    resource_detector = FakeHarborResourceDetector(_harbor_result())
    api = OcrTaskApi(
        screen_state_detector=state_detector,  # type: ignore[arg-type]
        harbor_resource_detector=resource_detector,
        use_singleton=False,
    )

    result = api.run_ocr_task(_touch(tmp_path), "harbor")

    assert result.success is True
    assert result.status == "success"
    assert result.payload is not None
    assert result.payload["scene"] == "unknown"
    assert result.payload["screen_state"] == "login"
    assert resource_detector.calls == []


def test_run_ocr_task_harbor_invokes_resource_detector(tmp_path: Path) -> None:
    """港区状态确认后才进入资源 OCR，并把资源状态放入 payload。"""
    state_detector = FakeScreenStateDetector(_state("harbor", RecognitionScene.HARBOR, confidence=0.91))
    resource_detector = FakeHarborResourceDetector(_harbor_result())
    api = OcrTaskApi(
        screen_state_detector=state_detector,  # type: ignore[arg-type]
        harbor_resource_detector=resource_detector,
        use_singleton=False,
    )
    screenshot_path = _touch(tmp_path)

    result = api.run_ocr_task(screenshot_path, "harbor")

    assert result.success is True
    assert result.status == "success"
    assert result.payload is not None
    assert result.payload["scene"] == "harbor"
    assert result.payload["screen_state"] == "harbor"
    assert result.payload["resource_status"]["oil"] == 1234
    assert resource_detector.calls == [Path(screenshot_path)]


def test_module_run_ocr_task_invalid_path_returns_ocrresult(tmp_path: Path) -> None:
    """模块级 run_ocr_task 遇到无效路径应返回 OCRResult(success=False)，不抛异常。"""
    OcrTaskApi.reset_for_tests()

    result = run_ocr_task(tmp_path / "missing.png", "harbor")

    assert result.success is False
    assert result.status == "error"
    assert result.scene == "unknown"
    assert result.payload is not None
    assert result.payload["screen_state"] == "unknown"


def test_run_ocr_task_cancels_after_state_probe_before_resource_ocr(tmp_path: Path) -> None:
    """状态探针后收到取消请求时，不应继续进入资源 OCR。"""
    context = TaskExecutionContext()
    state_detector = FakeScreenStateDetector(
        _state("harbor", RecognitionScene.HARBOR),
        on_detect=context.cancellation_token.request_cancel,
    )
    resource_detector = FakeHarborResourceDetector(_harbor_result())
    api = OcrTaskApi(
        screen_state_detector=state_detector,  # type: ignore[arg-type]
        harbor_resource_detector=resource_detector,
        use_singleton=False,
    )

    with pytest.raises(TaskCancelledError):
        api.run_ocr_task(_touch(tmp_path), "harbor", task_context=context)

    assert resource_detector.calls == []
