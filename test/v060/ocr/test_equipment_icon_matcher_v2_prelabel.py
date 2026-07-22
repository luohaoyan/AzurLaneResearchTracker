#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 装备图标 v2 预标注名称辅助测试                       ║
║                                                              ║
║  【测试目标】验证名称 OCR 能辅助 ambiguous 图标候选完成消歧。 ║
║  【类比理解】像图片看不清时，再读旁边铭牌确认身份。            ║
║  【数据流说明】fake OCR/fake matcher → build_card_row → 行。  ║
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

from core.recognition.design_fragment_detector import DesignFragmentCardCandidate
from core.recognition.equipment_name_resolver import EquipmentNameResolver
from core.recognition.ocr_engine import OcrReadResult


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "run_v2_prelabel.py"


def _load_lab_module() -> Any:
    """按文件路径加载 v2 预标注脚本，避免把 lab 目录改成正式包。"""
    spec = importlib.util.spec_from_file_location("run_v2_prelabel_for_test", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeNameOcrEngine:
    """只返回装备名称 OCR 结果的 fake 引擎。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """模拟 PaddleOCR 成功读到卡片旁边的装备名。"""
        return OcrReadResult(True, "success", "ok", text="液压弹射装置", confidence=0.88)


class FakeReader:
    """给 build_card_row 注入名称 OCR，不读碎片数量。"""

    ocr_engine = FakeNameOcrEngine()


class FakeIconMatcher:
    """返回 ambiguous 图标候选，让名称 OCR 负责消歧。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """模拟图标 top1/top2 接近，但 top-N 中包含正确装备。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "ambiguous",
                    "message": "close candidates",
                    "equipment_id": "unknown",
                    "confidence": 0.70,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "",
                    "candidates": [
                        {"equipment_id": "G0001", "confidence": 0.70, "image_path": "a.png"},
                        {"equipment_id": "G0002", "confidence": 0.69, "image_path": "b.png"},
                    ],
                    "warnings": [],
                }

        return Result()


class FakeConflictNameOcrEngine:
    """返回和图标结果冲突的装备名称。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """模拟 OCR 读到一个不在图标 top-N 里的装备名。"""
        return OcrReadResult(True, "success", "ok", text="高性能舵机", confidence=0.90)


class FakeConflictReader:
    """给冲突测试注入名称 OCR。"""

    ocr_engine = FakeConflictNameOcrEngine()


class FakeConfidentWrongIconMatcher:
    """模拟图标 top1 成功但和名称 OCR 冲突。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回不包含高性能舵机的候选。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "success",
                    "message": "ok",
                    "equipment_id": "G0083",
                    "confidence": 0.75,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "gun.png",
                    "candidates": [
                        {"equipment_id": "G0083", "confidence": 0.75, "image_path": "gun.png"},
                        {"equipment_id": "G0186", "confidence": 0.72, "image_path": "plane.png"},
                    ],
                    "warnings": [],
                }

        return Result()


class FakePartialCaliberNameOcrEngine:
    """模拟名称 OCR 只读到局部口径信息。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """返回足以发现 203mm/406mm 冲突的短文本。"""
        return OcrReadResult(True, "success", "ok", text="双联装203mm", confidence=0.99)


class FakePartialCaliberReader:
    """给局部口径冲突测试注入名称 OCR。"""

    ocr_engine = FakePartialCaliberNameOcrEngine()


class Fake203Vs406IconMatcher:
    """模拟图标把 203mm 主炮误判成 406mm 主炮。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回高于普通复核阈值但与名称 OCR 数字冲突的 top1。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "success",
                    "message": "ok",
                    "equipment_id": "G0345",
                    "confidence": 0.866,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "406.png",
                    "candidates": [
                        {"equipment_id": "G0345", "confidence": 0.866, "image_path": "406.png"},
                        {"equipment_id": "G0429", "confidence": 0.825, "image_path": "other.png"},
                    ],
                    "warnings": [],
                }

        return Result()


class Fake128NameOcrEngine:
    """模拟名称 OCR 读到 128mm 主炮短名称。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """名称和属性 ROI 共用 fake；属性文本内容由 fake reranker 接管。"""
        return OcrReadResult(True, "success", "ok", text="双联装128mm", confidence=0.99)


class Fake128Reader:
    """给名称/属性冲突测试注入 OCR。"""

    ocr_engine = Fake128NameOcrEngine()


class Fake128IconMatcher:
    """模拟图标 top1 正确识别为 128mm，但属性候选中也有 134mm。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回 128mm 为 top1，134mm 在 top-N。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "success",
                    "message": "ok",
                    "equipment_id": "G0310",
                    "confidence": 1.0,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "128.png",
                    "candidates": [
                        {"equipment_id": "G0310", "confidence": 1.0, "image_path": "128.png"},
                        {"equipment_id": "G0303", "confidence": 0.78, "image_path": "134.png"},
                    ],
                    "warnings": [],
                }

        return Result()


class FakeWrong134AttributeReranker:
    """模拟 Wiki 属性重排错误选择 134mm。"""

    def rerank(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回 success，但 selected_equipment_id 与名称辅助结果冲突。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "success",
                    "message": "ok",
                    "selected_equipment_id": "G0303",
                    "selected_equipment_name": "双联装134mm高炮#T3",
                    "attribute_score": 0.78,
                    "combined_score": 0.77,
                    "margin": 0.10,
                    "attribute_margin": 0.34,
                    "observed_text": "伤害",
                    "observed_tokens": ["伤害"],
                    "candidates": [
                        {
                            "equipment_id": "G0303",
                            "equipment_name": "双联装134mm高炮#T3",
                            "icon_confidence": 0.78,
                            "attribute_score": 0.78,
                            "combined_score": 0.77,
                            "matched_tokens": ["伤害"],
                        }
                    ],
                }

        return Result()


class FakeRepairNameOcrEngine:
    """返回不含 #T 等级的维修工具名称。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """模拟设计图名称区只显示基础名。"""
        return OcrReadResult(True, "success", "ok", text="维修工具", confidence=0.92)


class FakeRepairReader:
    """给同名多 T 等级测试注入 OCR。"""

    ocr_engine = FakeRepairNameOcrEngine()


class FakeRepairMatcher:
    """模拟当前稀有度图库里只有维修工具 T3 候选。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回 ambiguous，但 top-N 内含维修工具 T3。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "ambiguous",
                    "message": "close candidates",
                    "equipment_id": "unknown",
                    "confidence": 0.77,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "",
                    "candidates": [
                        {"equipment_id": "G0002", "confidence": 0.77, "image_path": "repair_t3.png"},
                        {"equipment_id": "G0003", "confidence": 0.76, "image_path": "other.png"},
                    ],
                    "warnings": [],
                }

        return Result()


class FakeGenericUrNameOcrEngine:
    """模拟 UR 设计图名称区只读到泛化前缀。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """返回无法区分 152mm/305mm 的短文本。"""
        return OcrReadResult(True, "success", "ok", text="试作型四联装", confidence=0.91)


class FakeGenericUrReader:
    """给高稀有度保守阀测试注入泛化名称 OCR。"""

    ocr_engine = FakeGenericUrNameOcrEngine()


class Fake610TorpedoNameOcrEngine:
    """模拟名称 OCR 读到四联装 610mm 鱼雷的关键短名称。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """返回缺少鱼雷/#T3，且把 mm 误读成 mn 的高置信 OCR 文本。"""
        return OcrReadResult(True, "success", "ok", text="四联装610mn", confidence=0.99)


class Fake610TorpedoReader:
    """给金装鱼雷高价值保护测试注入 OCR。"""

    ocr_engine = Fake610TorpedoNameOcrEngine()


class Fake610TorpedoIconMatcher:
    """模拟图标能识别 610mm 鱼雷，但分数低于金装强保护阈值。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回 G0106 为 top1，同时保留几个相似鱼雷/炮候选。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "success",
                    "message": "ok",
                    "equipment_id": "G0106",
                    "confidence": 0.899,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "610mm.png",
                    "candidates": [
                        {"equipment_id": "G0106", "confidence": 0.899, "image_path": "610mm.png"},
                        {"equipment_id": "G0144", "confidence": 0.767, "image_path": "90mm.png"},
                        {"equipment_id": "S9-005", "confidence": 0.762, "image_path": "550mm.png"},
                    ],
                    "warnings": [],
                }

        return Result()


class FakeExactUrNameOcrEngine:
    """模拟 UR 设计图名称区读到完整装备名。"""

    def recognize_text(self, *_args: Any, **_kwargs: Any) -> OcrReadResult:
        """返回可直接区分相似主炮的完整名称。"""
        return OcrReadResult(True, "success", "ok", text="试作型四联装152mm主炮#T0", confidence=0.93)


class FakeExactUrReader:
    """给高稀有度强名称测试注入完整名称 OCR。"""

    ocr_engine = FakeExactUrNameOcrEngine()


class FakeLowConfidenceUrIconMatcher:
    """模拟 UR 图标 top1 置信度不足，但仍返回 success。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回一个低于高价值阈值的 success 结果。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "success",
                    "message": "ok",
                    "equipment_id": "S8-003",
                    "confidence": 0.803,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "ur.png",
                    "candidates": [
                        {"equipment_id": "S8-003", "confidence": 0.803, "image_path": "ur.png"},
                        {"equipment_id": "S5-002", "confidence": 0.708, "image_path": "ur2.png"},
                    ],
                    "warnings": [],
                }

        return Result()


