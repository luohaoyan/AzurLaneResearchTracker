#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              🌈 稀有度独立管理器 (RarityManager)                 ║
║   【一句话解释】稀有度不是写死在代码里，存在 CSV 文件中。         ║
║   【类比理解】就像"稀有度字典"：查"海上传奇"→ ID=5, 颜色粉红   ║
║   【数据文件】data/rarities.csv                                  ║
║   【字段】rarity_id | name | color_hex | sort_order              ║
╚══════════════════════════════════════════════════════════════════╝
"""
import csv
import os
from typing import Any, Dict, List, Optional
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager


class RarityManager:
    """🌈 稀有度管理器 - 管理 data/rarities.csv"""
    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式：全局唯一实例（就像世界上的唯一一本字典）"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.csv_path = PathManager.get_data_dir() / "rarities.csv"
        self.fieldnames = ["rarity_id", "name", "color_hex", "sort_order"]
        self._data: List[Dict[str, Any]] = []
        self._ensure_csv()
        self._load()
        self._initialized = True

    # ── CSV 读写内部方法 ──
    def _ensure_csv(self):
        """【内部】文件不存在就创建带表头的空CSV"""
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=self.fieldnames).writeheader()

    def _load(self):
        """【内部】从 CSV 加载全部数据到内存列表"""
        try:
            self._data.clear()
            with open(self.csv_path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    row["rarity_id"] = int(row.get("rarity_id", 0))
                    row["sort_order"] = int(row.get("sort_order", 0))
                    self._data.append(row)
        except Exception as e:
            self.logger.error(f"加载稀有度CSV失败:{e}")

    def _save(self):
        """【内部】将内存数据写回 CSV 文件"""
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.fieldnames)
            w.writeheader()
            w.writerows(self._data)

    # ── 查询方法 ──
    def get_all(self) -> List[Dict[str, Any]]:
        """获取全部稀有度（按 sort_order 排序）
        返回示例: [{"rarity_id":1,"name":"普通","color_hex":"#FFFFFF","sort_order":1}, ...]"""
        return [r.copy() for r in sorted(self._data, key=lambda x: x["sort_order"])]

    def get_by_id(self, rarity_id: int) -> Optional[Dict[str, Any]]:
        """按ID查稀有度 → 字典或None。示例: get_by_id(5) → {"rarity_id":5,"name":"海上传奇",...}"""
        for r in self._data:
            if r["rarity_id"] == rarity_id:
                return r.copy()
        return None

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称查稀有度。示例: get_by_name("超稀有")"""
        for r in self._data:
            if r["name"] == name:
                return r.copy()
        return None

    # ── 增删改（仅供开发者通过代码调用）──
    def add_rarity(self, rarity: Dict[str, Any]) -> bool:
        """添加新稀有度等级。输入: {"name":"传说","color_hex":"#FF0000","sort_order":6}
        输出: True=成功, False=失败(ID重复)"""
        try:
            if not rarity.get("rarity_id", 0):
                max_id = max((r["rarity_id"] for r in self._data), default=0)
                rarity["rarity_id"] = max_id + 1
            if self.get_by_id(rarity["rarity_id"]):
                return False
            self._data.append({
                "rarity_id": int(rarity["rarity_id"]),
                "name": rarity.get("name", ""),
                "color_hex": rarity.get("color_hex", "#FFFFFF"),
                "sort_order": int(rarity.get("sort_order", 99)),
            })
            self._save()
            return True
        except Exception as e:
            self.logger.error(f"添加稀有度失败:{e}")
            return False

    def update_rarity(self, rarity_id: int, updates: Dict[str, Any]) -> bool:
        """更新稀有度。输入: update_rarity(5, {"name":"新名字"})"""
        try:
            for i, r in enumerate(self._data):
                if r["rarity_id"] == rarity_id:
                    for k, v in updates.items():
                        if k in self.fieldnames:
                            self._data[i][k] = int(v) if k in ("rarity_id","sort_order") else v
                    self._save()
                    return True
            return False
        except Exception as e:
            self.logger.error(f"更新稀有度失败:{e}")
            return False

    def delete_rarity(self, rarity_id: int) -> bool:
        """删除稀有度。示例: delete_rarity(5) → True"""
        for i, r in enumerate(self._data):
            if r["rarity_id"] == rarity_id:
                del self._data[i]
                self._save()
                self.logger.info(f"删除稀有度 ID:{rarity_id}")
                return True
        return False


_instance_cache = None

def get_rarity_manager() -> RarityManager:
    """获取全局唯一的 RarityManager 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = RarityManager()
    return _instance_cache
