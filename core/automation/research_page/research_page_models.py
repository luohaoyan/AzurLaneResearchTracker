#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          📦 研究页 ADB 结果模型 (research_page_models.py)    ║
║                                                              ║
║  【一句话解释】定义科研页/设计图页分帧采集时输出的数据结构。  ║
║  【类比理解】它像每张截图旁边的小标签，记住坐标和顺序。      ║
║  【数据流说明】ADB 截图 → 元数据帧 → manifest/actions/summary。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from core.contracts import RecognitionScene, StructuredTaskResult


# ============================================================
# 🏗️ 第二部分：结果对象
# ============================================================

@dataclass(frozen=True)
class ResearchPageAdbResult(StructuredTaskResult):
    """
    研究页 ADB 任务结果。
    输入：
        success/status/message/detail/payload/warnings。
    输出：
        与 StructuredTaskResult 兼容的不可变结构。
    使用示例：
        result = api.check_connection()
    """


@dataclass(frozen=True)
class ResearchPageCaptureArtifact:
    """
    科研页单帧截图产物。
    输入：
        screenshot_path/session_id/frame_index/scroll_index/page_state 等字段。
    输出：
        供 OCR 层直接消费的单帧原始图和元数据。
    使用示例：
        artifact = api.capture_design_chart_sequence(...).frames[0]
    """

    screenshot_path: str
    session_id: str
    frame_index: int
    scroll_index: int
    scroll_offset_px: int
    page_name: str = "research_design_chart"
    page_state: str = "research_design_chart"
    filter_state: str = ""
    rarity_state: str = ""
    sort_state: str = ""
    scene: str = RecognitionScene.RESEARCH.value
    action_name: str = "capture_viewport"
    action_result: str = "ready"
    action_message: str = "科研页截图完成。"
    sha1: str = ""
    resolution: Tuple[int, int] = (1280, 720)
    scroll_direction: str = "down"
    scroll_pixels: int = 0
    overlap_ratio: float = 0.35
    device_serial: str = ""
    adb_path: Optional[str] = None
    adb_source: str = "missing"
    timestamp: str = ""
    bottom_reached: bool = False
    is_duplicate_frame: bool = False
    duplicate_of_scroll_index: Optional[int] = None
    scrollbar_detected: bool = False
    scrollbar_state: str = "unknown"
    scrollbar_thumb_top: Optional[int] = None
    scrollbar_thumb_bottom: Optional[int] = None
    needs_retry: bool = False
    retry_count: int = 0
    success: bool = True
    status: str = "ready"
    message: str = "科研页截图完成。"
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为 manifest、actions.log 和 summary 都能直接使用的字典。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "scene": self.scene,
            "page_name": self.page_name,
            "page_state": self.page_state,
            "filter_state": self.filter_state,
            "rarity_state": self.rarity_state,
            "sort_state": self.sort_state,
            "screenshot_path": self.screenshot_path,
            "device_serial": self.device_serial,
            "resolution": list(self.resolution),
            "session_id": self.session_id,
            "frame_index": self.frame_index,
            "scroll_index": self.scroll_index,
            "scroll_offset_px": self.scroll_offset_px,
            "scroll_direction": self.scroll_direction,
            "scroll_pixels": self.scroll_pixels,
            "overlap_ratio": self.overlap_ratio,
            "sha1": self.sha1,
            "timestamp": self.timestamp,
            "adb_path": self.adb_path,
            "adb_source": self.adb_source,
            "action_name": self.action_name,
            "action_result": self.action_result,
            "action_message": self.action_message,
            "bottom_reached": self.bottom_reached,
            "is_duplicate_frame": self.is_duplicate_frame,
            "duplicate_of_scroll_index": self.duplicate_of_scroll_index,
            "scrollbar_detected": self.scrollbar_detected,
            "scrollbar_state": self.scrollbar_state,
            "scrollbar_thumb_top": self.scrollbar_thumb_top,
            "scrollbar_thumb_bottom": self.scrollbar_thumb_bottom,
            "needs_retry": self.needs_retry,
            "retry_count": self.retry_count,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ResearchPageScrollSession:
    """
    科研页连续滚动采集会话。
    输入：
        session_id/frames/run_dir/manifest_path/actions_log_path/summary_path 等字段。
    输出：
        后续 OCR 拼接层可断点续扫的会话结果。
    使用示例：
        session = api.capture_design_chart_sequence(frame_count=6)
    """

    session_id: str
    page_name: str
    page_state: str
    frames: Tuple[ResearchPageCaptureArtifact, ...]
    run_dir: str
    frames_dir: str
    manifest_path: str
    actions_log_path: str
    device_info_path: str
    summary_path: str
    resume_cursor: int
    bottom_reached: bool
    filter_state: str = ""
    rarity_state: str = ""
    sort_state: str = ""
    scroll_step_px: int = 0
    overlap_ratio: float = 0.35
    warnings: Tuple[str, ...] = ()
    success: bool = True
    status: str = "ready"
    message: str = "科研页分帧采集完成。"

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典，方便测试或 GUI 查看。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "session_id": self.session_id,
            "page_name": self.page_name,
            "page_state": self.page_state,
            "frames": [frame.to_dict() for frame in self.frames],
            "run_dir": self.run_dir,
            "frames_dir": self.frames_dir,
            "manifest_path": self.manifest_path,
            "actions_log_path": self.actions_log_path,
            "device_info_path": self.device_info_path,
            "summary_path": self.summary_path,
            "resume_cursor": self.resume_cursor,
            "bottom_reached": self.bottom_reached,
            "filter_state": self.filter_state,
            "rarity_state": self.rarity_state,
            "sort_state": self.sort_state,
            "scroll_step_px": self.scroll_step_px,
            "overlap_ratio": self.overlap_ratio,
            "warnings": list(self.warnings),
        }
