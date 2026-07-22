#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 Wiki 属性辅助训练集测试                              ║
║                                                              ║
║  【测试目标】确认人工 v2 标签能安全迁移成 Wiki 属性训练样本。  ║
║  【类比理解】检查“旧作业自动补属性答案”的流程不串题。          ║
║  【数据流说明】mock prelabel + human labels + wiki rows。      ║
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
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_attribute_scan" / "build_wiki_attribute_training_set.py"


def _load_lab_module() -> Any:
    """按文件路径加载实验脚本。"""
    spec = importlib.util.spec_from_file_location("wiki_attribute_training_set_for_test", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_select_training_samples_prefills_wiki_signature_and_skips_partial() -> None:
    """完整卡应写入 Wiki 属性；裁切卡默认跳过。"""
    lab = _load_lab_module()
    prelabel = [
        {
            "filename": "v2_elite_scroll_1.png",
            "screenshot_path": "source.png",
            "cards": [
                {
                    "filename": "v2_elite_scroll_1.png",
                    "card_no": 1,
                    "visibility": "full",
                    "filter_rarity": "elite",
                    "filter_rarity_id": 3,
                    "bbox": [100, 50, 540, 135],
                    "icon_roi": [115, 63, 108, 108],
                    "name_roi": [300, 55, 180, 30],
                    "quantity_roi": [500, 80, 120, 40],
                },
                {"filename": "v2_elite_scroll_1.png", "card_no": 2, "visibility": "partial_bottom"},
            ],
        }
    ]
    labels = {
        ("v2_elite_scroll_1.png", 1): lab.HumanLabel("v2_elite_scroll_1.png", 1, "基础声呐#T3"),
        ("v2_elite_scroll_1.png", 2): lab.HumanLabel("v2_elite_scroll_1.png", 2, "基础声呐#T3"),
    }
    signatures = {
        "基础声呐#T3": lab.WikiSignature(
            {
                "equipment_id": "G0477",
                "equipment_name": "基础声呐#T3",
                "wiki_slug": "基础声呐T3",
                "wiki_url": "https://example.invalid",
                "attribute_signature": "命中=4|反潜=5",
                "stat_1_label": "命中",
                "stat_1_initial": "4",
                "stat_2_label": "反潜",
                "stat_2_initial": "5",
            }
        )
    }

    samples, skipped = lab.select_training_samples(prelabel, labels, signatures)

    assert len(samples) == 1
    assert samples[0]["equipment_id"] == "G0477"
    assert samples[0]["attribute_signature"] == "命中=4|反潜=5"
    assert samples[0]["attribute_roi"] == "[237, 90, 255, 87]"
    assert skipped[0]["reason"] == "visibility_not_full"


def test_apply_manual_label_correction_repairs_known_typo() -> None:
    """明确人工笔误应在迁移训练集时修正，但不要求改源档案。"""
    lab = _load_lab_module()

    fixed = lab.apply_manual_label_correction("双联装128mmSKC41高平两用炮#T3sa")

    assert fixed == "双联装128mmSKC41高平两用炮#T3"


def test_load_wiki_signatures_many_keeps_primary_and_adds_extra(tmp_path: Path) -> None:
    """补充 Wiki 签名表应只填补主表没有的装备。"""
    lab = _load_lab_module()
    primary = tmp_path / "primary.csv"
    extra = tmp_path / "extra.csv"
    header = "equipment_id,equipment_name,parse_status,attribute_signature\n"
    primary.write_text(header + "G0477,基础声呐#T3,success,命中=4\n", encoding="utf-8-sig")
    extra.write_text(header + "G0310,双联装128mmSKC41高平两用炮#T3,success,伤害=5x4\n", encoding="utf-8-sig")

    signatures = lab.load_wiki_signatures_many([primary, extra])

    assert set(signatures) == {"基础声呐#T3", "双联装128mmSKC41高平两用炮#T3"}


def test_tokenize_attribute_signature_splits_label_and_value() -> None:
    """属性签名 token 应同时包含整段、字段名和值。"""
    lab = _load_lab_module()

    tokens = lab.tokenize_attribute_signature("伤害=17×4|标准射速=3.43s/轮|炮击=65")

    assert "伤害=17x4" in tokens
    assert "伤害" in tokens
    assert "17x4" in tokens
    assert "炮击" in tokens
    assert "65" in tokens


def test_build_attribute_model_counts_unique_equipment() -> None:
    """轻量模型应按装备去重并统计样本数量。"""
    lab = _load_lab_module()
    samples = [
        {"equipment_id": "G0477", "equipment_name": "基础声呐#T3", "filter_rarity_id": "3", "attribute_signature": "命中=4|反潜=5"},
        {"equipment_id": "G0477", "equipment_name": "基础声呐#T3", "filter_rarity_id": "3", "attribute_signature": "命中=4|反潜=5"},
        {"equipment_id": "S5-002", "equipment_name": "试作型四联装152mm主炮#T0", "filter_rarity_id": "5", "attribute_signature": "伤害=17x4|炮击=65"},
    ]

    model = lab.build_attribute_model(samples)

    assert model["document_count"] == 2
    assert model["sample_count"] == 3
    sonar = [item for item in model["equipment_index"] if item["equipment_name"] == "基础声呐#T3"][0]
    assert sonar["sample_count"] == 2
