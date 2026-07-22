#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════╗
║                 港区主页资源识别器                         ║
║  区分新旧主页 UI，裁剪用户名、石油、物资和钻石固定区域    ║
║  只返回识别结果，不负责定时调度，也不写入用户数据          ║
╚════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 第一部分：导入依赖与基础类型
# ============================================================

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .ocr_engine import OcrEngine, OcrReadResult
from core.utils.path_manager import PathManager

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - 可选依赖缺失时允许模块导入
    _cv2 = None


Box = Tuple[int, int, int, int]


@dataclass(frozen=True)
class HarborResourceResult:
    """一次港区资源识别的完整结果。"""

    success: bool
    status: str
    message: str
    ui_version: str
    player_name: str
    oil: Optional[int]
    coins: Optional[int]
    gems: Optional[int]
    confidence: float
    fields: Mapping[str, OcrReadResult]
    rois: Mapping[str, Box]
    warnings: Tuple[str, ...] = ()
    screenshot_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为 JSON 可序列化字典，字段与资源识别契约保持一致。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "ui_version": self.ui_version,
            "player_name": self.player_name,
            "oil": self.oil,
            "coins": self.coins,
            "gems": self.gems,
            "confidence": float(self.confidence),
            "fields": {name: value.to_dict() for name, value in self.fields.items()},
            "rois": {name: list(value) for name, value in self.rois.items()},
            "warnings": list(self.warnings),
            "screenshot_path": self.screenshot_path,
        }


# ============================================================
# 第二部分：港区资源识别器
# ============================================================


