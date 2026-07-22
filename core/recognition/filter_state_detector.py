#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        筛选状态识别器 (filter_state_detector.py)              ║
║                                                              ║
║  【一句话解释】识别仓库设计图页筛选面板、按钮和稀有度状态。  ║
║  【类比理解】它像一张固定坐标校准纸，专门判断哪个筛选按钮亮了。║
║  【数据流说明】1280x720截图 → ROI颜色占比 → 状态/点击区域。  ║
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
except Exception:  # pragma: no cover - 没有安装 OpenCV 时必须允许模块导入。
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - 极简环境下必须允许模块导入。
    _np = None


# ============================================================
# 🧱 第二部分：结果对象与常量
# ============================================================

Box = Tuple[int, int, int, int]
_UNSET = object()


def _box_center(box: Box) -> List[int]:
    """返回 ADB 点击最常用的 ROI 中心点坐标。"""
    x, y, width, height = box
    return [int(x + width // 2), int(y + height // 2)]


def _box_to_list(box: Box) -> List[int]:
    """把 tuple ROI 转成 JSON 友好的 list。"""
    return [int(item) for item in box]


def _normalized_box(box: Box, image_size: Tuple[int, int]) -> List[float]:
    """把当前截图像素 ROI 转成 0~1 归一化坐标，方便不同分辨率复用。"""
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        return []
    x, y, width, height = box
    return [
        round(float(x) / float(image_width), 6),
        round(float(y) / float(image_height), 6),
        round(float(width) / float(image_width), 6),
        round(float(height) / float(image_height), 6),
    ]


def _normalized_point(point: Sequence[int], image_size: Tuple[int, int]) -> List[float]:
    """把当前截图像素点转成 0~1 归一化坐标。"""
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        return []
    return [
        round(float(point[0]) / float(image_width), 6),
        round(float(point[1]) / float(image_height), 6),
    ]


def _coordinate_system_payload(
    image_size: Tuple[int, int],
    base_resolution: Tuple[int, int],
) -> Dict[str, Any]:
    """生成给 ADB/整合层读取的统一坐标系说明。"""
    image_width, image_height = image_size
    base_width, base_height = base_resolution
    scale_x = float(image_width) / float(max(1, base_width))
    scale_y = float(image_height) / float(max(1, base_height))
    base_aspect = float(base_width) / float(max(1, base_height))
    current_aspect = float(image_width) / float(max(1, image_height)) if image_height > 0 else 0.0
    aspect_delta = abs(current_aspect - base_aspect) / float(max(base_aspect, 0.000001))
    return {
        "space": "screen_pixels",
        "origin": "top_left",
        "unit": "pixel",
        "base_resolution": [int(base_width), int(base_height)],
        "current_resolution": [int(image_width), int(image_height)],
        "scale": [round(scale_x, 6), round(scale_y, 6)],
        "aspect_delta": round(aspect_delta, 6),
        "scaling_policy": "full_viewport_xy_scale_from_1280x720",
        "adb_tap_rule": "adb shell input tap <center_x> <center_y>",
    }


@dataclass(frozen=True)
class FilterStateElement:
    """
    筛选界面中的一个普通 UI 元素。
    输入：
        label/bbox/visible/enabled/state/confidence/score/kind。
    输出：
        可 JSON 序列化的按钮或面板状态。
    使用示例：
        element = FilterStateElement("confirm_button", (712, 566, 176, 60), True, True, "enabled", 0.95)
    """

    label: str
    bbox: Box
    visible: bool
    enabled: bool
    state: str
    confidence: float
    score: float = 0.0
    kind: str = "element"
    base_bbox: Box = (0, 0, 0, 0)
    image_size: Tuple[int, int] = (0, 0)
    base_resolution: Tuple[int, int] = (1280, 720)
    clickable: bool = False
    click_action: str = ""
    description: str = ""
    coordinate_space: str = "screen_pixels"

    def to_dict(self) -> Dict[str, Any]:
        """转换成训练脚本、接口层都能直接使用的普通字典。"""
        center = _box_center(self.bbox)
        base_bbox = self.base_bbox if any(self.base_bbox) else self.bbox
        base_center = _box_center(base_bbox)
        return {
            "label": self.label,
            "kind": self.kind,
            "bbox": _box_to_list(self.bbox),
            "center": center,
            "normalized_bbox": _normalized_box(self.bbox, self.image_size),
            "normalized_center": _normalized_point(center, self.image_size),
            "base_bbox": _box_to_list(base_bbox),
            "base_center": base_center,
            "base_resolution": [int(self.base_resolution[0]), int(self.base_resolution[1])],
            "coordinate_space": self.coordinate_space,
            "clickable": bool(self.clickable),
            "click_action": self.click_action,
            "description": self.description,
            "visible": bool(self.visible),
            "enabled": bool(self.enabled),
            "state": self.state,
            "confidence": round(float(self.confidence), 6),
            "score": round(float(self.score), 6),
        }


@dataclass(frozen=True)
class FilterStateOption:
    """
    筛选面板中的一个可点击选项。
    输入：
        group/name/text/bbox/visible/selected/enabled/颜色占比。
    输出：
        结构化的选项位置与状态。
    使用示例：
        option = FilterStateOption("rarity", "elite", "精锐", (660, 480, 140, 41), True, True, True, 0.95)
    """

    group: str
    name: str
    text: str
    bbox: Box
    visible: bool
    selected: bool
    enabled: bool
    confidence: float
    gold_ratio: float = 0.0
    blue_ratio: float = 0.0
    state: str = "hidden"
    base_bbox: Box = (0, 0, 0, 0)
    image_size: Tuple[int, int] = (0, 0)
    base_resolution: Tuple[int, int] = (1280, 720)
    clickable: bool = False
    click_action: str = ""
    description: str = ""
    coordinate_space: str = "screen_pixels"

    @property
    def label(self) -> str:
        """返回 group/name 组合标签，便于画框和 CSV 输出。"""
        return f"{self.group}_{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        """转换为普通字典，避免把 NumPy 标量漏到 JSON 里。"""
        center = _box_center(self.bbox)
        base_bbox = self.base_bbox if any(self.base_bbox) else self.bbox
        base_center = _box_center(base_bbox)
        return {
            "group": self.group,
            "name": self.name,
            "text": self.text,
            "label": self.label,
            "bbox": _box_to_list(self.bbox),
            "center": center,
            "normalized_bbox": _normalized_box(self.bbox, self.image_size),
            "normalized_center": _normalized_point(center, self.image_size),
            "base_bbox": _box_to_list(base_bbox),
            "base_center": base_center,
            "base_resolution": [int(self.base_resolution[0]), int(self.base_resolution[1])],
            "coordinate_space": self.coordinate_space,
            "clickable": bool(self.clickable),
            "click_action": self.click_action,
            "description": self.description,
            "visible": bool(self.visible),
            "selected": bool(self.selected),
            "enabled": bool(self.enabled),
            "state": self.state,
            "confidence": round(float(self.confidence), 6),
            "gold_ratio": round(float(self.gold_ratio), 6),
            "blue_ratio": round(float(self.blue_ratio), 6),
        }


@dataclass(frozen=True)
class FilterStateResult:
    """
    单张截图的筛选状态识别结果。
    输入：
        截图尺寸、面板状态、当前筛选项、元素列表和警告。
    输出：
        自动化层可用于点击/校验的结构化 payload。
    使用示例：
        result = FilterStateDetector().detect("design_filter.png")
    """

    success: bool
    status: str
    message: str
    screenshot_path: str = ""
    image_size: Tuple[int, int] = (0, 0)
    base_resolution: Tuple[int, int] = (1280, 720)
    page: str = "fragment"
    tab: str = "design"
    filter_panel_open: bool = False
    filter_button_active: bool = False
    current_type_filter: str = "unknown"
    current_camp_filter: str = "unknown"
    current_rarity_filter: str = "unknown"
    current_sort: str = "unknown"
    rarity_inference_source: str = "unknown"
    elements: Tuple[FilterStateElement, ...] = ()
    options: Tuple[FilterStateOption, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON/CSV 友好的普通字典。"""
        return {
            "success": bool(self.success),
            "status": self.status,
            "message": self.message,
            "screenshot_path": self.screenshot_path,
            "image_size": [int(self.image_size[0]), int(self.image_size[1])],
            "base_resolution": [int(self.base_resolution[0]), int(self.base_resolution[1])],
            "coordinate_system": _coordinate_system_payload(self.image_size, self.base_resolution),
            "page": self.page,
            "tab": self.tab,
            "filter_panel_open": bool(self.filter_panel_open),
            "filter_button_active": bool(self.filter_button_active),
            "current_type_filter": self.current_type_filter,
            "current_camp_filter": self.current_camp_filter,
            "current_rarity_filter": self.current_rarity_filter,
            "current_sort": self.current_sort,
            "rarity_inference_source": self.rarity_inference_source,
            "elements": [item.to_dict() for item in self.elements],
            "options": [item.to_dict() for item in self.options],
            "warnings": list(self.warnings),
        }


# ============================================================
# 🏗️ 第三部分：筛选状态识别器
# ============================================================

class FilterStateDetector:
    """
    仓库设计图筛选状态专用 OpenCV 检测器。
    输入：
        1280x720 或等比例截图；PaddleOCR 不参与本检测器。
    输出：
        筛选面板开闭、类型/阵营/稀有度选项状态、取消/确认按钮位置。
    使用示例：
        detector = FilterStateDetector()
        result = detector.detect("ocr_training_lab/fragment_filter_scan/filter_state_img_input/design_filter_menu_open.png")
    """

    BASE_RESOLUTION: Tuple[int, int] = (1280, 720)
    MIN_CAPTURE_RATIO: float = 0.85
    MAX_ASPECT_RATIO_DELTA: float = 0.12
    GOLD_SELECTED_THRESHOLD: float = 0.45
    BLUE_VISIBLE_THRESHOLD: float = 0.25
    FILTER_ACTIVE_THRESHOLD: float = 0.40
    FILTER_PANEL_RED_THRESHOLD: float = 0.30
    EMPTY_LIST_EDGE_THRESHOLD: float = 15.0

    ELEMENT_ROIS: Mapping[str, Box] = {
        "home_button": (1208, 3, 70, 70),
        "filter_button": (790, 4, 98, 45),
        "sort_button": (934, 4, 102, 45),
        "sort_mode_button": (1036, 4, 146, 45),
        "rarity_button": (1036, 4, 146, 45),
        "filter_panel": (20, 121, 1238, 422),
        "filter_cancel_button": (392, 566, 176, 60),
        "filter_confirm_button": (712, 566, 176, 60),
        "tab_design": (787, 651, 155, 54),
        "tab_equipment": (947, 651, 155, 54),
        "tab_material": (1106, 651, 154, 54),
    }
    ELEMENT_CLICK_ACTIONS: Mapping[str, Tuple[str, str]] = {
        "home_button": ("return_home", "ADB tap target: return to harbor/home screen."),
        "filter_button": ("open_filter_panel", "ADB tap target: open filter panel and read selected options."),
        "sort_button": ("toggle_sort_direction", "ADB tap target: toggle sort direction."),
        "sort_mode_button": ("open_sort_mode_menu", "ADB tap target: open sort mode selector."),
        "rarity_button": ("open_sort_mode_menu", "ADB tap target: open sort mode selector."),
        "filter_cancel_button": ("close_filter_panel_without_apply", "ADB tap target: close filter panel without applying changes."),
        "filter_confirm_button": ("apply_filter_panel", "ADB tap target: apply current filter panel selections."),
    }
    OPTION_CLICK_PREFIX: Mapping[str, Tuple[str, str]] = {
        "type": ("select_type", "ADB tap target: select equipment type filter option."),
        "index": ("open_index_filter", "ADB tap target: open or select index filter option."),
        "camp": ("select_camp", "ADB tap target: select camp filter option."),
        "rarity": ("select_rarity", "ADB tap target: select rarity filter option."),
    }

    TYPE_OPTIONS: Tuple[Tuple[str, str, Box], ...] = (
        ("all", "全部", (218, 148, 140, 41)),
        ("small_gun", "小型舰炮", (365, 148, 140, 41)),
        ("medium_gun", "中型舰炮", (513, 148, 140, 41)),
        ("large_gun", "大型舰炮", (660, 148, 140, 41)),
        ("surface_torpedo", "水面鱼雷", (807, 148, 140, 41)),
        ("submarine_torpedo", "潜艇鱼雷", (955, 148, 140, 41)),
        ("anti_air", "防空炮", (1102, 148, 140, 41)),
        ("fighter", "战斗机", (218, 205, 140, 41)),
        ("bomber", "轰炸机", (365, 205, 140, 41)),
        ("torpedo_bomber", "鱼雷机", (513, 205, 140, 41)),
        ("device", "设备", (660, 205, 140, 41)),
        ("other", "其他", (807, 205, 140, 41)),
    )
    INDEX_OPTIONS: Tuple[Tuple[str, str, Box], ...] = (
        ("attribute", "属性", (218, 277, 140, 43)),
    )
    CAMP_OPTIONS: Tuple[Tuple[str, str, Box], ...] = (
        ("all", "全阵营", (218, 350, 140, 41)),
        ("eagle_union", "白鹰", (365, 350, 140, 41)),
        ("royal_navy", "皇家", (513, 350, 140, 41)),
        ("sakura_empire", "重樱", (660, 350, 140, 41)),
        ("iron_blood", "铁血", (807, 350, 140, 41)),
        ("dragon_empire", "东煌", (955, 350, 140, 41)),
        ("sardegna_empire", "撒丁帝国", (1102, 350, 140, 41)),
        ("northern_parliament", "北方联合", (218, 407, 140, 41)),
        ("vichya_dominion", "自由鸢尾", (365, 407, 140, 41)),
        ("iris_orthodoxy", "维希教廷", (513, 407, 140, 41)),
        ("tempesta", "飓风", (660, 407, 140, 41)),
        ("collaboration", "联动", (807, 407, 140, 41)),
        ("other", "其他", (955, 407, 140, 41)),
    )
    RARITY_OPTIONS: Tuple[Tuple[str, str, Box], ...] = (
        ("all", "全部", (218, 480, 140, 41)),
        ("common", "普通", (365, 480, 140, 41)),
        ("rare", "稀有", (513, 480, 140, 41)),
        ("elite", "精锐", (660, 480, 140, 41)),
        ("super_rare", "超稀有", (807, 480, 140, 41)),
        ("ultra_rare", "海上传奇", (955, 480, 140, 41)),
    )
    DESIGN_CARD_ROIS: Tuple[Box, ...] = tuple(
        (card_x, card_y, 541, 135)
        for card_y in (72, 225, 378, 531)
        for card_x in (133, 690)
    )
    DESIGN_ICON_ROIS: Tuple[Box, ...] = tuple(
        (card_x + 10, card_y + 8, 118, 118)
        for card_y in (72, 225, 378, 531)
        for card_x in (133, 690)
    )

    def __init__(
        self,
        base_resolution: Tuple[int, int] = BASE_RESOLUTION,
        cv2_module: Any = _UNSET,
        np_module: Any = _UNSET,
    ) -> None:
        """初始化检测器；支持测试注入依赖，也支持缺失依赖时安全返回 unavailable。"""
        self.base_resolution = (int(base_resolution[0]), int(base_resolution[1]))
        self._cv2 = _cv2 if cv2_module is _UNSET else cv2_module
        self._np = _np if np_module is _UNSET else np_module

    def check_status(self) -> Dict[str, Any]:
        """
        检查 OpenCV/NumPy 是否可用。
        输入：
            无。
        输出：
            dict: 依赖状态和关键阈值。
        使用示例：
            status = FilterStateDetector().check_status()
        """
        return {
            "available": self._cv2 is not None and self._np is not None,
            "dependencies": {
                "opencv_cv2": self._cv2 is not None,
                "numpy": self._np is not None,
            },
            "base_resolution": list(self.base_resolution),
            "gold_selected_threshold": self.GOLD_SELECTED_THRESHOLD,
            "filter_panel_red_threshold": self.FILTER_PANEL_RED_THRESHOLD,
            "empty_list_edge_threshold": self.EMPTY_LIST_EDGE_THRESHOLD,
            "max_aspect_ratio_delta": self.MAX_ASPECT_RATIO_DELTA,
        }

    def load_image(self, screenshot_path: str | Path) -> Any:
        """
        读取截图文件，兼容 Windows 中文路径。
        输入：
            screenshot_path: PNG/JPG 等截图路径。
        输出：
            OpenCV BGR 图像。
        使用示例：
            image = detector.load_image("design_filter.png")
        """
        cv2_module, np_module = self._require_dependencies()
        path = Path(screenshot_path)
        if not path.exists():
            raise FileNotFoundError(f"筛选状态截图不存在: {path}")
        data = np_module.fromfile(str(path), dtype=np_module.uint8)
        image = cv2_module.imdecode(data, cv2_module.IMREAD_COLOR)
        if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
            raise ValueError(f"筛选状态截图无法读取或已损坏: {path}")
        return image

    def detect(self, screenshot: str | Path | Any) -> FilterStateResult:
        """
        识别设计图页筛选状态。
        输入：
            screenshot: 文件路径或已加载 OpenCV BGR 图像。
        输出：
            FilterStateResult。
        使用示例：
            result = detector.detect("design_filter_ultra_rare_selected_1.png")
        """
        if self._cv2 is None or self._np is None:
            message = "OpenCV(cv2) 或 NumPy 不可用，筛选状态识别返回 unavailable。"
            return FilterStateResult(False, "unavailable", message, warnings=(message,))

        try:
            image, path_text = self._coerce_image(screenshot)
        except (FileNotFoundError, ValueError) as exc:
            return FilterStateResult(False, "error", "截图读取失败，无法识别筛选状态。", warnings=(str(exc),))

        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        capture_warning = self._capture_warning(image_width, image_height)
        if capture_warning:
            return FilterStateResult(
                False,
                "partial_image",
                "截图尺寸疑似不完整，已跳过筛选状态识别。",
                screenshot_path=path_text,
                image_size=(image_width, image_height),
                base_resolution=self.base_resolution,
                warnings=(capture_warning,),
            )

        warnings: List[str] = []
        elements: List[FilterStateElement] = []
        filter_panel_open, panel_confidence, panel_score = self._detect_filter_panel(image)
        elements.append(
            self._make_element(
                "filter_panel",
                self._scale_roi("filter_panel", image_width, image_height),
                filter_panel_open,
                filter_panel_open,
                "open" if filter_panel_open else "closed",
                panel_confidence,
                panel_score,
                "overlay",
                image_width,
                image_height,
            )
        )

        filter_button = self._detect_top_button(image, "filter_button", image_width, image_height)
        filter_button_active = filter_button.state == "active"
        elements.extend(
            (
                filter_button,
                self._detect_top_button(image, "sort_button", image_width, image_height),
                self._detect_top_button(image, "rarity_button", image_width, image_height),
                self._detect_top_button(image, "home_button", image_width, image_height),
            )
        )
        elements.extend(self._detect_bottom_buttons(image, image_width, image_height, filter_panel_open))

        options = self._detect_options(image, image_width, image_height, filter_panel_open)
        current_type = self._selected_name(options, "type")
        current_camp = self._selected_name(options, "camp")
        current_rarity = self._selected_name(options, "rarity")
        rarity_source = "panel_selected_option" if filter_panel_open else "closed_list_inference"

        if not filter_panel_open:
            current_type = "unknown"
            current_camp = "unknown"
            if not filter_button_active:
                current_rarity = "all"
                rarity_source = "inactive_filter_button"
            else:
                current_rarity, rarity_source, rarity_warning = self._infer_closed_rarity(image)
                if rarity_warning:
                    warnings.append(rarity_warning)

        tab = self._detect_selected_tab(image, image_width, image_height)
        current_sort = self._detect_current_sort(elements, warnings)
        status = "success" if tab == "design" or filter_panel_open else "unknown_page"
        message = "筛选状态识别完成。" if status == "success" else "未能确认当前是否为设计图筛选相关界面。"
        return FilterStateResult(
            success=status == "success",
            status=status,
            message=message,
            screenshot_path=path_text,
            image_size=(image_width, image_height),
            base_resolution=self.base_resolution,
            page="fragment",
            tab=tab,
            filter_panel_open=filter_panel_open,
            filter_button_active=filter_button_active,
            current_type_filter=current_type,
            current_camp_filter=current_camp,
            current_rarity_filter=current_rarity,
            current_sort=current_sort,
            rarity_inference_source=rarity_source,
            elements=tuple(elements),
            options=tuple(options),
            warnings=tuple(warnings),
        )

    def draw_annotations(self, image: Any, result: FilterStateResult) -> Any:
        """
        在截图上绘制筛选状态识别框，供人工验收。
        输入：
            image/result。
        输出：
            带框 OpenCV BGR 图像。
        使用示例：
            annotated = detector.draw_annotations(image, result)
        """
        cv2_module, _np_module = self._require_dependencies()
        annotated = image.copy()
        for element in result.elements:
            color = self._element_color(element)
            x, y, width, height = element.bbox
            cv2_module.rectangle(annotated, (x, y), (x + width, y + height), color, 2)
            cv2_module.putText(
                annotated,
                f"{element.label}:{element.state}"[:48],
                (x, max(18, y - 6)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2_module.LINE_AA,
            )

        for option in result.options:
            if not option.visible:
                continue
            color = (0, 215, 255) if option.selected else (180, 180, 180)
            x, y, width, height = option.bbox
            cv2_module.rectangle(annotated, (x, y), (x + width, y + height), color, 2 if option.selected else 1)
            cv2_module.putText(
                annotated,
                f"{option.label}:{option.state}"[:48],
                (x + 2, max(18, y - 4)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                0.40,
                color,
                1,
                cv2_module.LINE_AA,
            )

        summary = (
            f"filter={result.filter_panel_open} "
            f"rarity={result.current_rarity_filter} "
            f"type={result.current_type_filter} camp={result.current_camp_filter}"
        )
        cv2_module.putText(
            annotated,
            summary,
            (24, 28),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.68,
            (0, 255, 255),
            2,
            cv2_module.LINE_AA,
        )
        return annotated

    def write_image(self, output_path: str | Path, image: Any) -> None:
        """
        写出 PNG 图片，兼容 Windows 中文路径。
        输入：
            output_path/image。
        输出：
            目标 PNG 文件。
        使用示例：
            detector.write_image("img_out/demo.png", annotated)
        """
        cv2_module, _np_module = self._require_dependencies()
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, encoded = cv2_module.imencode(".png", image)
        if not ok:
            raise ValueError(f"无法编码输出图片: {path}")
        encoded.tofile(str(path))

    def _make_element(
        self,
        label: str,
        bbox: Box,
        visible: bool,
        enabled: bool,
        state: str,
        confidence: float,
        score: float,
        kind: str,
        image_width: int,
        image_height: int,
    ) -> FilterStateElement:
        """创建带 ADB 点击元数据的普通 UI 元素结果。"""
        action, description = self.ELEMENT_CLICK_ACTIONS.get(label, ("", ""))
        clickable = bool(action and visible and enabled and kind != "overlay")
        return FilterStateElement(
            label=label,
            bbox=bbox,
            visible=visible,
            enabled=enabled,
            state=state,
            confidence=confidence,
            score=score,
            kind=kind,
            base_bbox=self.ELEMENT_ROIS.get(label, bbox),
            image_size=(image_width, image_height),
            base_resolution=self.base_resolution,
            clickable=clickable,
            click_action=action,
            description=description,
        )

    def _make_option(
        self,
        group: str,
        name: str,
        text: str,
        bbox: Box,
        visible: bool,
        selected: bool,
        enabled: bool,
        confidence: float,
        gold_ratio: float,
        blue_ratio: float,
        state: str,
        base_bbox: Box,
        image_width: int,
        image_height: int,
    ) -> FilterStateOption:
        """创建带 ADB 点击元数据的筛选面板选项结果。"""
        action_prefix, description = self.OPTION_CLICK_PREFIX.get(group, ("", ""))
        click_action = f"{action_prefix}:{name}" if action_prefix else ""
        return FilterStateOption(
            group=group,
            name=name,
            text=text,
            bbox=bbox,
            visible=visible,
            selected=selected,
            enabled=enabled,
            confidence=confidence,
            gold_ratio=gold_ratio,
            blue_ratio=blue_ratio,
            state=state,
            base_bbox=base_bbox,
            image_size=(image_width, image_height),
            base_resolution=self.base_resolution,
            clickable=bool(click_action and visible and enabled),
            click_action=click_action,
            description=description,
        )

    def _coerce_image(self, screenshot: str | Path | Any) -> Tuple[Any, str]:
        """把路径或已加载图像统一转换为 OpenCV 图像。"""
        if isinstance(screenshot, (str, Path)):
            path = Path(screenshot)
            return self.load_image(path), str(path)
        if screenshot is None or not hasattr(screenshot, "shape") or getattr(screenshot, "size", 0) == 0:
            raise ValueError("筛选状态截图为空。")
        if len(screenshot.shape) < 2:
            raise ValueError("筛选状态截图维度非法。")
        return screenshot, ""

    def _detect_filter_panel(self, image: Any) -> Tuple[bool, float, float]:
        """通过底部取消/确认按钮颜色判断筛选面板是否打开。"""
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        cancel_roi = self._scale_roi("filter_cancel_button", image_width, image_height)
        confirm_roi = self._scale_roi("filter_confirm_button", image_width, image_height)
        cancel_red = self._red_ratio(self._crop(image, cancel_roi))
        confirm_blue = self._blue_ratio(self._crop(image, confirm_roi))
        score = cancel_red * 0.75 + confirm_blue * 0.25
        opened = cancel_red >= self.FILTER_PANEL_RED_THRESHOLD and confirm_blue >= self.BLUE_VISIBLE_THRESHOLD
        confidence = self._ratio_confidence(cancel_red, self.FILTER_PANEL_RED_THRESHOLD)
        return opened, confidence, score

    def _detect_top_button(self, image: Any, label: str, image_width: int, image_height: int) -> FilterStateElement:
        """识别顶部按钮是否可见，以及筛选按钮是否处于金色激活态。"""
        roi = self._scale_roi(label, image_width, image_height)
        crop = self._crop(image, roi)
        gold = self._gold_ratio(crop)
        blue = self._blue_ratio(crop)
        visible = max(gold, blue) >= self.BLUE_VISIBLE_THRESHOLD
        if label == "filter_button" and gold >= self.FILTER_ACTIVE_THRESHOLD:
            state = "active"
            score = gold
        else:
            state = "visible" if visible else "missing"
            score = max(gold, blue)
        return self._make_element(
            label,
            roi,
            visible,
            visible,
            state,
            self._clamp(0.50 + score * 0.5),
            score,
            "button",
            image_width,
            image_height,
        )

    def _detect_bottom_buttons(
        self,
        image: Any,
        image_width: int,
        image_height: int,
        filter_panel_open: bool,
    ) -> Tuple[FilterStateElement, ...]:
        """识别筛选面板底部取消/确认按钮；面板关闭时按钮视为隐藏。"""
        results: List[FilterStateElement] = []
        for label, ratio_func, expected_state in (
            ("filter_cancel_button", self._red_ratio, "enabled"),
            ("filter_confirm_button", self._blue_ratio, "enabled"),
        ):
            roi = self._scale_roi(label, image_width, image_height)
            score = ratio_func(self._crop(image, roi))
            visible = filter_panel_open and score >= self.BLUE_VISIBLE_THRESHOLD
            state = expected_state if visible else "hidden"
            results.append(
                self._make_element(
                    label,
                    roi,
                    visible,
                    visible,
                    state,
                    self._clamp(0.50 + score * 0.5),
                    score,
                    "button",
                    image_width,
                    image_height,
                )
            )
        return tuple(results)

    def _detect_options(
        self,
        image: Any,
        image_width: int,
        image_height: int,
        filter_panel_open: bool,
    ) -> Tuple[FilterStateOption, ...]:
        """识别筛选面板里类型、索引、阵营、稀有度按钮的可见态和选中态。"""
        groups = (
            ("type", self.TYPE_OPTIONS),
            ("index", self.INDEX_OPTIONS),
            ("camp", self.CAMP_OPTIONS),
            ("rarity", self.RARITY_OPTIONS),
        )
        options: List[FilterStateOption] = []
        for group, definitions in groups:
            for name, text, base_roi in definitions:
                roi = self._scale_base_roi(base_roi, image_width, image_height)
                crop = self._crop(image, roi)
                gold = self._gold_ratio(crop)
                blue = self._blue_ratio(crop)
                visible = filter_panel_open and (gold >= 0.10 or blue >= self.BLUE_VISIBLE_THRESHOLD)
                selected = visible and gold >= self.GOLD_SELECTED_THRESHOLD
                state = "selected" if selected else "unselected" if visible else "hidden"
                score = gold if selected else max(gold, blue)
                options.append(
                    self._make_option(
                        group,
                        name,
                        text,
                        roi,
                        visible,
                        selected,
                        visible,
                        self._clamp(0.50 + score * 0.5),
                        gold,
                        blue,
                        state,
                        base_roi,
                        image_width,
                        image_height,
                    )
                )
        return tuple(options)

    def _selected_name(self, options: Sequence[FilterStateOption], group: str) -> str:
        """从某个选项组中取金色占比最高的已选中项。"""
        candidates = [item for item in options if item.group == group and item.visible]
        if not candidates:
            return "unknown"
        selected = [item for item in candidates if item.selected]
        if not selected:
            return "unknown"
        best = max(selected, key=lambda item: item.gold_ratio)
        return best.name

    def _detect_selected_tab(self, image: Any, image_width: int, image_height: int) -> str:
        """用底部标签金色占比识别设计图/装备/材料页。"""
        scores = {
            "design": self._gold_ratio(self._crop(image, self._scale_roi("tab_design", image_width, image_height))),
            "equipment": self._gold_ratio(self._crop(image, self._scale_roi("tab_equipment", image_width, image_height))),
            "material": self._gold_ratio(self._crop(image, self._scale_roi("tab_material", image_width, image_height))),
        }
        best_label, best_score = max(scores.items(), key=lambda item: item[1])
        return best_label if best_score >= 0.20 else "unknown"

    def _detect_current_sort(self, elements: Sequence[FilterStateElement], warnings: List[str]) -> str:
        """当前训练集固定使用“可建造”排序；无法读文字时给出约束说明。"""
        sort_element = next((item for item in elements if item.label == "rarity_button"), None)
        if sort_element and sort_element.visible:
            warnings.append("当前未做排序按钮文字 OCR：按设计图筛选训练约束返回 current_sort=buildable。")
            return "buildable"
        return "unknown"

    def _infer_closed_rarity(self, image: Any) -> Tuple[str, str, str]:
        """筛选面板关闭时，依据列表卡片底色推断当前稀有度筛选。"""
        card_edge_score = self._card_edge_score(image)
        if card_edge_score < self.EMPTY_LIST_EDGE_THRESHOLD:
            return (
                "unknown",
                "empty_design_list_requires_open_panel",
                "筛选面板关闭且设计图列表为空：新玩家也可能所有设计图为空，必须打开筛选面板才能确认当前稀有度筛选。",
            )

        ratios = self._average_icon_color_ratios(image)
        yellow = ratios["yellow"]
        blue = ratios["blue"]
        purple = ratios["purple"]
        magenta = ratios["magenta"]
        if yellow >= 0.45:
            return "super_rare", "icon_background_color", ""
        if purple >= 0.35:
            return "elite", "icon_background_color", ""
        if blue >= 0.20 and purple >= 0.12 and magenta >= 0.04:
            return "ultra_rare", "icon_background_color", ""
        if blue >= 0.45 and purple < 0.15 and yellow < 0.20:
            return "rare", "icon_background_color", ""
        return (
            "unknown",
            "icon_background_color_low_confidence",
            f"筛选面板关闭后列表底色无法稳定归类: yellow={yellow:.3f}, blue={blue:.3f}, purple={purple:.3f}, magenta={magenta:.3f}。",
        )

    def _card_edge_score(self, image: Any) -> float:
        """用固定卡片区域边缘强度判断列表是否为空。"""
        cv2_module, np_module = self._require_dependencies()
        gray = cv2_module.cvtColor(image, cv2_module.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        edges = cv2_module.Canny(gray, 60, 150)
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        values: List[float] = []
        for base_roi in self.DESIGN_CARD_ROIS:
            roi = self._scale_base_roi(base_roi, image_width, image_height)
            crop = self._crop(edges, roi)
            if getattr(crop, "size", 0):
                values.append(float(crop.mean()))
        return float(np_module.mean(values)) if values else 0.0

    def _average_icon_color_ratios(self, image: Any) -> Dict[str, float]:
        """统计可见装备图标底色，用于关闭态稀有度推断。"""
        np_module = self._require_np()
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        values: List[Dict[str, float]] = []
        for base_roi in self.DESIGN_ICON_ROIS:
            roi = self._scale_base_roi(base_roi, image_width, image_height)
            crop = self._crop(image, roi)
            if getattr(crop, "size", 0):
                values.append(self._rarity_color_ratios(crop))
        if not values:
            return {"yellow": 0.0, "blue": 0.0, "purple": 0.0, "magenta": 0.0}
        return {
            key: float(np_module.mean([item[key] for item in values]))
            for key in ("yellow", "blue", "purple", "magenta")
        }

    def _rarity_color_ratios(self, image: Any) -> Dict[str, float]:
        """计算装备图标背景的黄色/蓝色/紫色/洋红占比。"""
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        masks = {
            "yellow": self._cv2.inRange(hsv, self._np.array([12, 35, 60], dtype=self._np.uint8), self._np.array([45, 255, 255], dtype=self._np.uint8)),
            "blue": self._cv2.inRange(hsv, self._np.array([88, 35, 50], dtype=self._np.uint8), self._np.array([115, 255, 255], dtype=self._np.uint8)),
            "purple": self._cv2.inRange(hsv, self._np.array([120, 25, 40], dtype=self._np.uint8), self._np.array([160, 255, 255], dtype=self._np.uint8)),
            "magenta": self._cv2.inRange(hsv, self._np.array([140, 35, 50], dtype=self._np.uint8), self._np.array([175, 255, 255], dtype=self._np.uint8)),
        }
        return {key: float((mask > 0).mean()) for key, mask in masks.items()}

    def _gold_ratio(self, image: Any) -> float:
        """计算金色按钮底色占比，用于判断选中/激活态。"""
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        mask = self._cv2.inRange(
            hsv,
            self._np.array([10, 35, 55], dtype=self._np.uint8),
            self._np.array([42, 255, 255], dtype=self._np.uint8),
        )
        return float((mask > 0).mean())

    def _blue_ratio(self, image: Any) -> float:
        """计算蓝色按钮底色占比，用于判断按钮是否可见。"""
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        mask = self._cv2.inRange(
            hsv,
            self._np.array([90, 25, 35], dtype=self._np.uint8),
            self._np.array([135, 255, 255], dtype=self._np.uint8),
        )
        return float((mask > 0).mean())

    def _red_ratio(self, image: Any) -> float:
        """计算红色按钮底色占比，用于判断取消按钮。"""
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        low_red = self._cv2.inRange(
            hsv,
            self._np.array([0, 50, 50], dtype=self._np.uint8),
            self._np.array([12, 255, 255], dtype=self._np.uint8),
        )
        high_red = self._cv2.inRange(
            hsv,
            self._np.array([170, 50, 50], dtype=self._np.uint8),
            self._np.array([179, 255, 255], dtype=self._np.uint8),
        )
        mask = self._cv2.bitwise_or(low_red, high_red)
        return float((mask > 0).mean())

    def _scale_roi(self, label: str, image_width: int, image_height: int) -> Box:
        """按当前截图宽度缩放命名 ROI。"""
        if label not in self.ELEMENT_ROIS:
            raise ValueError(f"未知筛选状态 ROI: {label}")
        return self._scale_base_roi(self.ELEMENT_ROIS[label], image_width, image_height)

    def _scale_base_roi(self, roi: Box, image_width: int, image_height: int) -> Box:
        """把 1280x720 基准 ROI 缩放到当前截图；长截图按宽度比例保持 UI 坐标。"""
        base_width, base_height = self.base_resolution
        scale_x = image_width / float(max(1, base_width))
        scale_y = image_height / float(max(1, base_height))
        x, y, width, height = roi
        scaled = (
            int(round(x * scale_x)),
            int(round(y * scale_y)),
            max(1, int(round(width * scale_x))),
            max(1, int(round(height * scale_y))),
        )
        return self._clip_roi(scaled, image_width, image_height)

    def _capture_warning(self, image_width: int, image_height: int) -> str:
        """检查截图是否明显不是完整模拟器视口。"""
        base_width, base_height = self.base_resolution
        width_ratio = image_width / float(max(1, base_width))
        height_ratio = image_height / float(max(1, base_height))
        base_aspect = base_width / float(max(1, base_height))
        image_aspect = image_width / float(max(1, image_height))
        aspect_delta = abs(image_aspect - base_aspect) / float(max(base_aspect, 0.000001))
        if width_ratio < self.MIN_CAPTURE_RATIO or height_ratio < self.MIN_CAPTURE_RATIO:
            return (
                f"截图尺寸疑似不完整: actual={image_width}x{image_height}, "
                f"base={base_width}x{base_height}, width_ratio={width_ratio:.2f}, "
                f"height_ratio={height_ratio:.2f}。"
            )
        if aspect_delta > self.MAX_ASPECT_RATIO_DELTA:
            return (
                f"截图比例疑似不是完整模拟器视口: actual={image_width}x{image_height}, "
                f"base={base_width}x{base_height}, aspect_delta={aspect_delta:.2f}。"
            )
        return ""

    @staticmethod
    def _crop(image: Any, roi: Box) -> Any:
        """裁剪 x/y/w/h 区域。"""
        x, y, width, height = roi
        return image[y:y + height, x:x + width]

    @staticmethod
    def _clip_roi(roi: Box, image_width: int, image_height: int) -> Box:
        """把 ROI 裁剪到图片范围内，避免越界。"""
        x, y, width, height = roi
        x0 = min(max(0, int(x)), max(0, image_width - 1))
        y0 = min(max(0, int(y)), max(0, image_height - 1))
        x1 = min(max(0, int(x + width)), image_width)
        y1 = min(max(0, int(y + height)), image_height)
        return x0, y0, max(1, x1 - x0), max(1, y1 - y0)

    @staticmethod
    def _ratio_confidence(ratio: float, threshold: float) -> float:
        """把颜色占比和阈值距离转换为 0~1 置信度。"""
        return FilterStateDetector._clamp(0.55 + min(0.4, abs(float(ratio) - float(threshold)) * 1.15))

    @staticmethod
    def _element_color(element: FilterStateElement) -> Tuple[int, int, int]:
        """根据元素状态选择 OpenCV BGR 画框颜色。"""
        if element.label == "filter_panel" and element.visible:
            return 0, 0, 255
        if element.state == "active":
            return 0, 215, 255
        if element.visible:
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

    def _require_np(self) -> Any:
        """获取 NumPy 模块，不可用时抛出友好错误。"""
        if self._np is None:
            raise RuntimeError("NumPy 不可用。")
        return self._np


# ============================================================
# 🌐 第四部分：全局访问函数
# ============================================================

_filter_state_detector_instance: Optional[FilterStateDetector] = None


def get_filter_state_detector() -> FilterStateDetector:
    """
    获取筛选状态识别器单例。
    输入：
        无。
    输出：
        FilterStateDetector。
    使用示例：
        detector = get_filter_state_detector()
    """
    global _filter_state_detector_instance
    if _filter_state_detector_instance is None:
        _filter_state_detector_instance = FilterStateDetector()
    return _filter_state_detector_instance
