#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          📍 装备页坐标常量 (equipment_page_constants.py)     ║
║                                                              ║
║  【一句话解释】保存 1280x720 基准下的装备页点击和滑动坐标。   ║
║  【类比理解】它像一张透明描图纸，实际分辨率由 ADB 层缩放。    ║
║  【数据流说明】语义动作名 → 基准坐标 → AdbController 缩放。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from typing import Dict, Tuple


# ============================================================
# 🧱 第二部分：基础坐标与枚举
# ============================================================

BASE_RESOLUTION: Tuple[int, int] = (1280, 720)
SCENE_EQUIPMENT_LIST = "equipment_list"
DEFAULT_POST_ACTION_DELAY_MS = 350
DEFAULT_SCROLL_DISTANCE_PX = 420
DEFAULT_SCROLL_DURATION_MS = 650
DEFAULT_SCROLL_OVERLAP_HINT = 0.35
DEFAULT_SEARCH_CLEAR_DELETE_COUNT = 24

RARITY_FILTERS: Tuple[str, ...] = (
    "all",
    "common",
    "rare",
    "elite",
    "super_rare",
    "ultra_rare",
)

# 坐标按 1280x720 横屏基准记录；按钮文字以游戏真实语义命名，后续 OCR 层只需校准这些点位。
EQUIPMENT_PAGE_POINTS: Dict[str, Tuple[int, int]] = {
    "warehouse_equipment_tab": (1049, 679),
    "equipped_on": (1108, 138),
    "filter_button": (1184, 93),
    "filter_confirm": (1148, 640),
    "filter_reset": (1018, 640),
    "search_button": (1040, 92),
    "search_input": (615, 92),
    "search_confirm": (1165, 92),
    "search_clear": (994, 92),
    "list_center": (640, 370),
}

RARITY_FILTER_POINTS: Dict[str, Tuple[int, int]] = {
    "all": (210, 186),
    "common": (330, 186),
    "rare": (450, 186),
    "elite": (570, 186),
    "super_rare": (690, 186),
    "ultra_rare": (810, 186),
}

# 类型按钮保留中文真实文本，同时给常见英文别名，方便 GUI/测试传入稳定 key。
EQUIPMENT_TYPE_POINTS: Dict[str, Tuple[int, int]] = {
    "全部": (210, 285),
    "驱逐炮": (330, 285),
    "轻巡炮": (450, 285),
    "重巡炮": (570, 285),
    "战列炮": (690, 285),
    "水面鱼雷": (810, 285),
    "防空炮": (930, 285),
    "战斗机": (330, 365),
    "轰炸机": (450, 365),
    "鱼雷机": (570, 365),
    "设备": (690, 365),
    "反潜": (810, 365),
    "其他": (930, 365),
}

EQUIPMENT_TYPE_ALIASES: Dict[str, str] = {
    "all": "全部",
    "destroyer_gun": "驱逐炮",
    "dd_gun": "驱逐炮",
    "light_cruiser_gun": "轻巡炮",
    "cl_gun": "轻巡炮",
    "heavy_cruiser_gun": "重巡炮",
    "ca_gun": "重巡炮",
    "battleship_gun": "战列炮",
    "bb_gun": "战列炮",
    "torpedo": "水面鱼雷",
    "surface_torpedo": "水面鱼雷",
    "anti_air": "防空炮",
    "aa_gun": "防空炮",
    "fighter": "战斗机",
    "bomber": "轰炸机",
    "torpedo_bomber": "鱼雷机",
    "auxiliary": "设备",
    "equipment": "设备",
    "anti_submarine": "反潜",
    "other": "其他",
}

SCROLL_ANCHORS: Dict[str, Tuple[int, int, int, int]] = {
    "down": (640, 590, 640, 170),
    "up": (640, 170, 640, 590),
    "left": (1010, 360, 270, 360),
    "right": (270, 360, 1010, 360),
}
