#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              📈 历史趋势分析器 (trend_analyzer.py)           ║
║                                                              ║
║  【一句话解释】把每日用户记录转换成 GUI 可展示的趋势序列。     ║
║  【类比理解】它像港区档案员，把每天的装备日记整理成折线图材料。║
║  【数据流说明】user_records CSV → 趋势统计 → UI 表格/图表。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from core.calculation.fragment_calculator import get_fragment_calculator
from core.calculation.luck_calculator import get_luck_calculator
from core.calculation.user_data_manager import get_user_data_manager
from core.data.research_manager import get_research_manager
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class TrendMetricSpec:
    """
    趋势指标定义。
    输入：
        key: 程序内部用于取值的稳定键。
        title: GUI 展示给用户看的名称。
        color: 折线图颜色。
    输出：
        不可变指标配置对象。
    使用示例：
        spec = TrendMetricSpec("equipment_count", "装备数量", "#58D7FF")
    """

    key: str
    title: str
    color: str


TREND_METRICS: Dict[str, TrendMetricSpec] = {
    "equipment_count": TrendMetricSpec("equipment_count", "装备数量", "#58D7FF"),
    "fragment_count": TrendMetricSpec("fragment_count", "碎片总量", "#F6B3D0"),
    "equivalent_score": TrendMetricSpec("equivalent_score", "等值分", "#B8F09A"),
    "luck_value": TrendMetricSpec("luck_value", "欧非值", "#F7D56B"),
}

