#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║            📋 用户数据管理器 (UserDataManager)                    ║
║                                                                  ║
║   【一句话解释】管理用户每日的装备数量 & 碎片数量记录。           ║
║   每天一个 CSV 文件，修改只对当天文件进行，隔天自动新建。        ║
║                                                                  ║
║   【类比理解】                                                    ║
║   用户数据管理器 = "科研进度日记本"                               ║
║   每天一页，记录当天每种装备有多少件、多少碎片。                  ║
║   想翻看过去某天？直接翻到那一页。想统计趋势？把所有页汇总。     ║
║                                                                  ║
║   【目录结构】                                                    ║
║   data/user_records/                                             ║
║       ├── 2026-07-06.csv    ← 已归档，不再修改                    ║
║       ├── 2026-07-07.csv    ← 今天的记录（可修改）                ║
║       └── 2026-07-08.csv    ← 还没到呢                            ║
║                                                                  ║
║   【CSV 格式】equipment_id, equipment_count, fragment_count       ║
║   示例: S1-001,2,30  → 第1期第1件装备，拥有2件成品+30碎片        ║
╚══════════════════════════════════════════════════════════════════╝
"""
import csv
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.path_manager import PathManager


class UserDataManager:
    """📋 用户数据管理器 — 管理 data/user_records/ 下的每日 CSV"""
    _instance = None

    # ── CSV 字段名 ──
    FIELDNAMES = ["equipment_id", "equipment_count", "fragment_count"]

    def __new__(cls, *args, **kwargs):
        """单例模式：全局唯一实例（每个人的日记本只有一本）"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        # ── 用户数据根目录: data/user_records/ ──
        self._records_dir = PathManager.get_data_dir() / "user_records"
        self._ensure_dir_exists()
        self._initialized = True

    # ──────────────────────────────────────────────────────────────
    #  内部方法 — 目录 & 文件管理
    # ──────────────────────────────────────────────────────────────

    def _ensure_dir_exists(self):
        """【内部】确保 data/user_records/ 目录存在"""
        os.makedirs(self._records_dir, exist_ok=True)

    def _get_filepath(self, target_date: Optional[str] = None) -> str:
        """【内部】根据日期获取对应的 CSV 文件路径
        
        Args:
            target_date: 日期字符串 "YYYY-MM-DD"，不传则使用今天
        
        Returns:
            完整文件路径，如 "data/user_records/2026-07-07.csv"
        """
        date_str = target_date if target_date else self._today_str()
        return os.path.join(str(self._records_dir), f"{date_str}.csv")

    @staticmethod
    def _today_str() -> str:
        """【内部】获取今天的日期字符串 "YYYY-MM-DD" """
        return date.today().isoformat()

    def _ensure_file_exists(self, filepath: str):
        """【内部】如果文件不存在，创建带表头的空 CSV"""
        if not os.path.exists(filepath):
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=self.FIELDNAMES).writeheader()
            self.logger.debug(f"已创建用户数据文件: {os.path.basename(filepath)}")

    # ──────────────────────────────────────────────────────────────
    #  读取方法
    # ──────────────────────────────────────────────────────────────

    def get_today_data(self) -> Dict[str, Dict[str, int]]:
        """📖 读取今天的装备数据记录
        
        Returns:
            {
                "S1-001": {"equipment_count": 2, "fragment_count": 30},
                "S1-002": {"equipment_count": 1, "fragment_count": 15},
                ...
            }
            如果今天还没有记录文件，返回空字典 {}
        """
        return self.get_data_by_date(self._today_str())

    def get_data_by_date(self, target_date: str) -> Dict[str, Dict[str, int]]:
        """📖 读取指定日期的装备数据记录
        
        Args:
            target_date: 日期字符串 "YYYY-MM-DD"
        
        Returns:
            同 get_today_data() 格式。文件不存在或为空则返回 {}
        """
        filepath = self._get_filepath(target_date)
        if not os.path.exists(filepath):
            return {}
        try:
            result: Dict[str, Dict[str, int]] = {}
            with open(filepath, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    eq_id = row.get("equipment_id", "").strip()
                    if not eq_id:
                        continue
                    result[eq_id] = {
                        "equipment_count": int(row.get("equipment_count", 0)),
                        "fragment_count": int(row.get("fragment_count", 0)),
                    }
            return result
        except Exception as e:
            self.logger.error(f"读取用户数据失败 ({target_date}): {e}")
            return {}

    def get_history(self, equipment_id: str) -> List[Dict[str, Any]]:
        """📊 获取某件装备的历史数据（遍历所有日期文件，按时间排序）
        
        Args:
            equipment_id: 装备 ID，如 "S1-001"
        
        Returns:
            [
                {"date": "2026-07-06", "equipment_count": 1, "fragment_count": 20},
                {"date": "2026-07-07", "equipment_count": 2, "fragment_count": 30},
                ...
            ]
            按日期升序排列（旧 → 新）
        """
        eq_id = str(equipment_id).strip()
        history: List[Dict[str, Any]] = []

        # 列出 user_records 目录下所有 CSV 文件
        if not os.path.exists(str(self._records_dir)):
            return history
        for filename in os.listdir(str(self._records_dir)):
            if not filename.endswith(".csv"):
                continue
            date_str = filename[:-4]  # 去掉 .csv 后缀 → "2026-07-07"
            filepath = os.path.join(str(self._records_dir), filename)
            try:
                with open(filepath, "r", encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        if row.get("equipment_id", "").strip() == eq_id:
                            history.append({
                                "date": date_str,
                                "equipment_count": int(row.get("equipment_count", 0)),
                                "fragment_count": int(row.get("fragment_count", 0)),
                            })
                            break  # 每天只取第一条匹配
            except Exception as e:
                self.logger.warning(f"读取历史文件失败 ({filename}): {e}")

        # 按日期升序排序（旧在前，新在后）
        history.sort(key=lambda x: x["date"])
        return history

    def get_all_history(self) -> Dict[str, Dict[str, Dict[str, int]]]:
        """📊 获取全部装备的完整历史数据
        
        Returns:
            {
                "2026-07-06": {"S1-001": {"equipment_count": 1, "fragment_count": 20}, ...},
                "2026-07-07": {"S1-001": {"equipment_count": 2, "fragment_count": 30}, ...},
            }
            按日期键排序
        """
        result: Dict[str, Dict[str, Dict[str, int]]] = {}
        if not os.path.exists(str(self._records_dir)):
            return result
        for filename in sorted(os.listdir(str(self._records_dir))):
            if not filename.endswith(".csv"):
                continue
            date_str = filename[:-4]
            result[date_str] = self.get_data_by_date(date_str)
        return result

    def list_available_dates(self) -> List[str]:
        """📅 列出所有有记录的日期（按日期升序排列）
        
        Returns:
            ["2026-07-06", "2026-07-07", ...]
        """
        dates: List[str] = []
        if not os.path.exists(str(self._records_dir)):
            return dates
        for filename in os.listdir(str(self._records_dir)):
            if filename.endswith(".csv"):
                dates.append(filename[:-4])
        dates.sort()
        return dates

    # ──────────────────────────────────────────────────────────────
    #  写入方法
    # ──────────────────────────────────────────────────────────────

    def update_record(self, equipment_id: str, equipment_count: int, fragment_count: int,
                      target_date: Optional[str] = None) -> bool:
        """✏️ 更新单件装备的拥有数量 & 碎片数量（只修改当天文件）
        
        Args:
            equipment_id: 装备 ID，如 "S1-001"
            equipment_count: 拥有该装备的件数
            fragment_count: 拥有的该装备碎片数
            target_date: 指定日期（不传则默认今天）
        
        Returns:
            True 表示写入成功，False 表示失败
        """
        eq_id = str(equipment_id).strip()
        if not eq_id:
            self.logger.warning("装备 ID 不能为空")
            return False
        filepath = self._get_filepath(target_date)
        self._ensure_file_exists(filepath)

        try:
            # ── 步骤①: 读取当日全部数据 ──
            day_data = self.get_data_by_date(target_date or self._today_str())
            # ── 步骤②: 更新或新增指定装备的记录 ──
            day_data[eq_id] = {
                "equipment_count": int(equipment_count),
                "fragment_count": int(fragment_count),
            }
            # ── 步骤③: 全量写回 CSV ──
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
                for eid, data in day_data.items():
                    writer.writerow({
                        "equipment_id": eid,
                        "equipment_count": data["equipment_count"],
                        "fragment_count": data["fragment_count"],
                    })
            self.logger.debug(f"已更新记录: {eq_id} (件数={equipment_count}, 碎片={fragment_count})")
            return True
        except Exception as e:
            self.logger.error(f"更新记录失败 ({eq_id}): {e}")
            return False

    def update_batch(self, records: Dict[str, Dict[str, int]],
                     target_date: Optional[str] = None) -> Dict[str, Any]:
        """📦 批量更新多件装备的记录
        
        Args:
            records: {
                "S1-001": {"equipment_count": 2, "fragment_count": 30},
                "S1-002": {"equipment_count": 1, "fragment_count": 15},
            }
            target_date: 指定日期（不传则默认今天）
        
        Returns:
            {"total": 总数, "success": 成功数, "failed": 失败数, "failed_ids": [...]}
        """
        total = len(records)
        success = 0
        failed = 0
        failed_ids: List[str] = []

        for eq_id, data in records.items():
            if self.update_record(
                eq_id,
                data.get("equipment_count", 0),
                data.get("fragment_count", 0),
                target_date,
            ):
                success += 1
            else:
                failed += 1
                failed_ids.append(eq_id)

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "failed_ids": failed_ids,
        }

    def delete_record(self, equipment_id: str, target_date: Optional[str] = None) -> bool:
        """🗑️ 从当日记录中删除某件装备（不是删除历史文件，而是把这条装备从今日CSV中移除）
        
        Args:
            equipment_id: 装备 ID
            target_date: 指定日期（不传则默认今天）
        
        Returns:
            True 表示确实删除了记录，False 表示记录不存在或删除失败
        """
        eq_id = str(equipment_id).strip()
        if not eq_id:
            self.logger.warning("装备 ID 不能为空")
            return False

        filepath = self._get_filepath(target_date)
        if not os.path.exists(filepath):
            return False  # 文件不存在 = 没有可删除的记录

        try:
            day_data = self.get_data_by_date(target_date or self._today_str())
            if eq_id not in day_data:
                self.logger.debug(f"记录不存在，无需删除: {eq_id}")
                return False

            del day_data[eq_id]
            # 写回 CSV
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
                for eid, data in day_data.items():
                    writer.writerow({
                        "equipment_id": eid,
                        "equipment_count": data["equipment_count"],
                        "fragment_count": data["fragment_count"],
                    })
            self.logger.debug(f"已删除记录: {eq_id}")
            return True
        except Exception as e:
            self.logger.error(f"删除记录失败 ({eq_id}): {e}")
            return False


# ──────────────────────────────────────────────────────────────
#  全局访问函数
# ──────────────────────────────────────────────────────────────

_instance_cache: Optional[UserDataManager] = None


def get_user_data_manager() -> UserDataManager:
    """获取全局唯一的 UserDataManager 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = UserDataManager()
    return _instance_cache
