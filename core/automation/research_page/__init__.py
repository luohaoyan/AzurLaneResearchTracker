#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║            🧭 研究页 ADB 自动化包 (research_page)            ║
║                                                              ║
║  【一句话解释】集中导出科研页/设计图页的分帧采集接口。       ║
║  【类比理解】它像一份页面采集说明书，只管截图、滚动和留痕。  ║
║  【数据流说明】ADB 动作 → 分帧截图 → manifest/actions/summary。║
╚══════════════════════════════════════════════════════════════╝
"""

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from .research_page_adb_api import ResearchPageAdbApi, get_research_page_adb_api
from .research_page_models import (
    ResearchPageAdbResult,
    ResearchPageCaptureArtifact,
    ResearchPageScrollSession,
)


# ============================================================
# 🌐 第二部分：公开导出
# ============================================================

__all__ = [
    "ResearchPageAdbApi",
    "ResearchPageAdbResult",
    "ResearchPageCaptureArtifact",
    "ResearchPageScrollSession",
    "get_research_page_adb_api",
]
