#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              📜 核心共享契约 (contracts)                    ║
║                                                              ║
║  【一句话解释】集中导出 v0.6.0 并行模块共同依赖的数据结构。   ║
║  【类比理解】它像三路开发共同签署的接口清单。                 ║
║  【数据流说明】ADB/OCR/GUI → 共享类型 → 整合流水线。          ║
╚══════════════════════════════════════════════════════════════╝
"""

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from .task_contracts import (
    CancellationToken,
    EquipmentRecognitionRecord,
    RecognitionDetection,
    RecognitionDetectionType,
    RecognitionResult,
    RecognitionScene,
    ResourceRecognitionRecord,
    ScreenshotArtifact,
    StructuredTaskResult,
    TaskCancelledError,
    TaskExecutionContext,
    TaskProgressReporter,
)


# ============================================================
# 🌐 第二部分：公开导出
# ============================================================

__all__ = [
    "CancellationToken",
    "EquipmentRecognitionRecord",
    "RecognitionDetection",
    "RecognitionDetectionType",
    "RecognitionResult",
    "RecognitionScene",
    "ResourceRecognitionRecord",
    "ScreenshotArtifact",
    "StructuredTaskResult",
    "TaskCancelledError",
    "TaskExecutionContext",
    "TaskProgressReporter",
]
