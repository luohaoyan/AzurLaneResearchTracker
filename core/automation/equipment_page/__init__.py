#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║            🧰 装备页 ADB 自动化包 (equipment_page)           ║
║                                                              ║
║  【一句话解释】集中导出装备仓库页专用的 ADB 采集接口。        ║
║  【类比理解】通用 ADB 像手柄按钮，本包像“装备页操作手册”。    ║
║  【数据流说明】装备页动作 → 截图/manifest → 后续 OCR/拼接。   ║
╚══════════════════════════════════════════════════════════════╝
"""

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from .equipment_page_adb_api import EquipmentPageAdbApi, get_equipment_page_adb_api
from .equipment_page_models import (
    EquipmentPageAdbResult,
    EquipmentPageCaptureArtifact,
    EquipmentPageScrollFrame,
    EquipmentPageScrollSession,
)


# ============================================================
# 🌐 第二部分：公开导出
# ============================================================

__all__ = [
    "EquipmentPageAdbApi",
    "EquipmentPageAdbResult",
    "EquipmentPageCaptureArtifact",
    "EquipmentPageScrollFrame",
    "EquipmentPageScrollSession",
    "get_equipment_page_adb_api",
]
