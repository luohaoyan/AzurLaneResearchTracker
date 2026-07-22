#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 仓库标签识别测试 (test_warehouse_label_detector.py)  ║
║                                                              ║
║  【测试目标】验证仓库底部标签、筛选弹层、排序模板和半图拒绝。║
║  【类比理解】像用一组彩色假按钮检查识别尺有没有量准。        ║
║  【数据流说明】合成截图 → WarehouseLabelDetector → 结构化结果║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from core.recognition.warehouse_label_detector import WarehouseLabelDetector
from ocr_training_lab.warehouse_tabs.run_warehouse_label_detection import resolve_output_dir


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

def _blank_warehouse() -> np.ndarray:
    """构造 1280x720 的深色仓库背景。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:, :] = (35, 38, 48)
    return image


def _fill_roi(image: np.ndarray, label: str, color: tuple[int, int, int]) -> None:
    """按默认 ROI 给合成截图涂色。"""
    x, y, width, height = WarehouseLabelDetector.DEFAULT_ROIS[label]
    image[y:y + height, x:x + width] = color


def _paint_base_buttons(image: np.ndarray) -> None:
    """涂出未选中按钮和顶部按钮的蓝色底。"""
    blue = (142, 104, 88)
    for label in ("tab_design", "tab_equipment", "tab_material", "home_button", "filter_button", "sort_direction_button", "sort_mode_button"):
        _fill_roi(image, label, blue)


def _detection(result, label: str):
    """按 label 取单个检测项。"""
    return next(item for item in result.detections if item.label == label)


def _sort_pattern(kind: str) -> np.ndarray:
    """构造排序按钮模板图案，用不同白条代表不同文字。"""
    image = np.zeros((45, 146, 3), dtype=np.uint8)
    image[:, :] = (138, 98, 84)
    if kind == "quantity":
        image[8:37, 12:22] = (245, 245, 245)
        image[8:37, 34:44] = (245, 245, 245)
    else:
        image[8:37, 58:68] = (245, 245, 245)
        image[8:37, 82:92] = (245, 245, 245)
    return image


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_missing_cv2_or_numpy_returns_unavailable() -> None:
    """cv2/NumPy 缺失时应返回 unavailable，而不是 import 崩溃。"""
    detector = WarehouseLabelDetector(cv2_module=None, np_module=None)

    result = detector.detect(_blank_warehouse())

    assert result.success is False
    assert result.status == "unavailable"
    assert "不可用" in result.message


def test_detects_selected_equipment_tab_from_yellow_ratio() -> None:
    """装备标签为金黄色时，应识别为 equipment 页面。"""
    image = _blank_warehouse()
    _paint_base_buttons(image)
    _fill_roi(image, "tab_equipment", (82, 134, 168))

    result = WarehouseLabelDetector().detect(image)

    assert result.success is True
    assert result.page_type == "equipment"
    assert _detection(result, "tab_equipment").state == "selected"
    assert _detection(result, "tab_design").state == "unselected"


def test_filter_panel_blocks_top_buttons() -> None:
    """筛选弹层打开时，顶层房子和筛选按钮应标记为被遮挡。"""
    image = _blank_warehouse()
    _paint_base_buttons(image)
    _fill_roi(image, "tab_design", (82, 134, 168))
    _fill_roi(image, "filter_cancel_button", (92, 100, 177))
    _fill_roi(image, "filter_confirm_button", (186, 130, 85))

    result = WarehouseLabelDetector().detect(image)

    assert result.filter_panel_open is True
    assert _detection(result, "filter_panel").state == "open"
    assert _detection(result, "home_button").present is False
    assert _detection(result, "home_button").state == "blocked_by_filter_panel"


def test_partial_screenshot_is_rejected_before_detection() -> None:
    """模拟器传回半截截图时，应拒绝识别，避免产生脏点击坐标。"""
    image = np.zeros((720, 640, 3), dtype=np.uint8)

    result = WarehouseLabelDetector().detect(image)

    assert result.success is False
    assert result.status == "partial_image"
    assert result.detections == ()
    assert any("actual=640x720" in warning for warning in result.warnings)


def test_sort_mode_uses_template_bank_when_available() -> None:
    """排序按钮模板可区分 quantity/rarity 等状态。"""
    image = _blank_warehouse()
    _paint_base_buttons(image)
    _fill_roi(image, "tab_design", (82, 134, 168))
    x, y, width, height = WarehouseLabelDetector.DEFAULT_ROIS["sort_mode_button"]
    image[y:y + height, x:x + width] = _sort_pattern("quantity")
    templates = {
        "quantity": (_sort_pattern("quantity"),),
        "rarity": (_sort_pattern("rarity"),),
    }

    result = WarehouseLabelDetector(sort_template_threshold=0.8).detect(image, sort_templates=templates)

    assert result.success is True
    assert result.sort_mode == "quantity"
    assert _detection(result, "sort_mode_button").state == "quantity"


def test_lab_test_images_use_separate_output_dir_by_default() -> None:
    """test_img 批测默认输出到 test_out，避免覆盖 img_input 的校准结果。"""
    lab_dir = Path("ocr_training_lab/warehouse_tabs")

    assert resolve_output_dir(lab_dir, False, None) == lab_dir / "img_out"
    assert resolve_output_dir(lab_dir, True, None) == lab_dir / "test_out"
    assert resolve_output_dir(lab_dir, True, Path("custom_out")) == Path("custom_out")
