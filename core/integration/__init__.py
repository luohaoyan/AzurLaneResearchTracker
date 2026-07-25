#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🔄 v0.6.0 整合流水线 (integration)              ║
║                                                              ║
║  【一句话解释】集中导出 ADB → OCR → 预览确认 → 数据写入流程。 ║
║  【类比理解】它像港区调度航线，设备和识别各跑一段，最终汇合。║
║  【数据流说明】截图结果 → OCR 记录 → 预览缓存 → 用户确认写入。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from .collection_pipeline import (
    AutomationCollectionPipeline,
    CollectionPipelineResult,
    CollectionPreview,
    CollectionProfile,
    get_automation_collection_pipeline,
)


# ============================================================
# 🌐 第二部分：公开导出
# ============================================================

__all__ = [
    "AutomationCollectionPipeline",
    "CollectionPipelineResult",
    "CollectionPreview",
    "CollectionProfile",
    "get_automation_collection_pipeline",
]
