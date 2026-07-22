#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             🧪 OCR API 测试 (test_ocr_task_api.py)           ║
║                                                              ║
║  【测试目标】验证预检兼容、友好错误、注入分析器和取消传播。    ║
║  【类比理解】像检查 GUI 入口门铃和真实识别通道是否各走各路。   ║
║  【数据流说明】OcrTaskApi → fake analyzer/契约结果 → payload。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Callable

import pytest

from core.contracts import (
    EquipmentRecognitionRecord,
    RecognitionResult,
    RecognitionScene,
    TaskCancelledError,
    TaskExecutionContext,
)
from core.recognition.harbor_resource_detector import HarborResourceResult
from core.recognition.ocr_engine import OcrReadResult
from core.recognition.ocr_task_api import OcrTaskApi


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeAnalyzer:
    """返回固定 RecognitionResult 的 fake analyzer。"""

    def __init__(self, result: RecognitionResult | None = None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc

    def analyze(self, screenshot_path: Path, scene: RecognitionScene, task_context=None) -> RecognitionResult:
        """模拟场景分析器。"""
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        return self.result


class FakeHarborResourceDetector:
    """模拟 HarborResourceDetector，避免测试加载真实 OCR 模型。"""

    def __init__(
        self,
        result: HarborResourceResult | None = None,
        exc: Exception | None = None,
        on_detect: Callable[[], object] | None = None,
    ) -> None:
        self.result = result
        self.exc = exc
        self.on_detect = on_detect
        self.calls: list[Path] = []

    def detect(self, screenshot_path: Path) -> HarborResourceResult:
        """记录调用并返回预置港区识别结果。"""
        self.calls.append(Path(screenshot_path))
        if self.on_detect is not None:
            self.on_detect()
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        return self.result


def _touch(tmp_path: Path) -> str:
    """创建截图占位文件。"""
    path = tmp_path / "shot.png"
    path.write_bytes(b"fake")
    return str(path)


def _ocr_field(text: str, value: int | None = None, confidence: float = 0.95) -> OcrReadResult:
    """构造单个字段的成功 OCR 结果。"""
    return OcrReadResult(True, "success", "ok", text=text, value=value, confidence=confidence)


def _harbor_result(
    success: bool = True,
    status: str = "success",
    message: str = "港区资源识别完成。",
) -> HarborResourceResult:
    """构造港区资源检测器结果，字段固定为正式资源契约。"""
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
    if success:
        return HarborResourceResult(
            True,
            status,
            message,
            "new",
            "指挥官",
            1234,
            567890,
            321,
            0.94,
            fields,
            rois,
        )
    return HarborResourceResult(
        False,
        status,
        message,
        "unknown",
        "",
        None,
        None,
        None,
        0.0,
        {},
        {},
        (message,),
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_api_preserves_reserved_contracts_without_screenshot() -> None:
    """无截图调用必须保持旧 reserved 预检契约。"""
    api = OcrTaskApi(use_singleton=False)

    equipment = api.scan_equipment_counts()
    resource = api.scan_resource_status()

    assert equipment.status == "reserved"
    assert equipment.payload is not None
    assert [field["name"] for field in equipment.payload["result_schema"]] == [
        "equipment_id",
        "equipment_count",
        "fragment_count",
        "confidence",
    ]
    assert equipment.payload["equipment_records"] == []
    assert resource.payload is not None
    assert resource.payload["resource_status"] is None


def test_api_reports_missing_screenshot_as_friendly_error(tmp_path: Path) -> None:
    """损坏路径或不存在截图路径应返回 error，不应进入未处理异常。"""
    api = OcrTaskApi(use_singleton=False)
    result = api.scan_resource_status(str(tmp_path / "missing.png"))

    assert result.success is False
    assert result.status == "error"
    assert "截图文件不存在" in result.message


def test_api_uses_harbor_detector_for_resource_status_and_serializes_contract_payload(tmp_path: Path) -> None:
    """港区资源正式入口应使用 HarborResourceDetector 并输出冻结资源字段。"""
    detector = FakeHarborResourceDetector(_harbor_result())
    api = OcrTaskApi(harbor_resource_detector=detector, use_singleton=False)
    screenshot_path = _touch(tmp_path)

    result = api.scan_resource_status(screenshot_path)

    assert result.success is True
    assert result.status == "success"
    assert detector.calls == [Path(screenshot_path)]
    assert result.payload is not None
    assert result.payload["ui_version"] == "new"
    record = result.payload["resource_status"]
    assert record == {
        "player_name": "指挥官",
        "oil": 1234,
        "coins": 567890,
        "gems": 321,
        "confidence": 0.94,
    }
    assert "owned_quantity" not in record
    assert "fragment_quantity" not in record
    assert [item["label"] for item in result.payload["detections"]] == ["oil", "coins", "gems"]


def test_api_maps_harbor_unavailable_to_unavailable_status(tmp_path: Path) -> None:
    """本地 OCR 模型或依赖不可用时，正式资源入口应返回 unavailable。"""
    detector = FakeHarborResourceDetector(_harbor_result(False, "unavailable", "PaddleOCR 不可用。"))
    api = OcrTaskApi(harbor_resource_detector=detector, use_singleton=False)

    result = api.scan_resource_status(_touch(tmp_path))

    assert result.success is False
    assert result.status == "unavailable"
    assert result.payload is not None
    assert result.payload["resource_status"] is None
    assert result.payload["real_ocr_enabled"] is False
    assert "PaddleOCR 不可用" in result.message


def test_api_uses_injected_analyzer_and_serializes_contract_payload(tmp_path: Path) -> None:
    """有截图路径时 API 应调用 analyzer 并透传冻结字段。"""
    recognition = RecognitionResult(
        True,
        RecognitionScene.EQUIPMENT_LIST,
        screenshot_path="placeholder",
        equipment_records=(EquipmentRecognitionRecord("S1-001", 2, 35, 0.91),),
        warnings=("待校准",),
    )
    api = OcrTaskApi(scene_analyzer=FakeAnalyzer(recognition), use_singleton=False)

    result = api.scan_equipment_counts(_touch(tmp_path))

    assert result.success is True
    assert result.status == "success"
    assert result.payload is not None
    record = result.payload["equipment_records"][0]
    assert record == {
        "equipment_id": "S1-001",
        "equipment_count": 2,
        "fragment_count": 35,
        "confidence": 0.91,
    }
    assert "owned_quantity" not in record
    assert result.warnings == ("待校准",)


def test_api_propagates_task_cancelled_error(tmp_path: Path) -> None:
    """TaskCancelledError 必须向上抛出，让任务管理器转换为 cancelled。"""
    api = OcrTaskApi(
        scene_analyzer=FakeAnalyzer(exc=TaskCancelledError("用户取消")),
        use_singleton=False,
    )

    with pytest.raises(TaskCancelledError):
        api.scan_resource_status(_touch(tmp_path), scene=RecognitionScene.RESEARCH)


def test_resource_scan_cancels_before_harbor_detector_call(tmp_path: Path) -> None:
    """任务已取消时不应继续调用港区资源检测器。"""
    context = TaskExecutionContext()
    context.cancellation_token.request_cancel()
    detector = FakeHarborResourceDetector(_harbor_result())
    api = OcrTaskApi(harbor_resource_detector=detector, use_singleton=False)

    with pytest.raises(TaskCancelledError):
        api.scan_resource_status(_touch(tmp_path), task_context=context)

    assert detector.calls == []


def test_resource_scan_cancels_after_harbor_detector_call(tmp_path: Path) -> None:
    """检测器返回后若收到取消请求，应停止后续 payload 转换。"""
    context = TaskExecutionContext()
    detector = FakeHarborResourceDetector(
        _harbor_result(),
        on_detect=context.cancellation_token.request_cancel,
    )
    api = OcrTaskApi(harbor_resource_detector=detector, use_singleton=False)
    screenshot_path = _touch(tmp_path)

    with pytest.raises(TaskCancelledError):
        api.scan_resource_status(screenshot_path, task_context=context)

    assert detector.calls == [Path(screenshot_path)]


def test_check_engine_never_loads_real_model_and_reports_dependencies() -> None:
    """引擎检查只做预检，不触发 PaddleOCR 模型加载。"""
    api = OcrTaskApi(use_singleton=False)
    result = api.check_engine()

    assert result.status == "reserved"
    assert result.payload is not None
    assert "paddleocr" in result.payload["dependencies"]
    assert "opencv_cv2" in result.payload["dependencies"]
