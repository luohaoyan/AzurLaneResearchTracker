#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 场景分析测试 (test_scene_analyzer.py)            ║
║                                                              ║
║  【测试目标】验证四场景 ROI、契约字段、异常路径和取消安全点。  ║
║  【类比理解】像给每个截图格子派发读数员，并检查能否随时停工。  ║
║  【数据流说明】fake engine/config → SceneAnalyzer → 契约结果。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pytest

from core.contracts import RecognitionScene, TaskCancelledError, TaskExecutionContext
from core.recognition.ocr_engine import OcrReadResult
from core.recognition.scene_analyzer import SceneAnalyzer


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeOcrEngine:
    """SceneAnalyzer 测试用的最小 OCR 引擎。"""

    confidence_threshold = 0.8

    def __init__(
        self,
        digit_results: Optional[list[OcrReadResult]] = None,
        text_results: Optional[list[OcrReadResult]] = None,
        on_digit_call: Optional[Callable[[], None]] = None,
        load_error: Optional[Exception] = None,
        image: Optional[np.ndarray] = None,
    ) -> None:
        self.image = image if image is not None else np.zeros((720, 1280, 3), dtype=np.uint8)
        self.digit_results = list(digit_results or [])
        self.text_results = list(text_results or [])
        self.on_digit_call = on_digit_call
        self.load_error = load_error
        self.digit_call_count = 0

    def load_image(self, screenshot_path: str | Path) -> np.ndarray:
        """返回合成截图或抛出指定读取错误。"""
        if self.load_error is not None:
            raise self.load_error
        return self.image

    def validate_roi(self, image: np.ndarray, roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """校验 ROI 是否在合成截图内。"""
        x, y, width, height = roi
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("ROI 坐标或尺寸非法")
        if x + width > image.shape[1] or y + height > image.shape[0]:
            raise ValueError("ROI 越界")
        return roi

    def crop_roi(self, image: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
        """裁剪 ROI，供按钮选中态颜色判断测试使用。"""
        x, y, width, height = self.validate_roi(image, roi)
        return image[y:y + height, x:x + width]

    def recognize_digits(self, *args, **kwargs) -> OcrReadResult:
        """按队列返回数字识别结果。"""
        self.digit_call_count += 1
        if self.on_digit_call is not None:
            self.on_digit_call()
        return self.digit_results.pop(0)

    def recognize_text(self, *args, **kwargs) -> OcrReadResult:
        """按队列返回文本识别结果。"""
        return self.text_results.pop(0)


def _ok_digit(value: int, confidence: float = 0.9) -> OcrReadResult:
    """构造成功数字 OCR 结果。"""
    return OcrReadResult(True, "success", "ok", text=str(value), value=value, confidence=confidence, roi=(0, 0, 10, 10))


def _ok_text(text: str, confidence: float = 0.9) -> OcrReadResult:
    """构造成功文本 OCR 结果。"""
    return OcrReadResult(True, "success", "ok", text=text, confidence=confidence, roi=(0, 0, 10, 10))


def _config_for(rois: list[dict]) -> dict:
    """构造最小 ROI 配置。"""
    return {
        "schema_version": "0.6.0",
        "base_resolution": {"width": 1280, "height": 720},
        "calibration": {"status": "pending", "message": "待校准"},
        "scenes": {scene.value: {"rois": []} for scene in RecognitionScene},
    } | {"scenes": {**{scene.value: {"rois": []} for scene in RecognitionScene}, "harbor": {"rois": rois}}}


def _touch(tmp_path: Path) -> Path:
    """创建临时截图占位文件。"""
    path = tmp_path / "shot.png"
    path.write_bytes(b"not a real image because fake engine loads it")
    return path


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_default_roi_config_selects_all_four_scenes() -> None:
    """默认 ROI 配置应覆盖四个冻结场景。"""
    analyzer = SceneAnalyzer(ocr_engine=FakeOcrEngine())

    for scene in RecognitionScene:
        config = analyzer.get_scene_config(scene)
        assert config["scene"] == scene.value
        assert isinstance(config["rois"], list)


def test_harbor_scene_builds_resource_record_and_pending_warning(tmp_path: Path) -> None:
    """港区场景应生成 ResourceRecognitionRecord 的冻结字段。"""
    rois = [
        {"name": "player_name", "kind": "resource", "field": "player_name", "mode": "text", "bbox": [0, 0, 100, 20]},
        {"name": "oil", "kind": "resource", "field": "oil", "mode": "digits", "bbox": [0, 20, 100, 20]},
        {"name": "coins", "kind": "resource", "field": "coins", "mode": "digits", "bbox": [0, 40, 100, 20]},
        {"name": "gems", "kind": "resource", "field": "gems", "mode": "digits", "bbox": [0, 60, 100, 20]},
    ]
    engine = FakeOcrEngine(
        digit_results=[_ok_digit(1200), _ok_digit(34000), _ok_digit(50)],
        text_results=[_ok_text("Commander")],
    )
    analyzer = SceneAnalyzer(ocr_engine=engine, config=_config_for(rois))

    result = analyzer.analyze(_touch(tmp_path), RecognitionScene.HARBOR)

    assert result.success is True
    assert result.resource_status is not None
    assert result.resource_status.to_dict() == {
        "player_name": "Commander",
        "oil": 1200,
        "coins": 34000,
        "gems": 50,
        "confidence": 0.9,
    }
    assert "待校准" in " ".join(result.warnings)


def test_static_position_roi_returns_clickable_ui_detection(tmp_path: Path) -> None:
    """仓库入口这类固定按钮 ROI 应直接返回可点击区块，不触发 OCR。"""
    config = _config_for([
        {
            "name": "warehouse_entry_button",
            "kind": "ui_element",
            "field": "warehouse_entry",
            "mode": "position",
            "bbox": [324, 646, 156, 62],
            "confidence": 0.95,
        }
    ])
    analyzer = SceneAnalyzer(ocr_engine=FakeOcrEngine(), config=config)

    result = analyzer.analyze(_touch(tmp_path), RecognitionScene.HARBOR)

    assert result.success is True
    assert result.detections[0].to_dict() == {
        "label": "warehouse_entry_button",
        "type": "ui_element",
        "value": 1,
        "confidence": 0.95,
        "roi": [324, 646, 156, 62],
    }


def test_state_roi_uses_warm_color_rule_for_selected_tab(tmp_path: Path) -> None:
    """仓库底部选项选中态可用 ROI 颜色倾向判断，选中时 value=1。"""
    config = {
        "schema_version": "0.6.0",
        "base_resolution": {"width": 1280, "height": 720},
        "calibration": {"status": "pending", "message": "待校准"},
        "scenes": {scene.value: {"rois": []} for scene in RecognitionScene},
    }
    config["scenes"]["equipment_list"] = {
        "rois": [
            {
                "name": "warehouse_tab_equipment",
                "kind": "ui_element",
                "mode": "state",
                "bbox": [0, 0, 40, 20],
                "selected": True,
                "confidence": 0.76,
                "state_rule": {"color": "warm", "threshold": 20, "channel_order": "bgr"},
            }
        ]
    }
    engine = FakeOcrEngine()
    engine.image[:20, :40, 0] = 20
    engine.image[:20, :40, 1] = 180
    engine.image[:20, :40, 2] = 220
    analyzer = SceneAnalyzer(ocr_engine=engine, config=config)

    result = analyzer.analyze(_touch(tmp_path), RecognitionScene.EQUIPMENT_LIST)

    assert result.success is True
    assert result.detections[0].label == "warehouse_tab_equipment"
    assert result.detections[0].value == 1
    assert result.detections[0].confidence >= 0.76


def test_equipment_scene_uses_frozen_record_field_names(tmp_path: Path) -> None:
    """装备场景记录不得回退到 owned_quantity/fragment_quantity。"""
    config = {
        "schema_version": "0.6.0",
        "base_resolution": {"width": 1280, "height": 720},
        "calibration": {"status": "pending", "message": "待校准"},
        "scenes": {
            scene.value: {"rois": []} for scene in RecognitionScene
        },
    }
    config["scenes"]["equipment_list"] = {
        "rois": [
            {"name": "count", "kind": "equipment_count", "equipment_id": "S1-001", "bbox": [0, 0, 100, 20]},
            {"name": "fragment", "kind": "fragment_count", "equipment_id": "S1-001", "bbox": [0, 20, 100, 20]},
        ]
    }
    analyzer = SceneAnalyzer(
        ocr_engine=FakeOcrEngine(digit_results=[_ok_digit(2), _ok_digit(35)]),
        config=config,
    )

    result = analyzer.analyze(_touch(tmp_path), RecognitionScene.EQUIPMENT_LIST)

    assert result.equipment_records[0].to_dict() == {
        "equipment_id": "S1-001",
        "equipment_count": 2,
        "fragment_count": 35,
        "confidence": 0.9,
    }
    assert "owned_quantity" not in result.equipment_records[0].to_dict()


def test_cancelled_context_stops_before_processing_next_roi(tmp_path: Path) -> None:
    """TaskExecutionContext 取消后不应继续处理下一块 ROI。"""
    context = TaskExecutionContext()
    config = _config_for([
        {"name": "oil", "kind": "resource", "field": "oil", "bbox": [0, 0, 100, 20]},
        {"name": "coins", "kind": "resource", "field": "coins", "bbox": [0, 20, 100, 20]},
    ])
    engine = FakeOcrEngine(
        digit_results=[_ok_digit(1), _ok_digit(2)],
        on_digit_call=context.cancellation_token.request_cancel,
    )
    analyzer = SceneAnalyzer(ocr_engine=engine, config=config)

    with pytest.raises(TaskCancelledError):
        analyzer.analyze(_touch(tmp_path), RecognitionScene.HARBOR, task_context=context)

    assert engine.digit_call_count == 1


def test_partial_screenshot_is_rejected_before_any_roi_processing(tmp_path: Path) -> None:
    """模拟器传回半截截图时应直接跳过，避免基于缺失信息输出脏识别结果。"""
    config = _config_for([
        {"name": "oil", "kind": "resource", "field": "oil", "bbox": [0, 0, 100, 20]},
    ])
    config["capture_validation"] = {
        "allow_partial_image": False,
        "min_width_ratio": 0.85,
        "min_height_ratio": 0.85,
        "max_aspect_delta": 0.12,
    }
    engine = FakeOcrEngine(
        digit_results=[_ok_digit(1)],
        image=np.zeros((720, 640, 3), dtype=np.uint8),
    )
    analyzer = SceneAnalyzer(ocr_engine=engine, config=config)

    result = analyzer.analyze(_touch(tmp_path), RecognitionScene.HARBOR)

    assert result.success is False
    assert engine.digit_call_count == 0
    assert "不完整" in result.message
    assert any("actual=640x720" in warning for warning in result.warnings)


def test_damaged_image_and_roi_out_of_bounds_are_friendly_failures(tmp_path: Path) -> None:
    """损坏截图和 ROI 越界应进入 warning/error，而不是未处理异常。"""
    damaged = SceneAnalyzer(
        ocr_engine=FakeOcrEngine(load_error=ValueError("bad image")),
        config=_config_for([]),
    ).analyze(_touch(tmp_path), RecognitionScene.HARBOR)

    out_of_bounds = SceneAnalyzer(
        ocr_engine=FakeOcrEngine(digit_results=[_ok_digit(1)]),
        config=_config_for([
            {"name": "oil", "kind": "resource", "field": "oil", "bbox": [1260, 700, 100, 100]},
        ]),
    ).analyze(_touch(tmp_path), RecognitionScene.HARBOR)

    assert damaged.success is False
    assert "损坏" in damaged.message
    assert out_of_bounds.success is False
    assert any("ROI 越界" in warning for warning in out_of_bounds.warnings)
