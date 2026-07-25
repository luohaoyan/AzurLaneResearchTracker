#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      筛选状态识别测试 (test_filter_state_detector.py)        ║
║                                                              ║
║  【测试目标】验证筛选面板、稀有度选中态、空列表和脚本分流。  ║
║  【类比理解】像用彩色假按钮检查筛选状态尺有没有量准。        ║
║  【数据流说明】合成截图/exp → FilterStateDetector/lab script。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
import csv
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from core.recognition.filter_state_detector import FilterStateDetector


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "fragment_filter_scan" / "run_filter_state_detection.py"


def _load_lab_module() -> Any:
    """按文件路径加载 lab 脚本，避免要求 ocr_training_lab 变成正式包。"""
    spec = importlib.util.spec_from_file_location("run_filter_state_detection", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _blank() -> np.ndarray:
    """构造 1280x720 深色截图。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:, :] = (35, 38, 48)
    return image


def _fill_named(image: np.ndarray, label: str, color: tuple[int, int, int]) -> None:
    """按检测器命名 ROI 给合成图涂色。"""
    x, y, width, height = FilterStateDetector.ELEMENT_ROIS[label]
    image[y:y + height, x:x + width] = color


def _fill_base(image: np.ndarray, roi: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    """按基础 ROI 给合成图涂色。"""
    x, y, width, height = roi
    image[y:y + height, x:x + width] = color


def _paint_panel_open(image: np.ndarray) -> None:
    """画出筛选面板打开时的取消/确定按钮。"""
    _fill_named(image, "filter_cancel_button", (92, 100, 177))
    _fill_named(image, "filter_confirm_button", (186, 130, 85))


def _paint_design_tab(image: np.ndarray) -> None:
    """画出底部设计图标签选中态。"""
    _fill_named(image, "tab_design", (82, 134, 168))
    _fill_named(image, "tab_equipment", (142, 104, 88))
    _fill_named(image, "tab_material", (142, 104, 88))


def _option(result, group: str, name: str):
    """按 group/name 取一个筛选选项。"""
    return next(item for item in result.options if item.group == group and item.name == name)


def _open_ultra_rare_panel_image() -> np.ndarray:
    """构造一个打开筛选面板且选中 ultra_rare 的 1280x720 合成截图。"""
    image = _blank()
    _paint_design_tab(image)
    _paint_panel_open(image)
    _fill_named(image, "rarity_button", (142, 104, 88))
    for _name, _text, roi in FilterStateDetector.RARITY_OPTIONS:
        _fill_base(image, roi, (142, 104, 88))
    _fill_base(image, (955, 480, 140, 41), (82, 134, 168))
    _fill_base(image, (218, 148, 140, 41), (82, 134, 168))
    _fill_base(image, (218, 350, 140, 41), (82, 134, 168))
    return image


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_missing_cv2_or_numpy_returns_unavailable() -> None:
    """cv2/NumPy 缺失时应返回 unavailable，而不是 import 崩溃。"""
    detector = FilterStateDetector(cv2_module=None, np_module=None)

    result = detector.detect(_blank())

    assert result.success is False
    assert result.status == "unavailable"
    assert "不可用" in result.message


def test_open_panel_detects_selected_ultra_rare_and_buttons() -> None:
    """筛选面板打开时，应通过金色按钮识别海上传奇选中态。"""
    image = _blank()
    _paint_design_tab(image)
    _paint_panel_open(image)
    _fill_named(image, "rarity_button", (142, 104, 88))
    for _name, _text, roi in FilterStateDetector.RARITY_OPTIONS:
        _fill_base(image, roi, (142, 104, 88))
    _fill_base(image, (955, 480, 140, 41), (82, 134, 168))
    _fill_base(image, (218, 148, 140, 41), (82, 134, 168))
    _fill_base(image, (218, 350, 140, 41), (82, 134, 168))

    result = FilterStateDetector().detect(image)

    assert result.success is True
    assert result.filter_panel_open is True
    assert result.current_rarity_filter == "ultra_rare"
    assert result.current_type_filter == "all"
    assert result.current_camp_filter == "all"
    assert _option(result, "rarity", "ultra_rare").selected is True
    assert _option(result, "rarity", "all").selected is False


def test_result_payload_contains_adb_click_coordinate_metadata() -> None:
    """结果 payload 应提供 ADB 可直接使用的中心点和归一化坐标。"""
    result = FilterStateDetector().detect(_open_ultra_rare_panel_image())
    payload = result.to_dict()

    assert payload["base_resolution"] == [1280, 720]
    assert payload["coordinate_system"]["space"] == "screen_pixels"
    assert payload["coordinate_system"]["adb_tap_rule"] == "adb shell input tap <center_x> <center_y>"

    ultra_rare = next(
        item
        for item in payload["options"]
        if item["group"] == "rarity" and item["name"] == "ultra_rare"
    )
    assert ultra_rare["center"] == [1025, 500]
    assert ultra_rare["base_center"] == [1025, 500]
    assert ultra_rare["normalized_center"][0] == pytest.approx(1025 / 1280, abs=1e-6)
    assert ultra_rare["normalized_center"][1] == pytest.approx(500 / 720, abs=1e-6)
    assert ultra_rare["clickable"] is True
    assert ultra_rare["click_action"] == "select_rarity:ultra_rare"

    confirm = next(item for item in payload["elements"] if item["label"] == "filter_confirm_button")
    assert confirm["center"] == [800, 596]
    assert confirm["click_action"] == "apply_filter_panel"


def test_closed_empty_list_with_active_filter_stays_unknown() -> None:
    """关闭态空列表可能是新玩家无图纸，不能误判成 common。"""
    image = _blank()
    _paint_design_tab(image)
    _fill_named(image, "filter_button", (82, 134, 168))

    result = FilterStateDetector().detect(image)

    assert result.success is True
    assert result.filter_panel_open is False
    assert result.filter_button_active is True
    assert result.current_rarity_filter == "unknown"
    assert result.rarity_inference_source == "empty_design_list_requires_open_panel"
    assert any("必须打开筛选面板" in warning for warning in result.warnings)


def test_closed_inactive_filter_defaults_to_all() -> None:
    """筛选按钮未激活时，关闭态可以视为 all。"""
    image = _blank()
    _paint_design_tab(image)
    _fill_named(image, "filter_button", (142, 104, 88))

    result = FilterStateDetector().detect(image)

    assert result.success is True
    assert result.filter_button_active is False
    assert result.current_rarity_filter == "all"
    assert result.rarity_inference_source == "inactive_filter_button"


def test_partial_screenshot_is_rejected() -> None:
    """模拟器传来半截图时，应拒绝识别，避免产生错误点击坐标。"""
    image = np.zeros((720, 640, 3), dtype=np.uint8)

    result = FilterStateDetector().detect(image)

    assert result.success is False
    assert result.status == "partial_image"
    assert result.options == ()


def test_non_viewport_aspect_ratio_is_rejected_for_click_safety() -> None:
    """明显不是完整 16:9 视口的截图应拒绝，避免后续 ADB 点击坐标漂移。"""
    image = np.zeros((1000, 1280, 3), dtype=np.uint8)

    result = FilterStateDetector().detect(image)

    assert result.success is False
    assert result.status == "partial_image"
    assert result.image_size == (1280, 1000)


def test_lab_parser_and_comparison_work_with_option_fields(tmp_path: Path) -> None:
    """训练脚本应能解析 option_x.visible/selected 并和结果对照。"""
    lab = _load_lab_module()
    exp_path = tmp_path / "filter_state_exp.txt"
    exp_path.write_text(
        "\n".join(
            [
                "[shot.png]",
                "filter_panel_open:true",
                "current_rarity_filter:ultra_rare",
                "current_sort:buildable",
                "selected_option:ultra_rare",
                "option_ultra_rare.visible:true",
                "option_ultra_rare.selected:true",
            ]
        ),
        encoding="utf-8",
    )
    annotations = lab.parse_filter_state_exp(exp_path)
    image = _blank()
    _paint_design_tab(image)
    _paint_panel_open(image)
    _fill_named(image, "rarity_button", (142, 104, 88))
    for _name, _text, roi in FilterStateDetector.RARITY_OPTIONS:
        _fill_base(image, roi, (142, 104, 88))
    _fill_base(image, (955, 480, 140, 41), (82, 134, 168))
    result = FilterStateDetector().detect(image)

    ok, mismatches = lab.compare_with_annotation(result, annotations["shot.png"])

    assert annotations["shot.png"]["filter_panel_open"] is True
    assert ok is True
    assert mismatches == ()


def test_lab_output_dir_separates_training_and_test(tmp_path: Path) -> None:
    """训练输出和 test_img/filter_state 输出默认分开，避免混淆样本。"""
    lab = _load_lab_module()

    assert lab.resolve_output_dir(tmp_path, False, None) == tmp_path / "filter_state_img_out"
    assert lab.resolve_output_dir(tmp_path, True, None) == tmp_path / "test_out" / "filter_state"
    assert lab.resolve_output_dir(tmp_path, True, tmp_path / "custom") == tmp_path / "custom"


def test_lab_writes_click_targets_csv(tmp_path: Path) -> None:
    """批处理脚本应额外输出 ADB 点击目标 CSV，供后续整合层读取。"""
    lab = _load_lab_module()
    result = FilterStateDetector().detect(_open_ultra_rare_panel_image())
    lab.write_results(
        tmp_path,
        [
            {
                "filename": "shot.png",
                "annotation_match": True,
                "annotation_mismatches": [],
                "result": result.to_dict(),
                "annotated_output": "",
            }
        ],
    )

    click_csv = tmp_path / "filter_state_click_targets.csv"
    rows = list(csv.DictReader(click_csv.open("r", encoding="utf-8-sig", newline="")))

    assert click_csv.exists()
    assert any(
        row["click_action"] == "select_rarity:ultra_rare"
        and row["center_x"] == "1025"
        and row["center_y"] == "500"
        and row["clickable"] == "True"
        for row in rows
    )
    assert any(row["click_action"] == "apply_filter_panel" for row in rows)
