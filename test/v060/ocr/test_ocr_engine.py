#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             🧪 OCR 引擎测试 (test_ocr_engine.py)             ║
║                                                              ║
║  【测试目标】验证可选依赖、ROI、数字纠错和置信度过滤。         ║
║  【类比理解】像先试镜片和尺子，再拿真实截图上机。              ║
║  【数据流说明】合成图像/fake backend → OcrEngine → 结构化结果。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from typing import Any

import numpy as np
import pytest

from core.recognition.ocr_engine import OcrEngine, normalize_number_text


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeOcrBackend:
    """返回固定 OCR 结果的 fake backend。"""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.call_count = 0

    def ocr(self, image: Any, cls: bool = True) -> Any:
        """模拟 PaddleOCR classic .ocr()。"""
        self.call_count += 1
        return self.result


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_missing_optional_dependencies_return_unavailable_without_crash() -> None:
    """缺少 cv2/PaddleOCR 或本地模型时，识别应返回 unavailable 而不是导入崩溃。"""
    engine = OcrEngine()
    image = np.zeros((12, 12), dtype=np.uint8)

    status = engine.check_status()
    result = engine.recognize_digits(image)

    assert "opencv_cv2" in status["dependencies"]
    assert "paddleocr" in status["dependencies"]
    assert result.status == "unavailable"
    assert result.success is False


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("O, 12 A", 12),
        (" 1 234 ", 1234),
        ("９，８７６", 9876),
        ("abc", None),
        ("", None),
    ],
)
def test_digit_normalization_handles_common_ocr_noise(raw_text: str, expected: int | None) -> None:
    """数字规范化应处理 O→0、逗号、空格、全角数字和非数字字符。"""
    assert normalize_number_text(raw_text) == expected


def test_injected_backend_filters_low_confidence_and_empty_text() -> None:
    """注入 backend 时应按置信度过滤，并能处理空文本。"""
    backend = FakeOcrBackend([
        [[0, 0, 1, 1], ("O, 12A", 0.95)],
        [[0, 0, 1, 1], ("999", 0.50)],
    ])
    engine = OcrEngine(backend=backend, confidence_threshold=0.8)

    result = engine.recognize_digits(np.zeros((8, 8), dtype=np.uint8), preprocess=False)

    assert backend.call_count == 1
    assert result.success is True
    assert result.value == 12
    assert result.text == "12"
    assert result.confidence == pytest.approx(0.95)

    low_confidence = OcrEngine(
        backend=FakeOcrBackend([[[0, 0, 1, 1], ("123", 0.20)]]),
        confidence_threshold=0.8,
    ).recognize_digits(np.zeros((8, 8), dtype=np.uint8), preprocess=False)
    assert low_confidence.status == "low_confidence"

    empty = OcrEngine(backend=FakeOcrBackend([])).recognize_digits(
        np.zeros((8, 8), dtype=np.uint8),
        preprocess=False,
    )
    assert empty.status == "empty"


def test_digit_candidates_merge_adjacent_ocr_boxes_without_leading_zero_noise() -> None:
    """装备数量/碎片数量被 OCR 分成多段时，应按相邻框合并并去掉 O→0 噪声前导零。"""
    backend = FakeOcrBackend([
        [[[0, 0], [8, 0], [8, 12], [0, 12]], ("1", 0.93)],
        [[[9, 0], [17, 0], [17, 12], [9, 12]], ("2", 0.92)],
        [[[18, 0], [26, 0], [26, 12], [18, 12]], ("3", 0.91)],
        [[[70, 0], [78, 0], [78, 12], [70, 12]], ("O", 0.90)],
    ])
    engine = OcrEngine(backend=backend, confidence_threshold=0.8)

    result = engine.recognize_digits(np.zeros((16, 90), dtype=np.uint8), preprocess=False)

    assert result.success is True
    assert result.value == 123
    assert result.text == "123"
    assert result.confidence == pytest.approx(0.91)


def test_roi_validation_handles_black_white_empty_and_out_of_bounds_images() -> None:
    """黑图、白图、空图和 ROI 越界都不应产生未处理异常。"""
    engine = OcrEngine(backend=FakeOcrBackend([]))
    black = np.zeros((20, 30), dtype=np.uint8)
    white = np.full((20, 30), 255, dtype=np.uint8)

    assert engine.crop_roi(black, (0, 0, 10, 10)).shape == (10, 10)
    assert engine.crop_roi(white, (5, 5, 10, 10)).shape == (10, 10)

    with pytest.raises(ValueError, match="ROI 越界"):
        engine.validate_roi(black, (25, 0, 10, 10))

    with pytest.raises(ValueError):
        engine.validate_roi(np.zeros((0, 0), dtype=np.uint8), (0, 0, 1, 1))

    result = engine.recognize_digits(black, roi=(25, 0, 10, 10), preprocess=False)
    assert result.status == "error"
