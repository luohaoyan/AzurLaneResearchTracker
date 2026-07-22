#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""港区资源识别器单元测试。"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from core.recognition.harbor_resource_detector import HarborResourceDetector
from core.recognition.ocr_engine import OcrEngine


class QueueBackend:
    """按调用顺序返回用户名与三个数字。"""

    def __init__(self) -> None:
        self.values = iter(("测试Name", "1,524", "116262", "1484"))

    def ocr(self, _image, cls=True):
        """返回 PaddleOCR 2.x 兼容结构。"""
        value = next(self.values)
        return [[[[0, 0], [1, 0], [1, 1], [0, 1]], (value, 0.98)]]


def test_detect_new_ui_with_injected_backend() -> None:
    """新 UI 应输出冻结的四个资源字段。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[18:56, 1008:1263] = 255
    detector = HarborResourceDetector(OcrEngine(backend=QueueBackend()))
    result = detector.detect(image)
    assert result.success is True
    assert result.ui_version == "new"
    assert (result.player_name, result.oil, result.coins, result.gems) == ("测试Name", 1524, 116262, 1484)
    assert set(result.to_dict()) >= {"player_name", "oil", "coins", "gems", "confidence"}


def test_detect_old_ui_selection() -> None:
    """没有新 UI 白色功能栏时应选择旧版 ROI。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    detector = HarborResourceDetector(OcrEngine(backend=QueueBackend()))
    assert detector.detect(image).ui_version == "old"


def test_partial_and_empty_images_are_rejected() -> None:
    """半截图与空图不得进入 OCR。"""
    detector = HarborResourceDetector(OcrEngine(backend=QueueBackend()))
    assert detector.detect(np.zeros((360, 640, 3), dtype=np.uint8)).status == "partial_image"
    assert detector.detect(np.array([], dtype=np.uint8)).status == "error"


def test_missing_or_damaged_path_is_friendly(tmp_path: Path) -> None:
    """损坏路径和损坏文件返回 error，不抛出到调用方。"""
    detector = HarborResourceDetector(OcrEngine(backend=QueueBackend()))
    assert detector.detect(tmp_path / "missing.png").status == "error"
    damaged = tmp_path / "damaged.png"
    damaged.write_bytes(b"not an image")
    assert detector.detect(damaged).status == "error"


def test_missing_ocr_backend_returns_unavailable() -> None:
    """未配置 OCR 模型时模块仍可导入和运行。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    detector = HarborResourceDetector(OcrEngine(config={}))
    result = detector.detect(image, ui_version="new")
    assert result.success is False
    assert result.status == "unavailable"
