#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 设计图碎片识别测试 (test_design_fragment_detection)  ║
║                                                              ║
║  【测试目标】验证设计图页卡片定位、标注解析和训练输出分流。  ║
║  【类比理解】像先校准尺子，再检查标注纸能否贴到正确卡片上。  ║
║  【数据流说明】synthetic image/exp → detector/lab parser。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.recognition import design_fragment_detector as detector_module
from core.recognition.design_fragment_detector import DesignFragmentCardCandidate, DesignFragmentDetector


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_cards" / "run_design_fragment_detection.py"


def _load_lab_module() -> Any:
    """按文件路径加载 lab 脚本模块，避免要求 ocr_training_lab 变成正式包。"""
    spec = importlib.util.spec_from_file_location("run_design_fragment_detection", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _candidate(index: int, y: int, visibility: str = "full") -> DesignFragmentCardCandidate:
    """构造卡片候选，供对齐逻辑测试。"""
    return DesignFragmentCardCandidate(
        index=index,
        row_index=(index + 1) // 2,
        column_index=1 if index % 2 else 2,
        bbox=(133 if index % 2 else 690, y, 541, 135),
        raw_bbox=(133 if index % 2 else 690, y, 541, 135),
        icon_roi=(140, y + 8, 127, 116),
        quantity_roi=(541, y + 25, 122, 51),
        visibility=visibility,
        confidence=0.9,
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_design_exp_parser_tolerates_known_annotation_typos(tmp_path: Path) -> None:
    """标注解析应兼容 source_corp、buildable:ture 和 visibility:cut。"""
    lab = _load_lab_module()
    exp_path = tmp_path / "design_exp.txt"
    exp_path.write_text(
        "\n".join(
            [
                "[design_1.png]",
                "image_mode:viewport_full",
                "source_corp:full_screen",
                "candidate_cards:8",
                "card01.equipment_id:S6-003",
                "card01.fragment_owned:65",
                "card01.fragment_required:50",
                "card01.buildable:ture",
                "card01.visibility:cut",
            ]
        ),
        encoding="utf-8",
    )

    annotations = lab.parse_design_exp(exp_path)

    annotation = annotations["design_1.png"]
    assert annotation.fields["source_crop"] == "full_screen"
    assert annotation.fields["candidate_cards"] == 8
    assert annotation.cards[0]["craftable"] is True
    assert annotation.cards[0]["visibility"] == "partial"


def test_output_dir_resolver_separates_training_and_test_outputs(tmp_path: Path) -> None:
    """默认输出应 img_input→img_out，test_img→test_out，避免训练和测试混淆。"""
    lab = _load_lab_module()

    assert lab.resolve_output_dir(tmp_path, False, None) == tmp_path / "img_out"
    assert lab.resolve_output_dir(tmp_path, True, None) == tmp_path / "test_out"
    assert lab.resolve_output_dir(tmp_path, True, tmp_path / "custom") == tmp_path / "custom"


def test_alignment_uses_note_skip_hint_when_detector_has_all_candidates() -> None:
    """当检测候选数等于 candidate_cards 时，应按备注跳过顶部/底部不可用行。"""
    lab = _load_lab_module()
    annotation = lab.DesignFragmentAnnotation(
        "design_5.png",
        {
            "candidate_cards": 10,
            "note": "顶部有2个装备遮挡, 碎片数量不可见, 不可使用; 底部有2个装备遮挡碎片数量不可见, 不可使用",
        },
        tuple({"card_no": index + 1, "visibility": "full"} for index in range(6)),
    )
    candidates = tuple(_candidate(index, y=index * 10) for index in range(1, 11))

    alignment = lab.align_candidates_to_annotation(candidates, annotation)

    assert alignment.method == "annotation_note_skip_hint"
    assert [candidate.index for candidate in alignment.selected] == [3, 4, 5, 6, 7, 8]


def test_alignment_falls_back_to_visibility_window_when_partial_candidates_are_missing() -> None:
    """当检测器已漏掉部分不可用半截行时，应用可见性窗口排除底部 partial。"""
    lab = _load_lab_module()
    annotation = lab.DesignFragmentAnnotation(
        "design_3.png",
        {"candidate_cards": 10, "note": "顶部有2个装备遮挡无法使用; 底部有2个装备遮挡无法使用"},
        tuple({"card_no": index + 1, "visibility": "full"} for index in range(6)),
    )
    candidates = tuple(_candidate(index, y=index * 10, visibility="partial_bottom" if index >= 7 else "full") for index in range(1, 9))

    alignment = lab.align_candidates_to_annotation(candidates, annotation)

    assert alignment.method == "best_visibility_window"
    assert [candidate.index for candidate in alignment.selected] == [1, 2, 3, 4, 5, 6]


def test_detector_missing_cv2_or_numpy_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenCV/NumPy 缺失时设计图检测应返回 unavailable，而不是 import 崩溃。"""
    monkeypatch.setattr(detector_module, "_cv2", None)
    monkeypatch.setattr(detector_module, "_np", None)
    detector = DesignFragmentDetector()

    result = detector.detect(np.zeros((10, 10, 3), dtype=np.uint8))

    assert result.success is False
    assert result.status == "unavailable"


def test_detector_finds_synthetic_1280_design_grid() -> None:
    """在合成 1280x720 双列卡片边框图上，应能找到主体卡片网格。"""
    cv2 = pytest.importorskip("cv2")
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    for y in (70, 223, 376, 529):
        for x in (133, 690):
            cv2.rectangle(image, (x, y), (x + 541, y + 135), (255, 255, 255), 2)

    result = DesignFragmentDetector().detect(image)

    assert result.success is True
    assert len(result.candidates) >= 8
    assert abs(result.candidates[0].bbox[1] - 70) <= 3