class FakeWrongUrIconMatcher:
    """模拟 UR 图标 top1 错到相似装备，但完整名称 OCR 可纠正。"""

    def match_icon(self, *_args: Any, **_kwargs: Any) -> Any:
        """返回 234mm 为 top1，152mm 在 top-N。"""

        class Result:
            def to_dict(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "status": "success",
                    "message": "ok",
                    "equipment_id": "S3-002",
                    "confidence": 0.755,
                    "icon_roi": [0, 0, 10, 10],
                    "matched_image_path": "wrong_ur.png",
                    "candidates": [
                        {"equipment_id": "S3-002", "confidence": 0.755, "image_path": "wrong_ur.png"},
                        {"equipment_id": "S5-002", "confidence": 0.708, "image_path": "right_ur.png"},
                    ],
                    "warnings": [],
                }

        return Result()


def _candidate() -> DesignFragmentCardCandidate:
    """构造一张完整卡片候选。"""
    return DesignFragmentCardCandidate(
        index=1,
        row_index=1,
        column_index=1,
        bbox=(0, 0, 200, 100),
        raw_bbox=(0, 0, 200, 100),
        icon_roi=(5, 5, 40, 70),
        quantity_roi=(150, 10, 40, 25),
        visibility="full",
        confidence=0.95,
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_parse_v2_filename_accepts_test_prefix_for_rarity() -> None:
    """test_img 文件名允许带 test_ 前缀，但稀有度必须仍解析为正式桶。"""
    lab = _load_lab_module()

    meta = lab.parse_v2_filename(Path("v2_test_super_rare_scroll_001.png"))

    assert meta.rarity == "super_rare"
    assert meta.rarity_id == 4
    assert meta.page_index == 1


def test_parse_collection_fragment_filename_accepts_sort_token() -> None:
    """collection_next 的 frag_<rarity>_<sort>_scroll 文件名应解析出稀有度。"""
    lab = _load_lab_module()

    meta = lab.parse_v2_filename(Path("frag_super_rare_buildable_scroll_001.png"))

    assert meta.rarity == "super_rare"
    assert meta.rarity_id == 4
    assert meta.page_index == 1


def test_parse_collection_equipment_filename_without_sort_token() -> None:
    """装备页 collection 命名没有排序字段时，也不能被解析成 unknown。"""
    lab = _load_lab_module()

    meta = lab.parse_v2_filename(Path("equip_ultra_rare_scroll_012.png"))

    assert meta.rarity == "ultra_rare"
    assert meta.rarity_id == 5
    assert meta.page_index == 12


def test_probable_empty_false_positive_skips_review() -> None:
    """空白误检卡应被跳过，不再生成需要人工标注的 review 行。"""
    lab = _load_lab_module()

    assert lab._is_probable_empty_false_positive(
        full_card=True,
        high_value_card=True,
        raw_name_text="",
        icon_status="success",
        icon_confidence=0.66,
        ocr_status="skipped",
    )
    assert not lab._is_probable_empty_false_positive(
        full_card=True,
        high_value_card=True,
        raw_name_text="试作型三联装",
        icon_status="success",
        icon_confidence=0.66,
        ocr_status="skipped",
    )


def test_build_card_row_uses_name_ocr_to_disambiguate_icon_candidates() -> None:
    """名称 OCR 命中 top-N 候选时，应生成 name_assisted 预填名称。"""
    lab = _load_lab_module()
    catalog = {
        "G0001": {"equipment_id": "G0001", "name": "液压弹射装置#T3", "rarity_id": 4},
        "G0002": {"equipment_id": "G0002", "name": "潜艇用Mark 16鱼雷#T3", "rarity_id": 4},
    }
    candidate = _candidate()

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "super_rare", 4, 1, "start"),
        card_no=1,
        candidate=candidate,
        reader=FakeReader(),
        matcher=FakeIconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.80,
        name_global_assist_score=0.90,
    )

    assert row["name_assisted"] is True
    assert row["name_override_allowed"] is False
    assert row["suggested_equipment_id"] == "G0001"
    assert row["suggested_equipment_name"] == "液压弹射装置#T3"
    assert row["accepted_equipment_name"] == "液压弹射装置#T3"
    assert row["needs_review"] is False


