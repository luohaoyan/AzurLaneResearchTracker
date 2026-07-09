#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              🎮 装备数据管理器 (EquipmentManager)                 ║
║                                                                  ║
║   【一句话解释】装备库的"增删改查"大管家                           ║
║   【类比理解】就像仓库管理员，管每件装备的名称、类型、稀有度       ║
║                                                                  ║
║   【ID 规则】                                                     ║
║   科研装备: S{期数}-{序号:03d}  例如: S1-001, S7-003              ║
║   通用装备: G{序号:04d}         例如: G0001, G0002, G0003                     ║
║                                                                  ║
║   【期数编码】期数信息完全通过 ID 编码（S1-001 = 第1期第1件）     ║
║   CSV 中不再单独存 research_phase 字段，消除数据冗余              ║
║                                                                  ║
║   【数据文件】                                                    ║
║   data/equipment_library.csv  ← 装备数据                           ║
║   data/equipment_images.csv   ← 图片映射表（独立管理，分离存储）   ║
║   data/rarities.csv           ← 稀有度引用（通过 rarity_id 关联）  ║
╚══════════════════════════════════════════════════════════════════╝
"""
import csv
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager


class EquipmentManager:
    """🎮 装备数据管理器 — 管理装备库 CSV + 图片映射 CSV"""
    _instance = None
    RESEARCH_ID_PATTERN = re.compile(r"^S(\d+)-(\d{3})$")  # 正则: 匹配 S1-001 这类 ID

    def __new__(cls, *args, **kwargs):
        """单例模式：确保全局只有一个装备管理器实例"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.data_dir = PathManager.get_data_dir()
        self.csv_path = self.data_dir / "equipment_library.csv"
        self.images_csv_path = self.data_dir / "equipment_images.csv"
        self.fieldnames = ["equipment_id", "name", "rarity_id", "type"]  # 4 个字段, 无 research_phase
        self._data: List[Dict[str, Any]] = []
        self._images: Dict[str, str] = {}         # 图片映射 {equipment_id: image_path}
        self._rarity_manager = None                # 延迟加载
        self._ensure_csv_exists()
        self._load_data()
        self._load_images()
        self._initialized = True

    @property
    def rarity_manager(self):
        """延迟加载稀有度管理器（用的时候才加载，节省内存）"""
        if self._rarity_manager is None:
            from .rarity_manager import get_rarity_manager
            self._rarity_manager = get_rarity_manager()
        return self._rarity_manager

    # ── CSV 文件读写（内部方法）──

    def _ensure_csv_exists(self):
        """两个 CSV 文件不存在时自动创建（带表头）"""
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=self.fieldnames).writeheader()
        if not os.path.exists(self.images_csv_path):
            with open(self.images_csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=["equipment_id", "image_path"]).writeheader()

    def _load_data(self):
        """从 CSV 加载装备数据到内存列表 self._data"""
        try:
            self._data.clear()
            with open(self.csv_path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    row["rarity_id"] = int(row.get("rarity_id", 0))
                    self._data.append(row)
        except Exception as e:
            self.logger.error(f"加载装备库失败:{e}")

    def _load_images(self):
        """从 equipment_images.csv 加载图片映射到内存字典 self._images"""
        try:
            self._images.clear()
            if os.path.exists(self.images_csv_path):
                with open(self.images_csv_path, "r", encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        eid = row.get("equipment_id", "").strip()
                        pth = row.get("image_path", "").strip()
                        if eid:
                            self._images[eid] = pth
        except Exception as e:
            self.logger.error(f"加载图片映射失败:{e}")

    def _save_data(self):
        """将内存中的装备数据写回 CSV 文件"""
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=self.fieldnames).writeheader()
            csv.DictWriter(f, fieldnames=self.fieldnames).writerows(self._data)

    def _save_images(self):
        """将内存中的图片映射写回 CSV 文件"""
        with open(self.images_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["equipment_id", "image_path"])
            w.writeheader()
            for eid, pth in self._images.items():
                w.writerow({"equipment_id": eid, "image_path": pth})

    # ── ID 工具方法 ──

    @classmethod
    def parse_research_id(cls, equipment_id: str) -> Optional[Tuple[int, int]]:
        """🔍 解析科研装备 ID → (期数, 序号)
        输入: "S1-001" → 输出: (1, 1)
        输入: "123"   → 输出: None（通用装备）"""
        equipment_id = equipment_id.strip();m = cls.RESEARCH_ID_PATTERN.match(equipment_id)
        return (int(m.group(1)), int(m.group(2))) if m else None

    @classmethod
    def make_research_id(cls, phase: int, seq: int) -> str:
        """🔧 生成科研装备 ID
        输入: phase=7, seq=3 → 输出: "S7-003"（3位数字，不够补0）"""
        return f"S{phase}-{seq:03d}"

    def _generate_id(self, is_research: bool, phase: int = 0) -> str:
        """🤖 自动生成下一个装备 ID
        - is_research=True  → 找该期最大序号+1
        - is_research=False → 找最大 G 前缀 ID+1"""
        if is_research and phase <= 0:
            raise ValueError(f"research equip ID needs valid phase, got phase={phase}")
        if is_research:
            max_seq = 0
            prefix = f"S{phase}-"
            for eq in self._data:
                eid = eq.get("equipment_id", "")
                if eid.startswith(prefix):
                    p = self.parse_research_id(eid)
                    if p and p[1] > max_seq:
                        max_seq = p[1]
            return self.make_research_id(phase, max_seq + 1)
        else:
            max_seq = 0
            for eq in self._data:
                eid = eq.get("equipment_id", "")
                if eid.startswith("G"):
                    try:
                        seq = int(eid[1:])
                        if seq > max_seq:
                            max_seq = seq
                    except ValueError:
                        pass
            return f"G{max_seq + 1:04d}"

    def _is_research_equipment(self, equipment_id: str) -> bool:
        """🔍 判断是否为科研装备（ID 格式为 S{期数}-{序号}）"""
        return bool(self.RESEARCH_ID_PATTERN.match(equipment_id))

    # ── 基础查询方法 ──

    def get_all(self) -> List[Dict[str, Any]]:
        """📋 获取全部装备列表。返回: [{"equipment_id":"S1-001","name":"...","rarity_id":5,"type":"战列炮"}, ...]"""
        return [eq.copy() for eq in self._data]

    def get_by_id(self, equipment_id: str) -> Optional[Dict[str, Any]]:
        """🔎 按 ID 查找装备。示例: get_by_id("S1-001") → 返回装备字典或 None"""
        for eq in self._data:
            if eq.get("equipment_id") == equipment_id:
                return eq.copy()
        return None

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """🔎 按名称精确查找。示例: get_by_name("试作型三联装406mm主炮Mk6")"""
        for eq in self._data:
            if eq.get("name") == name:
                return eq.copy()
        return None

    def search_by_name(self, keyword: str) -> List[Dict[str, Any]]:
        """🔍 按名称模糊搜索（不区分大小写）。示例: search_by_name("406") → 找到包含"406"的所有装备"""
        kw = keyword.lower()
        return [eq.copy() for eq in self._data if kw in eq.get("name", "").lower()]

    def get_by_rarity_id(self, rarity_id: int) -> List[Dict[str, Any]]:
        """🎨 按稀有度筛选。示例: get_by_rarity_id(5) → 所有彩虹装备"""
        return [eq.copy() for eq in self._data if eq.get("rarity_id") == rarity_id]

    def get_by_type(self, eq_type: str) -> List[Dict[str, Any]]:
        """📦 按装备类型筛选。示例: get_by_type("战列炮") → 所有战列炮"""
        return [eq.copy() for eq in self._data if eq.get("type") == eq_type]

    def get_by_phase(self, phase_number: int) -> List[Dict[str, Any]]:
        """📅 按科研期数筛选（通过 ID 前缀匹配 S{期数}-）
        示例: get_by_phase(1) → 返回第1期所有装备"""
        prefix = f"S{phase_number}-"
        return [eq.copy() for eq in self._data if str(eq.get("equipment_id", "")).startswith(prefix)]

    def get_research_equipment(self) -> List[Dict[str, Any]]:
        """🏆 获取所有科研装备（ID 匹配 S{期数}-{序号} 格式）"""
        return [eq.copy() for eq in self._data if self._is_research_equipment(eq.get("equipment_id", ""))]

    def get_general_equipment(self) -> List[Dict[str, Any]]:
        """📦 获取所有通用装备（ID 不匹配科研格式的普通装备）"""
        return [eq.copy() for eq in self._data if not self._is_research_equipment(eq.get("equipment_id", ""))]

    # ── 稀有度增强 ──

    def get_rarity_info(self, rarity_id: int) -> Optional[Dict[str, Any]]:
        """🎨 查稀有度详情（委托 rarity_manager 处理）"""
        return self.rarity_manager.get_by_id(rarity_id)

    def get_with_rarity_name(self, equipment: Dict[str, Any]) -> Dict[str, Any]:
        """🎨 在装备字典上附加 rarity_name 和 rarity_color 两个字段
        输入: {"equipment_id":"S1-001","rarity_id":5,...}
        输出: {...加上 "rarity_name":"海上传奇","rarity_color":"#FF69B4"}"""
        result = equipment.copy()
        info = self.get_rarity_info(result.get("rarity_id", 0))
        if info:
            result["rarity_name"] = info["name"]
            result["rarity_color"] = info["color_hex"]
        return result

    # ── 图片映射管理 ──

    def get_image_path(self, equipment_id: str) -> Optional[str]:
        """🖼️ 获取装备图片路径。返回: "images/equipment/S1-001.png" 或 None"""
        pth = self._images.get(equipment_id, "")
        return pth if pth else None

    def set_image_path(self, equipment_id: str, image_path: str) -> bool:
        """🖼️ 设置装备图片路径（自动保存到 CSV）。返回 True/False"""
        if not self.get_by_id(equipment_id):
            self.logger.warning(f"装备{equipment_id}不存在")
            return False
        self._images[equipment_id] = image_path
        self._save_images()
        self.logger.info(f"设置图片:{equipment_id} → {image_path}")
        return True

    def batch_set_images(self, mappings: Dict[str, str]) -> int:
        """🖼️ 批量设置图片路径。输入: {"S1-001":"img/1.png","S1-002":"img/2.png"}
        返回: 成功设置的数量"""
        count = 0
        for eid, pth in mappings.items():
            if self.set_image_path(eid, pth):
                count += 1
        return count

    def get_all_images(self) -> Dict[str, str]:
        """🖼️ 获取全部图片映射字典 {equipment_id: image_path}"""
        return dict(self._images)

    def get_equipment_with_image(self) -> List[Dict[str, Any]]:
        """🖼️ 获取全部装备及其图片路径（含稀有度名称）"""
        result = []
        for eq in self._data:
            eid = eq.get("equipment_id", "")
            eq_copy = self.get_with_rarity_name(eq)
            eq_copy["image_path"] = self._images.get(eid, "") or None
            result.append(eq_copy)
        return result

    # ── CRUD 操作 ──

    def add_equipment(self, equipment: Dict[str, Any]) -> bool:
        """✨ 添加装备（自动 ID + 名称去重 + 稀有度校验）
        输入格式:
            {"name":"试作型三联装406mm","rarity_id":5,"type":"战列炮",
             "equipment_id":"S1-001"(可选, 不传自动生成),
             "research_phase":7(仅用于生成ID时判断是否为科研装备, 不入CSV)}
        输出: True=成功, False=失败"""
        try:
            name = equipment.get("name", "").strip()
            if not name:
                self.logger.warning("装备名称不能为空")
                return False
            if self.get_by_name(name):
                self.logger.warning(f"装备名称已存在:{name}")
                return False
            rarity_id = int(equipment.get("rarity_id", 0))
            if not self.rarity_manager.get_by_id(rarity_id):
                self.logger.warning(f"无效稀有度ID:{rarity_id}")
                return False
            eq_id = str(equipment.get("equipment_id", "")).strip()
            if not eq_id:
                # 没传 ID 就自动生成：通过 research_phase>0 判断是否为科研装备
                research_phase = int(equipment.get("research_phase", 0))
                eq_id = self._generate_id(research_phase > 0, research_phase)
            elif self.get_by_id(eq_id):
                self.logger.warning(f"装备ID已存在:{eq_id}")
                return False
            record = {
                "equipment_id": eq_id,
                "name": name,
                "rarity_id": rarity_id,
                "type": equipment.get("type", ""),
            }
            self._data.append(record)
            self._save_data()
            self.logger.info(f"装备已添加:{name}(ID:{eq_id})")
            return True
        except Exception as e:
            self.logger.error(f"添加装备失败:{e}")
            return False

    def update_equipment(self, equipment_id: str, updates: Dict[str, Any]) -> bool:
        """🔄 更新装备信息（改名时自动检查是否重名）
        输入: update_equipment("S1-001", {"name":"新名字","rarity_id":4})
        注意: research_phase 不可更新（它编码在 ID 中）"""
        try:
            new_name = updates.get("name", "").strip()
            if new_name:
                existing = self.get_by_name(new_name)
                if existing and existing["equipment_id"] != equipment_id:
                    self.logger.warning(f"装备名称已存在:{new_name}")
                    return False
            for i, eq in enumerate(self._data):
                if eq.get("equipment_id") == equipment_id:
                    if "rarity_id" in updates:
                        rid = int(updates["rarity_id"])
                        if not self.rarity_manager.get_by_id(rid):
                            return False
                    for k, v in updates.items():
                        if k in self.fieldnames:
                            self._data[i][k] = int(v) if k == "rarity_id" else str(v)
                    self._save_data()
                    self.logger.info(f"装备已更新:{equipment_id}")
                    return True
            self.logger.warning(f"装备ID不存在:{equipment_id}")
            return False
        except Exception as e:
            self.logger.error(f"更新装备失败:{e}")
            return False

    def delete_equipment(self, equipment_id: str) -> bool:
        """🗑️ 删除装备（同步删除图片映射）"""
        for i, eq in enumerate(self._data):
            if eq.get("equipment_id") == equipment_id:
                del self._data[i]
                self._save_data()
                self._images.pop(equipment_id, None)
                self._save_images()
                self.logger.info(f"装备已删除:{equipment_id}")
                return True
        return False

    # ── 批量导入 ──

    def import_equipment_batch(self, equipment_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """📦 批量导入装备，自动跳过重名
        返回: {"total":总数, "added":成功数, "skipped":跳过数, "failed":失败数}"""
        added = skipped = failed = 0
        for eq in equipment_list:
            if self.add_equipment(eq):
                added += 1
            elif self.get_by_name(eq.get("name", "")):
                skipped += 1
            else:
                failed += 1
        return {"total": len(equipment_list), "added": added, "skipped": skipped, "failed": failed}

    # ── 统计 ──

    def get_statistics(self) -> Dict[str, Any]:
        """📊 装备统计: 总数、科研/通用数量、各稀有度数量
        科研/通用通过 ID 格式自动判断，不依赖任何额外字段"""
        total = len(self._data)
        research = sum(1 for eq in self._data if self._is_research_equipment(eq.get("equipment_id", "")))
        by_rarity: Dict[int, int] = {}
        for eq in self._data:
            rid = eq.get("rarity_id", 0)
            by_rarity[rid] = by_rarity.get(rid, 0) + 1
        by_name = {}
        for rid, cnt in by_rarity.items():
            info = self.get_rarity_info(rid)
            by_name[info["name"] if info else f"ID:{rid}"] = cnt
        return {"total": total, "research": research, "general": total - research, "by_rarity": by_name}


_instance_cache = None

def get_equipment_manager() -> EquipmentManager:
    """获取全局唯一的 EquipmentManager 实例"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = EquipmentManager()
    return _instance_cache
