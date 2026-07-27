#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🧭 ADB 截图帧顺序与筛选                        ║
║                                                              ║
║  【一句话解释】把 ADB manifest 中的截图按滚动顺序交给上层。   ║
║  【类比理解】它像整理相册，只排照片，不判断照片内容。         ║
║  【数据流说明】manifest.json → 排序/过滤 → OCR frame 列表。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ============================================================
# 🧱 第二部分：数据结构
# ============================================================

@dataclass(frozen=True)
class AdbFrameSelection:
    """
    一张被排序后的 ADB 截图帧。

    输入：
        frame: manifest 中的原始帧字段。
        order_index: 本次送入 OCR 的顺序。
        selected: 是否进入 OCR。
        skip_reason: 未进入 OCR 时的原因。
    输出：
        不修改原始 manifest 的只读选择结果。
    使用示例：
        selection = order_manifest_frames(payload)[0]
    """

    frame: Dict[str, Any]
    order_index: int
    selected: bool
    skip_reason: str = ""

    @property
    def screenshot_path(self) -> Optional[Path]:
        """返回存在时的绝对截图路径。"""
        raw_path = str(self.frame.get("screenshot_path", "") or "").strip()
        if not raw_path:
            return None
        return Path(raw_path).expanduser().resolve()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为便于写入上下文 JSON 的字典。"""
        payload = dict(self.frame)
        payload["order_index"] = self.order_index
        payload["selected_for_ocr"] = self.selected
        payload["ocr_skip_reason"] = self.skip_reason
        return payload


@dataclass(frozen=True)
class AdbFrameOrder:
    """
    一次 manifest 排序/筛选结果。

    输入：
        manifest_path: 原始 manifest 路径。
        selections: 按 OCR 消费顺序排列的帧选择结果。
        resume_cursor: summary 中建议的下一次续接游标。
    输出：
        可直接给 OCR 工作台或测试代码消费的顺序对象。
    使用示例：
        order = build_frame_order(Path("run_xxx/manifest.json"))
    """

    manifest_path: str
    selections: Tuple[AdbFrameSelection, ...]
    resume_cursor: int = 0
    bottom_reached: bool = False
    warnings: Tuple[str, ...] = ()

    @property
    def selected_frames(self) -> Tuple[AdbFrameSelection, ...]:
        """返回进入 OCR 的帧。"""
        return tuple(item for item in self.selections if item.selected)

    @property
    def image_paths(self) -> Tuple[Path, ...]:
        """按排序结果返回 OCR 要读取的截图路径。"""
        paths: List[Path] = []
        for item in self.selected_frames:
            path = item.screenshot_path
            if path is not None:
                paths.append(path)
        return tuple(paths)

    def to_dict(self) -> Dict[str, Any]:
        """转换为结构化 JSON 结果。"""
        return {
            "manifest_path": self.manifest_path,
            "selected_frame_count": len(self.selected_frames),
            "total_frame_count": len(self.selections),
            "resume_cursor": self.resume_cursor,
            "bottom_reached": self.bottom_reached,
            "warnings": list(self.warnings),
            "frames": [item.to_dict() for item in self.selections],
        }


# ============================================================
# 🧭 第三部分：顺序与筛选函数
# ============================================================

def load_adb_manifest(manifest_path: Path) -> Dict[str, Any]:
    """
    读取 ADB 采集层写出的 manifest.json。

    输入：
        manifest_path: ADB run_xxx/manifest.json。
    输出：
        dict: manifest 内容。
    异常：
        文件不存在或 JSON 损坏时抛出明确异常。
    使用示例：
        manifest = load_adb_manifest(Path("workdir/automation/adb_capture_runs/run_x/manifest.json"))
    """
    path = Path(manifest_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"ADB manifest 不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ADB manifest 无法读取：{path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"ADB manifest 顶层必须是 JSON 对象：{path}")
    return payload


def _int_field(frame: Mapping[str, Any], key: str, default: int) -> int:
    """安全读取排序字段，非法值使用默认值。"""
    try:
        return int(frame.get(key, default))
    except (TypeError, ValueError):
        return default


def _frame_sort_key(item: Tuple[int, Mapping[str, Any]]) -> Tuple[int, int, int, int]:
    """
    按 frame_index → scroll_index → scroll_offset_px → 原始位置排序。

    frame_index 是 ADB 采集顺序的第一证据；后面两个字段用于兼容
    外部工具重排 frame_index 或只写滚动索引的情况。
    """
    original_index, frame = item
    return (
        _int_field(frame, "frame_index", 2**31 - 1),
        _int_field(frame, "scroll_index", 2**31 - 1),
        _int_field(frame, "scroll_offset_px", 2**31 - 1),
        original_index,
    )


def _manifest_frames(manifest: Mapping[str, Any]) -> Tuple[Dict[str, Any], ...]:
    """
    从 ADB manifest 中提取帧列表。

    输入：
        manifest: 兼容科研页 frames、装备页 scroll_session.frames 和 capture_manifest.artifacts。
    输出：
        tuple[dict]：只包含可排序字段的浅拷贝。
    使用示例：
        frames = _manifest_frames({"artifacts": [...]})
    """
    raw_frames = manifest.get("frames", [])
    if not isinstance(raw_frames, Sequence) or isinstance(raw_frames, (str, bytes)) or not raw_frames:
        raw_frames = manifest.get("artifacts", [])
    if not isinstance(raw_frames, Sequence) or isinstance(raw_frames, (str, bytes)):
        raw_frames = []

    frames: List[Dict[str, Any]] = []
    for index, frame in enumerate(raw_frames):
        if not isinstance(frame, Mapping):
            continue
        item = dict(frame)
        item.setdefault("frame_index", index)
        item.setdefault("scroll_index", item.get("frame_index", index))
        frames.append(item)
    return tuple(frames)


def order_manifest_frames(
    manifest: Mapping[str, Any],
    *,
    include_duplicates: bool = False,
    include_failed_frames: bool = False,
    require_existing_files: bool = True,
) -> AdbFrameOrder:
    """
    对 manifest 帧排序并筛选 OCR 可消费帧。

    输入：
        manifest:
            ADB manifest 字典。
        include_duplicates:
            False 时跳过 is_duplicate_frame=true。
        include_failed_frames:
            False 时跳过 success=false 或 status=error 的帧。
        require_existing_files:
            True 时截图文件不存在会被跳过。
    输出：
        AdbFrameOrder：包含完整选择记录、OCR 顺序、续接游标和底部状态。
    使用示例：
        order = order_manifest_frames(manifest)
        for image_path in order.image_paths:
            process(image_path)
    """
    warnings: List[str] = []
    indexed_frames = [
        (index, dict(frame))
        for index, frame in enumerate(_manifest_frames(manifest))
    ]
    ordered_frames = sorted(indexed_frames, key=_frame_sort_key)
    selections: List[AdbFrameSelection] = []

    for order_index, (_original_index, frame) in enumerate(ordered_frames):
        selected = True
        skip_reason = ""
        if not include_duplicates and bool(frame.get("is_duplicate_frame", False)):
            selected = False
            skip_reason = "duplicate_frame"
        elif not include_failed_frames and (
            frame.get("success") is False
            or str(frame.get("status", "")).lower() in {"error", "failed", "unavailable"}
        ):
            selected = False
            skip_reason = "failed_frame"

        screenshot_path = Path(str(frame.get("screenshot_path", "") or "")).expanduser()
        if selected and require_existing_files and not screenshot_path.is_file():
            selected = False
            skip_reason = "screenshot_missing"

        if skip_reason:
            frame["ocr_skip_reason"] = skip_reason
        else:
            frame["ocr_skip_reason"] = ""
        frame["ocr_order_index"] = order_index
        selections.append(AdbFrameSelection(frame, order_index, selected, skip_reason))

    selected_frame_count = len([item for item in selections if item.selected])
    if selected_frame_count == 0 and selections:
        warnings.append("没有可供 OCR 消费的 ADB 截图帧。")

    summary = manifest.get("summary", {})
    summary = summary if isinstance(summary, Mapping) else {}
    resume_cursor = _int_field(
        manifest,
        "next_resume_cursor",
        _int_field(summary, "next_resume_cursor", 0),
    )
    bottom_reached = bool(manifest.get("bottom_reached", summary.get("bottom_reached", False)))
    return AdbFrameOrder(
        manifest_path=str(manifest.get("manifest_path", "") or ""),
        selections=tuple(selections),
        resume_cursor=resume_cursor,
        bottom_reached=bottom_reached,
        warnings=tuple(warnings),
    )


def build_frame_order(
    manifest_path: Path,
    *,
    include_duplicates: bool = False,
    include_failed_frames: bool = False,
    require_existing_files: bool = True,
) -> AdbFrameOrder:
    """
    从 manifest 路径直接构造帧顺序。

    输入：
        manifest_path: ADB manifest.json。
        其余参数同 order_manifest_frames。
    输出：
        AdbFrameOrder。
    使用示例：
        order = build_frame_order(Path("run_xxx/manifest.json"))
    """
    path = Path(manifest_path).expanduser().resolve()
    manifest = load_adb_manifest(path)
    enriched = dict(manifest)
    enriched["manifest_path"] = str(path)
    order = order_manifest_frames(
        enriched,
        include_duplicates=include_duplicates,
        include_failed_frames=include_failed_frames,
        require_existing_files=require_existing_files,
    )
    return AdbFrameOrder(
        manifest_path=str(path),
        selections=order.selections,
        resume_cursor=order.resume_cursor,
        bottom_reached=order.bottom_reached,
        warnings=order.warnings,
    )


__all__ = [
    "AdbFrameOrder",
    "AdbFrameSelection",
    "build_frame_order",
    "load_adb_manifest",
    "order_manifest_frames",
]