class HarborResourceDetector:
    """针对 1280x720 港区主页新旧 UI 的固定区域 OCR 识别器。"""

    BASE_RESOLUTION = (1280, 720)
    DEFAULT_ROIS: Mapping[str, Mapping[str, Box]] = {
        "new": {
            "player_name": (88, 15, 155, 38),
            "oil": (555, 16, 55, 42),
            "coins": (708, 16, 76, 42),
            "gems": (907, 16, 56, 42),
        },
        "old": {
            "player_name": (109, 9, 190, 40),
            "oil": (635, 8, 100, 50),
            "coins": (830, 8, 115, 50),
            "gems": (1057, 8, 91, 50),
        },
    }
    FALLBACK_ROIS: Mapping[str, Mapping[str, Box]] = {
        "new": {
            "oil": (545, 16, 70, 42),
            "coins": (685, 8, 110, 54),
        }
    }
    NEW_UI_MARKER_ROI: Box = (1008, 18, 255, 38)

    def __init__(
        self,
        ocr_engine: Optional[OcrEngine] = None,
        rois: Optional[Mapping[str, Mapping[str, Sequence[int]]]] = None,
        cv2_module: Optional[Any] = None,
    ) -> None:
        """注入 OCR 后端可用于离线测试，构造过程不会加载模型。"""
        self.ocr_config = self._default_ocr_config()
        self.ocr_engine = ocr_engine or OcrEngine(config=self.ocr_config)
        self._fallback_ocr_engine: Optional[OcrEngine] = None
        self._fallback_enabled = ocr_engine is None
        self._cv2 = _cv2 if cv2_module is None else cv2_module
        source = rois or self.DEFAULT_ROIS
        self.rois = {
            version: {name: tuple(int(item) for item in box) for name, box in items.items()}
            for version, items in source.items()
        }

    def detect(self, screenshot: str | Path | Any, ui_version: Optional[str] = None) -> HarborResourceResult:
        """识别一张完整港区主页截图中的四个资源字段。"""
        try:
            image, screenshot_path = self._coerce_image(screenshot)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            return self._failure("error", str(exc))

        height, width = int(image.shape[0]), int(image.shape[1])
        warning = self._capture_warning(width, height)
        if warning:
            return self._failure("partial_image", warning, screenshot_path=screenshot_path)

        version = ui_version or self.detect_ui_version(image)
        if version not in self.rois:
            return self._failure("unknown_ui", f"无法确定港区主页 UI 版本: {version}", screenshot_path=screenshot_path)
        scaled_rois = {
            name: self._scale_roi(box, width, height)
            for name, box in self.rois[version].items()
        }

        fields: Dict[str, OcrReadResult] = {
            "player_name": self.ocr_engine.recognize_text(image, scaled_rois["player_name"], preprocess=False),
            "oil": self._recognize_resource_digits(image, version, "oil", scaled_rois["oil"]),
            "coins": self._recognize_resource_digits(image, version, "coins", scaled_rois["coins"]),
            "gems": self._recognize_resource_digits(image, version, "gems", scaled_rois["gems"]),
        }
        warnings = tuple(
            f"{name}: {result.message}" for name, result in fields.items() if not result.success
        )
        successful = [result for result in fields.values() if result.success]
        confidence = sum(item.confidence for item in successful) / len(successful) if successful else 0.0
        complete = len(successful) == 4
        unavailable = any(item.status == "unavailable" for item in fields.values())
        status = "success" if complete else ("unavailable" if unavailable else "partial")
        message = "港区资源识别完成。" if complete else "港区资源未能全部识别。"
        return HarborResourceResult(
            complete,
            status,
            message,
            version,
            fields["player_name"].text if fields["player_name"].success else "",
            fields["oil"].value,
            fields["coins"].value,
            fields["gems"].value,
            confidence,
            fields,
            scaled_rois,
            warnings,
            screenshot_path,
        )

    def detect_ui_version(self, image: Any) -> str:
        """通过新 UI 右上角白色功能栏判断主页版本。"""
        if self._cv2 is None:
            return "unknown"
        height, width = int(image.shape[0]), int(image.shape[1])
        roi = self._scale_roi(self.NEW_UI_MARKER_ROI, width, height)
        x, y, box_width, box_height = roi
        gray = self._cv2.cvtColor(image[y:y + box_height, x:x + box_width], self._cv2.COLOR_BGR2GRAY)
        bright_ratio = float((gray >= 185).mean())
        return "new" if bright_ratio >= 0.38 else "old"

    def draw_annotations(self, image: Any, result: HarborResourceResult) -> Any:
        """在原图上画出字段 ROI 和当前识别值，供人工复核。"""
        if self._cv2 is None:
            raise RuntimeError("OpenCV(cv2) 不可用，无法绘制标注。")
        annotated = image.copy()
        for name, roi in result.rois.items():
            x, y, width, height = roi
            field = result.fields.get(name)
            color = (50, 210, 50) if field and field.success else (0, 165, 255)
            value = field.text if field and field.success else (field.status if field else "missing")
            self._cv2.rectangle(annotated, (x, y), (x + width, y + height), color, 2)
            self._cv2.putText(annotated, f"{name}={value}"[:48], (x, y + height + 18), self._cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, self._cv2.LINE_AA)
        self._cv2.putText(annotated, f"harbor ui={result.ui_version} status={result.status}", (20, 90), self._cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, self._cv2.LINE_AA)
        return annotated

    def load_image(self, path: str | Path) -> Any:
        """读取图片；路径损坏时给出友好错误。"""
        if self._cv2 is None:
            raise RuntimeError("OpenCV(cv2) 不可用。")
        image_path = Path(path)
        if not image_path.is_file():
            raise FileNotFoundError(f"截图文件不存在: {image_path}")
        image = self._cv2.imread(str(image_path), self._cv2.IMREAD_COLOR)
        if image is None or getattr(image, "size", 0) == 0:
            raise ValueError(f"截图无法读取或已损坏: {image_path}")
        return image

    def _coerce_image(self, screenshot: str | Path | Any) -> Tuple[Any, str]:
        """把截图路径和已加载图像统一为 OpenCV 图像。"""
        if isinstance(screenshot, (str, Path)):
            return self.load_image(screenshot), str(screenshot)
        if screenshot is None or not hasattr(screenshot, "shape") or getattr(screenshot, "size", 0) == 0:
            raise ValueError("截图图像为空。")
        return screenshot, ""

    def _capture_warning(self, width: int, height: int) -> str:
        """拒绝裁掉一半或宽高比异常的模拟器截图。"""
        base_width, base_height = self.BASE_RESOLUTION
        if width < int(base_width * 0.85) or height < int(base_height * 0.85):
            return f"截图疑似不完整: actual={width}x{height}, expected={base_width}x{base_height}。"
        expected_aspect = base_width / base_height
        if abs(width / height - expected_aspect) / expected_aspect > 0.08:
            return f"截图宽高比异常: actual={width}x{height}, expected={base_width}x{base_height}。"
        return ""

    def _scale_roi(self, roi: Sequence[int], width: int, height: int) -> Box:
        """按完整截图分辨率缩放 1280x720 基准 ROI。"""
        x, y, box_width, box_height = (int(item) for item in roi)
        base_width, base_height = self.BASE_RESOLUTION
        return (
            int(round(x * width / base_width)),
            int(round(y * height / base_height)),
            max(1, int(round(box_width * width / base_width))),
            max(1, int(round(box_height * height / base_height))),
        )

    def _recognize_resource_digits(self, image: Any, ui_version: str, field: str, roi: Box) -> OcrReadResult:
        """识别港区资源数字；必要时对新 UI 物资启用高精度 fallback。"""
        primary = self.ocr_engine.recognize_digits(image, roi, preprocess=False)
        if field == "oil" and ui_version == "new":
            if not self._fallback_enabled:
                return primary
            if primary.success and primary.value is not None and primary.value >= 1000:
                return primary
            fallback_roi = self.FALLBACK_ROIS.get(ui_version, {}).get(field)
            if fallback_roi is None:
                return primary
            scaled_fallback_roi = self._scale_roi(fallback_roi, int(image.shape[1]), int(image.shape[0]))
            fallback = self.ocr_engine.recognize_digits(image, scaled_fallback_roi, preprocess=False)
            return fallback if fallback.success else primary
        if field != "coins" or ui_version != "new":
            return primary
        if not self._fallback_enabled:
            return primary
        if primary.success and primary.value is not None and primary.value >= 100000:
            return primary
        fallback_roi = self.FALLBACK_ROIS.get(ui_version, {}).get(field)
        if fallback_roi is None:
            return primary
        scaled_fallback_roi = self._scale_roi(fallback_roi, int(image.shape[1]), int(image.shape[0]))
        fallback = self._recognize_bottom_digits_with_fallback(image, scaled_fallback_roi, scale=3.0)
        if fallback.success:
            return fallback
        return primary

    def _recognize_bottom_digits_with_fallback(self, image: Any, roi: Box, scale: float = 1.0) -> OcrReadResult:
        """用高精度 OCR 读取较大资源 ROI，并跳过上方 MAX 行。"""
        engine = self._get_fallback_ocr_engine()
        x, y, width, height = roi
        crop = image[y:y + height, x:x + width]
        if scale != 1.0:
            if self._cv2 is None:
                return OcrReadResult(False, "unavailable", "OpenCV(cv2) 不可用，无法放大 fallback ROI。", roi=roi)
            crop = self._cv2.resize(crop, None, fx=scale, fy=scale, interpolation=self._cv2.INTER_CUBIC)
        try:
            lines = engine._run_backend(crop)
        except Exception as exc:
            return OcrReadResult(False, "error", f"fallback OCR 执行失败: {type(exc).__name__}: {exc}", roi=roi)

        candidates: List[Tuple[int, float, str]] = []
        for line in lines:
            text = line.text.strip()
            if not text or "MAX" in text.upper():
                continue
            value = OcrEngine.normalize_number(text)
            if value is None:
                continue
            y_score = line.box[1] if line.box else 0
            score = float(line.confidence) + min(0.25, y_score / 500.0)
            candidates.append((int(value), score, text))
        if not candidates:
            return OcrReadResult(False, "empty", "fallback OCR 未返回资源数字。", roi=roi)
        value, score, text = max(candidates, key=lambda item: item[1])
        return OcrReadResult(
            True,
            "success",
            "fallback OCR 数字识别完成。",
            text=str(value),
            value=int(value),
            confidence=max(0.0, min(1.0, float(score))),
            raw_texts=(text,),
            roi=roi,
        )

    def _get_fallback_ocr_engine(self) -> OcrEngine:
        """延迟创建高精度 fallback OCR 引擎。"""
        if self._fallback_ocr_engine is None:
            fallback_config = dict(self.ocr_config)
            fallback_paddle = fallback_config.get("fallback_paddleocr", {})
            if isinstance(fallback_paddle, dict) and fallback_paddle:
                fallback_config["paddleocr"] = fallback_paddle
            self._fallback_ocr_engine = OcrEngine(config=fallback_config)
        return self._fallback_ocr_engine

    @staticmethod
    def _failure(status: str, message: str, screenshot_path: str = "") -> HarborResourceResult:
        """构造无字段写入风险的失败结果。"""
        return HarborResourceResult(False, status, message, "unknown", "", None, None, None, 0.0, {}, {}, (message,), screenshot_path)

    @staticmethod
    def _default_ocr_config() -> Dict[str, Any]:
        """从 v0.6.0 ROI 配置读取 OCR 段；失败时保守返回空配置。"""
        config_path = PathManager.get_config_dir() / "recognition" / "roi_config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        ocr_config = data.get("ocr", {})
        return ocr_config if isinstance(ocr_config, dict) else {}


# ============================================================
# 第三部分：全局访问函数
# ============================================================

_harbor_resource_detector_instance: Optional[HarborResourceDetector] = None


def get_harbor_resource_detector() -> HarborResourceDetector:
    """获取港区资源识别器单例。"""
    global _harbor_resource_detector_instance
    if _harbor_resource_detector_instance is None:
        _harbor_resource_detector_instance = HarborResourceDetector()
    return _harbor_resource_detector_instance
