#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              📐 公式管理器 (FormulaManager)                       ║
║                                                                  ║
║   【一句话解释】管理所有计算公式相关的配置：碎片等值、特殊装备、  ║
║   欧非值阈值。是 FragmentCalculator 和 LuckCalculator 的基础。   ║
║                                                                  ║
║   【类比理解】                                                    ║
║   公式管理器 = 一本"游戏规则手册"                                 ║
║   里面记录着：每件装备值多少碎片、哪些是特殊装备、                ║
║   欧非值的等级线划在哪里。所有计算模块都来这本手册查规则。        ║
║                                                                  ║
║   【数据来源】                                                    ║
║   ① config/games/azur_lane.json → fragment_equivalents + luck_levels  ║
║   ② data/special_equipment.csv  → 特殊装备 ID 列表                ║
║   ③ data/research_phases.csv    → 科研装备 ID 列表（判断是否为科研装备）║
║                                                                  ║
║   【公式映射规则】get_equivalent() 的判断链:                       ║
║   rarity_id=1(普通) → None (无碎片公式)                           ║
║   rarity_id=2(稀有) → 5                                           ║
║   rarity_id=3(精锐) → 10                                          ║
║   rarity_id=4(超稀有) → 科研装备? 25 : 特殊装备? 25 : 15         ║
║   rarity_id=5(海上传奇) → 科研装备? 50 : None (普通彩无碎片)    ║
╚══════════════════════════════════════════════════════════════════╝
"""
import json
import os
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.path_manager import PathManager
from ..utils.config_loader import get_config_loader


class FormulaManager:
    """📐 公式管理器 — 管理碎片等值映射 + 特殊装备列表 + 欧非值阈值"""
    _instance = None

    # ── 预定义的配置键（用于写回 JSON）──
    CONFIG_KEY = "fragment_equivalents"  # azur_lane.json 中的配置键

    # ── 默认等值映射（当 JSON 不存在或缺失时使用）──
    DEFAULT_EQUIVALENTS: Dict[str, Any] = {
        "research_rainbow": 50,   # 科研彩色: 1件 = 50碎片
        "research_gold": 25,      # 科研金色: 1件 = 25碎片
        "general_gold": 15,       # 普通金色: 1件 = 15碎片
        "special_gold": 25,       # 特殊金色: 1件 = 25碎片 (BR.810, B-13)
        "purple": 10,             # 紫色: 1件 = 10碎片
        "blue": 5,                # 蓝色: 1件 = 5碎片
    }

    # ── 默认欧非值阈值 ──
    DEFAULT_LUCK_LEVELS: Dict[str, float] = {
        "极欧": 2.0,    # 欧非值 >= 2.0 → 极欧
        "较欧": 1.3,    # 欧非值 >= 1.3 → 较欧
        "正常": 0.7,    # 欧非值 >  0.7 → 正常
        "较非": 0.4,    # 欧非值 >  0.4 → 较非
        "极非": 0.0,    # 欧非值 <= 0.4 → 极非
    }

    def __new__(cls, *args, **kwargs):
        """单例模式：全局唯一公式管理器"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        # ── 碎片等值映射 ──
        self._equivalents: Dict[str, int] = {}
        # ── 欧非值等级阈值 ──
        self._luck_levels: Dict[str, float] = {}
        # ── 科研装备 ID 集合（从 research_phases.csv 动态提取）──
        self._research_equipment_ids: set = set()
        # ── 特殊装备 ID 集合（由外部注入，延迟加载）──
        self._special_equipment_ids: Optional[set] = None
        # ── 特殊装备管理器缓存 ──
        self._special_manager = None
        # ── 装备管理器缓存（用于读取时构建科研装备ID集合）──
        self._equip_manager = None
        # ── 科研管理器缓存 ──
        self._research_manager = None

        self._load_from_config()
        self._build_research_id_set()
        self._initialized = True
        self.logger.info("FormulaManager 初始化完成")

    # ══════════════════════════════════════════════════════════════
    #  延迟加载属性（用的时候才加载，避免循环依赖）
    # ══════════════════════════════════════════════════════════════

    @property
    def special_manager(self):
        """延迟加载特殊装备管理器"""
        if self._special_manager is None:
            from ..data.special_equipment_manager import get_special_equipment_manager
            self._special_manager = get_special_equipment_manager()
        return self._special_manager

    @property
    def equip_manager(self):
        """延迟加载装备管理器"""
        if self._equip_manager is None:
            from ..data.equipment_manager import get_equipment_manager
            self._equip_manager = get_equipment_manager()
        return self._equip_manager

    @property
    def research_manager(self):
        """延迟加载科研管理器"""
        if self._research_manager is None:
            from ..data.research_manager import get_research_manager
            self._research_manager = get_research_manager()
        return self._research_manager

    # ══════════════════════════════════════════════════════════════
    #  内部方法 — 加载配置
    # ══════════════════════════════════════════════════════════════

    def _load_from_config(self):
        """【内部】从 config/games/azur_lane.json 加载计算公式配置
        加载的内容包括: fragment_equivalents(碎片等值映射) 和 luck_levels(欧非值阈值)
        如果 JSON 中不存在则使用默认值"""
        try:
            config = get_config_loader().get_game_config("azur_lane")
            calc_config = config.get("calculations", {})

            # ── 加载碎片等值映射 ──
            self._equivalents = dict(self.DEFAULT_EQUIVALENTS)
            json_equivs = calc_config.get("fragment_equivalents", {})
            if json_equivs:
                # 覆盖默认值（JSON 中的优先）
                for key, val in json_equivs.items():
                    self._equivalents[key] = int(val)

            # ── 加载欧非值阈值 ──
            self._luck_levels = dict(self.DEFAULT_LUCK_LEVELS)
            json_levels = calc_config.get("luck_levels", {})
            if json_levels:
                self._luck_levels.clear()
                for level_name, threshold in json_levels.items():
                    self._luck_levels[level_name] = float(threshold)

            self.logger.debug(f"已加载配置: equivalents={self._equivalents}, luck_levels={self._luck_levels}")
        except Exception as e:
            self.logger.error(f"加载计算公式配置失败: {e}，使用默认值")
            self._equivalents = dict(self.DEFAULT_EQUIVALENTS)
            self._luck_levels = dict(self.DEFAULT_LUCK_LEVELS)

    def _build_research_id_set(self):
        """【内部】从 ResearchManager 的 research_phases.csv 提取所有科研装备 ID
        构建 self._research_equipment_ids 集合，用于快速判断某个 ID 是否为科研装备。
        
        遍历逻辑:
        ① 获取所有科研期数
        ② 每期取 equipment_list 字段（逗号分隔的ID列表）
        ③ 拆分后加入集合
        """
        try:
            self._research_equipment_ids.clear()
            phases = self.research_manager.get_all()
            for phase in phases:
                equip_list_str = phase.get("equipment_list", "")
                if equip_list_str:
                    for eid in equip_list_str.split(","):
                        eid = eid.strip()
                        if eid:
                            self._research_equipment_ids.add(eid)
            self.logger.debug(f"已构建科研装备ID集合: {len(self._research_equipment_ids)} 件")
        except Exception as e:
            self.logger.error(f"构建科研装备ID集合失败: {e}")

    @property
    def _special_id_set(self) -> set:
        """【内部】延迟获取特殊装备 ID 集合（首次访问时从 SpecialEquipmentManager 加载）"""
        if self._special_equipment_ids is None:
            try:
                self._special_equipment_ids = self.special_manager.get_all_ids()
            except Exception as e:
                self.logger.error(f"获取特殊装备ID列表失败: {e}")
                self._special_equipment_ids = set()
        return self._special_equipment_ids

    # ══════════════════════════════════════════════════════════════
    #  核心方法 — 碎片等值查询
    # ══════════════════════════════════════════════════════════════

    def get_equivalent(self, equipment_id: str, rarity_id: int) -> Optional[int]:
        """🔢 根据装备 ID 和稀有度返回每件装备的碎片等值
        
        这就是整个计算层的核心决策树！根据装备的稀有度和所属类别，
        自动判断应该使用哪个碎片等值公式。

        Args:
            equipment_id: 装备 ID，如 "S1-001" 或 "BR.810"
            rarity_id: 稀有度 ID (1~5)
        
        Returns:
            碎片等值（1件该装备 = ?碎片），无公式则返回 None
        
        判断链:
            rarity_id=1 → None (普通装备无碎片公式)
            rarity_id=2 → 5 (蓝色)
            rarity_id=3 → 10 (紫色)
            rarity_id=4 → 科研装备? 25 : 特殊装备? 25 : 15
            rarity_id=5 → 科研装备? 50 : None (普通彩色无碎片公式)
        """
        eq_id = str(equipment_id).strip()

        # ── 白色装备: 无碎片公式 ──
        if rarity_id == 1:
            return None

        # ── 蓝色装备: 1件 = 5碎片 ──
        if rarity_id == 2:
            return self._equivalents.get("blue", 5)

        # ── 紫色装备: 1件 = 10碎片 ──
        if rarity_id == 3:
            return self._equivalents.get("purple", 10)

        # ── 金色装备: 根据类别细分 ──
        if rarity_id == 4:
            # 检查1: 是科研装备? → 25
            if eq_id in self._research_equipment_ids:
                return self._equivalents.get("research_gold", 25)
            # 检查2: 是特殊装备(BR.810等)? → 25
            if eq_id in self._special_id_set:
                return self._equivalents.get("special_gold", 25)
            # 否则: 普通金色装备 → 15
            return self._equivalents.get("general_gold", 15)

        # ── 彩色装备: 科研彩有公式，普通彩无公式 ──
        if rarity_id == 5:
            # 检查: 是科研装备? → 50
            if eq_id in self._research_equipment_ids:
                return self._equivalents.get("research_rainbow", 50)
            # 否则: 普通彩色装备 → 无碎片公式
            return None

        # ── 超出范围的稀有度 ──
        self.logger.warning(f"未知稀有度: rarity_id={rarity_id}, equipment_id={eq_id}")
        return None

    def is_research_equipment(self, equipment_id: str) -> bool:
        """🔎 判断某个装备是否为科研装备（ID 在 research_phases.csv 的 equipment_list 中）
        
        Args:
            equipment_id: 装备 ID
        
        Returns:
            True 表示是科研装备，False 表示不是
        """
        return str(equipment_id).strip() in self._research_equipment_ids

    def is_special_equipment(self, equipment_id: str) -> bool:
        """🔎 判断某个装备是否为特殊装备（ID 在 special_equipment.csv 中）
        
        Args:
            equipment_id: 装备 ID
        
        Returns:
            True 表示是特殊装备，False 表示不是
        """
        return str(equipment_id).strip() in self._special_id_set

    def get_equipment_category(self, equipment_id: str, rarity_id: int) -> str:
        """🏷️ 获取装备的类别标签（用于调试和UI展示）
        
        Args:
            equipment_id: 装备 ID
            rarity_id: 稀有度 ID
        
        Returns:
            类别字符串: "科研彩色" / "科研金色" / "特殊金色" / "普通金色" /
                       "紫色" / "蓝色" / "普通彩色" / "普通白色" / "未知"
        """
        eq_id = str(equipment_id).strip()

        if rarity_id == 1:
            return "普通白色"
        if rarity_id == 2:
            return "蓝色"
        if rarity_id == 3:
            return "紫色"
        if rarity_id == 4:
            if eq_id in self._research_equipment_ids:
                return "科研金色"
            if eq_id in self._special_id_set:
                return "特殊金色"
            return "普通金色"
        if rarity_id == 5:
            if eq_id in self._research_equipment_ids:
                return "科研彩色"
            return "普通彩色"
        return "未知"

    # ══════════════════════════════════════════════════════════════
    #  碎片等值修改方法（持久化到 JSON）
    # ══════════════════════════════════════════════════════════════

    def set_equivalent(self, key: str, value: int) -> bool:
        """✏️ 修改碎片等值映射，并持久化写入 azur_lane.json
        
        Args:
            key: 等值键名 ("research_rainbow", "research_gold", "purple" 等)
            value: 新的碎片等值
        
        Returns:
            True 表示修改成功，False 表示失败
        """
        key = key.strip()
        if key not in self._equivalents:
            self.logger.warning(f"未知的等值键: {key}")
            return False
        self._equivalents[key] = int(value)
        success = self._save_to_config()
        if success:
            self.logger.info(f"已更新等值: {key} = {value}")
        return success

    def set_luck_level(self, level_name: str, threshold: float) -> bool:
        """✏️ 修改欧非值等级阈值，并持久化写入 azur_lane.json
        
        Args:
            level_name: 等级名称 ("极欧", "较欧", "正常", "较非", "极非")
            threshold: 新阈值
        
        Returns:
            True 表示修改成功，False 表示失败
        """
        level_name = level_name.strip()
        if not level_name:
            return False
        self._luck_levels[level_name] = float(threshold)
        success = self._save_to_config()
        if success:
            self.logger.info(f"已更新欧非值阈值: {level_name} = {threshold}")
        return success

    def reset_to_defaults(self) -> bool:
        """🔄 将所有公式恢复为默认值，并持久化"""
        self._equivalents = dict(self.DEFAULT_EQUIVALENTS)
        self._luck_levels = dict(self.DEFAULT_LUCK_LEVELS)
        self._special_equipment_ids = None  # 清除缓存，下次重新加载
        success = self._save_to_config()
        if success:
            self.logger.info("已恢复默认公式配置")
        return success

    def _save_to_config(self) -> bool:
        """【内部】将当前等值映射和欧非值阈值写回 azur_lane.json 配置文件"""
        try:
            config_loader = get_config_loader()
            game_config = config_loader.get_game_config("azur_lane")
            if "calculations" not in game_config:
                game_config["calculations"] = {}
            game_config["calculations"]["fragment_equivalents"] = dict(self._equivalents)
            game_config["calculations"]["luck_levels"] = dict(self._luck_levels)
            config_loader.save_config("games", "azur_lane", game_config)
            self.logger.debug("已保存公式配置到 azur_lane.json")
            return True
        except Exception as e:
            self.logger.error(f"保存公式配置失败: {e}")
            return False

    # ══════════════════════════════════════════════════════════════
    #  特殊装备管理代理方法
    # ══════════════════════════════════════════════════════════════

    def add_special_equipment(self, equipment_id: str, name: str = "", notes: str = "") -> bool:
        """➕ 添加特殊装备（代理到 SpecialEquipmentManager）"""
        result = self.special_manager.add_special(equipment_id, name, notes)
        if result:
            self._special_equipment_ids = None  # 清除缓存
        return result

    def remove_special_equipment(self, equipment_id: str) -> bool:
        """🗑️ 删除特殊装备（代理到 SpecialEquipmentManager）"""
        result = self.special_manager.delete_special(equipment_id)
        if result:
            self._special_equipment_ids = None
        return result

    def get_special_equipment_list(self) -> List[Dict[str, Any]]:
        """📋 获取所有特殊装备列表"""
        return self.special_manager.get_all()

    # ══════════════════════════════════════════════════════════════
    #  欧非值相关方法
    # ══════════════════════════════════════════════════════════════

    def get_luck_levels(self) -> List[Dict[str, Any]]:
        """📊 获取欧非值等级阈值列表（按阈值从高到低排序）
        
        Returns:
            [{"level": "极欧", "threshold": 2.0}, {"level": "较欧", "threshold": 1.3}, ...]
        """
        if not self._luck_levels:
            self._load_from_config()
        # 按阈值从高到低排序
        sorted_levels = sorted(self._luck_levels.items(), key=lambda x: x[1], reverse=True)
        return [{"level": name, "threshold": val} for name, val in sorted_levels]

    def get_luck_level_name(self, luck_value: float) -> str:
        """🏷️ 根据欧非值数字返回对应的等级名称
        
        Args:
            luck_value: 欧非值（浮点数）
        
        Returns:
            等级名称 ("极欧" / "较欧" / "正常" / "较非" / "极非")
        
        判定逻辑（按阈值从高到低遍历，第一个满足条件的即为结果）:
            value >= 2.0 → "极欧"
            value >= 1.3 → "较欧"
            value >  0.7 → "正常"
            value >  0.4 → "较非"
            否则        → "极非"
        """
        # 按阈值从高到低排序，依次判断
        sorted_levels = sorted(self._luck_levels.items(), key=lambda x: x[1], reverse=True)
        for level_name, threshold in sorted_levels:
            if luck_value >= threshold:
                return level_name
        # 理论上不会走到这里（极非的阈值是 0.0），但兜底返回
        return list(self._luck_levels.keys())[-1] if self._luck_levels else "未知"

    def get_equivalents(self) -> Dict[str, int]:
        """📋 获取当前全部碎片等值映射（返回副本）"""
        return dict(self._equivalents)

    # ══════════════════════════════════════════════════════════════
    #  缓存刷新
    # ══════════════════════════════════════════════════════════════

    def refresh(self):
        """🔄 重新加载所有配置和缓存（用于CSV修改后刷新）"""
        self._load_from_config()
        self._build_research_id_set()
        self._special_equipment_ids = None
        self.logger.info("FormulaManager 已刷新所有缓存")


# ──────────────────────────────────────────────────────────────
#  全局访问函数
# ──────────────────────────────────────────────────────────────

_instance_cache: Optional[FormulaManager] = None


def get_formula_manager() -> FormulaManager:
    """获取全局唯一的 FormulaManager 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = FormulaManager()
    return _instance_cache
