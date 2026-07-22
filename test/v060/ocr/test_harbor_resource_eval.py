#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════╗
║        港区资源样本评估测试              ║
║   校验用户名视觉近似字符的宽松匹配规则    ║
║   数字资源仍保持严格匹配，避免误写统计值  ║
╚══════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path

from ocr_training_lab.harbor_resources.run_harbor_resource_detection import (
    resolve_output_dir,
    values_match_for_eval,
)


# ============================================================
# 🧪 第二部分：港区资源评估规则测试
# ============================================================


def test_player_name_allows_visual_equivalent_characters() -> None:
    """用户名评估允许 o/O/0 与 l/L/I/1 这类视觉近似字符互相等价。"""
    matched, match_mode = values_match_for_eval("name", "Loong0T", "LoongoT")

    assert matched is True
    assert match_mode == "visual_equivalent"


def test_resource_numbers_stay_strict() -> None:
    """资源数字关系到统计写入，不能套用用户名的宽松匹配规则。"""
    matched, match_mode = values_match_for_eval("oil", "1001", "lOOl")

    assert matched is False
    assert match_mode == "different"


def test_exact_match_is_reported_before_visual_equivalence() -> None:
    """完全一致的字段仍标记为 exact，便于评估 CSV 区分真实全等和视觉等价。"""
    matched, match_mode = values_match_for_eval("name", "Loong0T", "Loong0T")

    assert matched is True
    assert match_mode == "exact"


def test_test_images_use_separate_output_dir_by_default() -> None:
    """test_img 批测默认输出到 test_out，避免覆盖 img_input 的校准结果。"""
    lab_dir = Path("ocr_training_lab/harbor_resources")

    assert resolve_output_dir(lab_dir, False, None) == lab_dir / "img_out"
    assert resolve_output_dir(lab_dir, True, None) == lab_dir / "test_out"
    assert resolve_output_dir(lab_dir, True, Path("custom_out")) == Path("custom_out")
