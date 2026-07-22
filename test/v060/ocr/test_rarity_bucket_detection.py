#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      稀有度分桶预标注测试 (test_rarity_bucket_detection.py)  ║
║                                                              ║
║  【测试目标】验证分桶标注解析、卡片选择和测试输出目录分流。  ║
║  【类比理解】像先检查分桶篮子标签，再检查卡片有没有放错篮子。║
║  【数据流说明】exp/candidates → run_rarity_bucket_detection。 ║
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

from core.recognition.design_fragment_detector import DesignFragmentCardCandidate


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "fragment_filter_scan" / "run_rarity_bucket_detection.py"


def _load_lab_module() -> Any:
    """按文件路径加载 lab 脚本，避免要求 ocr_training_lab 变成正式包。"""
    spec = importlib.util.spec_from_file_location("run_rarity_bucket_detection", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _candidate(index: int) -> DesignFragmentCardCandidate:
    """构造一个排序稳定的卡片候选。"""
    row = (index - 1) // 2
    col = (index - 1) % 2
    x = 133 if col == 0 else 690
    y = 70 + row * 153
    return DesignFragmentCardCandidate(
        index=index,
        row_index=row + 1,
        column_index=col + 1,
        bbox=(x, y, 541, 135),
        raw_bbox=(x, y, 541, 135),
        icon_roi=(x + 15, y + 10, 110, 110),
        quantity_roi=(x + 400, y + 20, 120, 50),
        visibility="full",
        confidence=0.9,
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_exp_parser_normalizes_rarity_typo_and_values(tmp_path: Path) -> None:
    """标注解析应兼容 utral_rare、overview:on 和 unknown page_index。"""
    lab = _load_lab_module()
    exp_path = tmp_path / "rarity_bucket_exp.txt"
    exp_path.write_text(
        "\n".join(
            [
                "[design_ur_1.png]",
                "filter_rarity:utral_rare",
                "filter_rarity_id:5",
                "page_index:unknown",
                "candidate_cards:8",
                "usable_quantity_cards:8",
                "usable_icon_cards:6",
                "overview:on",
            ]
        ),
        encoding="utf-8",
    )

    annotations = lab.parse_rarity_bucket_exp(exp_path)
    fields = annotations["design_ur_1.png"].fields

    assert fields["filter_rarity"] == "ultra_rare"
    assert fields["filter_rarity_id"] == 5
    assert fields["page_index"] == "unknown"
    assert fields["overview"] is True


def test_candidate_selection_skips_bottom_blocked_icons() -> None:
    """底部两个装备被遮挡时，图标可用卡片应排除最后一行。"""
    lab = _load_lab_module()
    annotation = lab.RarityBucketAnnotation(
        "shot.png",
        {
            "candidate_cards": 8,
            "usable_quantity_cards": 8,
            "usable_icon_cards": 6,
            "note": "底部两个装备被遮挡, 数量可读",
        },
    )
    candidates = tuple(_candidate(index) for index in range(1, 11))

    selection = lab.select_candidates_for_annotation(candidates, annotation)

    assert [item.index for item in selection.selected] == list(range(1, 9))
    assert [item.index for item in selection.quantity_selected] == list(range(1, 9))
    assert [item.index for item in selection.icon_selected] == list(range(1, 7))


def test_candidate_selection_skips_top_blocked_icons() -> None:
    """顶部两个装备被遮挡时，图标可用卡片应从第三张开始。"""
    lab = _load_lab_module()
    annotation = lab.RarityBucketAnnotation(
        "shot.png",
        {
            "candidate_cards": 8,
            "usable_quantity_cards": 8,
            "usable_icon_cards": 6,
            "note": "顶部两个装备被遮挡, 数量可读",
        },
    )
    candidates = tuple(_candidate(index) for index in range(1, 11))

    selection = lab.select_candidates_for_annotation(candidates, annotation)

    assert [item.index for item in selection.selected] == list(range(1, 9))
    assert [item.index for item in selection.icon_selected] == list(range(3, 9))


def test_candidate_selection_respects_empty_annotation() -> None:
    """common 空列表标注应优先于几何候选，避免把背景误当卡片。"""
    lab = _load_lab_module()
    annotation = lab.RarityBucketAnnotation(
        "empty.png",
        {
            "candidate_cards": 0,
            "usable_quantity_cards": 0,
            "usable_icon_cards": 0,
        },
    )
    candidates = tuple(_candidate(index) for index in range(1, 5))

    selection = lab.select_candidates_for_annotation(candidates, annotation)

    assert selection.selected == ()
    assert selection.quantity_selected == ()
    assert selection.icon_selected == ()
    assert any("candidate_cards=0" in warning for warning in selection.warnings)


def test_card_accepted_fields_support_padded_card_number(tmp_path: Path) -> None:
    """逐卡人工确认字段应支持 card_04 前缀并转成结果表 accepted_* 字段。"""
    lab = _load_lab_module()
    exp_path = tmp_path / "rarity_bucket_exp.txt"
    exp_path.write_text(
        "\n".join(
            [
                "[design_rare_2.png]",
                "filter_rarity:rare",
                "card_04.accepted_equipment_id:G0645",
                "card_04.accepted_fragment_owned:8",
                "card_04.accepted_fragment_required:5",
            ]
        ),
        encoding="utf-8",
    )

    annotation = lab.parse_rarity_bucket_exp(exp_path)["design_rare_2.png"]
    accepted = lab._accepted_fields_for_card(annotation, 4)

    assert accepted["accepted_equipment_id"] == "G0645"
    assert accepted["accepted_fragment_owned"] == 8
    assert accepted["accepted_fragment_required"] == 5


def test_output_dir_separates_training_and_test(tmp_path: Path) -> None:
    """训练输出和 test_img/rarity_bucket 输出默认分开，避免测试混淆。"""
    lab = _load_lab_module()

    assert lab.resolve_output_dir(tmp_path, False, None) == tmp_path / "rarity_bucket_img_out"
    assert lab.resolve_output_dir(tmp_path, True, None) == tmp_path / "test_out" / "rarity_bucket"
    assert lab.resolve_output_dir(tmp_path, True, tmp_path / "custom") == tmp_path / "custom"
