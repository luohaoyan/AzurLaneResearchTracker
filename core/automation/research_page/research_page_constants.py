#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          📐 研究页采集常量 (research_page_constants.py)      ║
║                                                              ║
║  【一句话解释】保存科研页分帧截图的 1280x720 基准设置。      ║
║  【类比理解】它像设计图页的尺子，先定标尺再谈滑动。          ║
║  【数据流说明】页面动作 → 滚动步长 → 截图序列元数据。        ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from typing import Dict, Tuple


# ============================================================
# 🧱 第二部分：基础常量
# ============================================================

BASE_RESOLUTION: Tuple[int, int] = (1280, 720)
DEFAULT_PAGE_NAME = "research_design_chart"
DEFAULT_PAGE_STATE = "research_design_chart"
DEFAULT_FILTER_STATE = ""
DEFAULT_RARITY_STATE = ""
DEFAULT_SORT_STATE = "default"
DEFAULT_CAPTURE_RETRY_LIMIT = 1
DEFAULT_SCROLL_RETRY_LIMIT = 1
DEFAULT_SCROLL_DURATION_MS = 780
DEFAULT_SCROLL_OVERLAP_RATIO = 0.35
DEFAULT_SCROLL_STEP_PX = 0
DEFAULT_POST_ACTION_DELAY_MS = 350
DEFAULT_ACTION_NOTIFICATION_TITLE = "研究页采集"

SCROLL_ANCHORS: Dict[str, Tuple[int, int, int, int]] = {
    "down": (640, 590, 640, 170),
    "up": (640, 170, 640, 590),
    "left": (1010, 360, 270, 360),
    "right": (270, 360, 1010, 360),
}
