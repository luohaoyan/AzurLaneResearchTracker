#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        设计图数据集构建器测试                                ║
║                                                              ║
║  【一句话解释】验证历史标注不会被机器建议覆盖。                ║
║  【类比理解】先确认“人工答案纸”永远比“机器草稿”优先。          ║
║  【数据流说明】临时 exp/CSV → 标签解析/空目录构建。            ║
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
# 🏗️ 第二部分：测试工具
# ============================================================

def load_builder_module() -> Any:
    """用文件路径加载 lab 脚本，避免要求 active_workbench 必须是包。"""
    project_root = Path(__file__).resolve().parents[3]
    script_path = (
        project_root
        / "ocr_training_lab"
        / "equipment_icon_matcher_v2"
        / "active_workbench"
        / "scripts"
        / "build_design_fragment_dataset.py"
    )
    spec = importlib.util.spec_from_file_location("build_design_fragment_dataset", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# ✅ 第三部分：测试用例
# ============================================================

def test_parse_exp_label_file_keeps_user_accepted_name(tmp_path: Path) -> None:
    """解析 exp 时只读取 accepted_equipment_name，不读取注释里的机器建议。"""
    builder = load_builder_module()
    exp_path = tmp_path / "v2_review_todo_exp.txt"
    exp_path.write_text(
        "\n".join(
            [
                "[v2_rare_scroll_1.png]",
                "# card_03.suggested:G0001 错误装备#T3 status=success conf=0.999",
                "card_03.accepted_equipment_name:正确装备#T3",
                "card_03.current_resolved_equipment_id:G9999",
                "card_03.accepted_fragment_owned:12",
                "card_03.accepted_fragment_required:25",
            ]
        ),
        encoding="utf-8",
    )

    labels = builder.parse_exp_label_file(exp_path)

    label = labels[("v2_rare_scroll_1.png", 3)]
    assert label.equipment_name == "正确装备#T3"
    assert label.equipment_id == "G9999"
    assert label.fragment_owned == "12"
    assert label.fragment_required == "25"
    assert label.label_trusted is True


def test_choose_best_label_prefers_trusted_user_label() -> None:
    """同一卡片同时有人工标签和机器建议时，必须选择人工标签。"""
    builder = load_builder_module()
    trusted = {
        ("v2_rare_scroll_1.png", 1): builder.LabelRecord(
            equipment_name="人工确认装备#T3",
            equipment_id="G0001",
            label_source="reviewed_gallery",
            label_source_path="reviewed.csv",
            label_trusted=True,
            priority=100,
        )
    }
    machine = {
        ("v2_rare_scroll_1.png", 1): builder.MachineRecord(
            suggested_equipment_name="机器猜错装备#T3",
            suggested_equipment_id="G0002",
            icon_status="success",
            icon_confidence=0.99,
            icon_top_candidates="G0002:机器猜错装备#T3:0.990",
            name_ocr_text="",
            name_resolve_equipment_name="",
            name_resolve_score=0.0,
            ocr_fragment_count="",
            ocr_required_count="",
            ocr_confidence=0.0,
            csv_path="machine.csv",
            modified_time_ns=1,
        )
    }

    label = builder.choose_best_label("v2_rare_scroll_1.png", 1, trusted, machine, {}, {})

    assert label.equipment_name == "人工确认装备#T3"
    assert label.label_source == "reviewed_gallery"
    assert label.label_trusted is True


def test_build_dataset_empty_source_is_friendly(tmp_path: Path) -> None:
    """空输入目录不会崩溃，会写出空 manifest 和 warning。"""
    builder = load_builder_module()
    source_dir = tmp_path / "empty_img_input"
    dataset_dir = tmp_path / "dataset"
    source_dir.mkdir()

    summary = builder.build_dataset(
        source_dir=source_dir,
        dataset_dir=dataset_dir,
        reviewed_gallery_csv=tmp_path / "missing_reviewed.csv",
        accepted_gallery_csv=tmp_path / "missing_accepted.csv",
        equipment_library_csv=tmp_path / "missing_equipment.csv",
        clean_generated=True,
    )

    assert summary["source_images"] == 0
    assert summary["cards"] == 0
    assert summary["warnings"]
    assert (dataset_dir / "manifests" / "design_fragment_dataset_manifest.csv").exists()
