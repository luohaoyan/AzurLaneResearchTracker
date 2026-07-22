#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🏷️ 仓库标签识别器 (warehouse_label_detector.py)       ║
║                                                              ║
║  【一句话解释】识别仓库页固定按钮、底部标签选中态和排序状态。║
║  【类比理解】它像一把透明坐标尺，专门量仓库 UI 的几个按钮。  ║
║  【数据流说明】1280x720截图 → 固定ROI → 颜色/模板判断 → 结果。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - 用户未安装 OpenCV 时需要安全降级。
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - 极简运行环境下需要安全降级。
    _np = None


# ============================================================
# 🧱 第二部分：结果对象
# ============================================================

Box = Tuple[int, int, int, int]
_UNSET = object()


@dataclass(frozen=True)
class WarehouseLabelDetection:
    """
    单个仓库 UI 元素检测结果。
    输入：
        label/bbox/present/confidence/state/score/kind。
    输出：
        可 JSON 序列化的按钮或标签状态。
    使用示例：
        detection = WarehouseLabelDetection("tab_design", (787, 651, 155, 54), True, 0.95, "selected")
    """

    label: str
    bbox: Box
    present: bool
    confidence: float
    state: str = ""
    score: float = 0.0
    kind: str = "ui_element"

    def to_dict(self) -> Dict[str, Any]:
        """转换为不包含 OpenCV/NumPy 私有类型的普通字典。"""
        return {
            "label": self.label,
            "kind": self.kind,
            "bbox": [int(item) for item in self.bbox],
            "present": bool(self.present),
            "confidence": round(float(self.confidence), 6),
            "state": self.state,
            "score": round(float(self.score), 6),
        }


