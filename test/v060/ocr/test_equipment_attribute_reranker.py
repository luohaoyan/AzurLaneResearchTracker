#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 Equipment attribute reranker tests                   ║
║                                                              ║
║  【测试目标】确认 Wiki 属性签名能保守重排图标候选。            ║
║  【类比理解】图标像双胞胎时，用说明书里的伤害/射速再确认。     ║
║  【数据流说明】OCR text + icon top-N + signature model。       ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from core.recognition.equipment_attribute_reranker import EquipmentAttributeReranker, tokenize_attribute_text


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_tokenize_attribute_text_handles_joined_label_and_number() -> None:
    """OCR 把“炮击 65”连成“炮击65”时，也应拆出可匹配 token。"""
    tokens = tokenize_attribute_text("伤害17×4 标准射速3.43s/轮 炮击65")

    assert "伤害=17x4" in tokens
    assert "17x4" in tokens
    assert "炮击=65" in tokens


def test_rerank_selects_candidate_with_matching_attribute_tokens() -> None:
    """属性文本与第二候选强匹配时，应能把第二候选排到第一。"""
    reranker = EquipmentAttributeReranker(
        {
            "A": {"equipment_id": "A", "equipment_name": "错候选", "tokens": ["伤害=10", "炮击=20"]},
            "B": {"equipment_id": "B", "equipment_name": "试作型四联装152mm主炮#T0", "tokens": ["伤害=17x4", "17x4", "炮击=65", "65"]},
        },
        {"伤害=17x4": 2.0, "17x4": 1.5, "炮击=65": 2.0, "65": 1.2},
        icon_weight=0.45,
        attribute_weight=0.55,
        min_attribute_score=0.10,
        min_margin=0.01,
    )

    result = reranker.rerank(
        "伤害17×4 炮击65",
        [{"equipment_id": "A", "confidence": 0.90}, {"equipment_id": "B", "confidence": 0.75}],
    )

    assert result.success is True
    assert result.selected_equipment_id == "B"
    assert result.attribute_score > 0.3


def test_rerank_stays_ambiguous_without_enough_attribute_overlap() -> None:
    """属性重合太少时，不能贸然接管图标结果。"""
    reranker = EquipmentAttributeReranker(
        {"A": {"equipment_id": "A", "equipment_name": "候选A", "tokens": ["航空=45"]}},
        icon_weight=0.50,
        attribute_weight=0.50,
        min_attribute_score=0.50,
        min_margin=0.20,
    )

    result = reranker.rerank("看不清", [{"equipment_id": "A", "confidence": 0.99}])

    assert result.success is False
    assert result.status in {"empty", "ambiguous"}


def test_rerank_does_not_accept_label_only_overlap() -> None:
    """只命中“标准射速/耐久”这种字段名时，不能接管候选。"""
    reranker = EquipmentAttributeReranker(
        {"A": {"equipment_id": "A", "equipment_name": "候选A", "tokens": ["标准射速", "标准射速=2.02s/轮"]}},
        icon_weight=0.50,
        attribute_weight=0.50,
        min_attribute_score=0.10,
        min_margin=0.0,
    )

    result = reranker.rerank("标准射速", [{"equipment_id": "A", "confidence": 0.90}])

    assert result.success is False
    assert result.attribute_score > 0


def test_rerank_requires_attribute_score_margin_not_only_icon_margin() -> None:
    """多个候选属性分相同时，不能只靠图标分差宣布属性重排成功。"""
    reranker = EquipmentAttributeReranker(
        {
            "A": {"equipment_id": "A", "equipment_name": "候选A", "tokens": ["伤害", "25"]},
            "B": {"equipment_id": "B", "equipment_name": "候选B", "tokens": ["伤害", "25"]},
        },
        icon_weight=0.70,
        attribute_weight=0.30,
        min_attribute_score=0.10,
        min_margin=0.01,
    )

    result = reranker.rerank("伤害 25", [{"equipment_id": "A", "confidence": 0.90}, {"equipment_id": "B", "confidence": 0.70}])

    assert result.success is False
    assert result.margin > 0
    assert result.attribute_margin == 0
