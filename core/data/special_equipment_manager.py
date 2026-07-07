#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║           ⭐ 特殊装备管理器 (SpecialEquipmentManager)             ║
║                                                                  ║
║   【一句话解释】管理那些"不合常规"的特殊装备（如 BR.810 和       ║
║   B-13 这种 25 碎片合成 1 件的非科研金色装备）                   ║
║                                                                  ║
║   【类比理解】                                                    ║
║   装备管理器 = 仓库管理员（管所有装备）                            ║
║   特殊装备管理器 = "特殊物品清单"（管那些不合常规的例外装备）     ║
║                                                                  ║
║   【使用限制】                                                    ║
║   本管理器仅供开发者使用（源码级增删改），不暴露给最终用户。     ║
║   程序运行时只读这份清单来判断装备是否属于特殊类别。              ║
║                                                                  ║
║   【ID 对应规则】                                                 ║
║   equipment_id 必须与 equipment_library.csv 中的 ID 一致。        ║
║   add_special() 会自动校验 ID 是否在装备库中存在。                ║
║   add_special_by_name() 可按装备名称自动查库获取 ID。            ║
║                                                                  ║
║   【数据文件】data/special_equipment.csv                          ║
║   【字段】equipment_id | equipment_name | notes                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
import csv
import os
from typing import Any, Dict, List, Optional, Set
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager


