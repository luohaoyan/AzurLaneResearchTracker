#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║            🧩 OpenCV 模板匹配器 (template_matcher.py)        ║
║                                                              ║
║  【一句话解释】封装游戏 UI 模板匹配、多尺度搜索和重复框抑制。║
║  【类比理解】它像拿着透明描图纸在截图上找按钮轮廓。           ║
║  【数据流说明】截图 + 模板 → 多尺度相关性 → NMS → 标准匹配框。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - 本机缺 OpenCV 时的安全降级。
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - 极端精简环境兜底。
    _np = None


# ============================================================
# 🧱 第二部分：结果对象
# ============================================================

Box = Tuple[int, int, int, int]


@dataclass(frozen=True)
class TemplateMatch:
    """
    单个模板匹配框。
    输入：
        label/confidence/box/scale。
    输出：
        可序列化的 UI 元素检测结果。
    使用示例：
        match = TemplateMatch("research_button", 0.92, (10, 20, 80, 40), 1.0)
    """

    label: str
    confidence: float
    box: Box
    scale: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为基础 Python 类型字典。"""
        return {
            "label": self.label,
            "confidence": float(self.confidence),
            "box": [int(item) for item in self.box],
            "scale": float(self.scale),
        }


@dataclass(frozen=True)
class TemplateMatchResult:
    """
    模板匹配批次结果。
    输入：
        success/status/message/matches/warnings。
    输出：
        无 OpenCV 私有类型的结构化结果。
    使用示例：
        result = matcher.match_template(image, template)
    """

    success: bool
    status: str
    message: str
    matches: Tuple[TemplateMatch, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "matches": [item.to_dict() for item in self.matches],
            "warnings": list(self.warnings),
        }


# ============================================================
# 🏗️ 第三部分：模板匹配器
# ============================================================

class TemplateMatcher:
    """
    OpenCV 模板匹配封装。
    输入：
        threshold/scales/iou_threshold/cv2_module/np_module。
    输出：
        支持无依赖降级和 fake cv2 测试注入的匹配器。
    使用示例：
        matcher = TemplateMatcher(threshold=0.8, scales=(0.9, 1.0, 1.1))
    """

    def __init__(
        self,
        threshold: float = 0.8,
        scales: Sequence[float] = (1.0,),
        iou_threshold: float = 0.3,
        cv2_module: Optional[Any] = None,
        np_module: Optional[Any] = None,
    ) -> None:
        """初始化匹配参数并做范围校验。"""
        self.threshold = self._validate_threshold(threshold)
        self.scales = self._validate_scales(scales)
        self.iou_threshold = self._validate_threshold(iou_threshold)
        self._cv2 = cv2_module
        self._np = np_module

    def check_status(self) -> Dict[str, Any]:
        """
        检查模板匹配环境状态。
        输入：
            无。
        输出：
            dict: 依赖可用性。
        使用示例：
            status = matcher.check_status()
        """
        cv2_available = self._get_cv2() is not None
        np_available = self._get_np() is not None
        return {
            "available": cv2_available and np_available,
            "dependencies": {
                "opencv_cv2": cv2_available,
                "numpy": np_available,
            },
            "threshold": self.threshold,
            "scales": list(self.scales),
            "iou_threshold": self.iou_threshold,
        }

    def match_template(
        self,
        image: Any,
        template: Any,
        label: str = "template",
        threshold: Optional[float] = None,
        scales: Optional[Sequence[float]] = None,
        max_results: Optional[int] = None,
    ) -> TemplateMatchResult:
        """
        执行多尺度模板匹配并去重。
        输入：
            image/template/label/threshold/scales/max_results。
        输出：
            TemplateMatchResult。
        使用示例：
            result = matcher.match_template(screenshot, button_template)
        """
        cv2_module = self._get_cv2()
        np_module = self._get_np()
        if cv2_module is None or np_module is None:
            message = "OpenCV(cv2) 或 NumPy 不可用，模板匹配返回 unavailable。"
            return TemplateMatchResult(False, "unavailable", message, warnings=(message,))

        try:
            safe_threshold = self._validate_threshold(self.threshold if threshold is None else threshold)
            safe_scales = self._validate_scales(self.scales if scales is None else scales)
            self._validate_image_pair(image, template)
        except ValueError as exc:
            return TemplateMatchResult(False, "error", str(exc), warnings=(str(exc),))

        image_ready = self._as_match_image(image, cv2_module)
        template_ready = self._as_match_image(template, cv2_module)
        image_height, image_width = int(image_ready.shape[0]), int(image_ready.shape[1])

        candidates: List[TemplateMatch] = []
        skipped_scales = 0
        for scale in safe_scales:
            scaled_template = self._resize_template(template_ready, scale, cv2_module)
            template_height, template_width = int(scaled_template.shape[0]), int(scaled_template.shape[1])
            if template_width <= 0 or template_height <= 0:
                skipped_scales += 1
                continue
            if template_width > image_width or template_height > image_height:
                skipped_scales += 1
                continue

            score_map = cv2_module.matchTemplate(
                image_ready,
                scaled_template,
                getattr(cv2_module, "TM_CCOEFF_NORMED", 5),
            )
            locations = np_module.where(score_map >= safe_threshold)
            for y, x in zip(locations[0], locations[1]):
                confidence = float(score_map[int(y)][int(x)])
                candidates.append(
                    TemplateMatch(
                        label=label,
                        confidence=confidence,
                        box=(int(x), int(y), template_width, template_height),
                        scale=float(scale),
                    )
                )

        if not candidates:
            status = "no_valid_scale" if skipped_scales == len(safe_scales) else "no_match"
            message = "没有可用模板尺度。" if status == "no_valid_scale" else "未找到超过阈值的模板匹配。"
            return TemplateMatchResult(True, status, message)

        matches = self._suppress_duplicates(candidates, self.iou_threshold)
        if max_results is not None:
            matches = matches[:max(0, int(max_results))]
        return TemplateMatchResult(True, "success", "模板匹配完成。", tuple(matches))

    def match(self, image: Any, template: Any, **kwargs: Any) -> TemplateMatchResult:
        """
        match_template 的短别名。
        输入：
            image/template 和其他关键字参数。
        输出：
            TemplateMatchResult。
        使用示例：
            result = matcher.match(image, template, label="button")
        """
        return self.match_template(image, template, **kwargs)

    @classmethod
    def _suppress_duplicates(
        cls,
        candidates: Iterable[TemplateMatch],
        iou_threshold: float,
    ) -> List[TemplateMatch]:
        """按置信度排序后用 IoU 抑制重复框。"""
        kept: List[TemplateMatch] = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            if all(cls._iou(candidate.box, kept_match.box) <= iou_threshold for kept_match in kept):
                kept.append(candidate)
        return kept

    @staticmethod
    def _iou(first: Box, second: Box) -> float:
        """计算两个 x/y/w/h 框的交并比。"""
        ax, ay, aw, ah = first
        bx, by, bw, bh = second
        left = max(ax, bx)
        top = max(ay, by)
        right = min(ax + aw, bx + bw)
        bottom = min(ay + ah, by + bh)
        intersection_width = max(0, right - left)
        intersection_height = max(0, bottom - top)
        intersection = intersection_width * intersection_height
        if intersection == 0:
            return 0.0
        first_area = aw * ah
        second_area = bw * bh
        return intersection / float(first_area + second_area - intersection)

    @staticmethod
    def _validate_threshold(value: float) -> float:
        """校验阈值必须位于 0.0 到 1.0。"""
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("模板匹配阈值必须位于 0.0 到 1.0。")
        return numeric

    @staticmethod
    def _validate_scales(scales: Sequence[float]) -> Tuple[float, ...]:
        """校验多尺度列表必须非空且全部为正数。"""
        values = tuple(float(item) for item in scales)
        if not values:
            raise ValueError("模板匹配尺度列表不能为空。")
        if any(item <= 0 for item in values):
            raise ValueError("模板匹配尺度必须为正数。")
        return values

    @staticmethod
    def _validate_image_pair(image: Any, template: Any) -> None:
        """校验输入图像非空且模板尺寸不为零。"""
        for name, value in (("截图", image), ("模板", template)):
            if value is None or not hasattr(value, "shape") or getattr(value, "size", 0) == 0:
                raise ValueError(f"{name}图像为空，无法模板匹配。")
            if len(value.shape) < 2:
                raise ValueError(f"{name}图像维度非法。")
        if int(template.shape[0]) <= 0 or int(template.shape[1]) <= 0:
            raise ValueError("模板尺寸非法。")

    @staticmethod
    def _as_match_image(image: Any, cv2_module: Any) -> Any:
        """把彩色图像转为灰度，减少通道差异带来的匹配失败。"""
        if len(image.shape) == 3:
            return cv2_module.cvtColor(image, cv2_module.COLOR_BGR2GRAY)
        return image

    @staticmethod
    def _resize_template(template: Any, scale: float, cv2_module: Any) -> Any:
        """按给定尺度缩放模板，保持至少 1 像素尺寸。"""
        if abs(float(scale) - 1.0) < 1e-9:
            return template
        width = max(1, int(round(int(template.shape[1]) * float(scale))))
        height = max(1, int(round(int(template.shape[0]) * float(scale))))
        return cv2_module.resize(template, (width, height))

    def _get_cv2(self) -> Optional[Any]:
        """获取 cv2 模块，优先使用测试注入。"""
        if self._cv2 is not None:
            return self._cv2
        return _cv2

    def _get_np(self) -> Optional[Any]:
        """获取 NumPy 模块，优先使用测试注入。"""
        if self._np is not None:
            return self._np
        return _np

    @staticmethod
    def _module_available(module_name: str) -> bool:
        """安全检查模块是否可发现。"""
        try:
            return importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False
