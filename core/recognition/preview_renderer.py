#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              识别预览图中文渲染工具                         ║
║  【一句话解释】用 Pillow 给 OpenCV 图片绘制中文审核文字。      ║
║  【类比理解】OpenCV 负责画框，Pillow 负责写中文标签。          ║
║  【数据流说明】BGR 图像 + 文字操作 → 带中文标签的 BGR 图像。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - OpenCV 是可选识别依赖。
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - NumPy 是 OpenCV 图像的常规载体。
    _np = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow 缺失时安全退回 ASCII。
    Image = None
    ImageDraw = None
    ImageFont = None


# ============================================================
# 🧱 第二部分：类型与常量
# ============================================================

BgrColor = Tuple[int, int, int]
Point = Tuple[int, int]
TextOperation = Tuple[str, Point, BgrColor, float]


def _windows_font_dir() -> Path:
    """返回 Windows 字体目录；环境变量缺失时使用系统默认位置。"""
    return Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


DEFAULT_FONT_PATHS: Tuple[Path, ...] = (
    _windows_font_dir() / "msyh.ttc",
    _windows_font_dir() / "simhei.ttf",
    _windows_font_dir() / "simsun.ttc",
    _windows_font_dir() / "msyhbd.ttc",
)


# ============================================================
# 🎨 第三部分：中文绘制函数
# ============================================================

def load_chinese_font(font_size: int) -> Any:
    """
    加载本机中文字体。

    输入：
        font_size：字号。
    输出：
        Pillow 字体对象；失败时返回 Pillow 默认字体或 None。
    使用示例：
        font = load_chinese_font(18)
    """
    if ImageFont is None:
        return None
    for font_path in DEFAULT_FONT_PATHS:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), int(font_size))
    return ImageFont.load_default()


def draw_unicode_labels(
    image_bgr: Any,
    operations: Sequence[TextOperation],
    *,
    fallback_label: str = "unicode preview unavailable",
) -> Any:
    """
    在 OpenCV BGR 图像上绘制可读中文标签。

    输入：
        image_bgr：OpenCV BGR 图像。
        operations：[(text, (x, y), (b, g, r), font_size)]。
    输出：
        带文字的 BGR 图像；依赖缺失时仍返回一张安全预览图。
    使用示例：
        out = draw_unicode_labels(img, [("高性能舵机#T0", (10, 20), (0, 255, 0), 18)])
    """
    if not operations:
        return image_bgr
    if Image is not None and ImageDraw is not None and _cv2 is not None and _np is not None:
        try:
            rgb = _cv2.cvtColor(image_bgr, _cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb)
            draw = ImageDraw.Draw(pil_image)
            font_cache: Dict[int, Any] = {}
            for text, position, color, font_size in operations:
                size = max(8, int(round(font_size)))
                if size not in font_cache:
                    font_cache[size] = load_chinese_font(size)
                bgr = tuple(int(item) for item in color)
                rgb_color = (bgr[2], bgr[1], bgr[0])
                draw.text(position, str(text), fill=rgb_color, font=font_cache[size])
            return _cv2.cvtColor(_np.asarray(pil_image), _cv2.COLOR_RGB2BGR)
        except Exception:
            pass
    return _draw_ascii_fallback(image_bgr, operations, fallback_label)


def _draw_ascii_fallback(
    image_bgr: Any,
    operations: Sequence[TextOperation],
    fallback_label: str,
) -> Any:
    """
    Pillow 不可用时绘制不含问号乱码的英文占位。

    输入：
        image_bgr/operations/fallback_label。
    输出：
        回退预览图。
    使用示例：
        out = _draw_ascii_fallback(img, ops, "unicode preview unavailable")
    """
    if _cv2 is None:
        return image_bgr
    fallback = image_bgr.copy()
    for text, position, color, font_size in operations:
        ascii_text = _ascii_preview_text(str(text), fallback_label)
        _cv2.putText(
            fallback,
            ascii_text,
            position,
            _cv2.FONT_HERSHEY_SIMPLEX,
            max(0.35, float(font_size) / 34.0),
            color,
            1,
            _cv2.LINE_AA,
        )
    return fallback


def _ascii_preview_text(text: str, fallback_label: str) -> str:
    """
    把中文文本变成安全英文占位，避免继续出现一串问号。

    输入：
        text/fallback_label。
    输出：
        ASCII 预览文本。
    使用示例：
        label = _ascii_preview_text("高性能舵机#T0", "unicode preview unavailable")
    """
    ascii_text = re.sub(r"[^\x20-\x7E]+", "", text).strip()
    return ascii_text or fallback_label
