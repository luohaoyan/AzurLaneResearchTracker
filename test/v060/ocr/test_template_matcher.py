#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧪 模板匹配测试 (test_template_matcher.py)          ║
║                                                              ║
║  【测试目标】验证阈值、多尺度、尺寸校验和重复框抑制。          ║
║  【类比理解】像用可控的相关性热力图测试找按钮逻辑。            ║
║  【数据流说明】fake cv2 score map → TemplateMatcher → matches。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from typing import Any

import numpy as np
import pytest

from core.recognition import template_matcher as template_matcher_module
from core.recognition.template_matcher import TemplateMatcher


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeCv2:
    """只实现模板匹配测试需要的 cv2 最小接口。"""

    COLOR_BGR2GRAY = 6
    TM_CCOEFF_NORMED = 5

    def __init__(self, score_maps: list[np.ndarray]) -> None:
        self.score_maps = list(score_maps)
        self.resize_calls: list[tuple[int, int]] = []

    def matchTemplate(self, image: Any, template: Any, method: int) -> np.ndarray:
        """按调用顺序返回预设 score map。"""
        return self.score_maps.pop(0)

    def resize(self, template: np.ndarray, size: tuple[int, int]) -> np.ndarray:
        """返回指定尺寸的空模板，并记录多尺度调度。"""
        self.resize_calls.append(size)
        width, height = size
        return np.zeros((height, width), dtype=template.dtype)

    def cvtColor(self, image: np.ndarray, code: int) -> np.ndarray:
        """彩色转灰度的最小实现。"""
        return image.mean(axis=2).astype(image.dtype)


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_missing_cv2_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenCV 缺失时模板匹配应返回 unavailable。"""
    monkeypatch.setattr(template_matcher_module, "_cv2", None)
    matcher = TemplateMatcher(np_module=np)

    result = matcher.match_template(np.zeros((4, 4)), np.zeros((2, 2)))

    assert result.success is False
    assert result.status == "unavailable"


def test_threshold_multiscale_schedule_and_duplicate_suppression() -> None:
    """多尺度匹配应按阈值取候选，并用 IoU 抑制重复框。"""
    first_map = np.zeros((9, 9), dtype=float)
    first_map[1, 1] = 0.91
    first_map[1, 2] = 0.89
    first_map[6, 6] = 0.85
    second_map = np.zeros((7, 7), dtype=float)
    second_map[0, 0] = 0.95
    fake_cv2 = FakeCv2([first_map, second_map])
    matcher = TemplateMatcher(threshold=0.8, scales=(1.0, 2.0), iou_threshold=0.3, cv2_module=fake_cv2, np_module=np)

    result = matcher.match_template(
        np.zeros((10, 10), dtype=np.uint8),
        np.ones((2, 2), dtype=np.uint8),
        label="button",
    )

    assert result.status == "success"
    assert len(result.matches) == 3
    assert result.matches[0].confidence == pytest.approx(0.95)
    assert result.matches[0].box == (0, 0, 4, 4)
    assert fake_cv2.resize_calls == [(4, 4)]


def test_no_match_and_oversized_template_are_safe_results() -> None:
    """无匹配和模板尺寸超过图像时应安全返回空结果。"""
    fake_cv2 = FakeCv2([np.zeros((3, 3), dtype=float)])
    matcher = TemplateMatcher(threshold=0.8, cv2_module=fake_cv2, np_module=np)

    no_match = matcher.match_template(np.zeros((4, 4)), np.ones((2, 2)))
    oversized = matcher.match_template(np.zeros((4, 4)), np.ones((8, 8)))

    assert no_match.success is True
    assert no_match.status == "no_match"
    assert no_match.matches == ()
    assert oversized.status == "no_valid_scale"


def test_invalid_threshold_scales_and_empty_images_are_rejected() -> None:
    """阈值、尺度和空图输入应有明确错误。"""
    with pytest.raises(ValueError):
        TemplateMatcher(threshold=1.5)
    with pytest.raises(ValueError):
        TemplateMatcher(scales=(1.0, 0.0))

    matcher = TemplateMatcher(cv2_module=FakeCv2([]), np_module=np)
    result = matcher.match_template(np.zeros((0, 0)), np.ones((2, 2)))

    assert result.success is False
    assert result.status == "error"
