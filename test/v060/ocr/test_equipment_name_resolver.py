#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 装备名称解析器测试                                ║
║                                                              ║
║  【测试目标】验证 OCR 装备名可按名称而非固定 ID 解析。         ║
║  【类比理解】像检查“读铭牌助手”能不能帮图标识别排除同脸装备。║
║  【数据流说明】合成 catalog/OCR 文本 → resolver → 解析结果。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from core.recognition.equipment_name_resolver import (
    EquipmentNameResolver,
    normalize_equipment_base_name,
    normalize_equipment_name,
    normalize_ocr_confusion_skeleton,
)


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

def _catalog() -> dict[str, dict[str, object]]:
    """构造一份小型装备库，避免读写正式 CSV。"""
    return {
        "G0001": {"equipment_id": "G0001", "name": "液压弹射装置#T3", "rarity_id": 4},
        "G0002": {"equipment_id": "G0002", "name": "液压弹射装置#T2", "rarity_id": 3},
        "G0003": {"equipment_id": "G0003", "name": "潜艇用Mark 16鱼雷#T3", "rarity_id": 4},
        "G0004": {"equipment_id": "G0004", "name": "潜艇用Mark 20S鱼雷-彼得#T0", "rarity_id": 5},
    }


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_normalization_removes_spaces_fullwidth_and_tier_suffix() -> None:
    """名称规范化应消除空格/全角差异，并支持基础名比较。"""
    assert normalize_equipment_name(" G0001 液压 弹射装置 ＃T3 ") == "液压弹射装置#t3"
    assert normalize_equipment_name("双联装128mmSKC41高平两用炮#T3sa") == "双联装128mmskc41高平两用炮#t3"
    assert normalize_equipment_base_name("液压弹射装置#T3") == "液压弹射装置"
    assert normalize_ocr_confusion_skeleton("J e-87C") == normalize_ocr_confusion_skeleton("Ju-87C")


def test_exact_name_resolves_to_equipment_name_and_id() -> None:
    """完整装备名应能直接解析为当前装备库 ID。"""
    resolver = EquipmentNameResolver.from_catalog(_catalog())

    result = resolver.resolve("液压弹射装置#T3")

    assert result.success is True
    assert result.equipment_id == "G0001"
    assert result.equipment_name == "液压弹射装置#T3"
    assert result.score >= 0.99


def test_base_name_without_tier_uses_icon_candidates_to_disambiguate() -> None:
    """OCR 只读到基础名时，应优先用图标 top-N 候选区分 T2/T3。"""
    resolver = EquipmentNameResolver.from_catalog(_catalog())

    result = resolver.resolve("液压弹射装置", candidate_equipment_ids=["G0002"])

    assert result.success is True
    assert result.equipment_id == "G0002"
    assert "icon_candidates" in result.status


def test_base_name_without_candidates_remains_ambiguous() -> None:
    """同基础名存在多个 T 等级且没有图标候选时，不应强行猜一个。"""
    resolver = EquipmentNameResolver.from_catalog(_catalog())

    result = resolver.resolve("液压弹射装置")

    assert result.success is False
    assert result.status == "ambiguous"
    assert len(result.candidates) >= 2


def test_name_outside_icon_candidates_reports_conflict_for_review() -> None:
    """名称能全局解析但不在图标 top-N 里时，应显式暴露候选冲突。"""
    resolver = EquipmentNameResolver.from_catalog(_catalog())

    result = resolver.resolve("潜艇用Mark 16鱼雷#T3", candidate_equipment_ids=["G0001", "G0002"])

    assert result.success is True
    assert result.status == "outside_icon_candidates"
    assert result.equipment_id == "G0003"


def test_short_generic_ocr_text_is_rejected_before_fuzzy_matching() -> None:
    """OCR 只读到“设备/装备”这类泛词时，不应误解析成某个具体装备。"""
    resolver = EquipmentNameResolver.from_catalog(_catalog() | {
        "G0201": {"equipment_id": "G0201", "name": "舰艇维修设备#T3", "rarity_id": 3},
    })

    result = resolver.resolve("设备", candidate_equipment_ids=["G0201"])

    assert result.success is False
    assert result.status == "too_short"
    assert result.equipment_id == ""


def test_short_full_name_with_tier_can_resolve_exactly() -> None:
    """像“剑鱼#T3”这种短但完整的人工标签，应先精确命中再执行短文本保护。"""
    resolver = EquipmentNameResolver.from_catalog({
        "G0441": {"equipment_id": "G0441", "name": "剑鱼#T3", "rarity_id": 3},
        "G0442": {"equipment_id": "G0442", "name": "梭鱼#T3", "rarity_id": 3},
    })

    result = resolver.resolve("剑鱼#T3")

    assert result.success is True
    assert result.equipment_id == "G0441"
    assert result.equipment_name == "剑鱼#T3"


def test_short_base_name_without_tier_still_keeps_too_short_guard() -> None:
    """短基础名没有 #T 等级时仍然拒绝，避免 OCR 两三个字误消歧。"""
    resolver = EquipmentNameResolver.from_catalog({
        "G0441": {"equipment_id": "G0441", "name": "剑鱼#T3", "rarity_id": 3},
    })

    result = resolver.resolve("剑鱼")

    assert result.success is False
    assert result.status == "too_short"


def test_english_ocr_confusion_can_resolve_mixed_name() -> None:
    """英文混排名称里 u/e、空格、大小写误差应能保守拉回候选装备。"""
    resolver = EquipmentNameResolver.from_catalog({
        "G0001": {"equipment_id": "G0001", "name": "Ju-87C俯冲轰炸机#T3", "rarity_id": 4},
        "G0002": {"equipment_id": "G0002", "name": "BF-109T舰载战斗机#T3", "rarity_id": 4},
    })

    result = resolver.resolve("J e-87C 俯冲轰炸机", candidate_equipment_ids=["G0001", "G0002"])

    assert result.success is True
    assert result.equipment_id == "G0001"
    assert result.status.startswith("icon_candidates")


def test_display_alias_can_assist_harmonized_game_name() -> None:
    """游戏内和谐显示名“赫尔卡特”应能辅助解析到 F6F 地狱猫候选。"""
    resolver = EquipmentNameResolver.from_catalog({
        "G0151": {"equipment_id": "G0151", "name": "F6F地狱猫#T3", "rarity_id": 4},
        "G0186": {"equipment_id": "G0186", "name": "BTD-1毁灭者#T3", "rarity_id": 4},
    })

    result = resolver.resolve("赫尔卡特战斗", candidate_equipment_ids=["G0151", "G0186"])

    assert result.success is True
    assert result.equipment_id == "G0151"
    assert "display_alias" in result.status