class SpecialEquipmentManager:
    """⭐ 特殊装备管理器 — 管理 data/special_equipment.csv"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式：全局唯一实例（就像一本只给开发者看的特殊清单）"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        # CSV 文件路径：存储在 data/ 目录下，和装备库同级
        self.csv_path = PathManager.get_data_dir() / "special_equipment.csv"
        # CSV 字段名：装备ID | 装备名称 | 备注说明
        self.fieldnames = ["equipment_id", "equipment_name", "notes"]
        # 内存中的数据列表：[{equipment_id, equipment_name, notes}, ...]
        self._data: List[Dict[str, Any]] = []
        # 快速查找集合：存储所有特殊装备的 ID，O(1) 判断
        self._id_set: Set[str] = set()
        # 延迟加载装备管理器（用于校验特殊装备ID是否在装备库中存在）
        self._equip_manager = None
        self._ensure_csv_exists()
        self._load_data()
        self._initialized = True

    # ══════════════════════════════════════════════════════════════
    #  延迟加载属性
    # ══════════════════════════════════════════════════════════════

    @property
    def equip_manager(self):
        """延迟加载装备管理器（用于校验特殊装备ID是否在装备库中存在）"""
        if self._equip_manager is None:
            from .equipment_manager import get_equipment_manager
            self._equip_manager = get_equipment_manager()
        return self._equip_manager

    # ──────────────────────────────────────────────────────────────
    #  内部方法 — CSV 文件读写
    # ──────────────────────────────────────────────────────────────

    def _ensure_csv_exists(self):
        """【内部】确认 special_equipment.csv 存在，不存在则创建带表头的空文件"""
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=self.fieldnames).writeheader()
            self.logger.info("已创建特殊装备表: special_equipment.csv")

    def _load_data(self):
        """【内部】从 CSV 加载全部特殊装备到内存
        同时维护 self._id_set 用于快速查找（O(1) 判断某装备是否为特殊装备）"""
        try:
            self._data.clear()
            self._id_set.clear()
            with open(self.csv_path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    eq_id = row.get("equipment_id", "").strip()
                    if eq_id:
                        self._data.append({
                            "equipment_id": eq_id,
                            "equipment_name": row.get("equipment_name", "").strip(),
                            "notes": row.get("notes", "").strip(),
                        })
                        self._id_set.add(eq_id)
        except Exception as e:
            self.logger.error(f"加载特殊装备表失败: {e}")

    def _save_data(self):
        """【内部】将内存中的特殊装备数据写回 CSV 文件"""
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(self._data)

    # ──────────────────────────────────────────────────────────────
    #  查询方法 — 供计算层调用
    # ──────────────────────────────────────────────────────────────

    def is_special(self, equipment_id: str) -> bool:
        """🔎 判断某个装备 ID 是否为特殊装备

        Args:
            equipment_id: 装备 ID（必须与 equipment_library.csv 中的 ID 一致）

        Returns:
            True 表示该装备在特殊装备清单中，False 表示不在

        示例:
            is_special("1") → True  (BR.810 剑鱼)
            is_special("2") → True  (B-13 双联装130mm)
            is_special("S1-001") → False
        """
        return equipment_id.strip() in self._id_set

    def get_all(self) -> List[Dict[str, Any]]:
        """📋 获取全部特殊装备列表（返回副本，防止外部意外修改）

        Returns:
            [{"equipment_id":"1", "equipment_name":"BR.810 剑鱼(810中队)", "notes":"..."}, ...]
        """
        return [item.copy() for item in self._data]

    def get_all_ids(self) -> Set[str]:
        """🔢 获取所有特殊装备 ID 的集合（返回副本）

        Returns:
            {"1", "2", ...}  (equipment_library.csv 中的真实 ID)
        """
        return self._id_set.copy()

    def get_by_id(self, equipment_id: str) -> Optional[Dict[str, Any]]:
        """🔎 按装备库 ID 查询特殊装备详情

        Args:
            equipment_id: 装备库中的 ID

        Returns:
            找到返回字典，找不到返回 None
        """
        eq_id = equipment_id.strip()
        for item in self._data:
            if item["equipment_id"] == eq_id:
                return item.copy()
        return None

    # ──────────────────────────────────────────────────────────────
    #  增删改方法 — 仅供开发者通过代码调用
    # ──────────────────────────────────────────────────────────────

    def add_special(self, equipment_id: str, equipment_name: str = "",
                    notes: str = "", validate_library: bool = True) -> bool:
        """➕ 添加一件特殊装备到清单中

        重要: equipment_id 必须与 equipment_library.csv 中的 ID 一致！

        Args:
            equipment_id: 装备库中的真实 ID（必填，不可重复）
            equipment_name: 装备名称（可选，留空时自动从装备库获取）
            notes: 备注说明（如"25碎片合成的特殊金装备"）
            validate_library: 是否校验 ID 在装备库中存在（默认 True）

        Returns:
            True 表示添加成功，False 表示失败

        示例:
            add_special("1", notes="特殊金装备——英航剑鱼")
        """
        eq_id = equipment_id.strip()
        if not eq_id:
            self.logger.warning("特殊装备 ID 不能为空")
            return False
        if eq_id in self._id_set:
            self.logger.warning(f"特殊装备 ID 已存在: {eq_id}")
            return False
        # 校验装备ID是否在装备库中存在
        if validate_library:
            lib_equip = self.equip_manager.get_by_id(eq_id)
            if not lib_equip:
                self.logger.warning(
                    f"装备ID {eq_id} 在装备库中不存在，无法添加为特殊装备"
                )
                return False
            # 如果没传名称，从装备库自动获取
            if not equipment_name.strip():
                equipment_name = lib_equip.get("name", "")
        self._data.append({
            "equipment_id": eq_id,
            "equipment_name": equipment_name.strip(),
            "notes": notes.strip(),
        })
        self._id_set.add(eq_id)
        self._save_data()
        self.logger.info(f"已添加特殊装备: {eq_id} ({equipment_name})")
        return True

    def add_special_by_name(self, equipment_name: str, notes: str = "") -> bool:
        """🔍 按装备名称添加特殊装备（自动查装备库获取ID）

        Args:
            equipment_name: 装备名称（必须在装备库中存在）
            notes: 备注说明

        Returns:
            True 添加成功，False 失败（名称不存在或已添加）

        示例:
            add_special_by_name("BR.810 剑鱼(810中队)", "特殊金装备")
        """
        name = equipment_name.strip()
        if not name:
            self.logger.warning("装备名称不能为空")
            return False
        lib_equip = self.equip_manager.get_by_name(name)
        if not lib_equip:
            self.logger.warning(f"装备库中不存在名为 {name} 的装备")
            return False
        eq_id = lib_equip.get("equipment_id", "")
        return self.add_special(eq_id, name, notes, validate_library=False)

    def update_special(self, equipment_id: str, updates: Dict[str, Any]) -> bool:
        """🔄 更新特殊装备信息（不能修改 ID）

        Args:
            equipment_id: 要更新的装备库 ID
            updates: 要更新的字段，如 {"equipment_name": "新名称", "notes": "新备注"}

        Returns:
            True 表示更新成功，False 表示 ID 不存在
        """
        eq_id = equipment_id.strip()
        for i, item in enumerate(self._data):
            if item["equipment_id"] == eq_id:
                for key, value in updates.items():
                    if key in self.fieldnames:
                        self._data[i][key] = str(value).strip()
                self._save_data()
                self.logger.info(f"已更新特殊装备: {eq_id}")
                return True
        self.logger.warning(f"特殊装备 ID 不存在: {eq_id}")
        return False

    def delete_special(self, equipment_id: str) -> bool:
        """🗑️ 从特殊装备清单中删除一件装备

        Args:
            equipment_id: 装备库中的 ID

        Returns:
            True 表示删除成功，False 表示 ID 不存在
        """
        eq_id = equipment_id.strip()
        for i, item in enumerate(self._data):
            if item["equipment_id"] == eq_id:
                del self._data[i]
                self._id_set.discard(eq_id)
                self._save_data()
                self.logger.info(f"已删除特殊装备: {eq_id}")
                return True
        self.logger.warning(f"特殊装备 ID 不存在: {eq_id}")
        return False

    def reload(self):
        """🔄 重新从 CSV 加载数据（手动修改 CSV 后调用此方法刷新内存）"""
        self._load_data()
        self.logger.info(f"已重新加载特殊装备表，共 {len(self._data)} 条记录")


# ──────────────────────────────────────────────────────────────
#  全局访问函数
# ──────────────────────────────────────────────────────────────

_instance_cache: Optional[SpecialEquipmentManager] = None


def get_special_equipment_manager() -> SpecialEquipmentManager:
    """获取全局唯一的 SpecialEquipmentManager 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = SpecialEquipmentManager()
    return _instance_cache
