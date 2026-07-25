#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        Equipment Attribute Reranker                         ║
║  Uses Wiki attribute signatures to rerank visually similar   ║
║  equipment candidates from design-fragment cards.            ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ============================================================
# 🧱 第二部分：结果对象
# ============================================================

@dataclass(frozen=True)
class AttributeRerankCandidate:
    """
    A single reranked candidate.

    输入：
        equipment_id/name/icon_confidence/attribute_score/combined_score。
    输出：
        可序列化候选对象。
    使用示例：
        candidate.to_dict()
    """

    equipment_id: str
    equipment_name: str
    icon_confidence: float
    attribute_score: float
    combined_score: float
    matched_tokens: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a serializable dict."""
        return {
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment_name,
            "icon_confidence": float(self.icon_confidence),
            "attribute_score": float(self.attribute_score),
            "combined_score": float(self.combined_score),
            "matched_tokens": list(self.matched_tokens),
        }


@dataclass(frozen=True)
class AttributeRerankResult:
    """
    Attribute reranking result.

    输入：
        OCR 文本和图标候选。
    输出：
        是否可接管、最佳候选和 Top-N 评分。
    使用示例：
        result.to_dict()
    """

    success: bool
    status: str
    message: str
    selected_equipment_id: str = ""
    selected_equipment_name: str = ""
    attribute_score: float = 0.0
    combined_score: float = 0.0
    margin: float = 0.0
    attribute_margin: float = 0.0
    observed_text: str = ""
    observed_tokens: Tuple[str, ...] = ()
    candidates: Tuple[AttributeRerankCandidate, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a serializable dict."""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "selected_equipment_id": self.selected_equipment_id,
            "selected_equipment_name": self.selected_equipment_name,
            "attribute_score": float(self.attribute_score),
            "combined_score": float(self.combined_score),
            "margin": float(self.margin),
            "attribute_margin": float(self.attribute_margin),
            "observed_text": self.observed_text,
            "observed_tokens": list(self.observed_tokens),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


# ============================================================
# 🏗️ 第三部分：重排器
# ============================================================

