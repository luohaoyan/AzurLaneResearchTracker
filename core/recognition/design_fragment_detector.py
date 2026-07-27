#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        设计图碎片卡片检测器 (design_fragment_detector.py)    ║
║  【一句话解释】在仓库“设计图”页截图里定位每张碎片卡片。        ║
║  【类比理解】它像一把会顺着滚动偏移移动的卡片尺。              ║
║  【数据流说明】截图 → 行偏移扫描 → 卡片框/图标ROI/数量ROI。    ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - 允许无 OpenCV 环境导入模块
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - 允许极简环境导入模块
    _np = None


RoiRegion = Tuple[int, int, int, int]
RatioRegion = Tuple[float, float, float, float]


@dataclass(frozen=True)
class DesignFragmentCardCandidate:
    """设计图页中单个卡片候选。"""

    index: int
    row_index: int
    column_index: int
    bbox: RoiRegion
    raw_bbox: RoiRegion
    icon_roi: RoiRegion
    quantity_roi: RoiRegion
    visibility: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON/CSV 友好的基础类型。"""
        return {
            "index": int(self.index),
            "row_index": int(self.row_index),
            "column_index": int(self.column_index),
            "bbox": [int(item) for item in self.bbox],
            "raw_bbox": [int(item) for item in self.raw_bbox],
            "icon_roi": [int(item) for item in self.icon_roi],
            "quantity_roi": [int(item) for item in self.quantity_roi],
            "visibility": self.visibility,
            "confidence": float(self.confidence),
        }


@dataclass(frozen=True)
class DesignFragmentDetectionResult:
    """一张设计图页截图的卡片检测结果。"""

    success: bool
    status: str
    message: str
    image_size: Tuple[int, int]
    row_offset: int = 0
    row_pitch: int = 0
    card_size: Tuple[int, int] = (0, 0)
    candidates: Tuple[DesignFragmentCardCandidate, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "image_size": [int(item) for item in self.image_size],
            "row_offset": int(self.row_offset),
            "row_pitch": int(self.row_pitch),
            "card_size": [int(item) for item in self.card_size],
            "candidates": [item.to_dict() for item in self.candidates],
            "warnings": list(self.warnings),
        }


# ============================================================
# 🏗️ 第二部分：设计图卡片检测器
# ============================================================

class DesignFragmentDetector:
    """针对 1280x720 UI 尺寸的仓库设计图卡片检测器。"""

    BASE_WIDTH = 1280
    BASE_HEIGHT = 720
    BASE_CARD_X = (133, 690)
    BASE_CARD_WIDTH = 541
    BASE_CARD_HEIGHT = 135
    BASE_ROW_PITCH = 153
    BASE_BOTTOM_OVERLAY_Y = 637
    ICON_RATIO: RatioRegion = (0.028, 0.096, 0.200, 0.80)
    QUANTITY_RATIO: RatioRegion = (0.755, 0.185, 0.225, 0.38)

    def __init__(
        self,
        cv2_module: Optional[Any] = None,
        np_module: Optional[Any] = None,
        edge_threshold: float = 24.0,
    ) -> None:
        """初始化检测器；不加载 OCR 或图库模型。"""
        self._cv2 = _cv2 if cv2_module is None else cv2_module
        self._np = _np if np_module is None else np_module
        self.edge_threshold = float(edge_threshold)

    def check_status(self) -> Dict[str, Any]:
        """检查 OpenCV/NumPy 是否可用。"""
        return {
            "available": self._cv2 is not None and self._np is not None,
            "dependencies": {
                "opencv_cv2": self._cv2 is not None,
                "numpy": self._np is not None,
            },
            "edge_threshold": self.edge_threshold,
        }

    def load_image(self, image_path: str | Path) -> Any:
        """读取截图，路径不存在或损坏时给出友好异常。"""
        cv2_module = self._require_cv2()
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"设计图截图不存在: {path}")
        image = cv2_module.imread(str(path), getattr(cv2_module, "IMREAD_COLOR", 1))
        if image is None or getattr(image, "size", 0) == 0:
            raise ValueError(f"设计图截图无法读取或已损坏: {path}")
        return image

    def detect(self, screenshot: str | Path | Any, image_mode: str = "viewport_full") -> DesignFragmentDetectionResult:
        """检测一张设计图页截图中的卡片候选。"""
        if self._cv2 is None or self._np is None:
            return DesignFragmentDetectionResult(False, "unavailable", "OpenCV(cv2)/NumPy 不可用。", (0, 0))
        try:
            image = self.load_image(screenshot) if isinstance(screenshot, (str, Path)) else screenshot
            if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
                raise ValueError("设计图截图为空。")
        except Exception as exc:
            return DesignFragmentDetectionResult(False, "error", str(exc), (0, 0), warnings=(str(exc),))

        height, width = int(image.shape[0]), int(image.shape[1])
        if self.detect_empty_state(image):
            return DesignFragmentDetectionResult(
                False,
                "empty",
                "当前设计图稀有度页面为空，未获得任何设计图。",
                (width, height),
                warnings=("检测到“暂无设计图”空状态提示，已跳过卡片识别。",),
            )
        geometry = self._scaled_geometry(width)
        row_offset, offset_score = self._detect_row_offset(image, geometry)
        rows = self._generate_rows(height, row_offset, geometry["card_height"], geometry["row_pitch"])
        candidates = self._build_candidates(width, height, rows, geometry, image_mode, offset_score)
        if not candidates:
            return DesignFragmentDetectionResult(
                False,
                "empty",
                "未检测到设计图卡片候选。",
                (width, height),
                row_offset=row_offset,
                row_pitch=geometry["row_pitch"],
                card_size=(geometry["card_width"], geometry["card_height"]),
            )
        return DesignFragmentDetectionResult(
            True,
            "success",
            "设计图卡片检测完成。",
            (width, height),
            row_offset=row_offset,
            row_pitch=geometry["row_pitch"],
            card_size=(geometry["card_width"], geometry["card_height"]),
            candidates=tuple(candidates),
        )

    def detect_empty_state(self, screenshot: str | Path | Any) -> bool:
        """
        判断设计图页是否显示“暂无设计图”空状态。

        空页面的背景网格线很容易被普通边缘扫描误判成卡片，因此先检查：
        右侧空状态红色警告图标，以及中部提示文字的高亮密度。
        """
        if self._cv2 is None or self._np is None:
            return False
        try:
            image = self.load_image(screenshot) if isinstance(screenshot, (str, Path)) else screenshot
            if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
                return False
            height, width = int(image.shape[0]), int(image.shape[1])
            scale_x = width / float(self.BASE_WIDTH)
            scale_y = height / float(self.BASE_HEIGHT)
            x0, x1 = int(round(1040 * scale_x)), int(round(1230 * scale_x))
            y0, y1 = int(round(285 * scale_y)), int(round(445 * scale_y))
            x0, x1 = max(0, x0), min(width, x1)
            y0, y1 = max(0, y0), min(height, y1)
            if x1 <= x0 or y1 <= y0:
                return False

            hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
            red_roi = hsv[y0:y1, x0:x1]
            red_mask = (
                ((red_roi[:, :, 0] <= 15) | (red_roi[:, :, 0] >= 170))
                & (red_roi[:, :, 1] >= 80)
                & (red_roi[:, :, 2] >= 100)
            ).astype("uint8")
            component_count, _labels, stats, _centroids = self._cv2.connectedComponentsWithStats(red_mask, 8)
            largest_red_component = 0
            if component_count > 1:
                largest_red_component = int(max(stats[1:, self._cv2.CC_STAT_AREA]))

            text_x0, text_x1 = int(round(120 * scale_x)), int(round(520 * scale_x))
            text_y0, text_y1 = int(round(315 * scale_y)), int(round(390 * scale_y))
            text_roi = image[
                max(0, text_y0):min(height, text_y1),
                max(0, text_x0):min(width, text_x1),
            ]
            white_density = 0.0
            if getattr(text_roi, "size", 0):
                white_mask = (
                    (text_roi[:, :, 0] >= 180)
                    & (text_roi[:, :, 1] >= 180)
                    & (text_roi[:, :, 2] >= 180)
                )
                white_density = float(white_mask.mean())

            # 右侧红色菱形面积和左侧提示文字需同时存在，才判定为空状态。
            return largest_red_component >= 400 and white_density >= 0.10
        except (OSError, ValueError, TypeError):
            return False

    def draw_annotations(
        self,
        image: Any,
        result: DesignFragmentDetectionResult,
        labels: Optional[Sequence[str]] = None,
    ) -> Any:
        """把卡片框、图标 ROI 和数量 ROI 画到图片上，供人工验收。"""
        cv2_module = self._require_cv2()
        annotated = image.copy()
        labels = tuple(labels or ())
        for index, candidate in enumerate(result.candidates):
            x, y, width, height = candidate.bbox
            color = (50, 210, 50) if candidate.visibility == "full" else (0, 180, 255)
            cv2_module.rectangle(annotated, (x, y), (x + width, y + height), color, 2)
            ix, iy, iw, ih = candidate.icon_roi
            qx, qy, qw, qh = candidate.quantity_roi
            cv2_module.rectangle(annotated, (ix, iy), (ix + iw, iy + ih), (255, 180, 0), 1)
            cv2_module.rectangle(annotated, (qx, qy), (qx + qw, qy + qh), (255, 255, 0), 2)
            text = labels[index] if index < len(labels) else f"card{candidate.index:02d}:{candidate.visibility}"
            cv2_module.putText(
                annotated,
                text[:48],
                (x + 4, max(18, y + 18)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2_module.LINE_AA,
            )
        cv2_module.putText(
            annotated,
            f"design cards={len(result.candidates)} offset={result.row_offset}",
            (20, 90),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2,
            cv2_module.LINE_AA,
        )
        return annotated

    def write_image(self, output_path: str | Path, image: Any) -> None:
        """写出 PNG 图片，并兼容 Windows 中文路径。"""
        cv2_module = self._require_cv2()
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, encoded = cv2_module.imencode(".png", image)
        if not ok:
            raise ValueError(f"无法编码输出图片: {path}")
        encoded.tofile(str(path))

    def _scaled_geometry(self, image_width: int) -> Dict[str, Any]:
        """按宽度缩放卡片几何；长截图高度不参与 UI 尺寸缩放。"""
        scale = image_width / float(self.BASE_WIDTH)
        return {
            "scale": scale,
            "x_positions": tuple(int(round(item * scale)) for item in self.BASE_CARD_X),
            "card_width": max(1, int(round(self.BASE_CARD_WIDTH * scale))),
            "card_height": max(1, int(round(self.BASE_CARD_HEIGHT * scale))),
            "row_pitch": max(1, int(round(self.BASE_ROW_PITCH * scale))),
            "bottom_overlay_y": int(round(self.BASE_BOTTOM_OVERLAY_Y * scale)),
        }

    def _detect_row_offset(self, image: Any, geometry: Dict[str, Any]) -> Tuple[int, float]:
        """用卡片边框能量扫描当前滚动偏移。"""
        cv2_module = self._require_cv2()
        np_module = self._require_np()
        gray = cv2_module.cvtColor(image, cv2_module.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        edges = cv2_module.Canny(gray, 60, 150)
        card_height = int(geometry["card_height"])
        row_pitch = int(geometry["row_pitch"])
        search_min = -card_height + 6
        search_max = row_pitch - 1
        best_offset = 0
        best_score = -1.0
        for offset in range(search_min, search_max + 1):
            row_scores: List[float] = []
            y = offset
            while y < int(image.shape[0]):
                if y + card_height > 0:
                    row_scores.append(self._rectangle_edge_score(edges, y, geometry))
                y += row_pitch
            if not row_scores:
                continue
            score = float(np_module.mean(row_scores))
            if score > best_score:
                best_score = score
                best_offset = offset
        return best_offset, max(0.0, best_score)

    def _rectangle_edge_score(self, edges: Any, y: int, geometry: Dict[str, Any]) -> float:
        """计算某个行偏移下两列卡片边框的平均边缘强度。"""
        values: List[float] = []
        image_height, image_width = int(edges.shape[0]), int(edges.shape[1])
        card_width = int(geometry["card_width"])
        card_height = int(geometry["card_height"])
        for x in geometry["x_positions"]:
            for yy in (y, y + card_height):
                if 0 <= yy < image_height:
                    x0, x1 = max(0, x), min(image_width, x + card_width)
                    if x1 > x0:
                        values.append(float(edges[yy, x0:x1].mean()))
            for xx in (x, x + card_width):
                if 0 <= xx < image_width:
                    y0, y1 = max(0, y), min(image_height, y + card_height)
                    if y1 > y0:
                        values.append(float(edges[y0:y1, xx].mean()))
        return sum(values) / float(max(1, len(values)))

    @staticmethod
    def _generate_rows(image_height: int, row_offset: int, card_height: int, row_pitch: int) -> Tuple[int, ...]:
        """根据偏移和行距生成所有可见行的原始 y 坐标。"""
        rows: List[int] = []
        y = int(row_offset)
        while y + card_height <= 0:
            y += row_pitch
        while y < image_height:
            if y + card_height > 0:
                rows.append(y)
            y += row_pitch
        return tuple(rows)

    def _build_candidates(
        self,
        image_width: int,
        image_height: int,
        rows: Sequence[int],
        geometry: Dict[str, Any],
        image_mode: str,
        offset_score: float,
    ) -> List[DesignFragmentCardCandidate]:
        """把行坐标和两列 x 坐标组合成卡片候选。"""
        candidates: List[DesignFragmentCardCandidate] = []
        card_width = int(geometry["card_width"])
        card_height = int(geometry["card_height"])
        for row_index, raw_y in enumerate(rows, start=1):
            for column_index, raw_x in enumerate(geometry["x_positions"], start=1):
                raw_bbox = (int(raw_x), int(raw_y), card_width, card_height)
                bbox = self._clip_roi(raw_bbox, image_width, image_height)
                if bbox[2] < int(card_width * 0.35) or bbox[3] < int(card_height * 0.25):
                    continue
                visibility = self._visibility(raw_bbox, bbox, image_width, image_height, geometry, image_mode)
                icon_roi = self._clip_roi(self._ratio_roi(raw_bbox, self.ICON_RATIO), image_width, image_height)
                quantity_roi = self._clip_roi(self._ratio_roi(raw_bbox, self.QUANTITY_RATIO), image_width, image_height)
                candidates.append(
                    DesignFragmentCardCandidate(
                        index=len(candidates) + 1,
                        row_index=row_index,
                        column_index=column_index,
                        bbox=bbox,
                        raw_bbox=raw_bbox,
                        icon_roi=icon_roi,
                        quantity_roi=quantity_roi,
                        visibility=visibility,
                        confidence=max(0.0, min(1.0, offset_score / 120.0)),
                    )
                )
        return candidates

    def _visibility(
        self,
        raw_bbox: RoiRegion,
        clipped_bbox: RoiRegion,
        image_width: int,
        image_height: int,
        geometry: Dict[str, Any],
        image_mode: str,
    ) -> str:
        """根据边界和底部 UI 遮挡判断卡片可见状态。"""
        x, y, width, height = raw_bbox
        bottom = y + height
        flags: List[str] = []
        if y < 0:
            flags.append("partial_top")
        if x < 0:
            flags.append("partial_left")
        if x + width > image_width:
            flags.append("partial_right")
        if bottom > image_height:
            flags.append("partial_bottom")
        if image_mode == "viewport_full" and bottom > int(geometry["bottom_overlay_y"]):
            flags.append("partial_bottom")
        if clipped_bbox[2] < width or clipped_bbox[3] < height:
            if clipped_bbox[3] < height and not any(item.startswith("partial_") for item in flags):
                flags.append("partial_bottom")
        if not flags:
            return "full"
        return "+".join(dict.fromkeys(flags))

    @staticmethod
    def _ratio_roi(parent: RoiRegion, ratio: RatioRegion) -> RoiRegion:
        """把相对卡片比例转换成绝对 ROI。"""
        x, y, width, height = parent
        rx, ry, rw, rh = ratio
        return (
            x + int(round(width * rx)),
            y + int(round(height * ry)),
            max(1, int(round(width * rw))),
            max(1, int(round(height * rh))),
        )

    @staticmethod
    def _clip_roi(roi: RoiRegion, image_width: int, image_height: int) -> RoiRegion:
        """把 ROI 裁剪到图片范围内。"""
        x, y, width, height = roi
        x0 = min(max(0, int(x)), max(0, image_width - 1))
        y0 = min(max(0, int(y)), max(0, image_height - 1))
        x1 = min(max(0, int(x + width)), image_width)
        y1 = min(max(0, int(y + height)), image_height)
        return x0, y0, max(1, x1 - x0), max(1, y1 - y0)

    def _require_cv2(self) -> Any:
        """获取 OpenCV 模块，不可用时抛出友好错误。"""
        if self._cv2 is None:
            raise RuntimeError("OpenCV(cv2) 不可用，无法检测设计图卡片。")
        return self._cv2

    def _require_np(self) -> Any:
        """获取 NumPy 模块，不可用时抛出友好错误。"""
        if self._np is None:
            raise RuntimeError("NumPy 不可用，无法检测设计图卡片。")
        return self._np


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_design_fragment_detector_instance: Optional[DesignFragmentDetector] = None


def get_design_fragment_detector() -> DesignFragmentDetector:
    """获取设计图碎片卡片检测器单例。"""
    global _design_fragment_detector_instance
    if _design_fragment_detector_instance is None:
        _design_fragment_detector_instance = DesignFragmentDetector()
    return _design_fragment_detector_instance
