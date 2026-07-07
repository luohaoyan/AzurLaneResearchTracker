#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║             🎲 欧非值计算器 (LuckCalculator)                      ║
║                                                                  ║
║   【一句话解释】根据各期科研装备的碎片等值分，计算欧非值。       ║
║   欧非值 = 彩虹装备等值总分 / 金色装备等值总分。                 ║
║                                                                  ║
║   【类比理解】                                                    ║
║   欧非值 = "运气指数"                                             ║
║   彩装备碎片多 → 运气好(欧) → 值 > 1                              ║
║   金装备碎片多 → 运气差(非) → 值 < 1                              ║
║                                                                  ║
║   【核心公式】                                                    ║
║   luck_value = rainbow_total_score / gold_total_score              ║
║   rainbow: 该科研期数中所有彩色(海上传奇)装备的等值总分           ║
║   gold:    该科研期数中所有金色(超稀有)装备的等值总分             ║
║                                                                  ║
║   【欧非值公式可配置】                                            ║
║   FormulaManager 中预留 luck_formula，后续可自定义计算逻辑。     ║
║   当前实现：简单比值 rainbow / gold                               ║
║                                                                  ║
║   【等级判定】由 FormulaManager.get_luck_level_name() 提供        ║
║   阈值可在 azur_lane.json 中修改（极欧/较欧/正常/较非/极非）    ║
╚══════════════════════════════════════════════════════════════════╝
"""
import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from .fragment_calculator import get_fragment_calculator
from .formula_manager import get_formula_manager


class LuckCalculator:
    """🎲 欧非值计算器 — 按期计算运气指数"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式：全局唯一欧非值计算器"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        # ── 延迟加载的资源 ──
        self._fragment_calculator = None     # 碎片计算器
        self._formula_manager = None          # 公式管理器
        self._user_data_manager = None        # 用户数据管理器
        self._initialized = True

    # ══════════════════════════════════════════════════════════════
    #  延迟加载属性
    # ══════════════════════════════════════════════════════════════

    @property
    def fragment_calc(self):
        """延迟加载碎片计算器"""
        if self._fragment_calculator is None:
            self._fragment_calculator = get_fragment_calculator()
        return self._fragment_calculator

    @property
    def formula_manager(self):
        """延迟加载公式管理器"""
        if self._formula_manager is None:
            self._formula_manager = get_formula_manager()
        return self._formula_manager

    @property
    def user_data_manager(self):
        """延迟加载用户数据管理器"""
        if self._user_data_manager is None:
            from .user_data_manager import get_user_data_manager
            self._user_data_manager = get_user_data_manager()
        return self._user_data_manager

    # ══════════════════════════════════════════════════════════════
    #  核心方法 — 单期欧非值计算
    # ══════════════════════════════════════════════════════════════

    def calculate_phase_luck(self, phase_number: int,
                              input_data: Optional[Dict[str, Dict[str, int]]] = None) -> Dict[str, Any]:
        """🎲 计算单期科研的欧非值
        
        工作流程:
        ① 调 FragmentCalculator.calculate_by_phase() → 拿到该期每件装备的等值分
        ② 将装备分为"彩虹装备组"和"金色装备组"
        ③ rainbow_total = 彩虹组等值总分
        ④ gold_total = 金色组等值总分
        ⑤ luck = rainbow_total / gold_total
        ⑥ 查 luck_level 阈值 → 返回等级名称
        
        Args:
            phase_number: 科研期数 (1~6)
            input_data: 可选的显式传入数据，不传则从今日用户数据读取
        
        Returns:
            {
                "phase_number": 1,
                "phase_name": "科研1期(PR1)",
                "rainbow_equipments": [    ← 该期所有彩色装备的等值计算详情
                    {equipment_id, equipment_name, score, ...}, ...
                ],
                "gold_equipments": [       ← 该期所有金色装备的等值计算详情
                    {equipment_id, equipment_name, score, ...}, ...
                ],
                "rainbow_total": 130,    ← 彩虹装备等值总分
                "gold_total": 40,        ← 金色装备等值总分
                "luck_value": 3.25,        ← 欧非值
                "luck_level": "极欧",       ← 欧非等级
                "luck_formula_used": "rainbow_total / gold_total",
                "warnings": []              ← 异常情况警告
            }
        """
        warnings: List[str] = []

        # ── 步骤①: 获取该期所有装备的碎片等值计算结果 ──
        phase_result = self.fragment_calc.calculate_by_phase(phase_number, input_data)

        if phase_result.get("error"):
            return {
                "phase_number": phase_number,
                "phase_name": "未知",
                "rainbow_equipments": [],
                "gold_equipments": [],
                "rainbow_total": 0.0,
                "gold_total": 0.0,
                "luck_value": None,
                "luck_level": "未知",
                "luck_formula_used": "rainbow_total / gold_total",
                "warnings": [phase_result.get("error", "未知错误")],
            }

        phase_name = phase_result.get("phase_name", f"科研{phase_number}期")
        equipments = phase_result.get("equipments", [])

        # ── 步骤②: 按稀有度分组至彩虹组 vs 金色组 ──
        rainbow_equipments: List[Dict[str, Any]] = []  # 海上传奇(rarity_id=5)
        gold_equipments: List[Dict[str, Any]] = []     # 超稀有(rarity_id=4)

        for eq in equipments:
            rarity_id = eq.get("rarity_id")
            if rarity_id == 5:
                rainbow_equipments.append(eq)
            elif rarity_id == 4:
                gold_equipments.append(eq)
            # rarity_id=1/2/3 的装备不参与科研欧非值计算
            # 一期科研只含彩色+金色装备

        # ── 步骤③: 计算两组各自的等值总分 ──
        # 累加彩虹装备等值总分（整数）
        rainbow_total = sum(
            eq.get("score", 0) for eq in rainbow_equipments
            if eq.get("score") is not None
        )
        gold_total = sum(
            eq.get("score", 0) for eq in gold_equipments
            if eq.get("score") is not None
        )

        # ── 步骤④: 处理边界情况 ──
        luck_value: Optional[float] = None
        luck_level: str = "未知"

        if len(rainbow_equipments) == 0:
            warnings.append("该科研期数没有彩虹装备，无法计算欧非值")
        if len(gold_equipments) == 0:
            warnings.append("该科研期数没有金色装备，无法计算欧非值")

        if gold_total == 0:
            if rainbow_total > 0:
                # 有彩虹装备但无金色装备 → 理论上极欧
                warnings.append("金色装备总分为0，欧非值趋近无穷（极欧）")
                luck_value = float("inf")
                luck_level = "极欧"
            elif rainbow_total == 0:
                # 两边都是0 → 无数据
                warnings.append("彩虹和金色装备总分均为0，无数据")
                luck_value = None
                luck_level = "未知"
            else:
                warnings.append("彩虹装备总分为0，欧非值为0（极非）")
                luck_value = 0.0
                luck_level = "极非"
        else:
            # ── 正常计算欧非值（使用 Decimal 保证 3 位小数精度）──
            # 碎片等值分都是整数，用 Decimal 做除法可以避免浮点误差
            # 例如: 100/30 → Decimal('3.333') 而不是 float 的 3.3333333333333335
            raw_value = Decimal(str(rainbow_total)) / Decimal(str(gold_total))
            luck_value = float(raw_value.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP))
            luck_level = self.get_luck_level(luck_value)

        return {
            "phase_number": phase_number,
            "phase_name": phase_name,
            "rainbow_equipments": rainbow_equipments,
            "gold_equipments": gold_equipments,
            "rainbow_total": int(rainbow_total),
            "gold_total": int(gold_total),
            "luck_value": luck_value,
            "luck_level": luck_level,
            "luck_formula_used": "rainbow_total / gold_total",
            "warnings": warnings,
        }

    # ══════════════════════════════════════════════════════════════
    #  全期汇总
    # ══════════════════════════════════════════════════════════════

    def calculate_all_luck(self,
                           input_data: Optional[Dict[str, Dict[str, int]]] = None) -> Dict[str, Any]:
        """🎲 计算所有科研期数的欧非值
        
        Returns:
            {
                "phases": [
                    {phase_number: 1, luck_value: 3.25, luck_level: "极欧", ...},
                    ...
                ],
                "overall_luck_value": 总和虹 / 总和金,
                "overall_luck_level": "极欧",
                "total_phases": 6,
            }
        """
        from ..data.research_manager import get_research_manager
        research_mgr = get_research_manager()

        all_phases = research_mgr.get_all()
        phase_results: List[Dict[str, Any]] = []
        overall_rainbow = 0.0
        overall_gold = 0.0

        for phase in all_phases:
            phase_num = phase.get("phase_number", 0)
            luck_result = self.calculate_phase_luck(phase_num, input_data)
            phase_results.append(luck_result)
            if luck_result.get("rainbow_total", 0) is not None:
                overall_rainbow += luck_result.get("rainbow_total", 0)
            if luck_result.get("gold_total", 0) is not None:
                overall_gold += luck_result.get("gold_total", 0)

        # ── 整体欧非值（使用 Decimal 保证精度）──
        overall_luck: Optional[float] = None
        overall_level: str = "未知"
        if overall_gold > 0:
            raw = Decimal(str(overall_rainbow)) / Decimal(str(overall_gold))
            overall_luck = float(raw.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP))
            overall_level = self.get_luck_level(overall_luck)
        elif overall_rainbow > 0:
            overall_luck = float("inf")
            overall_level = "极欧"
        else:
            overall_luck = None
            overall_level = "未知"

        return {
            "phases": phase_results,
            "overall_rainbow_total": int(overall_rainbow),
            "overall_gold_total": int(overall_gold),
            "overall_luck_value": overall_luck,
            "overall_luck_level": overall_level,
            "total_phases": len(all_phases),
        }

    # ══════════════════════════════════════════════════════════════
    #  欧非值等级判定
    # ══════════════════════════════════════════════════════════════

    def get_luck_level(self, luck_value: float) -> str:
        """🏷️ 将欧非值数值映射为等级名称
        
        Args:
            luck_value: 欧非值 (浮点数)
        
        Returns:
            "极欧" / "较欧" / "正常" / "较非" / "极非"
        
        特殊处理:
            - inf (正无穷) → "极欧"
            - NaN → "未知"
        """
        if math.isinf(luck_value):
            return "极欧" if luck_value > 0 else "极非"
        if math.isnan(luck_value):
            self.logger.warning("欧非值为 NaN")
            return "未知"
        return self.formula_manager.get_luck_level_name(luck_value)

    # ══════════════════════════════════════════════════════════════
    #  历史趋势
    # ══════════════════════════════════════════════════════════════

    def get_luck_trend(self, phase_number: int) -> List[Dict[str, Any]]:
        """📈 计算某期科研的欧非值历史趋势（按日期）
        
        遍历 data/user_records/ 下所有日期文件，
        对每一天的数据计算该期的欧非值，生成趋势数据。
        可以用于 UI 画折线图展示运气变化。
        
        Args:
            phase_number: 科研期数 (1~6)
        
        Returns:
            [
                {"date": "2026-07-06", "luck_value": 3.0, "luck_level": "极欧", "rainbow_total": 120, "gold_total": 40},
                {"date": "2026-07-07", "luck_value": 3.25, "luck_level": "极欧", "rainbow_total": 130, "gold_total": 40},
            ]
            按日期升序排列（旧 → 新）
        """
        trend: List[Dict[str, Any]] = []
        dates = self.user_data_manager.list_available_dates()

        for date_str in dates:
            date_data = self.user_data_manager.get_data_by_date(date_str)
            if not date_data:
                # 这天没数据，跳过
                continue

            luck_result = self.calculate_phase_luck(phase_number, date_data)
            luck_value = luck_result.get("luck_value")
            # 无限值在趋势图中不好展示，标记为 None
            if luck_value is not None and math.isinf(luck_value):
                luck_value = None

            trend.append({
                "date": date_str,
                "luck_value": luck_value,
                "luck_level": luck_result.get("luck_level", "未知"),
                "rainbow_total": luck_result.get("rainbow_total", 0),
                "gold_total": luck_result.get("gold_total", 0),
            })

        return trend

    def get_all_luck_trend(self) -> Dict[int, List[Dict[str, Any]]]:
        """📈 获取所有期数的欧非值历史趋势
        
        Returns:
            {
                1: [{date: "...", luck_value: 3.25, ...}, ...],
                2: [...],
                ...
            }
        """
        from ..data.research_manager import get_research_manager
        research_mgr = get_research_manager()

        all_trends: Dict[int, List[Dict[str, Any]]] = {}
        for phase in research_mgr.get_all():
            phase_num = phase.get("phase_number", 0)
            all_trends[phase_num] = self.get_luck_trend(phase_num)

        return all_trends

    # ══════════════════════════════════════════════════════════════
    #  便捷方法 — 从今日数据一键计算
    # ══════════════════════════════════════════════════════════════

    def calculate_today_all_luck(self) -> Dict[str, Any]:
        """📅 从今日用户数据一键计算所有科研期数的欧非值"""
        today_data = self.user_data_manager.get_today_data()
        return self.calculate_all_luck(today_data)

    def calculate_today_phase_luck(self, phase_number: int) -> Dict[str, Any]:
        """📅 从今日用户数据一键计算指定期数的欧非值"""
        today_data = self.user_data_manager.get_today_data()
        return self.calculate_phase_luck(phase_number, today_data)


# ──────────────────────────────────────────────────────────────
#  全局访问函数
# ──────────────────────────────────────────────────────────────

_instance_cache: Optional[LuckCalculator] = None


def get_luck_calculator() -> LuckCalculator:
    """获取全局唯一的 LuckCalculator 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = LuckCalculator()
    return _instance_cache