class EquipmentAttributeReranker:
    """Rerank icon candidates with Wiki attribute signature tokens."""

    def __init__(
        self,
        equipment_index: Mapping[str, Mapping[str, Any]],
        token_idf: Optional[Mapping[str, float]] = None,
        *,
        icon_weight: float = 0.70,
        attribute_weight: float = 0.30,
        min_attribute_score: float = 0.18,
        min_margin: float = 0.02,
    ) -> None:
        """Initialize the reranker from an equipment index."""
        self.equipment_index = {str(key): dict(value) for key, value in equipment_index.items()}
        self.token_idf = {str(key): float(value) for key, value in (token_idf or {}).items()}
        self.icon_weight = float(icon_weight)
        self.attribute_weight = float(attribute_weight)
        self.min_attribute_score = float(min_attribute_score)
        self.min_margin = float(min_margin)

    @classmethod
    def from_model_file(
        cls,
        model_path: str | Path,
        *,
        icon_weight: float = 0.70,
        attribute_weight: float = 0.30,
        min_attribute_score: float = 0.18,
        min_margin: float = 0.02,
    ) -> "EquipmentAttributeReranker":
        """
        Load a reranker from wiki_attribute_signature_model.json.

        输入：
            模型 JSON 路径。
        输出：
            EquipmentAttributeReranker。
        使用示例：
            reranker = EquipmentAttributeReranker.from_model_file(path)
        """
        path = Path(model_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        equipment_index = {
            str(item.get("equipment_id", "") or ""): dict(item)
            for item in data.get("equipment_index", [])
            if str(item.get("equipment_id", "") or "")
        }
        return cls(
            equipment_index,
            data.get("token_idf", {}),
            icon_weight=icon_weight,
            attribute_weight=attribute_weight,
            min_attribute_score=min_attribute_score,
            min_margin=min_margin,
        )

    def rerank(
        self,
        observed_text: str,
        icon_candidates: Sequence[Mapping[str, Any]],
        *,
        top_n: int = 5,
    ) -> AttributeRerankResult:
        """
        Rerank icon candidates using observed attribute OCR text.

        输入：
            属性 OCR 文本和图标候选。
        输出：
            AttributeRerankResult。
        使用示例：
            result = reranker.rerank("伤害17x4 炮击65", candidates)
        """
        observed_tokens = tokenize_attribute_text(observed_text)
        if not observed_tokens:
            return AttributeRerankResult(False, "empty", "属性 OCR 文本为空。", observed_text=observed_text)
        if not icon_candidates:
            return AttributeRerankResult(False, "no_candidates", "没有图标候选可重排。", observed_text=observed_text, observed_tokens=tuple(observed_tokens))

        reranked: List[AttributeRerankCandidate] = []
        for candidate in icon_candidates:
            equipment_id = str(candidate.get("equipment_id", "") or "")
            if not equipment_id:
                continue
            index_item = self.equipment_index.get(equipment_id)
            if index_item is None:
                continue
            icon_confidence = float(candidate.get("confidence", 0.0) or 0.0)
            model_tokens = tuple(str(token) for token in index_item.get("tokens", []) if str(token))
            attribute_score, matched = self._score_tokens(observed_tokens, model_tokens)
            combined = (self.icon_weight * icon_confidence) + (self.attribute_weight * attribute_score)
            reranked.append(
                AttributeRerankCandidate(
                    equipment_id=equipment_id,
                    equipment_name=str(index_item.get("equipment_name", "") or candidate.get("equipment_name", "") or ""),
                    icon_confidence=icon_confidence,
                    attribute_score=attribute_score,
                    combined_score=combined,
                    matched_tokens=tuple(matched),
                )
            )

        if not reranked:
            return AttributeRerankResult(False, "no_indexed_candidates", "图标候选没有 Wiki 属性签名。", observed_text=observed_text, observed_tokens=tuple(observed_tokens))

        reranked.sort(key=lambda item: (item.combined_score, item.attribute_score, item.icon_confidence), reverse=True)
        best = reranked[0]
        second_score = reranked[1].combined_score if len(reranked) > 1 else 0.0
        margin = best.combined_score - second_score
        second_attribute_score = reranked[1].attribute_score if len(reranked) > 1 else 0.0
        attribute_margin = best.attribute_score - second_attribute_score
        has_specific_match = any(_token_has_specific_value(token) for token in best.matched_tokens)
        success = bool(
            best.attribute_score >= self.min_attribute_score
            and margin >= self.min_margin
            and attribute_margin >= self.min_margin
            and has_specific_match
        )
        status = "success" if success else "ambiguous"
        message = "属性签名重排完成。" if success else "属性签名差距不足或只有通用字段名，保持复核。"
        return AttributeRerankResult(
            success,
            status,
            message,
            selected_equipment_id=best.equipment_id,
            selected_equipment_name=best.equipment_name,
            attribute_score=best.attribute_score,
            combined_score=best.combined_score,
            margin=margin,
            attribute_margin=attribute_margin,
            observed_text=observed_text,
            observed_tokens=tuple(observed_tokens),
            candidates=tuple(reranked[: max(1, int(top_n))]),
        )

    def _score_tokens(self, observed_tokens: Sequence[str], model_tokens: Sequence[str]) -> Tuple[float, List[str]]:
        """Return normalized weighted overlap between OCR tokens and model tokens."""
        observed = set(observed_tokens)
        model = set(model_tokens)
        if not observed or not model:
            return 0.0, []
        matched = sorted(observed & model)
        if not matched:
            return 0.0, []
        numerator = sum(self.token_idf.get(token, 1.0) for token in matched)
        # 属性 OCR 通常只能读到局部字段；用 observed 作为分母更适合“读到的内容是否支持候选”。
        denominator = sum(self.token_idf.get(token, 1.0) for token in observed)
        if denominator <= 0:
            return 0.0, matched
        return max(0.0, min(1.0, numerator / denominator)), matched


# ============================================================
# 🌐 第四部分：工具函数
# ============================================================

def tokenize_attribute_text(text: str) -> List[str]:
    """
    Tokenize OCR text and Wiki signatures into comparable fragments.

    输入：
        OCR 文本或 Wiki 属性签名。
    输出：
        token 列表。
    使用示例：
        tokenize_attribute_text("伤害=17×4 炮击 65")
    """
    normalized = normalize_attribute_text(text)
    tokens: List[str] = []
    for part in re.split(r"[|,，;；:/：\s]+", normalized):
        part = part.strip()
        if not part:
            continue
        tokens.append(part)
        if "=" in part:
            label, value = part.split("=", 1)
            if label:
                tokens.append(label)
            if value:
                tokens.append(value)
    # PaddleOCR 有时会把 “炮击65” 连在一起；拆出汉字标签和数字值。
    for label, value in re.findall(r"([\u4e00-\u9fff]{2,})([0-9]+(?:\.[0-9]+)?(?:x[0-9]+)?(?:s/轮)?)", normalized):
        tokens.append(label)
        tokens.append(value)
        tokens.append(f"{label}={value}")
    return sorted(set(tokens))


def normalize_attribute_text(text: str) -> str:
    """Normalize common OCR/Wiki differences in attribute text."""
    value = str(text or "").lower()
    value = value.replace("×", "x").replace("／", "/").replace("：", "=").replace(":", "=")
    value = re.sub(r"(?<=[0-9])\s*x\s*(?=[0-9])", "x", value)
    value = re.sub(r"(?<=[0-9])\s*/\s*(?=轮)", "/", value)
    value = value.replace("标准射速", "标准射速")
    value = re.sub(r"([伤害炮击航空雷装防空命中机动耐久反潜]{2,})(?=[0-9])", r"\1=", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def format_attribute_candidates(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Format reranked candidates for CSV and review hints."""
    chunks: List[str] = []
    for candidate in candidates:
        equipment_id = str(candidate.get("equipment_id", "") or "")
        name = str(candidate.get("equipment_name", "") or "")
        attribute_score = float(candidate.get("attribute_score", 0.0) or 0.0)
        combined = float(candidate.get("combined_score", 0.0) or 0.0)
        chunks.append(f"{equipment_id}:{name}:attr={attribute_score:.3f}:combo={combined:.3f}")
    return " | ".join(chunks)


def _token_has_specific_value(token: str) -> bool:
    """
    Return True when a matched token contains discriminative value information.

    输入：
        token。
    输出：
        True 表示包含数字、弹药/技能等具体信息。
    使用示例：
        _token_has_specific_value("标准射速") == False
        _token_has_specific_value("标准射速=3.43s/轮") == True
    """
    value = str(token or "")
    if re.search(r"\d", value):
        return True
    if "=" in value and len(value.split("=", 1)[1]) >= 2:
        return True
    return False
