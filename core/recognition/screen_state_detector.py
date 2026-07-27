#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧭 登录与港区状态识别器 (screen_state_detector.py)  ║
║                                                              ║
║  【一句话解释】只看 ADB 截图，判断登录页、加载页、港区或未知。║
║  【类比理解】它像门卫，先确认你站在哪个房间门口，再让 OCR 进门。║
║  【数据流说明】绝对截图路径 → OpenCV 颜色/形状特征 → screen_state。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.contracts import RecognitionScene, TaskExecutionContext
from core.recognition.ocr_engine import OcrEngine, OcrReadResult
from core.utils.path_manager import PathManager

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - OpenCV 缺失时模块仍可导入
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - numpy 缺失时模块仍可导入
    _np = None


# ============================================================
# 🧱 第二部分：基础数据结构
# ============================================================

Box = Tuple[int, int, int, int]


@dataclass(frozen=True)
class ScreenStateDetection:
    """
    单个状态特征命中结果。
    输入：
        label/state/roi/confidence/value/detail。
    输出：
        payload 中可展示的 UI 特征，不写入任何用户数据。
    使用示例：
        detection = ScreenStateDetection("harbor_bottom_nav", "harbor", (0, 0, 10, 10), 0.8)
    """

    label: str
    state: str
    roi: Box
    confidence: float
    value: int = 1
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 友好的基础字典。"""
        return {
            "label": self.label,
            "state": self.state,
            "roi": [int(item) for item in self.roi],
            "confidence": max(0.0, min(1.0, float(self.confidence))),
            "value": int(self.value),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ScreenStateResult:
    """
    一张截图的页面状态识别结果。
    输入：
        success/status/screen_state/scene/confidence/detections。
    输出：
        ADB state_probe 和 OCR run_ocr_task 都能直接消费的状态对象。
    使用示例：
        result = ScreenStateDetector().detect("G:/shot.png")
    """

    success: bool
    status: str
    message: str
    screen_state: str
    scene: RecognitionScene
    confidence: float
    detections: Tuple[ScreenStateDetection, ...] = ()
    warnings: Tuple[str, ...] = ()
    screenshot_path: str = ""
    detail: str = ""
    suggested_action: str = ""
    ui_version: str = "unknown"
    features: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为 OCR/ADB payload 可直接复用的结构。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "screen_state": self.screen_state,
            "scene": self.scene.value,
            "confidence": max(0.0, min(1.0, float(self.confidence))),
            "detections": [item.to_dict() for item in self.detections],
            "warnings": list(self.warnings),
            "screenshot_path": self.screenshot_path,
            "detail": self.detail,
            "suggested_action": self.suggested_action,
            "ui_version": self.ui_version,
            "features": {str(key): float(value) for key, value in self.features.items()},
        }


# ============================================================
# 🏗️ 第三部分：状态识别器
# ============================================================

class ScreenStateDetector:
    """
    登录/加载/港区主界面状态识别器。
    输入：
        config/ocr_engine/cv2_module 注入项。
    输出：
        ScreenStateResult；不执行点击、滑动、等待或数据写入。
    使用示例：
        state = ScreenStateDetector().detect("G:/adb/frame.png")
    """

    BASE_RESOLUTION: Box = (0, 0, 1280, 720)
    DEFAULT_CONFIG_PATH = PathManager.get_config_dir() / "recognition" / "roi_config.json"

    HARBOR_NEW_MARKER_ROI: Box = (1008, 18, 255, 38)
    HARBOR_TOP_RESOURCE_ROI: Box = (470, 0, 540, 75)
    HARBOR_BOTTOM_NAV_ROI: Box = (10, 640, 1260, 78)
    HARBOR_WAREHOUSE_ROI: Box = (324, 646, 156, 62)
    HARBOR_TOP_LEFT_PROFILE_ROI: Box = (0, 0, 340, 96)

    LOGIN_START_BUTTON_ROI: Box = (390, 500, 500, 155)
    LOGIN_NOTICE_CLOSE_ROI: Box = (1060, 18, 180, 110)
    LOADING_BOTTOM_ROI: Box = (230, 625, 820, 85)
    LOADING_CENTER_ROI: Box = (390, 285, 500, 150)

    TEXT_KEYWORDS: Mapping[str, Tuple[str, ...]] = {
        "login": ("开始", "登录", "start", "touch", "tap", "游客", "账号"),
        "loading": ("loading", "tips", "tip", "加载", "读取", "正在"),
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        ocr_engine: Optional[OcrEngine] = None,
        cv2_module: Optional[Any] = None,
        np_module: Optional[Any] = None,
    ) -> None:
        """初始化状态识别器；默认不会加载 PaddleOCR 模型。"""
        self.config = config if config is not None else self._load_default_config()
        self.state_config = self._state_config(self.config)
        ocr_config = self.config.get("ocr", {}) if isinstance(self.config.get("ocr", {}), dict) else {}
        self.ocr_engine = ocr_engine or OcrEngine(config=ocr_config)
        self._cv2 = _cv2 if cv2_module is None else cv2_module
        self._np = _np if np_module is None else np_module

    def detect(
        self,
        screenshot: str | Path | Any,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> ScreenStateResult:
        """
        识别截图所在页面状态。
        输入：
            screenshot: ADB 输出的绝对截图路径，或测试注入的 OpenCV 图像。
            task_context: 可选取消上下文。
        输出：
            ScreenStateResult，screen_state 只会是 login/loading/harbor/unknown。
        使用示例：
            result = detector.detect("G:/runs/frame_0001.png")
        """
        self._safe_cancel(task_context, "页面状态识别已取消。")
        try:
            image, screenshot_path = self._coerce_image(screenshot)
        except FileNotFoundError as exc:
            return self._failure("error", "截图文件不存在，无法判断页面状态。", str(exc), str(screenshot))
        except ValueError as exc:
            return self._failure("error", "截图无法读取或已损坏。", str(exc), str(screenshot))
        except RuntimeError as exc:
            return self._failure("unavailable", "OpenCV(cv2) 不可用，无法判断页面状态。", str(exc), str(screenshot))

        self._safe_cancel(task_context, "页面状态识别已取消。")
        capture_warning = self._capture_warning(image)
        if capture_warning:
            return ScreenStateResult(
                True,
                "unknown",
                "截图疑似不完整，已返回 unknown，避免误判页面。",
                "unknown",
                RecognitionScene.UNKNOWN,
                0.0,
                warnings=(capture_warning,),
                screenshot_path=screenshot_path,
                detail=capture_warning,
            )

        warnings: List[str] = []
        harbor_score, harbor_hits, harbor_features, ui_version = self._score_harbor(image)
        self._safe_cancel(task_context, "页面状态识别已取消。")
        login_score, login_hits, login_features = self._score_login(image)
        self._safe_cancel(task_context, "页面状态识别已取消。")
        loading_score, loading_hits, loading_features = self._score_loading(image)

        text_scores = self._score_text_keywords(image, task_context, warnings)
        login_score = min(1.0, login_score + text_scores.get("login", 0.0))
        loading_score = min(1.0, loading_score + text_scores.get("loading", 0.0))

        scores = {
            "harbor": float(harbor_score),
            "login": float(login_score),
            "loading": float(loading_score),
        }
        threshold = float(self.state_config.get("confidence_threshold", 0.58))
        margin = float(self.state_config.get("ambiguous_margin", 0.06))
        state = max(scores, key=scores.get)
        confidence = scores[state]
        ordered = sorted(scores.values(), reverse=True)
        second = ordered[1] if len(ordered) > 1 else 0.0

        if confidence < threshold or confidence - second < margin:
            detail = f"scores={self._format_scores(scores)}; threshold={threshold:.2f}; margin={margin:.2f}"
            return ScreenStateResult(
                True,
                "unknown",
                "未能稳定判断当前页面，已保守返回 unknown。",
                "unknown",
                RecognitionScene.UNKNOWN,
                confidence,
                warnings=tuple(warnings),
                screenshot_path=screenshot_path,
                detail=detail,
                features={**harbor_features, **login_features, **loading_features, **scores},
            )

        if state == "harbor":
            return ScreenStateResult(
                True,
                "success",
                "当前截图识别为港区主界面。",
                "harbor",
                RecognitionScene.HARBOR,
                confidence,
                detections=tuple(harbor_hits),
                warnings=tuple(warnings),
                screenshot_path=screenshot_path,
                detail=f"scores={self._format_scores(scores)}",
                ui_version=ui_version,
                features={**harbor_features, **scores},
            )

        detections = tuple(login_hits if state == "login" else loading_hits)
        message = "当前截图识别为登录页。" if state == "login" else "当前截图识别为加载页。"
        suggestion = "建议由 ADB/Integration 层根据策略点击登录或关闭公告。" if state == "login" else "建议由 ADB/Integration 层继续等待下一帧。"
        return ScreenStateResult(
            True,
            "success",
            message,
            state,
            RecognitionScene.UNKNOWN,
            confidence,
            detections=detections,
            warnings=tuple(warnings),
            screenshot_path=screenshot_path,
            detail=f"scores={self._format_scores(scores)}",
            suggested_action=suggestion,
            features={**login_features, **loading_features, **scores},
        )

    def _score_harbor(self, image: Any) -> Tuple[float, List[ScreenStateDetection], Dict[str, float], str]:
        """计算港区主界面得分，兼容新旧主页 UI。"""
        hits: List[ScreenStateDetection] = []
        features: Dict[str, float] = {}
        score = 0.0

        marker_roi, marker = self._crop(image, self.HARBOR_NEW_MARKER_ROI)
        marker_white = self._white_ratio(marker)
        features["harbor_marker_white_ratio"] = marker_white
        if marker_white >= 0.42:
            confidence = min(1.0, marker_white / 0.78)
            score += 0.34 * confidence
            hits.append(ScreenStateDetection("harbor_new_ui_marker", "harbor", marker_roi, confidence, detail="右上角白色功能栏"))

        resource_roi, resource = self._crop(image, self.HARBOR_TOP_RESOURCE_ROI)
        resource_bright = self._bright_ratio(resource, 185)
        resource_warm = self._color_ratio(resource, "warm")
        resource_edge = self._edge_density(resource)
        features["harbor_resource_bright_ratio"] = resource_bright
        features["harbor_resource_warm_ratio"] = resource_warm
        features["harbor_resource_edge_density"] = resource_edge
        if resource_bright >= 0.08 or resource_warm >= 0.22:
            confidence = min(1.0, max(resource_bright / 0.16, resource_warm / 0.55, resource_edge / 0.14))
            score += 0.22 * confidence
            hits.append(ScreenStateDetection("harbor_resource_bar", "harbor", resource_roi, confidence, detail="顶部资源栏"))

        bottom_roi, bottom = self._crop(image, self.HARBOR_BOTTOM_NAV_ROI)
        bottom_white = self._white_ratio(bottom)
        bottom_blue = self._color_ratio(bottom, "blue")
        bottom_warm = self._color_ratio(bottom, "warm")
        features["harbor_bottom_white_ratio"] = bottom_white
        features["harbor_bottom_blue_ratio"] = bottom_blue
        features["harbor_bottom_warm_ratio"] = bottom_warm
        if bottom_white >= 0.32 or bottom_blue >= 0.12 or bottom_warm >= 0.16:
            confidence = min(1.0, max(bottom_white / 0.56, bottom_blue / 0.27, bottom_warm / 0.33))
            score += 0.24 * confidence
            hits.append(ScreenStateDetection("harbor_bottom_navigation", "harbor", bottom_roi, confidence, detail="底部主界面导航栏"))

        warehouse_roi, warehouse = self._crop(image, self.HARBOR_WAREHOUSE_ROI)
        warehouse_white = self._white_ratio(warehouse)
        warehouse_blue = self._color_ratio(warehouse, "blue")
        warehouse_warm = self._color_ratio(warehouse, "warm")
        features["harbor_warehouse_white_ratio"] = warehouse_white
        features["harbor_warehouse_blue_ratio"] = warehouse_blue
        features["harbor_warehouse_warm_ratio"] = warehouse_warm
        if warehouse_white >= 0.30 or warehouse_blue >= 0.10 or warehouse_warm >= 0.08:
            confidence = min(1.0, max(warehouse_white / 0.70, warehouse_blue / 0.39, warehouse_warm / 0.20))
            score += 0.14 * confidence
            hits.append(ScreenStateDetection("harbor_warehouse_entry", "harbor", warehouse_roi, confidence, detail="仓库入口按钮区域"))

        profile_roi, profile = self._crop(image, self.HARBOR_TOP_LEFT_PROFILE_ROI)
        profile_edge = self._edge_density(profile)
        profile_bright = self._bright_ratio(profile, 170)
        features["harbor_profile_edge_density"] = profile_edge
        features["harbor_profile_bright_ratio"] = profile_bright
        if profile_edge >= 0.05 and profile_bright >= 0.04:
            confidence = min(1.0, max(profile_edge / 0.11, profile_bright / 0.12))
            score += 0.10 * confidence
            hits.append(ScreenStateDetection("harbor_profile_panel", "harbor", profile_roi, confidence, detail="左上角头像/名称面板"))

        ui_version = "new" if marker_white >= 0.42 else ("old" if score >= 0.50 else "unknown")
        return min(1.0, score), hits, features, ui_version

    def _score_login(self, image: Any) -> Tuple[float, List[ScreenStateDetection], Dict[str, float]]:
        """计算登录页得分；只在特征足够明显时命中。"""
        hits: List[ScreenStateDetection] = []
        features: Dict[str, float] = {}
        score = 0.0

        start_roi, start = self._crop(image, self.LOGIN_START_BUTTON_ROI)
        start_blue = self._color_ratio(start, "blue")
        start_warm = self._color_ratio(start, "warm")
        start_white = self._white_ratio(start)
        start_bright = self._bright_ratio(start, 185)
        features["login_start_blue_ratio"] = start_blue
        features["login_start_warm_ratio"] = start_warm
        features["login_start_white_ratio"] = start_white
        features["login_start_bright_ratio"] = start_bright
        if (start_blue >= 0.18 or start_white >= 0.20) and start_warm <= 0.62:
            confidence = min(1.0, max(start_blue / 0.30, start_white / 0.36, start_bright / 0.42))
            score += 0.48 * confidence
            hits.append(ScreenStateDetection("login_start_button_candidate", "login", start_roi, confidence, detail="中央/底部开始或登录按钮候选"))

        close_roi, close = self._crop(image, self.LOGIN_NOTICE_CLOSE_ROI)
        close_white = self._white_ratio(close)
        close_edge = self._edge_density(close)
        features["login_notice_close_white_ratio"] = close_white
        features["login_notice_close_edge_density"] = close_edge
        if close_white >= 0.12 and close_edge >= 0.03:
            confidence = min(1.0, max(close_white / 0.30, close_edge / 0.10))
            score += 0.18 * confidence
            hits.append(ScreenStateDetection("login_notice_close_candidate", "login", close_roi, confidence, detail="公告/登录弹窗关闭按钮候选"))

        full_brightness = self._image_mean_brightness(image)
        features["login_full_mean_brightness"] = full_brightness
        if 55.0 <= full_brightness <= 190.0:
            score += 0.08

        return min(1.0, score), hits, features

    def _score_loading(self, image: Any) -> Tuple[float, List[ScreenStateDetection], Dict[str, float]]:
        """计算加载页得分；等待行为由 ADB/Integration 层决定。"""
        hits: List[ScreenStateDetection] = []
        features: Dict[str, float] = {}
        score = 0.0

        bottom_roi, bottom = self._crop(image, self.LOADING_BOTTOM_ROI)
        bottom_bright = self._bright_ratio(bottom, 180)
        bottom_blue = self._color_ratio(bottom, "blue")
        bottom_edge = self._edge_density(bottom)
        features["loading_bottom_bright_ratio"] = bottom_bright
        features["loading_bottom_blue_ratio"] = bottom_blue
        features["loading_bottom_edge_density"] = bottom_edge
        if bottom_bright >= 0.10 or bottom_blue >= 0.10:
            confidence = min(1.0, max(bottom_bright / 0.35, bottom_blue / 0.24, bottom_edge / 0.12))
            score += 0.36 * confidence
            hits.append(ScreenStateDetection("loading_bottom_progress_candidate", "loading", bottom_roi, confidence, detail="底部 loading/tips/进度条候选"))

        center_roi, center = self._crop(image, self.LOADING_CENTER_ROI)
        center_dark = self._dark_ratio(center)
        center_edge = self._edge_density(center)
        features["loading_center_dark_ratio"] = center_dark
        features["loading_center_edge_density"] = center_edge
        if center_dark >= 0.45 and center_edge <= 0.08:
            confidence = min(1.0, center_dark / 0.70)
            score += 0.16 * confidence
            hits.append(ScreenStateDetection("loading_dark_center_candidate", "loading", center_roi, confidence, detail="加载页暗色中心区域候选"))

        full_brightness = self._image_mean_brightness(image)
        features["loading_full_mean_brightness"] = full_brightness
        if full_brightness <= 105.0:
            score += 0.10

        return min(1.0, score), hits, features

    def _score_text_keywords(
        self,
        image: Any,
        task_context: Optional[TaskExecutionContext],
        warnings: List[str],
    ) -> Dict[str, float]:
        """可选 OCR 文本探针；默认关闭以避免状态识别变慢。"""
        if not bool(self.state_config.get("ocr_text_probe_enabled", False)):
            return {}

        text_rois = {
            "login": self.LOGIN_START_BUTTON_ROI,
            "loading": self.LOADING_BOTTOM_ROI,
        }
        scores: Dict[str, float] = {}
        for state, raw_roi in text_rois.items():
            self._safe_cancel(task_context, "页面状态文本探针已取消。")
            roi, _ = self._crop(image, raw_roi)
            result = self.ocr_engine.recognize_text(
                image,
                roi=roi,
                confidence_threshold=float(self.state_config.get("ocr_text_confidence_threshold", 0.55)),
                preprocess=False,
            )
            if result.success and self._text_has_keyword(state, result.text):
                scores[state] = max(scores.get(state, 0.0), min(0.28, result.confidence * 0.28))
                continue
            if result.status == "unavailable":
                warnings.append(f"{state}: 文本探针不可用：{result.message}")
        return scores

    def _coerce_image(self, screenshot: str | Path | Any) -> Tuple[Any, str]:
        """读取路径截图或接收测试注入的图像对象。"""
        if self._cv2 is None:
            raise RuntimeError("OpenCV(cv2) 不可用。")
        if isinstance(screenshot, (str, Path)):
            path = Path(screenshot)
            if not path.is_file():
                raise FileNotFoundError(f"截图文件不存在: {path}")
            image = self._cv2.imread(str(path), self._cv2.IMREAD_COLOR)
            if image is None or getattr(image, "size", 0) == 0:
                raise ValueError(f"截图无法读取或已损坏: {path}")
            return image, str(path)
        if screenshot is None or not hasattr(screenshot, "shape") or getattr(screenshot, "size", 0) == 0:
            raise ValueError("截图图像为空。")
        return screenshot, ""

    def _capture_warning(self, image: Any) -> str:
        """拒绝半截图或宽高比明显不对的截图。"""
        height, width = int(image.shape[0]), int(image.shape[1])
        base_width, base_height = self._base_resolution()
        validation = self._capture_validation()
        if bool(validation.get("allow_partial_image", False)):
            return ""
        min_width_ratio = float(validation.get("min_width_ratio", 0.85))
        min_height_ratio = float(validation.get("min_height_ratio", 0.85))
        max_aspect_delta = float(validation.get("max_aspect_delta", 0.12))
        width_ratio = width / float(max(1, base_width))
        height_ratio = height / float(max(1, base_height))
        expected_aspect = base_width / float(max(1, base_height))
        actual_aspect = width / float(max(1, height))
        aspect_delta = abs(actual_aspect - expected_aspect) / float(max(expected_aspect, 1e-6))
        if width_ratio < min_width_ratio or height_ratio < min_height_ratio:
            return f"截图尺寸疑似不完整: actual={width}x{height}, expected={base_width}x{base_height}。"
        if aspect_delta > max_aspect_delta:
            return f"截图宽高比异常: actual={width}x{height}, expected={base_width}x{base_height}。"
        return ""

    def _crop(self, image: Any, roi: Sequence[int]) -> Tuple[Box, Any]:
        """按 1280x720 基准缩放并裁剪 ROI。"""
        scaled = self._scale_roi(roi, int(image.shape[1]), int(image.shape[0]))
        x, y, width, height = scaled
        return scaled, image[y:y + height, x:x + width]

    def _scale_roi(self, roi: Sequence[int], image_width: int, image_height: int) -> Box:
        """把配置 ROI 缩放到当前截图尺寸。"""
        x, y, width, height = (int(item) for item in roi)
        base_width, base_height = self._base_resolution()
        scaled = (
            int(round(x * image_width / float(base_width))),
            int(round(y * image_height / float(base_height))),
            max(1, int(round(width * image_width / float(base_width)))),
            max(1, int(round(height * image_height / float(base_height)))),
        )
        sx, sy, sw, sh = scaled
        safe_x = max(0, min(sx, image_width - 1))
        safe_y = max(0, min(sy, image_height - 1))
        safe_w = max(1, min(sw, image_width - safe_x))
        safe_h = max(1, min(sh, image_height - safe_y))
        return safe_x, safe_y, safe_w, safe_h

    def _base_resolution(self) -> Tuple[int, int]:
        """读取基准分辨率，默认 1280x720。"""
        value = self.config.get("base_resolution", {})
        if isinstance(value, dict):
            return int(value.get("width", 1280)), int(value.get("height", 720))
        return 1280, 720

    def _capture_validation(self) -> Dict[str, Any]:
        """读取截图完整性校验配置。"""
        config = self.config.get("capture_validation", {})
        return config if isinstance(config, dict) else {}

    def _bright_ratio(self, image: Any, threshold: int) -> float:
        """计算 ROI 中亮像素比例。"""
        gray = self._gray(image)
        return float((gray >= int(threshold)).mean())

    def _dark_ratio(self, image: Any, threshold: int = 70) -> float:
        """计算 ROI 中暗像素比例。"""
        gray = self._gray(image)
        return float((gray <= int(threshold)).mean())

    def _white_ratio(self, image: Any) -> float:
        """计算近白色 UI 像素比例。"""
        if image is None or not hasattr(image, "shape") or len(image.shape) < 3:
            return 0.0
        blue = image[:, :, 0]
        green = image[:, :, 1]
        red = image[:, :, 2]
        return float(((blue >= 200) & (green >= 200) & (red >= 200)).mean())

    def _color_ratio(self, image: Any, color: str) -> float:
        """用 HSV 粗略统计按钮/资源 UI 的颜色比例。"""
        if self._cv2 is None or image is None or not hasattr(image, "shape") or len(image.shape) < 3:
            return 0.0
        hsv = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0]
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        if color == "blue":
            mask = (hue >= 88) & (hue <= 118) & (saturation >= 40) & (value >= 75)
        elif color == "warm":
            mask = ((hue <= 35) | (hue >= 165)) & (saturation >= 50) & (value >= 90)
        else:
            mask = value >= 180
        return float(mask.mean())

    def _edge_density(self, image: Any) -> float:
        """计算边缘密度，用于辅助判断 UI 面板和按钮。"""
        if self._cv2 is None:
            return 0.0
        gray = self._gray(image)
        edges = self._cv2.Canny(gray, 50, 150)
        return float((edges > 0).mean())

    def _gray(self, image: Any) -> Any:
        """把 OpenCV BGR 图像转换成灰度图。"""
        if self._cv2 is None:
            raise RuntimeError("OpenCV(cv2) 不可用。")
        if image is None or not hasattr(image, "shape"):
            raise ValueError("图像为空。")
        if len(image.shape) == 2:
            return image
        return self._cv2.cvtColor(image, self._cv2.COLOR_BGR2GRAY)

    def _image_mean_brightness(self, image: Any) -> float:
        """计算整图平均亮度。"""
        return float(self._gray(image).mean())

    @classmethod
    def _text_has_keyword(cls, state: str, text: str) -> bool:
        """判断 OCR 文本是否包含该状态的关键词。"""
        normalized = str(text).strip().lower()
        return any(keyword.lower() in normalized for keyword in cls.TEXT_KEYWORDS.get(state, ()))

    @staticmethod
    def _format_scores(scores: Mapping[str, float]) -> str:
        """把状态得分压缩成 detail 文本。"""
        return ", ".join(f"{key}={value:.3f}" for key, value in sorted(scores.items()))

    @staticmethod
    def _safe_cancel(task_context: Optional[TaskExecutionContext], message: str) -> None:
        """在每个识别阶段检查取消请求。"""
        if task_context is not None:
            task_context.raise_if_cancelled(message)

    @staticmethod
    def _state_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """读取 screen_state_detection 配置段。"""
        state_config = config.get("screen_state_detection", {})
        return state_config if isinstance(state_config, dict) else {}

    @classmethod
    def _load_default_config(cls) -> Dict[str, Any]:
        """只读加载 ROI 配置，失败时返回最小配置。"""
        try:
            with open(cls.DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as file:
                data = __import__("json").load(file)
        except Exception:
            return {
                "schema_version": "0.6.0",
                "base_resolution": {"width": 1280, "height": 720},
                "capture_validation": {
                    "allow_partial_image": False,
                    "min_width_ratio": 0.85,
                    "min_height_ratio": 0.85,
                    "max_aspect_delta": 0.12,
                },
                "screen_state_detection": {
                    "enabled": True,
                    "confidence_threshold": 0.58,
                    "ambiguous_margin": 0.06,
                    "ocr_text_probe_enabled": False,
                },
            }
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _failure(status: str, message: str, detail: str, screenshot_path: str = "") -> ScreenStateResult:
        """构造失败状态结果，scene 固定为 unknown。"""
        return ScreenStateResult(
            False,
            status,
            message,
            "unknown",
            RecognitionScene.UNKNOWN,
            0.0,
            warnings=(detail,),
            screenshot_path=screenshot_path,
            detail=detail,
        )


# ============================================================
# 🌐 第四部分：全局访问函数
# ============================================================

_screen_state_detector_instance: Optional[ScreenStateDetector] = None


def get_screen_state_detector() -> ScreenStateDetector:
    """
    获取全局页面状态识别器。
    输入：
        无。
    输出：
        ScreenStateDetector 单例。
    使用示例：
        detector = get_screen_state_detector()
    """
    global _screen_state_detector_instance
    if _screen_state_detector_instance is None:
        _screen_state_detector_instance = ScreenStateDetector()
    return _screen_state_detector_instance