def test_build_card_row_name_override_can_replace_low_confidence_icon_result() -> None:
    """名称 OCR 很稳而图标分数不高时，应允许文字接管。"""
    lab = _load_lab_module()
    catalog = {
        "G0083": {"equipment_id": "G0083", "name": "四联装356mm主炮#T3", "rarity_id": 4},
        "G0186": {"equipment_id": "G0186", "name": "BTD-1毁灭者#T3", "rarity_id": 4},
        "S0-003": {"equipment_id": "S0-003", "name": "高性能舵机#T0", "rarity_id": 4},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "super_rare", 4, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=FakeConflictReader(),
        matcher=FakeConfidentWrongIconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.80,
        name_global_assist_score=0.90,
    )

    assert row["name_override_allowed"] is True
    assert row["name_assisted"] is True
    assert row["name_icon_conflict"] is False
    assert row["needs_review"] is False
    assert row["machine_prefill"] is True
    assert row["accepted_equipment_name"] == "高性能舵机#T0"


def test_build_card_row_high_confident_icon_still_blocks_name_conflict() -> None:
    """图标本身非常强时，文字若冲突仍应保守复核。"""
    lab = _load_lab_module()
    catalog = {
        "G0083": {"equipment_id": "G0083", "name": "四联装356mm主炮#T3", "rarity_id": 4},
        "G0186": {"equipment_id": "G0186", "name": "BTD-1毁灭者#T3", "rarity_id": 4},
        "S0-003": {"equipment_id": "S0-003", "name": "高性能舵机#T0", "rarity_id": 4},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "super_rare", 4, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=FakeConflictReader(),
        matcher=FakeConfidentWrongIconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.70,
        name_global_assist_score=0.90,
    )

    assert row["name_override_allowed"] is False
    assert row["name_icon_conflict"] is True
    assert row["needs_review"] is True
    assert row["machine_prefill"] is False
    assert row["accepted_equipment_name"] == ""


