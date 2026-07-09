#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        📊 科研进度分析器 (research_progress_analyzer.py)      ║
║                                                              ║
║  【一句话解释】把科研期、用户记录、碎片等值和欧非值整理成 GUI 可展示进度。║
║  【类比理解】它像科研档案板，把每期装备的完成度和运气评价排成清单。║
║  【数据流说明】research_phases + user_records → 进度汇总 → GUI。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import math
from typing import Any, Dict, List, Optional

from core.calculation.fragment_calculator import get_fragment_calculator
from core.calculation.luck_calculator import get_luck_calculator
from core.calculation.user_data_manager import get_user_data_manager
from core.data.research_manager import get_research_manager
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

class ResearchProgressAnalyzer:
    """
    科研进度分析器。
    输入：
        可选科研期数、日期或显式用户数据。
    输出：
        面向 GUI 的进度汇总和装备明细。
    使用示例：
        summary = get_research_progress_analyzer().get_phase_progress(1)
    """

    _instance: Optional["ResearchProgressAnalyzer"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "ResearchProgressAnalyzer":
        """单例模式：全局共享一个科研进度分析器。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化分析器，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self._research_manager = None
        self._fragment_calculator = None
        self._luck_calculator = None
        self._user_data_manager = None
        self._initialized = True

    @property
    def research_manager(self):
        """延迟加载科研期管理器。"""
        if self._research_manager is None:
            self._research_manager = get_research_manager()
        return self._research_manager

    @property
    def fragment_calculator(self):
        """延迟加载碎片等值计算器。"""
        if self._fragment_calculator is None:
            self._fragment_calculator = get_fragment_calculator()
        return self._fragment_calculator

    @property
    def luck_calculator(self):
        """延迟加载欧非值计算器。"""
        if self._luck_calculator is None:
            self._luck_calculator = get_luck_calculator()
        return self._luck_calculator

    @property
    def user_data_manager(self):
        """延迟加载用户数据管理器。"""
        if self._user_data_manager is None:
            self._user_data_manager = get_user_data_manager()
        return self._user_data_manager

    def get_latest_phase_number(self) -> int:
        """
        获取当前数据中最新科研期数。
        输入：
            无。
        输出：
            int: 最新期数；无数据时返回 0。
        使用示例：
            latest = analyzer.get_latest_phase_number()
        """
        phases = self.research_manager.get_all()
        return max((int(phase.get("phase_number", 0)) for phase in phases), default=0)

    def get_phase_progress(
        self,
        phase_number: Optional[int] = None,
        target_date: Optional[str] = None,
        input_data: Optional[Dict[str, Dict[str, int]]] = None,
        rainbow_target_count: int = 2,
    ) -> Dict[str, Any]:
        """
        获取某一期科研进度。
        输入：
            phase_number: 可选科研期数；不传时默认最新期。
            target_date: 可选用户记录日期。
            input_data: 可选显式用户数据，优先级高于 target_date。
            rainbow_target_count: 用户本期想完成的彩色科研装备数量。
        输出：
            dict: 包含期数、是否最新、汇总、欧非值和装备明细。
        使用示例：
            progress = analyzer.get_phase_progress(phase_number=1)
        """
        latest_phase = self.get_latest_phase_number()
        selected_phase = int(phase_number or latest_phase)
        if selected_phase <= 0:
            return self._empty_result(selected_phase, latest_phase, "科研期数据尚未加载")

        phase = self.research_manager.get_by_phase(selected_phase)
        if not phase:
            return self._empty_result(selected_phase, latest_phase, f"科研 {selected_phase} 期不存在")

        scoped_input = input_data if input_data is not None else self._load_input_data(target_date)
        phase_result = self.fragment_calculator.calculate_by_phase(selected_phase, scoped_input)
        luck_result = self.luck_calculator.calculate_phase_luck(selected_phase, scoped_input)
        equipment_rows = [
            self._build_equipment_row(item)
            for item in phase_result.get("equipments", [])
        ]
        completed_count = sum(1 for item in equipment_rows if item["is_completed"])
        total_count = len(equipment_rows)
        average_progress = self._average_progress(equipment_rows)
        rainbow_total = self._sum_score_by_rarity(equipment_rows, 5)
        gold_total = self._sum_score_by_rarity(equipment_rows, 4)
        target_count = max(1, min(20, int(rainbow_target_count)))
        target_fragments = target_count * 50
        target_progress = self._calculate_target_progress(rainbow_total, target_fragments)

        return {
            "phase_number": selected_phase,
            "phase_name": phase.get("name", f"科研 {selected_phase} 期"),
            "latest_phase": latest_phase,
            "is_latest": selected_phase == latest_phase,
            "equipment_total": total_count,
            "completed_count": completed_count,
            "overall_progress": target_progress,
            "average_equipment_progress": average_progress,
            "rainbow_target_count": target_count,
            "rainbow_target_fragments": target_fragments,
            "rainbow_total": rainbow_total,
            "gold_total": gold_total,
            "gold_rainbow_ratio": self._calculate_gold_rainbow_ratio(gold_total, rainbow_total),
            "total_score": int(phase_result.get("total_score", 0)),
            "luck_value": self._normalize_luck_value(luck_result.get("luck_value")),
            "luck_level": luck_result.get("luck_level", "未知"),
            "equipment_rows": equipment_rows,
            "message": "",
        }

    def _load_input_data(self, target_date: Optional[str]) -> Dict[str, Dict[str, int]]:
        """按日期读取用户记录；日期为空时读取今日记录。"""
        if target_date:
            return self.user_data_manager.get_data_by_date(target_date)
        return self.user_data_manager.get_today_data()

    def _build_equipment_row(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """把 FragmentCalculator 单件结果转换成 GUI 进度行。"""
        equipment_count = int(item.get("equipment_count", 0))
        fragment_count = int(item.get("fragment_count", 0))
        equivalent = item.get("equivalent")
        score = item.get("score")
        progress = self._calculate_item_progress(equipment_count, fragment_count, equivalent)
        return {
            "equipment_name": item.get("equipment_name", "未知装备"),
            "rarity_name": item.get("rarity_name", "未知"),
            "rarity_id": item.get("rarity_id"),
            "category": item.get("category", "未知"),
            "equipment_count": equipment_count,
            "fragment_count": fragment_count,
            "equivalent": equivalent,
            "score": score,
            "progress": progress,
            "is_completed": equipment_count > 0,
        }

    @staticmethod
    def _calculate_item_progress(
        equipment_count: int,
        fragment_count: int,
        equivalent: Optional[int],
    ) -> int:
        """计算单件装备合成进度百分比。"""
        if equipment_count > 0:
            return 100
        if equivalent is None or int(equivalent) <= 0:
            return 0
        return max(0, min(100, round(int(fragment_count) / int(equivalent) * 100)))

    @staticmethod
    def _average_progress(equipment_rows: List[Dict[str, Any]]) -> int:
        """计算当前科研期平均装备进度。"""
        if not equipment_rows:
            return 0
        return round(sum(int(row.get("progress", 0)) for row in equipment_rows) / len(equipment_rows))

    @staticmethod
    def _sum_score_by_rarity(equipment_rows: List[Dict[str, Any]], rarity_id: int) -> int:
        """按稀有度汇总等效碎片总量。"""
        total = 0
        for row in equipment_rows:
            if int(row.get("rarity_id") or 0) != rarity_id:
                continue
            score = row.get("score")
            if score is not None:
                total += int(score)
        return total

    @staticmethod
    def _calculate_target_progress(current_fragments: int, target_fragments: int) -> float:
        """按用户目标彩装数量计算总体进度百分比，保留两位小数。"""
        if target_fragments <= 0:
            return 0.0
        progress = int(current_fragments) / int(target_fragments) * 100
        return round(max(0.0, min(100.0, progress)), 2)

    @staticmethod
    def _calculate_gold_rainbow_ratio(gold_total: int, rainbow_total: int) -> Optional[float]:
        """计算金彩装备比：金色等效碎片总量 / 彩色等效碎片总量。"""
        if rainbow_total <= 0:
            return None
        return round(int(gold_total) / int(rainbow_total), 3)

    @staticmethod
    def _normalize_luck_value(value: object) -> Optional[float]:
        """把无穷欧非值转成 None，避免 GUI 表示异常。"""
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return None if math.isinf(numeric) else numeric

    @staticmethod
    def _empty_result(phase_number: int, latest_phase: int, message: str) -> Dict[str, Any]:
        """构建无数据或无效期数时的稳定返回结构。"""
        return {
            "phase_number": phase_number,
            "phase_name": "未知科研期",
            "latest_phase": latest_phase,
            "is_latest": phase_number == latest_phase and latest_phase > 0,
            "equipment_total": 0,
            "completed_count": 0,
            "overall_progress": 0.0,
            "average_equipment_progress": 0,
            "rainbow_target_count": 0,
            "rainbow_target_fragments": 0,
            "rainbow_total": 0,
            "gold_total": 0,
            "gold_rainbow_ratio": None,
            "total_score": 0,
            "luck_value": None,
            "luck_level": "未知",
            "equipment_rows": [],
            "message": message,
        }


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_research_progress_analyzer: Optional[ResearchProgressAnalyzer] = None


def get_research_progress_analyzer() -> ResearchProgressAnalyzer:
    """
    获取全局科研进度分析器。
    输入：
        无。
    输出：
        ResearchProgressAnalyzer: 全局共享实例。
    使用示例：
        analyzer = get_research_progress_analyzer()
    """
    global _research_progress_analyzer
    if _research_progress_analyzer is None:
        _research_progress_analyzer = ResearchProgressAnalyzer()
    return _research_progress_analyzer
