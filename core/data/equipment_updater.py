#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║          ➕ 装备批量更新工具 (EquipmentUpdater)                    ║
║                                                                  ║
║   【一句话解释】一行代码添加整期科研装备（1彩+5金），自动生成ID   ║
║                                                                  ║
║   【使用场景】                                                    ║
║   每次游戏更新科研期数时，调用 add_research_phase_equipment()     ║
║   传入: 期数、名称、5个金装备信息、1个彩装备信息                   ║
║   自动: 生成ID(S{期数}-001~006)、创建装备记录、创建期数记录       ║
║                                                                  ║
║   【依赖关系】                                                    ║
║   equipment_manager → 添加装备                                     ║
║   research_manager  → 创建期数记录                                ║
║   rarity_manager    → 查稀有度 ID                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
from typing import Any, Dict, List, Tuple
from .equipment_manager import get_equipment_manager, EquipmentManager
from .research_manager import get_research_manager
from .rarity_manager import get_rarity_manager
from ..utils.logger import get_logger

def add_research_phase_equipment(
    phase_number: int,
    phase_name: str,
    gold_equipment: List[Tuple[str, str]],
    rainbow_equipment: Tuple[str, str],
) -> Dict[str, Any]:
    """
    🎯 批量添加一期科研的全部装备（1彩虹 + 5金色）

    参数说明:
        phase_number: 科研期数编号 (1, 2, 3...)
        phase_name:   科研期数名称 ("科研1期(PR1)")
        gold_equipment: 5个金装备的列表，每个元素是 (名称, 类型)
                        [("试作型三联装152mm","轻巡炮"), ("试作型...","驱逐炮"), ...]
        rainbow_equipment: 1个彩虹装备，格式 (名称, 类型)
                          ("试作型三联装406mm主炮Mk6", "战列炮")

    ID 生成规则:
        彩虹 = S{期数}-001
        金1  = S{期数}-002
        金2  = S{期数}-003
        ...  = S{期数}-006

    返回:
        {"success": True/False,
         "equipment_added": 成功数,
         "equipment_ids": ["S7-001","S7-002",...],
         "failed_ids": [],
         "phase_added": True/False}

    使用示例:
        add_research_phase_equipment(
            7, "科研7期(PR7)",
            [("金装备1","战列炮"), ("金装备2","轻巡炮"), ("金装备3","驱逐炮"),
             ("金装备4","防空炮"), ("金装备5","重巡炮")],
            ("彩装备","战列炮")
        )
    """
    logger = get_logger()
    em = get_equipment_manager()
    rm = get_research_manager()
    rarity_mgr = get_rarity_manager()

    # 从稀有度表中查找"海上传奇"(彩虹)和"超稀有"(金色)的 ID
    rainbow_rarity = rarity_mgr.get_by_name("海上传奇")
    gold_rarity = rarity_mgr.get_by_name("超稀有")
    if not rainbow_rarity or not gold_rarity:
        logger.error("稀有度表中未找到海上传奇或超稀有")
        return {"success": False, "error": "稀有度配置缺失"}

    rainbow_rid = rainbow_rarity["rarity_id"]
    gold_rid = gold_rarity["rarity_id"]
    new_ids, failed = [], []

    # 步骤①: 添加彩虹装备（序号001）
    rid = EquipmentManager.make_research_id(phase_number, 1)
    if em.add_equipment({"equipment_id": rid, "name": rainbow_equipment[0],
                          "rarity_id": rainbow_rid, "type": rainbow_equipment[1]}):
        new_ids.append(rid)
    else:
        failed.append(rid)

    # 步骤②: 添加5个金色装备（序号002-006）
    for idx, (name, eq_type) in enumerate(gold_equipment, start=2):
        gid = EquipmentManager.make_research_id(phase_number, idx)
        if em.add_equipment({"equipment_id": gid, "name": name,
                              "rarity_id": gold_rid, "type": eq_type}):
            new_ids.append(gid)
        else:
            failed.append(gid)

    # 步骤③: 在 research_phases.csv 中创建期数记录
    phase_added = rm.add_phase({
        "phase_number": phase_number,
        "name": phase_name,
        "equipment_list": ",".join(new_ids),
    })

    logger.info(f"科研{phase_name}批量添加: 装备{len(new_ids)}(失败{failed}), 期数{phase_added}")
    return {"success": len(failed) == 0 and phase_added, "equipment_added": len(new_ids),
            "equipment_ids": new_ids, "failed_ids": failed, "phase_added": phase_added}
