#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          📦 装备页 ADB 结果模型 (equipment_page_models.py)   ║
║                                                              ║
║  【一句话解释】定义装备页采集过程交给 OCR/GUI 的结构化结果。  ║
║  【类比理解】它像每张截图旁边的标签纸，记录来源和滑动位置。   ║
║  【数据流说明】ADB 动作 → 截图文件 → 元数据/manifest。         ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from core.contracts import StructuredTaskResult


# ============================================================
# 🏗️ 第二部分：核心结果对象
# ============================================================

@dataclass(frozen=True)
class EquipmentPageAdbResult(StructuredTaskResult):
    """
    装备页 ADB 操作结果。
    输入：
        success/status/message/detail/payload/warnings。
    输出：
        与 StructuredTaskResult 兼容的不可变结构。
    使用示例：
        result = api.ensure_equipped_on()
    """


@dataclass(frozen=True)
class EquipmentPageCaptureArtifact:
    """
    装备页单帧截图产物。
    输入：
        screenshot_path/session_id/frame_index/sha1/resolution/scroll 信息。
    输出：
        可交给后续 OCR、拼接和人工审核的单帧元数据。
    使用示例：
        artifact = api.capture_viewport("session", 0)
    """

    screenshot_path: str
    session_id: str
    frame_index: int
    sha1: str
    resolution: Tuple[int, int]
    scroll_index: int
    scroll_direction: str
    scroll_pixels: int
    scene: str = "equipment_list"
    device_serial: str = ""
    rarity_filter: str = ""
    equipment_type: str = ""
    equipped_state: str = ""
    search_text: str = ""
    overlap_hint: float = 0.0
    timestamp: str = ""
    adb_path: Optional[str] = None
    adb_ready: bool = False
    real_command_enabled: bool = True
    success: bool = True
    status: str = "ready"
    message: str = "装备页截图完成。"
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为 manifest 和 API payload 都能直接使用的字典。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "scene": self.scene,
            "screenshot_path": self.screenshot_path,
            "device_serial": self.device_serial,
            "resolution": list(self.resolution),
            "rarity_filter": self.rarity_filter,
            "equipment_type": self.equipment_type,
            "equipped_state": self.equipped_state,
            "search_text": self.search_text,
            "session_id": self.session_id,
            "frame_index": self.frame_index,
            "scroll_index": self.scroll_index,
            "scroll_direction": self.scroll_direction,
            "scroll_pixels": self.scroll_pixels,
            "overlap_hint": self.overlap_hint,
            "sha1": self.sha1,
            "timestamp": self.timestamp,
            "adb_path": self.adb_path,
            "adb_ready": self.adb_ready,
            "real_command_enabled": self.real_command_enabled,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class EquipmentPageScrollFrame:
    """
    滚动采集序列中的单帧摘要。
    输入：
        screenshot_path/frame_index/sha1/scroll_index/overlap_hint。
    输出：
        比完整 artifact 更轻的序列清单记录。
    使用示例：
        frame = session.frames[0]
    """

    screenshot_path: str
    frame_index: int
    sha1: str
    scroll_index: int
    overlap_hint: float
    scroll_direction: str = "down"
    scroll_pixels: int = 0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为 scroll_session.json 的单帧字典。"""
        return {
            "screenshot_path": self.screenshot_path,
            "frame_index": self.frame_index,
            "sha1": self.sha1,
            "scroll_index": self.scroll_index,
            "overlap_hint": self.overlap_hint,
            "scroll_direction": self.scroll_direction,
            "scroll_pixels": self.scroll_pixels,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class EquipmentPageScrollSession:
    """
    装备页连续滚动采集会话。
    输入：
        session_id/frames/manifest_path/resume_cursor/end_of_list_suspected/warnings。
    输出：
        后续 OCR 拼接层可断点续扫的会话结果。
    使用示例：
        session = api.capture_scroll_sequence(frame_count=6)
    """

    session_id: str
    frames: Tuple[EquipmentPageScrollFrame, ...]
    manifest_path: str
    resume_cursor: int
    end_of_list_suspected: bool
    warnings: Tuple[str, ...] = ()
    json_manifest_path: str = ""
    scroll_session_path: str = ""
    success: bool = True
    status: str = "ready"
    message: str = "装备页滚动采集完成。"

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典，供 GUI 或测试查看。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "session_id": self.session_id,
            "frames": [frame.to_dict() for frame in self.frames],
            "manifest_path": self.manifest_path,
            "json_manifest_path": self.json_manifest_path,
            "scroll_session_path": self.scroll_session_path,
            "resume_cursor": self.resume_cursor,
            "end_of_list_suspected": self.end_of_list_suspected,
            "warnings": list(self.warnings),
        }