def test_partial_name_caliber_conflict_forces_review_without_prefill() -> None:
    """名称 OCR 只读到局部口径时，若与图标建议口径冲突，应转人工复核。"""
    lab = _load_lab_module()
    catalog = {
        "G0345": {"equipment_id": "G0345", "name": "双联装406mm主炮Mk5#T3", "rarity_id": 3},
        "G0429": {"equipment_id": "G0429", "name": "战斗机燃油箱#T2", "rarity_id": 3},
        "G0999": {"equipment_id": "G0999", "name": "双联装203mm主炮#T3", "rarity_id": 3},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "elite", 3, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=FakePartialCaliberReader(),
        matcher=Fake203Vs406IconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.80,
        name_global_assist_score=0.90,
    )

    assert row["name_partial_conflict"] is True
    assert row["needs_review"] is True
    assert row["machine_prefill"] is False
    assert row["accepted_equipment_name"] == ""
    assert "name_partial_conflict" in row["review_reason"]


def test_attribute_rerank_cannot_override_conflicting_name_assist() -> None:
    """属性重排和名称 OCR 冲突时，不能让属性结果覆盖名称结果。"""
    lab = _load_lab_module()
    catalog = {
        "G0310": {"equipment_id": "G0310", "name": "双联装128mmSKC41高平两用炮#T3", "rarity_id": 3},
        "G0303": {"equipment_id": "G0303", "name": "双联装134mm高炮#T3", "rarity_id": 3},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "elite", 3, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=Fake128Reader(),
        matcher=Fake128IconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.80,
        name_global_assist_score=0.90,
        attribute_reranker=FakeWrong134AttributeReranker(),
        enable_attribute_ocr=True,
        attribute_ocr_confidence=0.42,
    )

    assert row["name_assisted"] is True
    assert row["attribute_assisted"] is True
    assert row["attribute_name_conflict"] is True
    assert row["suggested_equipment_id"] == "G0310"
    assert row["suggested_equipment_name"] == "双联装128mmSKC41高平两用炮#T3"
    assert row["needs_review"] is True
    assert row["machine_prefill"] is False
    assert row["accepted_equipment_name"] == ""
    assert "attribute_name_conflict" in row["review_reason"]


