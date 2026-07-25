#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 collection_next 自标注规则测试                       ║
║                                                              ║
║  【测试目标】确保 Codex 自标注能减少重复人工标注。             ║
║  【类比理解】像检查“我替你做题”的规则不会把空白题硬填。        ║
║  【数据流说明】fake CSV row → decide_self_label → decision。   ║
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


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    PROJECT_ROOT
    / "ocr_training_lab"
    / "equipment_icon_matcher_v2"
    / "collection_next"
    / "auto_self_label_collection.py"
)


def _load_module() -> Any:
    """按文件路径加载 collection_next 自标注脚本。"""
    spec = importlib.util.spec_from_file_location("auto_self_label_collection_for_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_display_alias_can_self_label_candidate() -> None:
    """OCR 读到“海怒”且 top-N 有海怒时，应自动选择海怒而不是错误 top1。"""
    mod = _load_module()
    row = {
        "filename": "shot.png",
        "card_no": "4",
        "accepted_equipment_name": "",
        "suggested_equipment_name": "紫电改二#T0",
        "name_ocr_text": "海怒",
        "icon_status": "ambiguous",
        "icon_confidence": "0.78",
        "name_resolve_score": "0",
        "icon_top_candidates": "G0162:紫电改二#T0:0.785 | G0158:海怒#T0:0.776",
        "review_reason": "icon_ambiguous",
    }

    decision = mod.decide_self_label(row, {})

    assert decision.accepted_equipment_name == "海怒#T0"
    assert decision.decision == "display_alias_in_candidates"


def test_visual_reject_keeps_false_positive_out_of_training() -> None:
    """已肉眼确认的空白误检卡不应被强行写装备名。"""
    mod = _load_module()
    row = {
        "filename": "frag_ultra_rare_buildable_scroll_003.png",
        "card_no": "1",
        "accepted_equipment_name": "",
        "suggested_equipment_name": "五联装610mm鱼雷#T0",
        "icon_top_candidates": "G0016:五联装610mm鱼雷#T0:0.590",
    }

    decision = mod.decide_self_label(row, {})

    assert decision.accepted_equipment_name == ""
    assert decision.decision == "visual_reject_false_positive"


def test_distinct_icon_margin_self_labels_high_value_guard_case() -> None:
    """高价值卡被保守阈值拦住时，若 top1 与不同装备分差明显，可进入 Codex 自标注。"""
    mod = _load_module()
    row = {
        "filename": "v2_test_super_rare_scroll_002.png",
        "card_no": "1",
        "accepted_equipment_name": "",
        "suggested_equipment_name": "试作型三联装152mm主炮#T0",
        "name_ocr_text": "试作型三联装",
        "icon_status": "success",
        "icon_confidence": "0.8668",
        "name_resolve_score": "0",
        "icon_top_candidates": (
            "S1-001:试作型三联装152mm主炮#T0:0.8668 | "
            "S1-004:试作型三联装381mm主炮#T0:0.7960 | "
            "S1-005:试作型410mm三连装炮#T0:0.7940"
        ),
        "review_reason": "icon_confidence<0.90;high_value_confidence<0.90;high_value_weak_name",
    }

    decision = mod.decide_self_label(row, {})

    assert decision.accepted_equipment_name == "试作型三联装152mm主炮#T0"
    assert decision.decision == "distinct_icon_margin"


def test_disable_visual_overrides_prevents_old_filename_pollution() -> None:
    """新账号复用旧文件名时，不应触发旧的肉眼覆盖项。"""
    mod = _load_module()
    row = {
        "filename": "frag_super_rare_buildable_scroll_002.png",
        "card_no": "1",
        "accepted_equipment_name": "",
        "suggested_equipment_name": "新截图机器建议#T3",
        "name_resolve_equipment_name": "",
        "name_ocr_text": "",
        "icon_status": "success",
        "review_reason": "",
        "icon_confidence": "0.91",
        "name_resolve_score": "0",
        "icon_top_candidates": "G9999:新截图机器建议#T3:0.910 | G8888:其他候选#T3:0.700",
    }

    decision = mod.decide_self_label(row, {}, use_visual_overrides=False)

    assert decision.decision == "strong_icon"
    assert decision.accepted_equipment_name == "新截图机器建议#T3"


def test_current_workbench_self_label_command_ignores_filename_archive() -> None:
    """当前工作台面向新截图，应默认禁用旧视觉覆盖和历史同名继承。"""
    project_root = Path(__file__).resolve().parents[3]
    script_path = (
        project_root
        / "ocr_training_lab"
        / "equipment_icon_matcher_v2"
        / "current_test_workbench"
        / "run_current_test.py"
    )
    spec = importlib.util.spec_from_file_location("current_test_workbench_for_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    command = module.build_self_label_command(Path("out"), Path("review"))

    assert "--disable-visual-overrides" in command
    assert "--ignore-human-archive" in command