class TrendAnalyzer:
    """
    历史趋势分析器。
    输入：
        无，内部延迟加载用户数据、科研期、碎片计算和欧非值计算管理器。
    输出：
        按日期排序的趋势点列表，供 GUI 表格和后续 QtCharts 使用。
    使用示例：
        analyzer = get_trend_analyzer()
        rows = analyzer.get_trend(phase_number=1)
    """

    _instance: Optional["TrendAnalyzer"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "TrendAnalyzer":
        """单例模式：全局共享一个趋势分析器。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化趋势分析器，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self._user_data_manager = None
        self._research_manager = None
        self._fragment_calculator = None
        self._luck_calculator = None
        self._initialized = True

    @property
    def user_data_manager(self):
        """延迟加载用户数据管理器。"""
        if self._user_data_manager is None:
            self._user_data_manager = get_user_data_manager()
        return self._user_data_manager

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

    def get_available_date_range(self) -> Dict[str, Optional[str]]:
        """
        获取当前历史记录的日期范围。
        输入：
            无。
        输出：
            dict: {"start": 最早日期或 None, "end": 最晚日期或 None, "count": 日期数}
        使用示例：
            date_range = analyzer.get_available_date_range()
        """
        dates = self.user_data_manager.list_available_dates()
        if not dates:
            return {"start": None, "end": None, "count": 0}
        return {"start": dates[0], "end": dates[-1], "count": len(dates)}

    def get_trend(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phase_number: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取历史趋势点。
        输入：
            start_date: 可选开始日期，格式 YYYY-MM-DD。
            end_date: 可选结束日期，格式 YYYY-MM-DD。
            phase_number: 可选科研期；不传时统计全部装备记录。
        输出：
            List[dict]: 每个元素包含 date、equipment_count、fragment_count、equivalent_score、luck_value 等字段。
        使用示例：
            rows = analyzer.get_trend("2026-07-01", "2026-07-08", 1)
        """
        self._validate_optional_date(start_date)
        self._validate_optional_date(end_date)
        if start_date and end_date and start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")

        rows: List[Dict[str, Any]] = []
        for date_str in self._filter_dates(start_date, end_date):
            day_data = self.user_data_manager.get_data_by_date(date_str)
            scoped_data = self._filter_by_phase(day_data, phase_number)
            luck_result = self._calculate_luck(scoped_data, phase_number)
            rows.append({
                "date": date_str,
                "phase_number": phase_number,
                "equipment_count": self._sum_equipment_count(scoped_data),
                "fragment_count": self._sum_fragment_count(scoped_data),
                "equivalent_score": self._calculate_equivalent_score(scoped_data, phase_number),
                "luck_value": luck_result["luck_value"],
                "luck_level": luck_result["luck_level"],
            })
        return rows

    def get_metric_series(
        self,
        metric: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phase_number: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取单个指标的折线序列。
        输入：
            metric: equipment_count / fragment_count / equivalent_score / luck_value。
            start_date: 可选开始日期。
            end_date: 可选结束日期。
            phase_number: 可选科研期。
        输出：
            List[dict]: [{"date": "YYYY-MM-DD", "value": 数值或 None}, ...]
        使用示例：
            series = analyzer.get_metric_series("equipment_count", phase_number=1)
        """
        if metric not in TREND_METRICS:
            raise ValueError(f"未知趋势指标: {metric}")
        return [
            {"date": row["date"], "value": row.get(metric)}
            for row in self.get_trend(start_date, end_date, phase_number)
        ]

    def get_multi_metric_series(
        self,
        metrics: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phase_number: Optional[int] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取多个指标的折线序列。
        输入：
            metrics: 指标键列表，可包含装备数量、碎片总量、等值分和欧非值。
            start_date: 可选开始日期。
            end_date: 可选结束日期。
            phase_number: 可选科研期。
        输出：
            dict: {"指标键": [{"date": "YYYY-MM-DD", "value": 数值或 None}, ...]}
        使用示例：
            series_map = analyzer.get_multi_metric_series(["equipment_count", "luck_value"])
        """
        unknown_metrics = [metric for metric in metrics if metric not in TREND_METRICS]
        if unknown_metrics:
            raise ValueError(f"未知趋势指标: {', '.join(unknown_metrics)}")

        rows = self.get_trend(start_date, end_date, phase_number)
        return {
            metric: [{"date": row["date"], "value": row.get(metric)} for row in rows]
            for metric in metrics
        }

    def get_metric_specs(self) -> List[TrendMetricSpec]:
        """
        获取可展示的趋势指标定义。
        输入：
            无。
        输出：
            List[TrendMetricSpec]: 按 GUI 推荐顺序排列的指标定义。
        使用示例：
            specs = analyzer.get_metric_specs()
        """
        return list(TREND_METRICS.values())

    def _filter_dates(self, start_date: Optional[str], end_date: Optional[str]) -> List[str]:
        """按起止日期筛选可用历史日期。"""
        dates = self.user_data_manager.list_available_dates()
        return [
            date_str for date_str in dates
            if (start_date is None or date_str >= start_date)
            and (end_date is None or date_str <= end_date)
        ]

    def _filter_by_phase(
        self,
        day_data: Dict[str, Dict[str, int]],
        phase_number: Optional[int],
    ) -> Dict[str, Dict[str, int]]:
        """按科研期筛选某天记录；不传期数时返回全部记录。"""
        if phase_number is None:
            return dict(day_data)
        phase_ids = self._get_phase_equipment_ids(phase_number)
        return {
            equipment_id: data
            for equipment_id, data in day_data.items()
            if equipment_id in phase_ids
        }

    def _get_phase_equipment_ids(self, phase_number: int) -> Set[str]:
        """获取某科研期包含的装备 ID 集合。"""
        phase = self.research_manager.get_by_phase(int(phase_number))
        if not phase:
            return set()
        ids_str = str(phase.get("equipment_list", ""))
        return {equipment_id.strip() for equipment_id in ids_str.split(",") if equipment_id.strip()}

    @staticmethod
    def _sum_equipment_count(day_data: Dict[str, Dict[str, int]]) -> int:
        """汇总装备成品数量。"""
        return sum(int(record.get("equipment_count", 0)) for record in day_data.values())

    @staticmethod
    def _sum_fragment_count(day_data: Dict[str, Dict[str, int]]) -> int:
        """汇总装备碎片数量。"""
        return sum(int(record.get("fragment_count", 0)) for record in day_data.values())

    def _calculate_equivalent_score(
        self,
        day_data: Dict[str, Dict[str, int]],
        phase_number: Optional[int],
    ) -> int:
        """计算选中范围的碎片等值分。"""
        if phase_number is not None:
            phase_result = self.fragment_calculator.calculate_by_phase(int(phase_number), day_data)
            return int(phase_result.get("total_score", 0))
        batch = self.fragment_calculator.calculate_batch(day_data)
        return int(sum(item.get("score", 0) or 0 for item in batch))

    def _calculate_luck(
        self,
        day_data: Dict[str, Dict[str, int]],
        phase_number: Optional[int],
    ) -> Dict[str, Any]:
        """计算选中范围的欧非值，并把无穷值转换为 GUI 友好的 None。"""
        if phase_number is not None:
            result = self.luck_calculator.calculate_phase_luck(int(phase_number), day_data)
            luck_value = result.get("luck_value")
            if luck_value is not None and math.isinf(float(luck_value)):
                luck_value = None
            return {
                "luck_value": luck_value,
                "luck_level": result.get("luck_level", "未知"),
            }

        result = self.luck_calculator.calculate_all_luck(day_data)
        luck_value = result.get("overall_luck_value")
        if luck_value is not None and math.isinf(float(luck_value)):
            luck_value = None
        return {
            "luck_value": luck_value,
            "luck_level": result.get("overall_luck_level", "未知"),
        }

    @staticmethod
    def _validate_optional_date(date_str: Optional[str]) -> None:
        """校验可选日期字符串格式。"""
        if date_str is None:
            return
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("日期格式必须为 YYYY-MM-DD") from exc


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_trend_analyzer: Optional[TrendAnalyzer] = None


def get_trend_analyzer() -> TrendAnalyzer:
    """
    获取全局历史趋势分析器。
    输入：
        无。
    输出：
        TrendAnalyzer: 全局共享实例。
    使用示例：
        analyzer = get_trend_analyzer()
    """
    global _trend_analyzer
    if _trend_analyzer is None:
        _trend_analyzer = TrendAnalyzer()
    return _trend_analyzer