@dataclass(frozen=True)
class WarehouseLabelResult:
    """
    仓库标签识别批次结果。
    输入：
        success/status/message/image_size/page_type/sort_mode/filter_panel_open/detections/warnings。
    输出：
        供自动化点击和训练标注脚本复用的结构化结果。
    使用示例：
        result = WarehouseLabelDetector().detect("warehouse.png")
    """

    success: bool
    status: str
    message: str
    screenshot_path: str = ""
    image_size: Tuple[int, int] = (0, 0)
    page_type: str = "unknown"
    sort_mode: str = "unknown"
    filter_panel_open: bool = False
    detections: Tuple[WarehouseLabelDetection, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为训练输出和接口调试都能直接使用的普通字典。"""
        return {
            "success": bool(self.success),
            "status": self.status,
            "message": self.message,
            "screenshot_path": self.screenshot_path,
            "image_size": [int(self.image_size[0]), int(self.image_size[1])],
            "page_type": self.page_type,
            "sort_mode": self.sort_mode,
            "filter_panel_open": bool(self.filter_panel_open),
            "detections": [item.to_dict() for item in self.detections],
            "warnings": list(self.warnings),
        }


# ============================================================
# 🏗️ 第三部分：仓库标签识别器
# ============================================================

class WarehouseLabelDetector:
    """
    仓库标签专用 OpenCV 检测器。
    输入：
        1280x720 仓库截图，可选排序按钮模板。
    输出：
        房子按钮、筛选按钮、底部标签选中态、排序状态和筛选弹层状态。
    使用示例：
        detector = WarehouseLabelDetector()
        templates = detector.build_sort_template_bank("ocr_training_lab/warehouse_tabs/img_input")
        result = detector.detect("shot.png", sort_templates=templates)
    """

    DEFAULT_BASE_RESOLUTION: Tuple[int, int] = (1280, 720)
    DEFAULT_ROIS: Mapping[str, Box] = {
        "home_button": (1210, 4, 66, 64),
        "filter_button": (790, 4, 98, 45),
        "sort_direction_button": (934, 4, 102, 45),
        "sort_mode_button": (1036, 4, 146, 45),
        "tab_design": (787, 651, 155, 54),
        "tab_equipment": (947, 651, 155, 54),
        "tab_material": (1106, 651, 154, 54),
        "filter_panel": (20, 85, 1238, 494),
        "filter_cancel_button": (392, 601, 176, 62),
        "filter_confirm_button": (712, 601, 176, 62),
    }
    TAB_PAGE_TYPES: Mapping[str, str] = {
        "tab_design": "design",
        "tab_equipment": "equipment",
        "tab_material": "material",
    }
    SORT_FILENAME_MARKERS: Mapping[str, Tuple[str, ...]] = {
        "rarity": ("_rarity_", "rarity"),
        "buildable": ("_buildable_", "buildable"),
        "quantity": ("_nums_", "_quantity_", "quantity"),
    }

    def __init__(
        self,
        base_resolution: Tuple[int, int] = DEFAULT_BASE_RESOLUTION,
        rois: Optional[Mapping[str, Sequence[int]]] = None,
        tab_selected_threshold: float = 0.35,
        filter_panel_red_threshold: float = 0.22,
        sort_template_threshold: float = 0.82,
        sort_template_margin: float = 0.015,
        cv2_module: Any = _UNSET,
        np_module: Any = _UNSET,
    ) -> None:
        """初始化检测器，允许测试注入 cv2/np，也允许缺依赖时安全返回 unavailable。"""
        self.base_resolution = (int(base_resolution[0]), int(base_resolution[1]))
        self.rois = self._normalize_rois(rois or self.DEFAULT_ROIS)
        self.tab_selected_threshold = float(tab_selected_threshold)
        self.filter_panel_red_threshold = float(filter_panel_red_threshold)
        self.sort_template_threshold = float(sort_template_threshold)
        self.sort_template_margin = float(sort_template_margin)
        self._cv2 = _cv2 if cv2_module is _UNSET else cv2_module
        self._np = _np if np_module is _UNSET else np_module

    def check_status(self) -> Dict[str, Any]:
        """
        检查 OpenCV/NumPy 是否可用。
        输入：
            无。
        输出：
            dict: 可用性和当前阈值。
        使用示例：
            status = detector.check_status()
        """
        return {
            "available": self._cv2 is not None and self._np is not None,
            "dependencies": {
                "opencv_cv2": self._cv2 is not None,
                "numpy": self._np is not None,
            },
            "base_resolution": list(self.base_resolution),
            "tab_selected_threshold": self.tab_selected_threshold,
            "filter_panel_red_threshold": self.filter_panel_red_threshold,
            "sort_template_threshold": self.sort_template_threshold,
            "sort_template_margin": self.sort_template_margin,
        }

    def load_image(self, screenshot_path: str | Path) -> Any:
        """
        读取截图文件，兼容 Windows 中文路径。
        输入：
            screenshot_path: PNG/JPG 等截图路径。
        输出：
            OpenCV BGR 图像。
        使用示例：
            image = detector.load_image("warehouse.png")
        """
        cv2_module, np_module = self._require_dependencies()
        path = Path(screenshot_path)
        if not path.exists():
            raise FileNotFoundError(f"截图文件不存在: {path}")
        data = np_module.fromfile(str(path), dtype=np_module.uint8)
        image = cv2_module.imdecode(data, cv2_module.IMREAD_COLOR)
        if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
            raise ValueError(f"截图无法读取或已损坏: {path}")
        return image

    def detect(
        self,
        screenshot: str | Path | Any,
        sort_templates: Optional[Mapping[str, Sequence[Any]]] = None,
    ) -> WarehouseLabelResult:
        """
        识别仓库页面固定标签与排序状态。
        输入：
            screenshot: 文件路径或 OpenCV BGR 图像。
            sort_templates: 可选，按 rarity/buildable/quantity 分组的排序按钮模板。
        输出：
            WarehouseLabelResult。
        使用示例：
            result = detector.detect("warehouse.png", sort_templates=templates)
        """
        if self._cv2 is None or self._np is None:
            message = "OpenCV(cv2) 或 NumPy 不可用，仓库标签识别返回 unavailable。"
            return WarehouseLabelResult(False, "unavailable", message, warnings=(message,))

        try:
            image, path_text = self._coerce_image(screenshot)
        except (FileNotFoundError, ValueError) as exc:
            return WarehouseLabelResult(False, "error", "截图读取失败，无法识别仓库标签。", warnings=(str(exc),))

        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        capture_warning = self._capture_warning(image_width, image_height)
        if capture_warning:
            return WarehouseLabelResult(
                False,
                "partial_image",
                "截图尺寸疑似不完整，已跳过仓库标签识别。",
                screenshot_path=path_text,
                image_size=(image_width, image_height),
                warnings=(capture_warning,),
            )

        detections: List[WarehouseLabelDetection] = []
        warnings: List[str] = []
        filter_panel_open, filter_confidence, filter_score = self._detect_filter_panel(image)
        detections.append(
            WarehouseLabelDetection(
                "filter_panel",
                self._scale_roi("filter_panel", image_width, image_height),
                filter_panel_open,
                filter_confidence,
                "open" if filter_panel_open else "closed",
                filter_score,
                "overlay",
            )
        )

        tab_detections = self._detect_tabs(image, image_width, image_height)
        detections.extend(tab_detections)
        page_type = self._page_type_from_tabs(tab_detections)

        for label in ("home_button", "filter_button", "sort_direction_button"):
            detections.append(self._detect_static_button(image, label, image_width, image_height, filter_panel_open))

        sort_detection, sort_mode, sort_warnings = self._detect_sort_mode(
            image,
            image_width,
            image_height,
            filter_panel_open,
            sort_templates or {},
        )
        detections.append(sort_detection)
        warnings.extend(sort_warnings)

        status = "success" if page_type != "unknown" else "unknown_page"
        message = "仓库标签识别完成。" if status == "success" else "未能确认当前仓库页标签。"
        return WarehouseLabelResult(
            status == "success",
            status,
            message,
            screenshot_path=path_text,
            image_size=(image_width, image_height),
            page_type=page_type,
            sort_mode=sort_mode,
            filter_panel_open=filter_panel_open,
            detections=tuple(detections),
            warnings=tuple(warnings),
        )

    def build_sort_template_bank(
        self,
        training_dir: str | Path,
        max_per_label: int = 12,
    ) -> Dict[str, Tuple[Any, ...]]:
        """
        从按命名规则整理的训练图中裁剪排序按钮模板。
        输入：
            training_dir: img_input 目录。
            max_per_label: 每个排序状态最多保留多少张模板，避免过度膨胀。
        输出：
            dict[str, tuple[np.ndarray, ...]]。
        使用示例：
            templates = detector.build_sort_template_bank("ocr_training_lab/warehouse_tabs/img_input")
        """
        if self._cv2 is None or self._np is None:
            return {}

        root = Path(training_dir)
        template_bank: Dict[str, List[Any]] = {key: [] for key in self.SORT_FILENAME_MARKERS}
        for image_path in sorted(root.glob("*.png")):
            label = self._sort_label_from_filename(image_path.name)
            if not label or len(template_bank[label]) >= int(max_per_label):
                continue
            try:
                image = self.load_image(image_path)
            except (FileNotFoundError, ValueError):
                continue
            image_height, image_width = int(image.shape[0]), int(image.shape[1])
            if self._capture_warning(image_width, image_height):
                continue
            roi = self._scale_roi("sort_mode_button", image_width, image_height)
            template_bank[label].append(self._crop(image, roi).copy())

        return {label: tuple(items) for label, items in template_bank.items() if items}

    def draw_annotations(self, image: Any, result: WarehouseLabelResult) -> Any:
        """
        在截图上绘制识别框，供训练目录输出人工复核。
        输入：
            image/result。
        输出：
            带框 OpenCV BGR 图像。
        使用示例：
            annotated = detector.draw_annotations(image, result)
        """
        cv2_module, _np_module = self._require_dependencies()
        annotated = image.copy()
        for detection in result.detections:
            x, y, width, height = detection.bbox
            color = self._annotation_color(detection)
            cv2_module.rectangle(annotated, (x, y), (x + width, y + height), color, 2)
            text = f"{detection.label}:{detection.state or detection.present}"
            cv2_module.putText(
                annotated,
                text[:42],
                (x, max(18, y - 6)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                1,
                cv2_module.LINE_AA,
            )
        summary = f"page={result.page_type} sort={result.sort_mode} filter={result.filter_panel_open}"
        cv2_module.putText(
            annotated,
            summary,
            (24, 28),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.72,
            (0, 255, 255),
            2,
            cv2_module.LINE_AA,
        )
        return annotated

    def _coerce_image(self, screenshot: str | Path | Any) -> Tuple[Any, str]:
        """把路径或已加载图像统一转换为 OpenCV 图像。"""
        if isinstance(screenshot, (str, Path)):
            path = Path(screenshot)
            return self.load_image(path), str(path)
        if screenshot is None or not hasattr(screenshot, "shape") or getattr(screenshot, "size", 0) == 0:
            raise ValueError("截图图像为空，无法识别仓库标签。")
        if len(screenshot.shape) < 2:
            raise ValueError("截图图像维度非法。")
        return screenshot, ""

    def _detect_tabs(self, image: Any, image_width: int, image_height: int) -> List[WarehouseLabelDetection]:
        """用黄色像素占比识别设计图/装备/材料三个底部标签的选中态。"""
        detections: List[WarehouseLabelDetection] = []
        for label in self.TAB_PAGE_TYPES:
            roi = self._scale_roi(label, image_width, image_height)
            yellow_ratio = self._yellow_ratio(self._crop(image, roi))
            selected = yellow_ratio >= self.tab_selected_threshold
            confidence = self._ratio_confidence(yellow_ratio, self.tab_selected_threshold)
            detections.append(
                WarehouseLabelDetection(
                    label,
                    roi,
                    True,
                    confidence,
                    "selected" if selected else "unselected",
                    yellow_ratio,
                    "tab",
                )
            )
        return detections

    def _detect_static_button(
        self,
        image: Any,
        label: str,
        image_width: int,
        image_height: int,
        blocked_by_filter: bool,
    ) -> WarehouseLabelDetection:
        """识别固定按钮是否可用；筛选弹层打开时顶层按钮视为被遮挡。"""
        roi = self._scale_roi(label, image_width, image_height)
        crop = self._crop(image, roi)
        blue_ratio = self._blue_ratio(crop)
        present = blue_ratio >= 0.22 and not blocked_by_filter
        state = "blocked_by_filter_panel" if blocked_by_filter else ("visible" if present else "missing")
        confidence = 0.45 + min(0.5, blue_ratio)
        if blocked_by_filter:
            confidence = max(0.55, confidence - 0.2)
        return WarehouseLabelDetection(label, roi, present, self._clamp(confidence), state, blue_ratio, "button")

    def _detect_filter_panel(self, image: Any) -> Tuple[bool, float, float]:
        """通过底部红色取消按钮判断筛选弹层是否打开。"""
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        cancel_roi = self._scale_roi("filter_cancel_button", image_width, image_height)
        confirm_roi = self._scale_roi("filter_confirm_button", image_width, image_height)
        cancel_red_ratio = self._red_ratio(self._crop(image, cancel_roi))
        confirm_blue_ratio = self._blue_ratio(self._crop(image, confirm_roi))
        score = max(cancel_red_ratio, cancel_red_ratio * 0.75 + confirm_blue_ratio * 0.25)
        opened = cancel_red_ratio >= self.filter_panel_red_threshold
        confidence = self._ratio_confidence(cancel_red_ratio, self.filter_panel_red_threshold)
        return opened, confidence, score

    def _detect_sort_mode(
        self,
        image: Any,
        image_width: int,
        image_height: int,
        blocked_by_filter: bool,
        sort_templates: Mapping[str, Sequence[Any]],
    ) -> Tuple[WarehouseLabelDetection, str, List[str]]:
        """用训练图裁出的排序按钮模板判断稀有度/可建造/数量。"""
        roi = self._scale_roi("sort_mode_button", image_width, image_height)
        if blocked_by_filter:
            return (
                WarehouseLabelDetection(
                    "sort_mode_button",
                    roi,
                    False,
                    0.6,
                    "blocked_by_filter_panel",
                    0.0,
                    "sort",
                ),
                "unknown",
                [],
            )

        if not sort_templates:
            warning = "排序状态模板为空：当前只返回排序按钮位置，sort_mode=unknown。"
            return (
                WarehouseLabelDetection("sort_mode_button", roi, True, 0.5, "unknown", 0.0, "sort"),
                "unknown",
                [warning],
            )

        crop = self._crop(image, roi)
        scores = self._sort_template_scores(crop, sort_templates)
        if not scores:
            warning = "排序状态模板不可用：当前只返回排序按钮位置，sort_mode=unknown。"
            return (
                WarehouseLabelDetection("sort_mode_button", roi, True, 0.5, "unknown", 0.0, "sort"),
                "unknown",
                [warning],
            )

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_label, best_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else -1.0
        margin = best_score - second_score
        accepted = best_score >= self.sort_template_threshold and margin >= self.sort_template_margin
        if not accepted:
            warning = (
                f"排序状态低置信度：best={best_label}, score={best_score:.3f}, "
                f"margin={margin:.3f}，已返回 unknown。"
            )
            return (
                WarehouseLabelDetection("sort_mode_button", roi, True, self._clamp(best_score), "unknown", best_score, "sort"),
                "unknown",
                [warning],
            )
        return (
            WarehouseLabelDetection("sort_mode_button", roi, True, self._clamp(best_score), best_label, best_score, "sort"),
            best_label,
            [],
        )

    def _sort_template_scores(self, crop: Any, sort_templates: Mapping[str, Sequence[Any]]) -> Dict[str, float]:
        """计算当前排序按钮与每类模板的最高归一化相关性分数。"""
        scores: Dict[str, float] = {}
        prepared_crop = self._prepare_sort_image(crop)
        for label, templates in sort_templates.items():
            label_scores: List[float] = []
            for template in templates:
                if template is None or not hasattr(template, "shape") or getattr(template, "size", 0) == 0:
                    continue
                prepared_template = self._prepare_sort_image(template)
                prepared_template = self._resize_like(prepared_template, prepared_crop)
                score_map = self._cv2.matchTemplate(
                    prepared_crop,
                    prepared_template,
                    self._cv2.TM_CCOEFF_NORMED,
                )
                label_scores.append(float(score_map.max()))
            if label_scores:
                scores[str(label)] = max(label_scores)
        return scores

    def _prepare_sort_image(self, image: Any) -> Any:
        """只保留排序按钮左侧文字区域，避免右侧图标把文字差异冲淡。"""
        text_width = max(1, int(round(int(image.shape[1]) * 0.72)))
        text_area = image[:, :text_width]
        if len(text_area.shape) == 3:
            gray = self._cv2.cvtColor(text_area, self._cv2.COLOR_BGR2GRAY)
        else:
            gray = text_area
        return self._cv2.equalizeHist(gray)

    def _resize_like(self, template: Any, target: Any) -> Any:
        """把模板缩放到目标尺寸，保证 matchTemplate 能得到单一整体分数。"""
        target_height, target_width = int(target.shape[0]), int(target.shape[1])
        if int(template.shape[0]) == target_height and int(template.shape[1]) == target_width:
            return template
        return self._cv2.resize(template, (target_width, target_height))

    def _page_type_from_tabs(self, detections: Sequence[WarehouseLabelDetection]) -> str:
        """根据三个标签的黄色分数选择当前页面类型。"""
        tab_items = [item for item in detections if item.label in self.TAB_PAGE_TYPES]
        if not tab_items:
            return "unknown"
        best = max(tab_items, key=lambda item: item.score)
        if best.score < self.tab_selected_threshold:
            return "unknown"
        return self.TAB_PAGE_TYPES.get(best.label, "unknown")

    def _scale_roi(self, label: str, image_width: int, image_height: int) -> Box:
        """把 1280x720 基准 ROI 按实际截图尺寸缩放到当前图。"""
        if label not in self.rois:
            raise ValueError(f"未知仓库标签 ROI: {label}")
        x, y, width, height = self.rois[label]
        base_width, base_height = self.base_resolution
        scaled = (
            int(round(x * image_width / float(base_width))),
            int(round(y * image_height / float(base_height))),
            max(1, int(round(width * image_width / float(base_width)))),
            max(1, int(round(height * image_height / float(base_height)))),
        )
        return self._clip_roi(scaled, image_width, image_height)

    def _capture_warning(self, image_width: int, image_height: int) -> str:
        """检查截图是否明显不是完整 1280x720 模拟器画面。"""
        base_width, base_height = self.base_resolution
        width_ratio = image_width / float(max(1, base_width))
        height_ratio = image_height / float(max(1, base_height))
        expected_aspect = base_width / float(max(1, base_height))
        actual_aspect = image_width / float(max(1, image_height))
        aspect_delta = abs(actual_aspect - expected_aspect) / float(max(expected_aspect, 1e-6))
        if width_ratio < 0.85 or height_ratio < 0.85:
            return (
                f"截图尺寸疑似不完整: actual={image_width}x{image_height}, "
                f"base={base_width}x{base_height}, width_ratio={width_ratio:.2f}, "
                f"height_ratio={height_ratio:.2f}。"
            )
        if aspect_delta > 0.12:
            return (
                f"截图宽高比异常: actual={image_width}x{image_height}, "
                f"base={base_width}x{base_height}, aspect_delta={aspect_delta:.2f}。"
            )
        return ""

    def _yellow_ratio(self, image: Any) -> float:
        """计算 ROI 中金黄色按钮底色占比，用于判断选中态。"""
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        lower = self._np.array([10, 45, 70], dtype=self._np.uint8)
        upper = self._np.array([45, 255, 255], dtype=self._np.uint8)
        mask = self._cv2.inRange(hsv, lower, upper)
        return float((mask > 0).mean())

    def _blue_ratio(self, image: Any) -> float:
        """计算 ROI 中蓝色 UI 底色占比，用于判断按钮是否存在。"""
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        lower = self._np.array([90, 35, 45], dtype=self._np.uint8)
        upper = self._np.array([135, 255, 255], dtype=self._np.uint8)
        mask = self._cv2.inRange(hsv, lower, upper)
        return float((mask > 0).mean())

    def _red_ratio(self, image: Any) -> float:
        """计算 ROI 中红色按钮底色占比，用于判断筛选弹层取消按钮。"""
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        low_red = self._cv2.inRange(
            hsv,
            self._np.array([0, 70, 55], dtype=self._np.uint8),
            self._np.array([12, 255, 255], dtype=self._np.uint8),
        )
        high_red = self._cv2.inRange(
            hsv,
            self._np.array([170, 70, 55], dtype=self._np.uint8),
            self._np.array([179, 255, 255], dtype=self._np.uint8),
        )
        mask = self._cv2.bitwise_or(low_red, high_red)
        return float((mask > 0).mean())

    @staticmethod
    def _crop(image: Any, roi: Box) -> Any:
        """裁剪 x/y/w/h 区域。"""
        x, y, width, height = roi
        return image[y:y + height, x:x + width]

    @staticmethod
    def _ratio_confidence(ratio: float, threshold: float) -> float:
        """把颜色占比与阈值距离转换为 0~1 置信度。"""
        return WarehouseLabelDetector._clamp(0.55 + min(0.4, abs(float(ratio) - float(threshold)) * 1.15))

    @staticmethod
    def _clip_roi(roi: Box, image_width: int, image_height: int) -> Box:
        """把 ROI 裁剪到图像内部，避免画框或裁剪越界。"""
        x, y, width, height = roi
        x = max(0, min(int(x), max(0, image_width - 1)))
        y = max(0, min(int(y), max(0, image_height - 1)))
        width = max(1, min(int(width), image_width - x))
        height = max(1, min(int(height), image_height - y))
        return x, y, width, height

    @staticmethod
    def _normalize_rois(rois: Mapping[str, Sequence[int]]) -> Dict[str, Box]:
        """把外部传入 ROI 配置标准化为 tuple[int,int,int,int]。"""
        normalized: Dict[str, Box] = {}
        for label, raw in rois.items():
            if len(raw) != 4:
                raise ValueError(f"{label} ROI 必须包含 [x,y,w,h] 四个整数。")
            normalized[str(label)] = tuple(int(item) for item in raw)  # type: ignore[assignment]
        return normalized

    @staticmethod
    def _sort_label_from_filename(filename: str) -> str:
        """从训练图命名中解析排序状态标签。"""
        normalized = f"_{filename.lower()}_"
        for label, markers in WarehouseLabelDetector.SORT_FILENAME_MARKERS.items():
            if any(marker in normalized for marker in markers):
                return label
        return ""

    @staticmethod
    def _annotation_color(detection: WarehouseLabelDetection) -> Tuple[int, int, int]:
        """根据识别状态选择 OpenCV BGR 画框颜色。"""
        if detection.kind == "tab" and detection.state == "selected":
            return 0, 215, 255
        if detection.kind == "overlay" and detection.present:
            return 0, 0, 255
        if detection.present:
            return 80, 220, 80
        return 128, 128, 128

    @staticmethod
    def _clamp(value: float) -> float:
        """把浮点值限制在 0.0 到 1.0。"""
        return max(0.0, min(1.0, float(value)))

    def _require_dependencies(self) -> Tuple[Any, Any]:
        """需要实际图像处理时统一检查 OpenCV 和 NumPy。"""
        if self._cv2 is None or self._np is None:
            raise RuntimeError("OpenCV(cv2) 或 NumPy 不可用。")
        return self._cv2, self._np


# ============================================================
# 🌐 第四部分：全局访问函数
# ============================================================

_warehouse_label_detector_instance: Optional[WarehouseLabelDetector] = None


def get_warehouse_label_detector() -> WarehouseLabelDetector:
    """
    获取仓库标签识别器单例。
    输入：
        无。
    输出：
        WarehouseLabelDetector。
    使用示例：
        detector = get_warehouse_label_detector()
    """
    global _warehouse_label_detector_instance
    if _warehouse_label_detector_instance is None:
        _warehouse_label_detector_instance = WarehouseLabelDetector()
    return _warehouse_label_detector_instance
