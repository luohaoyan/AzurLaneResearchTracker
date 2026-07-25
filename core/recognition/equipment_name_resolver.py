#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        装备名称解析器 (equipment_name_resolver.py)           ║
║  【一句话解释】把 OCR 读到的装备名片段解析成当前装备库条目。   ║
║  【类比理解】像给图标识别配一位“读铭牌”的助手，帮它排除同脸。║
║  【数据流】OCR 文本/候选 ID → 名称规范化/模糊匹配 → 装备条目。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import csv
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.utils.path_manager import PathManager


# ============================================================
# 🧱 第二部分：结果对象
# ============================================================

EquipmentCatalog = Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class EquipmentNameCandidate:
    """
    单个装备名称候选。

    输入：
        equipment_id/equipment_name/score/reason。
    输出：
        可序列化候选结果。
    使用示例：
        candidate = EquipmentNameCandidate("G0001", "液压弹射装置#T3", 0.98, "base_exact")
    """

    equipment_id: str
    equipment_name: str
    score: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """转换成 JSON/CSV 友好的字典。"""
        return {
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment_name,
            "score": float(self.score),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EquipmentNameResolveResult:
    """
    装备名称解析结果。

    输入：
        OCR 文本和可选图标候选 ID。
    输出：
        当前装备库中的装备 ID/名称，以及是否需要继续人工复核。
    使用示例：
        result = resolver.resolve("液压弹射装置", candidate_equipment_ids=["G0001"])
    """

    success: bool
    status: str
    message: str
    equipment_id: str = ""
    equipment_name: str = ""
    score: float = 0.0
    normalized_text: str = ""
    candidates: Tuple[EquipmentNameCandidate, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换成可序列化字典。"""
        return {
            "success": bool(self.success),
            "status": self.status,
            "message": self.message,
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment_name,
            "score": float(self.score),
            "normalized_text": self.normalized_text,
            "candidates": [item.to_dict() for item in self.candidates],
        }


# ============================================================
# 🏗️ 第三部分：名称解析器
# ============================================================

class EquipmentNameResolver:
    """
    装备名称 OCR 解析器。

    输入：
        equipment_library.csv、或测试/训练脚本注入的 catalog。
    输出：
        EquipmentNameResolveResult。
    使用示例：
        resolver = EquipmentNameResolver()
        result = resolver.resolve("试作型三联装152mm主炮", candidate_equipment_ids=["S5-001"])
    """

    DEFAULT_MIN_SCORE = 0.66
    DEFAULT_AMBIGUOUS_MARGIN = 0.045
    DEFAULT_MIN_QUERY_LENGTH = 4
    GENERIC_SHORT_TEXTS = frozenset({"设备", "装备", "设计图", "图纸", "材料"})
    OCR_DISPLAY_NAME_ALIASES: Tuple[Tuple[str, str], ...] = (
        ("赫尔卡特", "f6f地狱猫"),
        ("赫尔卡特战斗机", "f6f地狱猫"),
        ("赫尔卡特战斗", "f6f地狱猫"),
    )

    def __init__(
        self,
        catalog: Optional[EquipmentCatalog] = None,
        project_root: Optional[str | Path] = None,
        library_csv_path: Optional[str | Path] = None,
        min_score: float = DEFAULT_MIN_SCORE,
        ambiguous_margin: float = DEFAULT_AMBIGUOUS_MARGIN,
        min_query_length: int = DEFAULT_MIN_QUERY_LENGTH,
    ) -> None:
        """初始化名称索引；默认只读 data/equipment_library.csv。"""
        self.project_root = Path(project_root) if project_root is not None else PathManager.get_project_root()
        self.library_csv_path = (
            Path(library_csv_path)
            if library_csv_path is not None
            else self.project_root / "data" / "equipment_library.csv"
        )
        self.min_score = float(min_score)
        self.ambiguous_margin = float(ambiguous_margin)
        self.min_query_length = max(1, int(min_query_length))
        self._rows = self._rows_from_catalog(catalog) if catalog is not None else self._load_library_rows()
        self._row_by_id = {row["equipment_id"]: row for row in self._rows}

    @classmethod
    def from_catalog(
        cls,
        catalog: EquipmentCatalog,
        min_score: float = DEFAULT_MIN_SCORE,
        ambiguous_margin: float = DEFAULT_AMBIGUOUS_MARGIN,
        min_query_length: int = DEFAULT_MIN_QUERY_LENGTH,
    ) -> "EquipmentNameResolver":
        """从已经加载好的装备 catalog 构建解析器，避免重复读 CSV。"""
        return cls(
            catalog=catalog,
            min_score=min_score,
            ambiguous_margin=ambiguous_margin,
            min_query_length=min_query_length,
        )

    def check_status(self) -> Dict[str, Any]:
        """检查名称解析器是否有可用装备条目。"""
        return {
            "available": bool(self._rows),
            "library_csv_path": str(self.library_csv_path),
            "equipment_count": len(self._rows),
            "min_score": self.min_score,
            "ambiguous_margin": self.ambiguous_margin,
            "min_query_length": self.min_query_length,
        }

    def resolve(
        self,
        raw_text: str,
        candidate_equipment_ids: Optional[Sequence[str]] = None,
        min_score: Optional[float] = None,
    ) -> EquipmentNameResolveResult:
        """
        把 OCR 名称文本解析为装备库条目。

        输入：
            raw_text: OCR 读到的装备名，可缺少 #T3 或包含空格/标点噪声。
            candidate_equipment_ids: 图标匹配 top-N 候选；传入后优先在候选里消歧。
            min_score: 本次解析的最低相似度阈值。
        输出：
            EquipmentNameResolveResult。
        使用示例：
            resolver.resolve("四联40mm博福斯对空机炮", ["G0123", "G0456"])
        """
        normalized_text = normalize_equipment_name(raw_text)
        if not normalized_text:
            return EquipmentNameResolveResult(False, "empty", "OCR 名称文本为空。")
        if not self._rows:
            return EquipmentNameResolveResult(False, "no_catalog", "装备名称索引为空。", normalized_text=normalized_text)

        threshold = self.min_score if min_score is None else float(min_score)
        candidate_ids = self._unique_ids(candidate_equipment_ids or ())
        if self._is_too_short_or_generic(normalized_text):
            exact_short_result = self._resolve_short_exact_name(normalized_text, candidate_ids)
            if exact_short_result is not None:
                return exact_short_result
            return EquipmentNameResolveResult(
                False,
                "too_short",
                "OCR 名称文本过短或过于泛化，已跳过名称辅助，避免误消歧。",
                normalized_text=normalized_text,
            )
        if candidate_ids:
            scoped_rows = [self._row_by_id[equipment_id] for equipment_id in candidate_ids if equipment_id in self._row_by_id]
            scoped = self._resolve_in_rows(normalized_text, scoped_rows, threshold, scope="icon_candidates")
            if scoped.status not in {"unresolved"}:
                return scoped

            # 如果图标 top-N 里找不到文本对应项，只允许全局精确/强匹配返回；
            # 这能暴露“图标候选和名称 OCR 冲突”，但不会悄悄覆盖图标结果。
            global_result = self._resolve_in_rows(normalized_text, self._rows, 0.92, scope="global")
            if global_result.success:
                return EquipmentNameResolveResult(
                    True,
                    "outside_icon_candidates",
                    "名称可解析，但不在图标 top-N 候选中，需要人工确认是否图标候选漏召回。",
                    global_result.equipment_id,
                    global_result.equipment_name,
                    global_result.score,
                    normalized_text,
                    global_result.candidates,
                )
            return scoped

        return self._resolve_in_rows(normalized_text, self._rows, threshold, scope="global")

    def _resolve_short_exact_name(
        self,
        normalized_text: str,
        candidate_ids: Sequence[str],
    ) -> Optional[EquipmentNameResolveResult]:
        """
        短名称只允许“带 #T 等级的完整精确命中”通过。

        输入：
            normalized_text: 已规范化的 OCR/人工名称。
            candidate_ids: 图标 top-N 候选 ID。
        输出：
            精确解析结果；无法精确命中时返回 None。
        使用示例：
            resolver.resolve("剑鱼#T3") 可以命中；resolver.resolve("剑鱼") 仍会 too_short。
        """
        if re.search(r"#t[0-9]+$", normalized_text, flags=re.IGNORECASE) is None:
            return None

        scoped_rows = [self._row_by_id[equipment_id] for equipment_id in candidate_ids if equipment_id in self._row_by_id]
        scoped_exact = self._find_exact_name_match(normalized_text, scoped_rows)
        if scoped_exact is not None:
            return scoped_exact

        global_exact = self._find_exact_name_match(normalized_text, self._rows)
        if global_exact is None:
            return None
        if scoped_rows:
            return EquipmentNameResolveResult(
                True,
                "outside_icon_candidates",
                "短装备名可精确解析，但不在图标 top-N 候选中，需要人工确认是否图标候选漏召回。",
                global_exact.equipment_id,
                global_exact.equipment_name,
                global_exact.score,
                normalized_text,
                global_exact.candidates,
            )
        return global_exact

    def _find_exact_name_match(
        self,
        normalized_text: str,
        rows: Sequence[Mapping[str, str]],
    ) -> Optional[EquipmentNameResolveResult]:
        """在给定装备行中寻找规范化后完全相等的装备名。"""
        exact_matches: List[EquipmentNameCandidate] = []
        for row in rows:
            equipment_id = str(row.get("equipment_id", "") or "").strip()
            equipment_name = str(row.get("name", "") or "").strip()
            if not equipment_id or not equipment_name:
                continue
            if normalized_text == normalize_equipment_name(equipment_name):
                exact_matches.append(EquipmentNameCandidate(equipment_id, equipment_name, 1.0, "exact"))
        if not exact_matches:
            return None
        if len(exact_matches) > 1:
            return EquipmentNameResolveResult(
                False,
                "ambiguous",
                "短装备名精确匹配到多个装备 ID，需要人工确认。",
                normalized_text=normalized_text,
                candidates=tuple(exact_matches[:5]),
            )
        top = exact_matches[0]
        return EquipmentNameResolveResult(
            True,
            "global_exact",
            "短装备名带 #T 等级，已按完整装备名精确解析。",
            top.equipment_id,
            top.equipment_name,
            top.score,
            normalized_text,
            tuple(exact_matches[:5]),
        )

    def _resolve_in_rows(
        self,
        normalized_text: str,
        rows: Sequence[Mapping[str, str]],
        threshold: float,
        scope: str,
    ) -> EquipmentNameResolveResult:
        """在给定装备行集合中按名称打分并解析。"""
        if not rows:
            return EquipmentNameResolveResult(False, "unresolved", "没有可用于名称解析的候选装备。", normalized_text=normalized_text)

        ranked = self._rank_rows(normalized_text, rows)
        if not ranked:
            return EquipmentNameResolveResult(False, "unresolved", "装备名称没有达到最低相似度。", normalized_text=normalized_text)

        top = ranked[0]
        if top.score < threshold:
            return EquipmentNameResolveResult(
                False,
                "unresolved",
                f"最高名称相似度 {top.score:.3f} 低于阈值 {threshold:.3f}。",
                normalized_text=normalized_text,
                candidates=tuple(ranked[:5]),
            )

        second = self._first_distinct_name_candidate(ranked, top.equipment_id)
        second_score = second.score if second is not None else 0.0
        if top.reason == "exact" and (second is None or second.reason != "exact"):
            return EquipmentNameResolveResult(
                True,
                f"{scope}_{top.reason}",
                "装备名称精确解析完成。",
                top.equipment_id,
                top.equipment_name,
                top.score,
                normalized_text,
                tuple(ranked[:5]),
            )
        if second is not None and top.score - second_score < self.ambiguous_margin:
            return EquipmentNameResolveResult(
                False,
                "ambiguous",
                f"名称候选分差 {top.score - second_score:.3f} 过小，避免错认。",
                normalized_text=normalized_text,
                candidates=tuple(ranked[:5]),
            )

        return EquipmentNameResolveResult(
            True,
            f"{scope}_{top.reason}",
            "装备名称解析完成。",
            top.equipment_id,
            top.equipment_name,
            top.score,
            normalized_text,
            tuple(ranked[:5]),
        )

    def _rank_rows(
        self,
        normalized_text: str,
        rows: Sequence[Mapping[str, str]],
    ) -> List[EquipmentNameCandidate]:
        """对装备名称行打分并排序。"""
        ranked: List[EquipmentNameCandidate] = []
        for row in rows:
            equipment_id = str(row.get("equipment_id", "") or "").strip()
            equipment_name = str(row.get("name", "") or "").strip()
            if not equipment_id or not equipment_name:
                continue
            score, reason = self._score_name(normalized_text, equipment_name)
            ranked.append(EquipmentNameCandidate(equipment_id, equipment_name, score, reason))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    @classmethod
    def _score_name(cls, normalized_text: str, equipment_name: str) -> Tuple[float, str]:
        """计算 OCR 文本和装备名的保守相似度。"""
        full = normalize_equipment_name(equipment_name)
        base = normalize_equipment_base_name(equipment_name)
        query_base = strip_tier_suffix(normalized_text)
        alias_score = cls._score_display_alias(normalized_text, full, base)
        if normalized_text == full:
            return 1.0, "exact"
        if normalized_text == base or query_base == base:
            return 0.965, "base_exact"
        if alias_score > 0.0:
            return alias_score, "display_alias"
        if full and normalized_text in full:
            return cls._contained_score(normalized_text, full), "contains_full"
        if base and normalized_text in base:
            return cls._contained_score(normalized_text, base), "contains_base"
        if query_base and base and (query_base in base or base in query_base):
            return cls._contained_score(query_base, base), "contains_base"

        full_score = SequenceMatcher(None, normalized_text, full).ratio() if full else 0.0
        base_score = SequenceMatcher(None, query_base or normalized_text, base).ratio() if base else 0.0
        confusion_full_score = cls._ocr_confusion_ratio(normalized_text, full) * 0.90 if full else 0.0
        confusion_base_score = cls._ocr_confusion_ratio(query_base or normalized_text, base) * 0.92 if base else 0.0
        confusion_score = max(confusion_full_score, confusion_base_score)
        if confusion_score > max(full_score * 0.92, base_score * 0.94):
            return confusion_score, "ocr_confusable"
        if base_score >= full_score:
            return base_score * 0.94, "fuzzy_base"
        return full_score * 0.92, "fuzzy_full"

    @classmethod
    def _score_display_alias(cls, normalized_text: str, full: str, base: str) -> float:
        """
        根据游戏内显示别名给保守加分。

        输入：
            OCR 规范化文本、装备完整名和基础名。
        输出：
            命中别名时的名称分；未命中返回 0。
        使用示例：
            “赫尔卡特战斗”可以辅助指向“F6F地狱猫”。
        """
        if not normalized_text:
            return 0.0
        for alias, target in cls.OCR_DISPLAY_NAME_ALIASES:
            alias_key = normalize_equipment_name(alias)
            target_key = normalize_equipment_name(target)
            if not alias_key or not target_key:
                continue
            if alias_key not in normalized_text:
                continue
            if target_key == full or target_key == base or target_key in full or target_key in base:
                return 0.925
        return 0.0

    @staticmethod
    def _ocr_confusion_ratio(left: str, right: str) -> float:
        """
        用 OCR 混淆骨架计算英文/数字混排装备名相似度。

        输入：
            已规范化名称，例如 “je-87c” 和 “ju-87c”。
        输出：
            SequenceMatcher 相似度；无英文数字特征时返回 0。
        使用示例：
            _ocr_confusion_ratio("je87c", "ju87c") 接近 1。
        """
        left_skeleton = normalize_ocr_confusion_skeleton(left)
        right_skeleton = normalize_ocr_confusion_skeleton(right)
        if not left_skeleton or not right_skeleton:
            return 0.0
        if not re.search(r"[a-z0-9]", left_skeleton, flags=re.IGNORECASE):
            return 0.0
        return SequenceMatcher(None, left_skeleton, right_skeleton).ratio()

    @staticmethod
    def _contained_score(shorter: str, longer: str) -> float:
        """给包含关系一个高分，但按缺失字符比例略微扣分。"""
        if not shorter or not longer:
            return 0.0
        ratio = min(len(shorter), len(longer)) / float(max(len(shorter), len(longer)))
        return max(0.0, min(0.955, 0.88 + ratio * 0.075))

    @staticmethod
    def _first_distinct_name_candidate(
        ranked: Sequence[EquipmentNameCandidate],
        equipment_id: str,
    ) -> Optional[EquipmentNameCandidate]:
        """找到第一个不同装备 ID 的名称候选。"""
        for candidate in ranked:
            if candidate.equipment_id != equipment_id:
                return candidate
        return None

    @staticmethod
    def _unique_ids(values: Iterable[str]) -> Tuple[str, ...]:
        """保序去重装备 ID。"""
        seen: set[str] = set()
        result: List[str] = []
        for value in values:
            equipment_id = str(value or "").strip()
            if not equipment_id or equipment_id in seen or equipment_id == "unknown":
                continue
            seen.add(equipment_id)
            result.append(equipment_id)
        return tuple(result)

    def _is_too_short_or_generic(self, normalized_text: str) -> bool:
        """过滤“设备/装备”这类太短、太泛的 OCR 文本。"""
        base = strip_tier_suffix(normalized_text)
        if base in self.GENERIC_SHORT_TEXTS:
            return True
        meaningful = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", base)
        return len(meaningful) < self.min_query_length

    def _load_library_rows(self) -> List[Dict[str, str]]:
        """只读加载 equipment_library.csv。"""
        if not self.library_csv_path.exists():
            return []
        with self.library_csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            return [
                {
                    "equipment_id": str(row.get("equipment_id", "") or "").strip(),
                    "name": str(row.get("name", "") or "").strip(),
                }
                for row in csv.DictReader(file)
            ]

    @staticmethod
    def _rows_from_catalog(catalog: EquipmentCatalog) -> List[Dict[str, str]]:
        """从训练脚本已加载的 catalog 中抽取名称索引。"""
        rows: List[Dict[str, str]] = []
        for equipment_id, item in catalog.items():
            name = str(item.get("name", "") or "").strip()
            if equipment_id and name:
                rows.append({"equipment_id": str(equipment_id), "name": name})
        return rows


# ============================================================
# 🌐 第四部分：名称规范化函数
# ============================================================

def strip_leading_equipment_id(name: str) -> str:
    """
    去掉人工标注或 OCR 文本前面误带的装备 ID。

    输入：
        "G0123 液压弹射装置#T3"。
    输出：
        "液压弹射装置#T3"。
    使用示例：
        strip_leading_equipment_id("S4-005 试作舰载型天雷#T0")
    """
    return re.sub(r"^(?:G\d{4}|S\d+-\d{1,3})\s+", "", str(name or "").strip(), flags=re.IGNORECASE)


def normalize_equipment_name(name: str) -> str:
    """
    规范化装备名，消除空格、全角符号和普通标点差异。

    输入：
        OCR 文本或 equipment_library.csv 名称。
    输出：
        适合比较的紧凑字符串。
    使用示例：
        normalize_equipment_name(" 试作型三联装 152mm 主炮 #T0 ")
    """
    text = unicodedata.normalize("NFKC", strip_leading_equipment_id(name))
    text = text.replace("＃", "#").replace("﹟", "#")
    text = text.replace("—", "-").replace("–", "-").replace("＋", "+")
    text = re.sub(r"\s+", "", text)
    compact = "".join(re.findall(r"[0-9A-Za-z#\+\-\u4e00-\u9fff]+", text)).lower()
    return strip_tier_noise(compact)


def normalize_ocr_confusion_skeleton(name: str) -> str:
    """
    生成英文 OCR 易混字符骨架。

    输入：
        OCR 文本或装备名。
    输出：
        将 u/e/v/c、o/0、i/l/1 等相近字符压到同一骨架后的字符串。
    使用示例：
        normalize_ocr_confusion_skeleton("J e-87C") == normalize_ocr_confusion_skeleton("Ju-87C")
    """
    normalized = normalize_equipment_name(name)
    translation = str.maketrans(
        {
            "0": "o",
            "1": "i",
            "l": "i",
            "u": "e",
            "v": "e",
            "c": "e",
        }
    )
    return normalized.translate(translation)


def strip_tier_noise(normalized_name: str) -> str:
    """
    去掉 #T3 后误输入的短英文尾巴。

    输入：
        "双联装128mmskc41高平两用炮#t3sa"。
    输出：
        "双联装128mmskc41高平两用炮#t3"。
    使用示例：
        strip_tier_noise("液压弹射装置#t3x")
    """
    return re.sub(r"(#t[0-9]+)[a-z]{1,3}$", r"\1", str(normalized_name or ""), flags=re.IGNORECASE)


def strip_tier_suffix(normalized_name: str) -> str:
    """
    去掉 #T0/#T1/#T2/#T3 后缀，便于设计图页面短名称匹配。

    输入：
        规范化后的装备名。
    输出：
        去掉装备等级后缀的基础名。
    使用示例：
        strip_tier_suffix("液压弹射装置#t3")
    """
    return re.sub(r"#?t[0-9]+$", "", str(normalized_name or "").strip(), flags=re.IGNORECASE)


def normalize_equipment_base_name(name: str) -> str:
    """规范化装备基础名；主要用于 OCR 只读到短名称时消歧。"""
    return strip_tier_suffix(normalize_equipment_name(name))


# ============================================================
# 🌐 第五部分：全局访问函数
# ============================================================

_equipment_name_resolver_instance: Optional[EquipmentNameResolver] = None


def get_equipment_name_resolver() -> EquipmentNameResolver:
    """获取装备名称解析器单例。"""
    global _equipment_name_resolver_instance
    if _equipment_name_resolver_instance is None:
        _equipment_name_resolver_instance = EquipmentNameResolver()
    return _equipment_name_resolver_instance
