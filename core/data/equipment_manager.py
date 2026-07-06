#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║               🎮 装备数据管理器 (EquipmentManager)           ║
║                                                              ║
║   【一句话解释】                                              ║
║   这个文件就像"装备仓库的管理员"，负责记录、查找、修改、      ║
║   删除碧蓝航线游戏里所有科研装备的信息。                      ║
║                                                              ║
║   【类比理解】                                                ║
║   想象你有一个"装备收集册"（CSV文件），                      ║
║   这个类就是帮你翻册子、写新内容、改旧内容的"助手"。          ║
║                                                              ║
║   【数据存储位置】                                            ║
║   data/equipment_library.csv ── 就像一个Excel表格             ║
╚══════════════════════════════════════════════════════════════╝
"""

# ============================================================
# 📦 第一部分：导入需要的"工具包"
# ============================================================
# csv       → 用来读写CSV表格文件（就像Excel的简单版）
# os        → 用来检查文件是否存在等操作系统功能
# typing    → 用来标注"这是什么类型的数据"，让代码更清楚
# get_logger→ 我们之前写的"日志记录员"（记录谁动了装备）
# PathManager→ 我们之前写的"路径管理员"（知道文件该放哪里）

import csv
import os
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.path_manager import PathManager


# ============================================================
# 🏗️ 第二部分：装备管理器类（核心！）
# ============================================================
class EquipmentManager:
    """
    🎯 装备管理器 ── 管理所有科研装备的数据
    
    ┌─────────────────────────────────────┐
    │  比喻：你是图书馆管理员              │
    │  - 书架 = CSV文件                    │
    │  - 每本书 = 一条装备记录             │
    │  - 你的工作 = 增/删/改/查 装备       │
    └─────────────────────────────────────┘
    """

    # ── 单例模式的"身份证" ──
    # 整个程序只有一个装备管理器，就像一个国家只有一个总统
    # _instance 存着那唯一一个实例
    _instance = None

    # ── 稀有度等级表 ──
    # 碧蓝航线中装备有5个稀有度等级，从低到高：
    # 普通(白) → 稀有(蓝) → 精锐(紫) → 超稀有(金) → 海上传奇(彩/彩虹)
    RARITIES = ["普通", "稀有", "精锐", "超稀有", "海上传奇"]

    # ==========================================================
    # 🔧 __new__：单例模式的"守门员"
    # ==========================================================
    # Python创建对象时会先调用__new__，再调用__init__
    # 这里的逻辑是："如果还没有实例，就造一个；如果已经有了，直接用旧的"
    # 这样就保证：不管你在哪里调用 EquipmentManager()，拿到的都是同一个对象
    def __new__(cls, *args, **kwargs):
        """单例模式：确保整个程序只有一个装备管理器"""
        if not cls._instance:
            # 第一次创建 → 造一个新的
            cls._instance = super(EquipmentManager, cls).__new__(cls)
        # 之后每次 → 返回之前造好的那个
        return cls._instance

    # ==========================================================
    # 🚀 __init__：初始化 ── 装备管理器"上班"时要做的事
    # ==========================================================
    def __init__(self):
        """
        初始化装备管理器（只在第一次创建时执行）
        
        启动流程：
        ① 准备日志本（记录操作）
        ② 找到CSV文件的位置
        ③ 如果CSV文件不存在 → 创建一个空的
        ④ 把CSV里的数据读到内存里（这样查起来快）
        """
        # ── 防止重复初始化 ──
        # 因为单例模式会让每次调用都返回同一个对象，
        # 但__init__每次都会被调用，所以我们加个标记，
        # 如果已经初始化过了，就直接跳过
        if hasattr(self, '_initialized'):
            return  # "我已经准备好了，不重复干活"

        # ── 步骤①：拿到日志记录员 ──
        # logger会帮我们记录每一步操作，出问题可以看日志找原因
        self.logger = get_logger()

        # ── 步骤②：确定数据文件放在哪里 ──
        # data_dir = 项目根目录/data/
        # csv_path = 项目根目录/data/equipment_library.csv
        self.data_dir = PathManager.get_data_dir()
        self.csv_path = self.data_dir / "equipment_library.csv"

        # ── 步骤③：定义CSV表格的列名（就像Excel的表头）──
        # 每条装备记录都有这7个属性：
        self.fieldnames = [
            "equipment_id",      # ① 装备ID（独一无二的编号，如1,2,3...）
            "name",              # ② 名称（如"试作型三联装406mm主炮Mk6"）
            "rarity",            # ③ 稀有度（普通/稀有/精锐/超稀有/海上传奇）
            "type",              # ④ 类型（战列炮/轻巡炮/驱逐炮/防空炮...）
            "research_phase",    # ⑤ 所属科研期数（第1期/第2期...）
            "owned_quantity",    # ⑥ 拥有数量（你仓库里有多少个）
            "fragment_quantity"  # ⑦ 碎片数量（图纸碎片，够50个可以合成）
        ]

        # ── 步骤④：在内存中准备一个"临时列表"来存数据 ──
        # 为什么要读到内存？因为读内存比读硬盘快几千倍！
        # self._data 是一个列表，里面每个元素是一个字典（一行数据）
        # 例如：self._data = [
        #   {"equipment_id":1, "name":"试作型三联装406mm", "rarity":"海上传奇", ...},
        #   {"equipment_id":2, "name":"试作型三联装152mm", "rarity":"超稀有", ...},
        #   ...
        # ]
        self._data: List[Dict[str, Any]] = []

        # ── 步骤⑤⑥：确保CSV存在，然后把数据读到内存 ──
        self._ensure_csv_exists()  # 如果CSV文件不存在就创建一个空的
        self._load_data()          # 把CSV内容读到self._data里

        # ── 标记：初始化完成！ ──
        self._initialized = True  # 下次别人再想初始化，看到这个标记就跳过了

    # ==========================================================
    # 🔒 私有方法（_开头）= 内部使用，外部不要直接调用
    # ==========================================================

    def _ensure_csv_exists(self):
        """
        🏠 确保装备库CSV文件存在
        
        逻辑：如果文件不存在 → 创建一个带表头的空表格
        类比：如果仓库的登记本丢了 → 拿一本新的，写上栏目名
        """
        if not os.path.exists(self.csv_path):
            # 以utf-8-sig编码打开（加BOM头，Excel能正确识别中文）
            # newline='' 防止Windows下多出空行
            with open(self.csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                # 先写表头（第一行：equipment_id,name,rarity,...）
                writer.writeheader()
            self.logger.info(f"📝 装备库CSV文件已创建: {self.csv_path}")

    def _load_data(self):
        """
        📥 从CSV文件加载数据到内存
        
        类比：把登记本上的内容全部抄到脑子里（内存），
        这样以后查找时就不用每次翻本子了
        
        注意：CSV里存的全是文字（字符串），
        但"数量"应该是数字，所以要转换类型
        """
        try:
            self._data.clear()  # 先清空内存中的数据

            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                # reader 每次给你一行，自动把表头当作key
                # 例如：{"equipment_id":"1", "name":"试作型三联装406mm", ...}

                for row in reader:
                    # ⚠️ CSV里的数字其实是字符串"1"，需要转成真正的数字1
                    # 为什么要转？因为字符串"10" < "2"（按字母排序），
                    # 数字10 > 2（按数值排序），不转会出bug！

                    # owned_quantity: 拥有数量 → 转整数
                    if 'owned_quantity' in row:
                        row['owned_quantity'] = int(row['owned_quantity']) if row['owned_quantity'] else 0

                    # fragment_quantity: 碎片数量 → 转整数
                    if 'fragment_quantity' in row:
                        row['fragment_quantity'] = int(row['fragment_quantity']) if row['fragment_quantity'] else 0

                    # equipment_id: 装备编号 → 转整数
                    if 'equipment_id' in row:
                        row['equipment_id'] = int(row['equipment_id']) if row['equipment_id'] else 0

                    # research_phase: 期数 → 转整数
                    if 'research_phase' in row:
                        row['research_phase'] = int(row['research_phase']) if row['research_phase'] else 0

                    # 把处理好的这一行加到内存列表中
                    self._data.append(row)

            self.logger.debug(f"📥 装备库数据已加载，共 {len(self._data)} 条记录")

        except Exception as e:
            self.logger.error(f"❌ 加载装备库CSV失败: {e}")

    def _save_data(self):
        """
        📤 把内存中的数据保存回CSV文件
        
        类比：把脑子里记的内容写回到登记本上
        
        ⚠️ 每次增/删/改操作后都要调用这个方法，
        否则修改只存在内存里，程序关了数据就丢了！
        """
        try:
            with open(self.csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)
                writer.writeheader()      # 写表头
                writer.writerows(self._data)  # 写所有数据行
            self.logger.debug(f"📤 装备库数据已保存，共 {len(self._data)} 条记录")
        except Exception as e:
            self.logger.error(f"❌ 保存装备库CSV失败: {e}")
            raise  # 保存失败是严重问题，把错误往上抛

    # ==========================================================
    # 📖 查询操作（Read - CRUD中的R）
    # ==========================================================

    def get_all(self) -> List[Dict[str, Any]]:
        """
        📋 获取所有装备数据
        
        输入：无
        输出：一个列表，包含所有装备的字典
        示例输出：
        [
          {"equipment_id":1, "name":"试作型三联装406mm", ...},
          {"equipment_id":2, "name":"试作型三联装152mm", ...},
          ...
        ]
        
        注意：返回的是copy()（复制品），不是原始数据
             这样外部修改副本不会影响内部数据，保护数据安全
        """
        return self._data.copy()

    def get_by_id(self, equipment_id: int) -> Optional[Dict[str, Any]]:
        """
        🔍 根据装备ID查找装备
        
        输入：
          equipment_id ── 整数，装备的编号，如 1
        
        输出：
          找到了 → 返回装备字典（如{"equipment_id":1, "name":"试作型..."})
          没找到 → 返回 None（相当于"空"）
        
        示例：
          mgr.get_by_id(1)  → {"equipment_id":1, "name":"试作型三联装406mm主炮Mk6", ...}
          mgr.get_by_id(999) → None  （因为不存在编号999的装备）
        """
        for eq in self._data:
            if eq.get('equipment_id') == equipment_id:
                return eq.copy()  # 返回副本，保护原始数据
        return None  # 循环结束还没找到 = 不存在

    def get_by_rarity(self, rarity: str) -> List[Dict[str, Any]]:
        """
        🌈 按稀有度筛选装备
        
        输入：
          rarity ── 字符串，如 "海上传奇"、"超稀有"、"精锐"、"稀有"、"普通"
        
        输出：
          符合该稀有度的所有装备列表
        
        示例：
          mgr.get_by_rarity("海上传奇")  → 所有彩虹装备的列表
          mgr.get_by_rarity("传说")       → []（无效稀有度，返回空列表）
        """
        # 先检查稀有度是否合法
        if rarity not in self.RARITIES:
            self.logger.warning(f"⚠️ 无效的稀有度: {rarity}")
            return []

        # 列表推导式（Python的快捷写法）：
        # "对于data里每个装备eq，如果eq的稀有度==要查的稀有度，就把它放进结果"
        return [eq.copy() for eq in self._data if eq.get('rarity') == rarity]

    def get_by_type(self, eq_type: str) -> List[Dict[str, Any]]:
        """
        🎯 按装备类型筛选
        
        输入：
          eq_type ── 字符串，如 "战列炮"、"轻巡炮"、"驱逐炮"、"防空炮"
        
        输出：
          符合该类型的所有装备列表
        
        示例：
          mgr.get_by_type("战列炮")  → [试作型三联装406mm, 试作型双联装457mm, ...]
        """
        return [eq.copy() for eq in self._data if eq.get('type') == eq_type]

    def get_by_phase(self, phase_number: int) -> List[Dict[str, Any]]:
        """
        🔢 按所属科研期数筛选装备
        
        输入：
          phase_number ── 整数，如 1 表示"科研一期"
        
        输出：
          属于该期数的所有装备列表
        
        示例：
          mgr.get_by_phase(1)  → [试作型三联装406mm, 试作型三联装152mm]
        """
        return [eq.copy() for eq in self._data if eq.get('research_phase') == phase_number]

    def get_statistics(self) -> Dict[str, Any]:
        """
        📊 获取装备统计信息
        
        输入：无
        输出：一个包含统计数据的字典
        示例输出：
        {
          "total": 12,                          # 总装备数
          "by_rarity": {                        # 各稀有度装备数量
            "普通": 0,
            "稀有": 0,
            "精锐": 1,
            "超稀有": 6,
            "海上传奇": 5
          }
        }
        """
        total = len(self._data)  # 总共有多少件装备

        # 初始化计数器：每种稀有度初始都是0
        by_rarity = {r: 0 for r in self.RARITIES}
        # 等同于：{"普通":0, "稀有":0, "精锐":0, "超稀有":0, "海上传奇":0}

        # 遍历每件装备，统计稀有度分布
        for eq in self._data:
            rarity = eq.get('rarity', '')
            if rarity in by_rarity:
                by_rarity[rarity] += 1  # 该稀有度计数+1

        return {
            "total": total,
            "by_rarity": by_rarity,
        }

    # ==========================================================
    # ✏️ 增删改操作（Create / Update / Delete - CRUD）
    # ==========================================================

    def add_equipment(self, equipment: Dict[str, Any]) -> bool:
        """
        ➕ 添加新装备到装备库
        
        输入格式（一个字典）：
        {
          "name": "试作型三联装406mm主炮Mk6",  ← 必填：装备名称
          "rarity": "海上传奇",                ← 必填：稀有度
          "type": "战列炮",                     ← 必填：类型
          "research_phase": 1,                  ← 必填：所属期数
          "owned_quantity": 0,                  ← 可选：拥有数量（默认0）
          "fragment_quantity": 0                ← 可选：碎片数量（默认0）
        }
        
        输出：
          True  → 添加成功 ✅
          False → 添加失败 ❌（稀有度无效或ID重复）
        
        流程：
        ① 自动分配一个新ID（当前最大ID + 1）
        ② 检查ID是否已存在 → 存在则拒绝
        ③ 检查稀有度是否合法 → 不合法则拒绝
        ④ 补全默认值，构建完整记录
        ⑤ 添加到内存 + 保存到CSV
        ⑥ 记录日志
        """
        try:
            # ── 步骤①：自动生成ID ──
            # 如果没提供ID或者ID为0，就自动找一个最大的ID然后+1
            # 比如当前最大ID是12，新装备就是13号
            if 'equipment_id' not in equipment or equipment['equipment_id'] == 0:
                # 找到所有现有装备中最大的ID
                max_id = max((eq.get('equipment_id', 0) for eq in self._data), default=0)
                equipment['equipment_id'] = max_id + 1

            # ── 步骤②：检查ID是否重复 ──
            if self.get_by_id(equipment['equipment_id']) is not None:
                self.logger.warning(f"⚠️ 装备ID {equipment['equipment_id']} 已存在，添加失败")
                return False

            # ── 步骤③：检查稀有度是否合法 ──
            if equipment.get('rarity') not in self.RARITIES:
                self.logger.warning(f"⚠️ 无效的稀有度: {equipment.get('rarity')}")
                return False

            # ── 步骤④：构建完整的装备记录 ──
            # 用.get(字段名, 默认值)确保每个字段都有值
            # int() 确保数字字段真的是整数
            record = {
                'equipment_id': int(equipment.get('equipment_id', 0)),
                'name': equipment.get('name', ''),
                'rarity': equipment.get('rarity', '普通'),
                'type': equipment.get('type', ''),
                'research_phase': int(equipment.get('research_phase', 0)),
                'owned_quantity': int(equipment.get('owned_quantity', 0)),
                'fragment_quantity': int(equipment.get('fragment_quantity', 0)),
            }

            # ── 步骤⑤：加入内存并保存 ──
            self._data.append(record)  # 加到内存列表末尾
            self._save_data()           # 保存到CSV文件

            # ── 步骤⑥：记录日志 ──
            self.logger.info(f"✅ 装备已添加: {record['name']} (ID:{record['equipment_id']})")
            return True

        except Exception as e:
            self.logger.error(f"❌ 添加装备失败: {e}")
            return False

    def update_equipment(self, equipment_id: int, updates: Dict[str, Any]) -> bool:
        """
        ✏️ 更新装备信息（修改已有的装备）
        
        输入：
          equipment_id ── 要修改的装备编号
          updates       ── 一个字典，只包含要修改的字段
                           不需要的字段可以省略
        
        输出：
          True  → 更新成功 ✅
          False → 更新失败 ❌
        
        示例：
          # 把1号装备的拥有数量改为5，碎片数量改为20
          mgr.update_equipment(1, {"owned_quantity": 5, "fragment_quantity": 20})
          
          # 修改装备的名称
          mgr.update_equipment(1, {"name": "新名字"})
        """
        try:
            # 遍历所有装备，找到ID匹配的那个
            for i, eq in enumerate(self._data):
                if eq.get('equipment_id') == equipment_id:
                    # 找到了！
                    
                    # 如果要改稀有度，先检查新稀有度是否合法
                    if 'rarity' in updates and updates['rarity'] not in self.RARITIES:
                        self.logger.warning(f"⚠️ 无效的稀有度: {updates.get('rarity')}")
                        return False

                    # 逐个更新字段
                    for key, value in updates.items():
                        if key in self.fieldnames:  # 只更新合法的字段名
                            # 数字字段需要转换类型
                            if key in ('equipment_id', 'research_phase', 'owned_quantity', 'fragment_quantity'):
                                self._data[i][key] = int(value) if value is not None else 0
                            else:
                                # 文字字段直接赋值
                                self._data[i][key] = value

                    self._save_data()  # 改动完了，记得保存！
                    self.logger.info(f"✅ 装备已更新: ID={equipment_id}, 更新字段={list(updates.keys())}")
                    return True

            # 循环结束都没找到 → ID不存在
            self.logger.warning(f"⚠️ 未找到装备ID {equipment_id}，更新失败")
            return False

        except Exception as e:
            self.logger.error(f"❌ 更新装备失败: {e}")
            return False

    def delete_equipment(self, equipment_id: int) -> bool:
        """
        🗑️ 删除装备
        
        输入：
          equipment_id ── 要删除的装备编号
        
        输出：
          True  → 删除成功 ✅
          False → 删除失败 ❌（ID不存在）
        
        示例：
          mgr.delete_equipment(13)  # 删除编号13的装备
        """
        try:
            for i, eq in enumerate(self._data):
                if eq.get('equipment_id') == equipment_id:
                    name = eq.get('name', '')
                    del self._data[i]  # 从列表中移除这条记录
                    self._save_data()   # 保存更改
                    self.logger.info(f"🗑️ 装备已删除: {name} (ID:{equipment_id})")
                    return True

            self.logger.warning(f"⚠️ 未找到装备ID {equipment_id}，删除失败")
            return False

        except Exception as e:
            self.logger.error(f"❌ 删除装备失败: {e}")
            return False


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

# 全局变量：存着装备管理器的唯一实例
_equipment_manager_instance = None


def get_equipment_manager() -> EquipmentManager:
    """
    🌍 获取全局唯一的装备管理器实例
    
    这是外部代码调用的"入口"：
    from core.data.equipment_manager import get_equipment_manager
    mgr = get_equipment_manager()  # 拿到全局唯一的装备管理器
    mgr.get_all()                  # 然后就可以用了
    
    为什么需要这个函数？
    因为装备管理器是单例的，这个函数确保所有人拿到的都是同一个对象
    """
    global _equipment_manager_instance
    if _equipment_manager_instance is None:
        _equipment_manager_instance = EquipmentManager()
    return _equipment_manager_instance
