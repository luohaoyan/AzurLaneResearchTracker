#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🔬 科研数据管理器 (ResearchManager)            ║
║                                                              ║
║   【一句话解释】                                              ║
║   这个文件就像"科研项目记录本"，记录碧蓝航线每一期            ║
║   科研计划有哪些装备，以及与装备管理器的关联查询。            ║
║                                                              ║
║   【类比理解】                                                ║
║   如果装备管理器是"仓库管理员"（管每件装备），                ║
║   那科研管理器就是"项目负责人"（管每期科研计划），            ║
║   项目负责人可以找仓库管理员查"我这期有哪些装备"。            ║
║                                                              ║
║   【核心功能：关联查询】                                      ║
║   科研期数存的是"装备ID列表"（如"1,2,3"），                  ║
║   查询时会拿着这些ID去找装备管理器要详细信息。                ║
║                                                              ║
║   【数据存储位置】                                            ║
║   data/research_phases.csv ── 科研期数表格                   ║
╚══════════════════════════════════════════════════════════════╝
"""

import csv
import os
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.path_manager import PathManager
from .equipment_manager import get_equipment_manager


class ResearchManager:
    """
    🔬 科研管理器 ── 管理碧蓝航线科研期数数据
    
    ┌───────────────────────────────────────────────────┐
    │  科研管理器 与 装备管理器 的关系：                  │
    │                                                    │
    │  科研管理器                                         │
    │  ├─ 第1期 → 装备列表"1,2" ──┐                      │
    │  ├─ 第2期 → 装备列表"3,4" ──┤                      │
    │  └─ 第3期 → 装备列表"5,6" ──┤                      │
    │                              ↓                     │
    │                    装备管理器（根据ID查详情）        │
    │                    └→ ID:1 → "试作型三联装406mm"   │
    │                    └→ ID:2 → "试作型三联装152mm"   │
    └───────────────────────────────────────────────────┘
    
    字段说明：
    - phase_number (期数编号)     : 第几期科研，如1,2,3...
    - name (名称)                 : 如"科研一期(PR1)"
    - equipment_list (装备列表)   : 用逗号分隔的装备ID，如"1,2,3"
    - luck_benchmark (欧非基准值) : 统计用的欧非分界线
    """

    # ── 单例模式：全局唯一实例 ──
    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式：确保只有一个科研管理器"""
        if not cls._instance:
            cls._instance = super(ResearchManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """
        初始化科研管理器
        
        启动流程：
        ① 拿到日志记录员
        ② 确定CSV文件位置（data/research_phases.csv）
        ③ 如CSV不存在则创建
        ④ 加载数据到内存
        ⑤ 准备关联装备管理器（但先不急着连接，等用到再说）
        """
        if hasattr(self, '_initialized'):
            return

        # ── 步骤①：日志 ──
        self.logger = get_logger()

        # ── 步骤②：文件路径 ──
        self.data_dir = PathManager.get_data_dir()
        self.csv_path = self.data_dir / "research_phases.csv"

        # ── 步骤③：定义CSV列 ──
        # 科研期数表有4个字段：
        self.fieldnames = [
            "phase_number",    # ① 期数编号（如1,2,3...）
            "name",            # ② 期数名称（如"科研一期(PR1)"）
            "equipment_list",  # ③ 包含的装备ID列表（如"1,2,3"用逗号分隔）
            "luck_benchmark"   # ④ 欧非基准值（一个浮点数）
        ]

        # ── 步骤④：内存数据缓存 ──
        self._data: List[Dict[str, Any]] = []

        # ── 步骤⑤⑥：确保CSV存在并加载 ──
        self._ensure_csv_exists()
        self._load_data()

        # ── 步骤⑦：装备管理器引用（延迟加载） ──
        # 为什么延迟加载？
        # 因为装备管理器和科研管理器互相可能还没初始化完，
        # 等到真正要用装备管理器的时候再去获取，避免循环依赖
        self._equip_manager = None

        self._initialized = True

    # ==========================================================
    # 🏠 属性：获取装备管理器（用到时才连接）
    # ==========================================================
    @property
    def equip_manager(self):
        """
        🤝 获取装备管理器实例（延迟加载）
        
        @property 是Python的"属性装饰器"，
        让 self.equip_manager 看起来像普通属性，
        但每次访问时会自动执行这个方法。
        
        第一次访问时：去拿装备管理器并记住它
        之后再访问：直接用记住的那个
        """
        if self._equip_manager is None:
            self._equip_manager = get_equipment_manager()
        return self._equip_manager

    # ==========================================================
    # 🔒 私有方法：CSV文件操作
    # ==========================================================

    def _ensure_csv_exists(self):
        """🏠 确保科研期数CSV文件存在"""
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                writer.writeheader()
            self.logger.info(f"📝 科研期数CSV文件已创建: {self.csv_path}")

    def _load_data(self):
        """
        📥 从CSV文件加载数据到内存
        
        比装备管理器简单，因为字段少。
        注意：luck_benchmark是浮点数（带小数），不是整数！
        """
        try:
            self._data.clear()
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # phase_number: 期数编号 → 整数
                    if 'phase_number' in row:
                        row['phase_number'] = int(row['phase_number']) if row['phase_number'] else 0
                    # luck_benchmark: 基准值 → 浮点数（可以有小数）
                    if 'luck_benchmark' in row:
                        row['luck_benchmark'] = float(row['luck_benchmark']) if row['luck_benchmark'] else 0.0
                    self._data.append(row)
            self.logger.debug(f"📥 科研期数数据已加载，共 {len(self._data)} 条记录")
        except Exception as e:
            self.logger.error(f"❌ 加载科研期数CSV失败: {e}")

    def _save_data(self):
        """📤 保存内存数据到CSV"""
        try:
            with open(self.csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                writer.writeheader()
                writer.writerows(self._data)
            self.logger.debug(f"📤 科研期数数据已保存，共 {len(self._data)} 条记录")
        except Exception as e:
            self.logger.error(f"❌ 保存科研期数CSV失败: {e}")
            raise

    # ==========================================================
    # 📖 查询操作
    # ==========================================================

    def get_all(self) -> List[Dict[str, Any]]:
        """
        📋 获取所有科研期数
        
        输入：无
        输出：期数列表
        示例：[{"phase_number":1, "name":"科研一期(PR1)", ...}, ...]
        """
        return self._data.copy()

    def get_by_phase(self, phase_number: int) -> Optional[Dict[str, Any]]:
        """
        🔍 按期数编号查找科研期数
        
        输入：period_number ── 如 1
        输出：找到了返回字典，没找到返回None
        """
        for phase in self._data:
            if phase.get('phase_number') == phase_number:
                return phase.copy()
        return None

    # ==========================================================
    # ✏️ 增删改操作
    # ==========================================================

    def add_phase(self, phase: Dict[str, Any]) -> bool:
        """
        ➕ 添加新科研期数
        
        输入格式：
        {
          "name": "科研一期(PR1)",            ← 必填：期数名称
          "equipment_list": "1,2,3",          ← 必填：装备ID列表(逗号分隔)
          "luck_benchmark": 100.0             ← 必填：欧非基准值(浮点数)
        }
        
        输出：True=成功, False=失败
        
        流程：自动分配期数编号 → 检查重复 → 构建记录 → 保存 → 记日志
        """
        try:
            # 自动生成期数编号
            if 'phase_number' not in phase or phase.get('phase_number', 0) == 0:
                max_num = max((p.get('phase_number', 0) for p in self._data), default=0)
                phase['phase_number'] = max_num + 1

            # 检查是否已存在
            if self.get_by_phase(phase['phase_number']) is not None:
                self.logger.warning(f"⚠️ 科研期数 {phase['phase_number']} 已存在，添加失败")
                return False

            # 构建完整记录
            record = {
                'phase_number': int(phase.get('phase_number', 0)),
                'name': phase.get('name', ''),
                'equipment_list': phase.get('equipment_list', ''),
                'luck_benchmark': float(phase.get('luck_benchmark', 0.0)),
            }

            self._data.append(record)
            self._save_data()
            self.logger.info(f"✅ 科研期数已添加: {record['name']} (第{record['phase_number']}期)")
            return True

        except Exception as e:
            self.logger.error(f"❌ 添加科研期数失败: {e}")
            return False

    def update_phase(self, phase_number: int, updates: Dict[str, Any]) -> bool:
        """
        ✏️ 更新科研期数信息
        
        输入：
          phase_number ── 要修改的期数编号
          updates       ── 要修改的字段（只传要改的）
        
        示例：
          mgr.update_phase(1, {"luck_benchmark": 200.0, "name": "新名字"})
        """
        try:
            for i, phase in enumerate(self._data):
                if phase.get('phase_number') == phase_number:
                    for key, value in updates.items():
                        if key in self.fieldnames:
                            # 数字字段特殊处理
                            if key == 'phase_number':
                                self._data[i][key] = int(value) if value is not None else 0
                            elif key == 'luck_benchmark':
                                self._data[i][key] = float(value) if value is not None else 0.0
                            else:
                                # equipment_list 和 name 都是文本
                                self._data[i][key] = value

                    self._save_data()
                    self.logger.info(f"✅ 科研期数已更新: 第{phase_number}期, 更新字段={list(updates.keys())}")
                    return True

            self.logger.warning(f"⚠️ 未找到第{phase_number}期科研，更新失败")
            return False

        except Exception as e:
            self.logger.error(f"❌ 更新科研期数失败: {e}")
            return False

    def delete_phase(self, phase_number: int) -> bool:
        """🗑️ 删除科研期数"""
        try:
            for i, phase in enumerate(self._data):
                if phase.get('phase_number') == phase_number:
                    name = phase.get('name', '')
                    del self._data[i]
                    self._save_data()
                    self.logger.info(f"🗑️ 科研期数已删除: {name} (第{phase_number}期)")
                    return True

            self.logger.warning(f"⚠️ 未找到第{phase_number}期科研，删除失败")
            return False

        except Exception as e:
            self.logger.error(f"❌ 删除科研期数失败: {e}")
            return False

    # ==========================================================
    # 🔗 关联查询（科研管理器的核心亮点！）
    # ==========================================================

    def get_phase_equipment(self, phase_number: int) -> List[Dict[str, Any]]:
        """
        🔗 获取指定科研期数的所有装备详情
        
        这是科研管理器最重要的方法！它连接了两个管理器。
        
        工作流程（图解）：
        ┌─────────────────────────────────────────────────┐
        │ 输入：phase_number = 1                           │
        │                                                   │
        │ ① 从科研期数表查第1期                             │
        │    → {"equipment_list": "1,2"}                    │
        │                                                   │
        │ ② 把 "1,2" 拆成 ["1","2"]                        │
        │    → 再转成数字 [1, 2]                            │
        │                                                   │
        │ ③ 拿着每个ID去找装备管理器                        │
        │    → equip_manager.get_by_id(1)                   │
        │    → equip_manager.get_by_id(2)                   │
        │                                                   │
        │ ④ 返回装备详情列表                                │
        │    → [{id:1, name:"406mm炮", ...},                │
        │       {id:2, name:"152mm炮", ...}]                │
        └─────────────────────────────────────────────────┘
        
        输入：
          phase_number ── 期数编号
        
        输出：
          装备详情列表（每条都是完整的装备字典）
        """
        # ① 先查科研期数
        phase = self.get_by_phase(phase_number)
        if phase is None:
            self.logger.warning(f"⚠️ 未找到第{phase_number}期科研")
            return []

        # ② 获取装备ID字符串
        # equipment_list 格式如："1,2,3" 或 "1, 2, 3"（可能有多余空格）
        equipment_ids_str = phase.get('equipment_list', '')
        if not equipment_ids_str:
            return []  # 该期没有装备

        # ③ 把字符串拆成ID列表
        try:
            # "1, 2, 3" → 按逗号分割 → ["1", " 2", " 3"] → strip去空格 → ["1","2","3"] → 转整数 → [1,2,3]
            equipment_ids = [int(eid.strip()) for eid in equipment_ids_str.split(',') if eid.strip()]
        except ValueError:
            self.logger.error(f"❌ 第{phase_number}期装备列表格式错误: {equipment_ids_str}")
            return []

        # ④ 逐个查询装备详情
        result = []
        for eid in equipment_ids:
            eq = self.equip_manager.get_by_id(eid)  # 👈 跨管理器调用！
            if eq:
                result.append(eq)
            else:
                # 装备ID在科研期数里写了，但装备库里没这个ID → 数据不一致
                self.logger.warning(f"⚠️ 装备ID {eid} 在装备库中不存在（第{phase_number}期）")

        return result

    def get_phase_equipment_count(self, phase_number: int) -> int:
        """
        🔢 获取某期科研的装备数量
        
        输入：phase_number ── 期数编号
        输出：整数 ── 该期有多少件装备
        
        跟 get_phase_equipment 的区别：
        - 这个只返回"数量"（轻量级，不需要查详情）
        - get_phase_equipment 返回"完整信息"（重量级，需要跨管理器查询）
        """
        phase = self.get_by_phase(phase_number)
        if phase is None:
            return 0

        equipment_ids_str = phase.get('equipment_list', '')
        if not equipment_ids_str:
            return 0

        # 简单数一下逗号分隔的ID数量
        return len([eid for eid in equipment_ids_str.split(',') if eid.strip()])

    def get_statistics(self) -> Dict[str, Any]:
        """
        📊 获取科研统计信息
        
        输入：无
        输出：
        {
          "total_phases": 6,         # 总共几期科研
          "total_equipment": 12      # 所有期数加起来有多少装备
        }
        """
        total_phases = len(self._data)
        total_equipment = 0

        for phase in self._data:
            # 每期都数一下装备数量，累加起来
            total_equipment += self.get_phase_equipment_count(phase.get('phase_number', 0))

        return {
            "total_phases": total_phases,
            "total_equipment": total_equipment,
        }


# ============================================================
# 🌐 全局访问函数
# ============================================================
_research_manager_instance = None


def get_research_manager() -> ResearchManager:
    """
    🌍 获取全局唯一的科研管理器实例
    
    使用方式：
    from core.data.research_manager import get_research_manager
    mgr = get_research_manager()
    mgr.get_phase_equipment(1)  # 查第1期有哪些装备
    """
    global _research_manager_instance
    if _research_manager_instance is None:
        _research_manager_instance = ResearchManager()
    return _research_manager_instance
