#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║           🧮 碎片等值计算器 (FragmentCalculator)                  ║
║                                                                  ║
║   【一句话解释】输入装备数量和碎片数量，输出碎片等值总分。       ║
║   自动根据装备的稀有度和类别选择正确的等值公式。                 ║
║                                                                  ║
║   【类比理解】                                                    ║
║   碎片计算器 = "装备估价师"                                       ║
║   你有 2 件 S1-001（科研彩色）+ 30 个碎片 → 估价师算:            ║
║   2 × 50 + 30 = 130 碎片等值。                                   ║
║   不同装备用不同的"汇率"换算成统一的碎片等值。                   ║
║                                                                  ║
║   【核心公式】                                                    ║
║   score = equipment_count × equivalent + fragment_count           ║
║   equivalent 由 FormulaManager.get_equivalent() 根据装备类别返回  ║
║                                                                  ║
║   【数据来源】                                                    ║
║   ① 可显式传入 count/frag，也可自动从 UserDataManager 的今日数据读取 ║
║   ② 装备信息(稀有度)从 EquipmentManager 获取                      ║
║   ③ 等值公式从 FormulaManager 获取                                ║
╚══════════════════════════════════════════════════════════════════╝
"""
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..data.equipment_manager import get_equipment_manager
from .formula_manager import get_formula_manager


class FragmentCalculator:
    """🧮 碎片等值计算器 — 将装备数量换算为碎片等值分"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式：全局唯一碎片计算器"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        # ── 延迟加载的资源（首次使用时加载）──
        self._equip_manager = None        # 装备管理器
        self._formula_manager = None      # 公式管理器
        self._user_data_manager = None    # 用户数据管理器
        self._initialized = True

    # ══════════════════════════════════════════════════════════════
    #  延迟加载属性
    # ══════════════════════════════════════════════════════════════

    @property
    def equip_manager(self):
        """延迟加载装备管理器"""
        if self._equip_manager is None:
            self._equip_manager = get_equipment_manager()
        return self._equip_manager

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
    #  核心方法 — 单件装备计算
    # ══════════════════════════════════════════════════════════════

    def calculate_single(self, equipment_id: str,
                         equipment_count: int = 0,
                         fragment_count: int = 0) -> Dict[str, Any]:
        """🔢 计算单件装备的碎片等值总分
        
        Args:
            equipment_id: 装备 ID，如 "S1-001"
            equipment_count: 拥有该装备的成品件数
            fragment_count: 拥有的该装备碎片数量
        
        Returns:
            {
                "equipment_id": "S1-001",
                "equipment_name": "试作型三联装406mm主炮Mk6",
                "rarity_id": 5,
                "rarity_name": "海上传奇",
                "category": "科研彩色",
                "equipment_count": 2,
                "fragment_count": 30,
                "equivalent": 50,    ← 每件装备的碎片等值
                "score": 130.0       ← 总分 = 2×50 + 30 = 130
            }
            如果装备不存在或没有碎片公式，score 和 equivalent 为 None
        """
        eq_id = str(equipment_id).strip()
        eq_count = max(0, int(equipment_count))
        frag_count = max(0, int(fragment_count))

        # ── 步骤①: 从装备管理器查询装备信息 ──
        equip = self.equip_manager.get_by_id(eq_id)
        if not equip:
            self.logger.warning(f"装备不存在: {eq_id}")
            return {
                "equipment_id": eq_id,
                "equipment_name": "未知装备",
                "rarity_id": None,
                "rarity_name": "未知",
                "category": "不存在",
                "equipment_count": eq_count,
                "fragment_count": frag_count,
                "equivalent": None,
                "score": None,
                "error": f"装备ID '{eq_id}' 在装备库中不存在",
            }

        rarity_id = equip.get("rarity_id", 0)
        equip_name = equip.get("name", "未知")

        # ── 步骤②: 获取稀有度名称 ──
        equip_with_rarity = self.equip_manager.get_with_rarity_name(equip)
        rarity_name = equip_with_rarity.get("rarity_name", "未知") if equip_with_rarity else "未知"

        # ── 步骤③: 获取装备类别和碎片等值 ──
        category = self.formula_manager.get_equipment_category(eq_id, rarity_id)
        equivalent = self.formula_manager.get_equivalent(eq_id, rarity_id)

        # ── 步骤④: 计算总分（无公式的装备只计件数，不计碎片）──
        if equivalent is not None:
            score = int(eq_count) * int(equivalent) + int(frag_count)
        else:
            # 无碎片公式（普通白色、普通彩色），只返回装备数量作为参考
            score = None
            self.logger.debug(f"装备 {eq_id} ({equip_name}) 没有碎片公式，不计算等值分")

        return {
            "equipment_id": eq_id,
            "equipment_name": equip_name,
            "rarity_id": rarity_id,
            "rarity_name": rarity_name,
            "category": category,
            "equipment_count": eq_count,
            "fragment_count": frag_count,
            "equivalent": equivalent,
            "score": score,
        }

    def calculate_from_user_data(self, equipment_id: str,
                                  target_date: Optional[str] = None) -> Dict[str, Any]:
        """📖 从用户数据文件读取 count & frag，然后计算碎片等值
        
        Args:
            equipment_id: 装备 ID
            target_date: 日期 "YYYY-MM-DD"，不传则取今天
        
        Returns:
            同 calculate_single() 的返回值格式
            如果用户数据中没有该装备，equipment_count 和 fragment_count 均为 0
        """
        data = self.user_data_manager.get_data_by_date(target_date or self.user_data_manager._today_str())
        if data:
            record = data.get(str(equipment_id).strip(), {})
            return self.calculate_single(
                equipment_id,
                record.get("equipment_count", 0),
                record.get("fragment_count", 0),
            )
        return self.calculate_single(equipment_id, 0, 0)

    # ══════════════════════════════════════════════════════════════
    #  批量计算
    # ══════════════════════════════════════════════════════════════

    def calculate_batch(self, input_data: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
        """📦 批量计算多件装备的碎片等值
        
        Args:
            input_data: {
                "S1-001": {"equipment_count": 2, "fragment_count": 30},
                "S1-002": {"equipment_count": 1, "fragment_count": 15},
            }
        
        Returns:
            [calculate_single("S1-001", 2, 30), calculate_single("S1-002", 1, 15), ...]
        """
        results: List[Dict[str, Any]] = []
        for eq_id, data in input_data.items():
            result = self.calculate_single(
                eq_id,
                data.get("equipment_count", 0),
                data.get("fragment_count", 0),
            )
            results.append(result)
        return results

    def calculate_batch_from_today(self) -> List[Dict[str, Any]]:
        """📖 从今天的用户数据计算全部装备的碎片等值
        
        Returns:
            同 calculate_batch() 返回值
        """
        today_data = self.user_data_manager.get_today_data()
        return self.calculate_batch(today_data)

    # ══════════════════════════════════════════════════════════════
    #  按期数汇总计算
    # ══════════════════════════════════════════════════════════════

    def calculate_by_phase(self, phase_number: int,
                           input_data: Optional[Dict[str, Dict[str, int]]] = None) -> Dict[str, Any]:
        """📊 计算某一期科研中所有装备的碎片等值汇总
        
        Args:
            phase_number: 科研期数编号 (1~)
            input_data: 可选的显式传入数据，不传则从今日用户数据读取
        
        Returns:
            {
                "phase_number": 1,
                "phase_name": "科研1期(PR1)",
                "equipments": [... calculate_single的结果 ...],
                "total_score": 170,              ← 该期所有有公式装备的等值总分
                "valid_equipment_count": 2,         ← 有公式的装备数
                "skipped_equipment_count": 0,       ← 无公式(白色/普通彩)被跳过的装备数
                "equipment_count": 2,               ← 该期装备总数
            }
        """
        from ..data.research_manager import get_research_manager
        research_mgr = get_research_manager()

        # ── 步骤①: 获取该期的期数信息和装备列表 ──
        phase = research_mgr.get_by_phase(phase_number)
        if not phase:
            self.logger.warning(f"科研期数不存在: 第{phase_number}期")
            return {
                "phase_number": phase_number,
                "phase_name": "未知",
                "equipments": [],
                "total_score": 0,
                "valid_equipment_count": 0,
                "skipped_equipment_count": 0,
                "equipment_count": 0,
                "error": f"第{phase_number}期科研不存在",
            }

        phase_name = phase.get("name", f"科研{phase_number}期")
        equip_ids_str = phase.get("equipment_list", "")
        equip_ids = [eid.strip() for eid in equip_ids_str.split(",") if eid.strip()]

        # ── 步骤②: 逐个计算该期每件装备的碎片等值 ──
        equipment_results: List[Dict[str, Any]] = []
        total_score = 0
        valid_count = 0
        skipped_count = 0

        for eid in equip_ids:
            if input_data and eid in input_data:
                # 使用显式传入的数据
                eq_data = input_data[eid]
                result = self.calculate_single(
                    eid,
                    eq_data.get("equipment_count", 0),
                    eq_data.get("fragment_count", 0),
                )
            else:
                # 从今日用户数据读取
                result = self.calculate_from_user_data(eid)

            equipment_results.append(result)
            if result.get("score") is not None:
                total_score += result["score"]
                valid_count += 1
            else:
                skipped_count += 1

        return {
            "phase_number": phase_number,
            "phase_name": phase_name,
            "equipments": equipment_results,
            "total_score": total_score,
            "valid_equipment_count": valid_count,
            "skipped_equipment_count": skipped_count,
            "equipment_count": len(equip_ids),
        }

    def calculate_all_phases(self,
                             input_data: Optional[Dict[str, Dict[str, int]]] = None) -> Dict[str, Any]:
        """📊 计算所有科研期数的碎片等值汇总
        
        Returns:
            {
                "phases": [{phase_number: 1, ...}, ...],
                "overall_total_score": 1020,    ← 全部期数的等值总分
                "total_valid_equipment": 12,       ← 全部有公式的装备数
                "total_phases": 6,
            }
        """
        from ..data.research_manager import get_research_manager
        research_mgr = get_research_manager()

        all_phases = research_mgr.get_all()
        phase_results: List[Dict[str, Any]] = []
        overall_total = 0
        total_valid = 0

        for phase in all_phases:
            phase_num = phase.get("phase_number", 0)
            phase_result = self.calculate_by_phase(phase_num, input_data)
            phase_results.append(phase_result)
            overall_total += phase_result.get("total_score", 0)
            total_valid += phase_result.get("valid_equipment_count", 0)

        return {
            "phases": phase_results,
            "overall_total_score": overall_total,
            "total_valid_equipment": total_valid,
            "total_phases": len(all_phases),
        }

    # ══════════════════════════════════════════════════════════════
    #  汇总统计
    # ══════════════════════════════════════════════════════════════

    def get_summary(self, input_data: Optional[Dict[str, Dict[str, int]]] = None) -> Dict[str, Any]:
        """📊 获取碎片等值计算的完整汇总（各类别分组统计）
        
        Returns:
            {
                "overview": {"total_score": xxx, "total_equipments": xx},
                "by_category": {
                    "科研彩色": {"count": 5, "total_score": 650, "items": [...]},
                    ...
                },
                "by_phase": [...],
            }
        """
        if input_data is None:
            input_data = self.user_data_manager.get_today_data()

        batch_results = self.calculate_batch(input_data)
        all_phases = self.calculate_all_phases(input_data)

        # ── 按类别分组统计 ──
        by_category: Dict[str, Dict[str, Any]] = {}
        overall_total = 0
        for item in batch_results:
            cat = item.get("category", "未知")
            if cat not in by_category:
                by_category[cat] = {"count": 0, "total_score": 0, "items": []}
            by_category[cat]["count"] += 1
            by_category[cat]["items"].append(item)
            if item.get("score") is not None:
                by_category[cat]["total_score"] += item["score"]
                overall_total += item["score"]

        return {
            "overview": {
                "total_score": overall_total,
                "total_equipments": len(batch_results),
            },
            "by_category": by_category,
            "by_phase": all_phases["phases"],
        }


# ──────────────────────────────────────────────────────────────
#  全局访问函数
# ──────────────────────────────────────────────────────────────

_instance_cache: Optional[FragmentCalculator] = None


def get_fragment_calculator() -> FragmentCalculator:
    """获取全局唯一的 FragmentCalculator 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = FragmentCalculator()
    return _instance_cache