def test_build_card_row_strong_name_can_recover_outside_ambiguous_icon_candidates() -> None:
    """图标 ambiguous 且 top-N 漏召回时，强名称 OCR 可以救回结果。"""
    lab = _load_lab_module()
    catalog = {
        "G0001": {"equipment_id": "G0001", "name": "液压弹射装置#T3", "rarity_id": 4},
        "G0002": {"equipment_id": "G0002", "name": "潜艇用Mark 16鱼雷#T3", "rarity_id": 4},
        "S0-003": {"equipment_id": "S0-003", "name": "高性能舵机#T0", "rarity_id": 4},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "super_rare", 4, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=FakeConflictReader(),
        matcher=FakeIconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.80,
        name_global_assist_score=0.90,
    )

    assert row["name_global_strong"] is True
    assert row["name_can_recover_weak_icon"] is True
    assert row["name_assisted"] is True
    assert row["suggested_equipment_id"] == "S0-003"
    assert row["accepted_equipment_name"] == "高性能舵机#T0"
    assert row["needs_review"] is False


def test_filter_catalog_by_rarity_limits_name_resolver_scope() -> None:
    """名称 OCR 应按当前筛选稀有度缩小搜索范围，避免同名不同 T 等级串台。"""
    lab = _load_lab_module()
    catalog = {
        "G0001": {"equipment_id": "G0001", "name": "维修工具#T2", "rarity_id": 2},
        "G0002": {"equipment_id": "G0002", "name": "维修工具#T3", "rarity_id": 3},
    }

    rare_catalog = lab.filter_catalog_by_rarity(catalog, 2)
    elite_catalog = lab.filter_catalog_by_rarity(catalog, 3)

    assert tuple(rare_catalog) == ("G0001",)
    assert tuple(elite_catalog) == ("G0002",)


def test_tierless_base_name_with_multiple_variants_stays_in_review() -> None:
    """OCR 没读到 #T 等级且全库同名多等级时，不能直接自动接管 ambiguous 图标。"""
    lab = _load_lab_module()
    full_catalog = {
        "G0001": {"equipment_id": "G0001", "name": "维修工具#T2", "rarity_id": 2},
        "G0002": {"equipment_id": "G0002", "name": "维修工具#T3", "rarity_id": 3},
        "G0003": {"equipment_id": "G0003", "name": "SG雷达#T2", "rarity_id": 3},
    }
    elite_catalog = lab.filter_catalog_by_rarity(full_catalog, 3)

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "elite", 3, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=FakeRepairReader(),
        matcher=FakeRepairMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(elite_catalog),
        catalog=full_catalog,
        top_n=10,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.86,
        name_global_assist_score=0.90,
    )

    assert row["name_tierless_base_ambiguous"] is True
    assert row["name_assisted"] is False
    assert row["needs_review"] is True
    assert "name_tier_ambiguous" in row["review_reason"]


def test_high_value_generic_name_does_not_prefill_low_confidence_icon() -> None:
    """金/彩装备只读到泛化名称片段时，即使名称辅助命中也要人工复核。"""
    lab = _load_lab_module()
    catalog = {
        "S8-003": {"equipment_id": "S8-003", "name": "试作型四联装305mmSKC39主炮#T0", "rarity_id": 5},
        "S5-002": {"equipment_id": "S5-002", "name": "试作型四联装152mm主炮#T0", "rarity_id": 5},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "ultra_rare", 5, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=FakeGenericUrReader(),
        matcher=FakeLowConfidenceUrIconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.86,
        name_global_assist_score=0.90,
    )

    assert row["high_value_guard_active"] is True
    assert row["high_value_name_weak"] is True
    assert row["needs_review"] is True
    assert row["machine_prefill"] is False
    assert row["accepted_equipment_name"] == ""
    assert "high_value_weak_name" in row["review_reason"]


