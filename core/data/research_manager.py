#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║            🔬 科研数据管理器 (ResearchManager)                    ║
║                                                                  ║
║   【一句话解释】管理科研期数表，并提供"查某期→所有装备详情"功能   ║
║                                                                  ║
║   【类比理解】                                                    ║
║   装备管理器 = 仓库管理员（管每件装备）                            ║
║   科研管理器 = 项目主任（管每期科研计划）                          ║
║   项目主任说"第1期" → 翻计划表 → 拿到装备ID列表 →               ║
║   再找仓库管理员要每件装备的详情 → 返回完整信息                   ║
║                                                                  ║
║   【数据流向】                                                    ║
║   research_phases.csv ←→ ResearchManager(内存)                    ║
║                              ↓ 关联查询                           ║
║                         EquipmentManager.get_by_id()              ║
║                                                                  ║
║   【字段】phase_number | name | equipment_list                     ║
║   equipment_list 示例: "S1-001,S1-002"（逗号分隔的装备ID列表）    ║
╚══════════════════════════════════════════════════════════════════╝
"""
import csv
from typing import Any, Dict, List, Optional
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager
from .equipment_manager import get_equipment_manager


class ResearchManager:
    """🔬 科研数据管理器 - 管理 data/research_phases.csv"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式：全局唯一实例"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.csv_path = PathManager.get_data_dir() / "research_phases.csv"
        self.fieldnames = ["phase_number", "name", "equipment_list"]
        self._data: List[Dict[str, Any]] = []
        self._equip_manager = None
        self._ensure_csv()
        self._load()
        self._initialized = True

    @property
    def equip_manager(self):
        """延迟加载装备管理器（用的时候才加载）"""
        if self._equip_manager is None:
            self._equip_manager = get_equipment_manager()
        return self._equip_manager

    # ── CSV 内部方法 ──
    def _ensure_csv(self):
        """文件不存在则创建带表头的空 CSV"""
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=self.fieldnames).writeheader()

    def _load(self):
        """从 CSV 加载全部期数数据到内存"""
        try:
            self._data.clear()
            with open(self.csv_path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    row["phase_number"] = int(row.get("phase_number", 0))
                    self._data.append(row)
        except Exception as e:
            self.logger.error(f"加载科研期数失败:{e}")

    def reload(self) -> None:
        """
        重新从正式 CSV 载入科研期数。
        输入:
            无。
        输出:
            None，内部缓存会替换为当前 data/research_phases.csv 内容。
        使用示例:
            get_research_manager().reload()
        """
        self._ensure_csv()
        self._load()
        self.logger.info("科研期数缓存已从正式 CSV 重新载入")

    def _save(self):
        """将内存期数数据写回 CSV"""
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.fieldnames)
            w.writeheader()
            w.writerows(self._data)

    # ── 基础查询 ──
    def get_all(self) -> List[Dict[str, Any]]:
        """📋 获取全部科研期数
        返回: [{"phase_number":1,"name":"科研1期(PR1)","equipment_list":"S1-001,S1-002"}, ...]"""
        return self._data.copy()

    def get_by_phase(self, phase_number: int) -> Optional[Dict[str, Any]]:
        """🔎 按期数编号查询。示例: get_by_phase(1) → 第1期数据或 None"""
        for p in self._data:
            if p.get("phase_number") == phase_number:
                return p.copy()
        return None

    # ── CRUD ──
    def add_phase(self, phase: Dict[str, Any]) -> bool:
        """✨ 添加科研期数
        输入: {"phase_number":7(可选), "name":"科研7期(PR7)", "equipment_list":"S7-001,S7-002"}
        输出: True=成功, False=失败"""
        try:
            if not phase.get("phase_number", 0):
                phase["phase_number"] = max((p.get("phase_number", 0) for p in self._data), default=0) + 1
            if self.get_by_phase(phase["phase_number"]):
                return False
            self._data.append({
                "phase_number": int(phase["phase_number"]),
                "name": phase.get("name", ""),
                "equipment_list": phase.get("equipment_list", ""),
            })
            self._save()
            self.logger.info(f"添加科研期数:{phase['phase_number']}")
            return True
        except Exception as e:
            self.logger.error(f"添加科研期数失败:{e}")
            return False

    def update_phase(self, phase_number: int, updates: Dict[str, Any]) -> bool:
        """🔄 更新科研期数。示例: update_phase(1, {"name":"新名称"})"""
        try:
            for i, p in enumerate(self._data):
                if p.get("phase_number") == phase_number:
                    for k, v in updates.items():
                        if k in self.fieldnames:
                            self._data[i][k] = int(v) if k == "phase_number" else v
                    self._save()
                    return True
            return False
        except Exception as e:
            self.logger.error(f"更新科研期数失败:{e}")
            return False

    def delete_phase(self, phase_number: int) -> bool:
        """🗑️ 删除科研期数"""
        for i, p in enumerate(self._data):
            if p.get("phase_number") == phase_number:
                del self._data[i]
                self._save()
                return True
        return False

    # ── 关联查询（核心功能）──
    def get_phase_equipment(self, phase_number: int) -> List[Dict[str, Any]]:
        """🔗 获取某期科研的全部装备详情（含稀有度名称和颜色）
        工作流程:
        ① 查 research_phases.csv → 拿到 equipment_list (如 "S1-001,S1-002")
        ② 拆分为 ID 列表 ["S1-001","S1-002"]
        ③ 逐个调用 equipment_manager.get_by_id() 拿装备详情
        ④ 附加 rarity_name / rarity_color → 返回完整列表"""
        phase = self.get_by_phase(phase_number)
        if not phase:
            return []
        ids_str = phase.get("equipment_list", "")
        if not ids_str:
            return []
        ids = [eid.strip() for eid in ids_str.split(",") if eid.strip()]
        result = []
        for eid in ids:
            eq = self.equip_manager.get_by_id(eid)
            if eq:
                result.append(self.equip_manager.get_with_rarity_name(eq))
        return result

    def get_phase_equipment_count(self, phase_number: int) -> int:
        """🔢 获取某期科研的装备数量。示例: get_phase_equipment_count(1) → 2"""
        phase = self.get_by_phase(phase_number)
        if not phase:
            return 0
        ids_str = phase.get("equipment_list", "")
        return len([e for e in ids_str.split(",") if e.strip()]) if ids_str else 0

    # ── 统计 ──
    def get_statistics(self) -> Dict[str, Any]:
        """📊 科研统计: {"total_phases":6, "total_equipment":12}"""
        return {
            "total_phases": len(self._data),
            "total_equipment": sum(
                self.get_phase_equipment_count(p.get("phase_number", 0)) for p in self._data
            ),
        }


_instance_cache = None

def get_research_manager() -> ResearchManager:
    """获取全局唯一的 ResearchManager 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = ResearchManager()
    return _instance_cache