def test_high_value_distinctive_caliber_name_releases_repeated_torpedo_review() -> None:
    """金装名称读到 610mn/mm 这类强口径 token，且图标 top1 同意时，不应反复黄框。"""
    lab = _load_lab_module()
    catalog = {
        "G0106": {"equipment_id": "G0106", "name": "四联装610mm鱼雷#T3", "rarity_id": 4},
        "G0144": {"equipment_id": "G0144", "name": "90mm单装高角炮Model1939#T3", "rarity_id": 4},
        "S9-005": {"equipment_id": "S9-005", "name": "试作型三联装550mm鱼雷改（弹药调整）#T0", "rarity_id": 4},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "super_rare", 4, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=Fake610TorpedoReader(),
        matcher=Fake610TorpedoIconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.90,
        auto_accept_confidence=0.92,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.86,
        name_global_assist_score=0.90,
    )

    assert row["name_assisted"] is True
    assert row["high_value_name_weak"] is False
    assert row["high_value_guard_active"] is False
    assert row["machine_prefill"] is True
    assert row["needs_review"] is False
    assert row["accepted_equipment_name"] == "四联装610mm鱼雷#T3"


def test_high_value_exact_name_can_override_similar_icon() -> None:
    """金/彩装备读到完整名称时，可以接管低置信度相似图标结果。"""
    lab = _load_lab_module()
    catalog = {
        "S3-002": {"equipment_id": "S3-002", "name": "试作型三联装234mm主炮#T0", "rarity_id": 5},
        "S5-002": {"equipment_id": "S5-002", "name": "试作型四联装152mm主炮#T0", "rarity_id": 5},
    }

    row = lab.build_card_row(
        image=np.zeros((120, 220, 3), dtype=np.uint8),
        filename="shot.png",
        meta=lab.V2ImageMeta("shot.png", "ultra_rare", 5, 1, "start"),
        card_no=1,
        candidate=_candidate(),
        reader=FakeExactUrReader(),
        matcher=FakeWrongUrIconMatcher(),
        name_resolver=EquipmentNameResolver.from_catalog(catalog),
        catalog=catalog,
        top_n=5,
        review_confidence=0.72,
        auto_accept_confidence=0.90,
        read_quantity_ocr=False,
        enable_name_ocr=True,
        name_ocr_confidence=0.55,
        name_fuzzy_threshold=0.66,
        name_assist_icon_confidence=0.60,
        name_override_icon_confidence=0.86,
        name_global_assist_score=0.90,
    )

    assert row["high_value_guard_active"] is False
    assert row["high_value_strong_name"] is True
    assert row["name_override_allowed"] is True
    assert row["suggested_equipment_id"] == "S5-002"
    assert row["accepted_equipment_name"] == "试作型四联装152mm主炮#T0"


def test_draft_exp_keeps_machine_prefill_as_hint_not_human_answer() -> None:
    """机器建议只能出现在注释里，不能写进人工 accepted_equipment_name 字段。"""
    lab = _load_lab_module()
    text = lab.build_draft_exp(
        [
            {
                "filename": "shot.png",
                "meta": {"rarity": "super_rare", "rarity_id": 4, "page_index": 1, "scroll_position": "start"},
                "cards": [
                    {
                        "selected": True,
                        "icon_selected": True,
                        "quantity_selected": True,
                        "card_no": 1,
                        "suggested_equipment_id": "G0001",
                        "suggested_equipment_name": "液压弹射装置#T3",
                        "current_resolved_equipment_id": "G0001",
                        "icon_status": "success",
                        "icon_confidence": 0.95,
                        "machine_prefill": True,
                        "auto_accept": True,
                        "needs_review": False,
                        "review_reason": "",
                        "icon_top_candidates": "G0001:液压弹射装置#T3:0.950",
                        "name_resolve_candidates": "G0001:液压弹射装置#T3:0.990",
                        "name_ocr_text": "液压弹射装置",
                        "name_ocr_confidence": 0.98,
                        "name_assisted": True,
                        "name_resolve_equipment_name": "液压弹射装置#T3",
                        "name_resolve_score": 0.99,
                        "accepted_equipment_name": "液压弹射装置#T3",
                        "accepted_equipment_id": "G0001",
                        "accepted_fragment_owned": 12,
                        "accepted_fragment_required": 25,
                    }
                ],
            }
        ]
    )

    assert "# card_01.suggested:G0001 液压弹射装置#T3" in text
    assert "# card_01.image_top3:1) G0001 液压弹射装置#T3 0.950" in text
    assert "card_01.accepted_equipment_name:\n" in text
    assert "card_01.accepted_equipment_name:液压弹射装置#T3" not in text
    assert "card_01.accepted_equipment_id:G0001" not in text
