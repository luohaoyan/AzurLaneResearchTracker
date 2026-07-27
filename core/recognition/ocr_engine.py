#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════╗
║                   OCR 数字识别引擎                         ║
║  安全封装 PaddleOCR 与 OpenCV 预处理，专注数字/文本识别   ║
║  依赖缺失时返回 unavailable，不隐式联网，不启动 GUI        ║
╚════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 导入依赖
# ============================================================

import importlib
import importlib.util
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.utils.path_manager import PathManager

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - 依赖缺失时允许降级
    _cv2 = None

try:
    import numpy as _np
except Exception:  # pragma: no cover - 依赖缺失时允许降级
    _np = None


# ============================================================
# 基础类型与结果对象
# ============================================================

RoiRegion = Tuple[int, int, int, int]


class OcrUnavailableError(RuntimeError):
    """OCR 引擎或本地模型不可用时抛出的内部异常。"""


@dataclass(frozen=True)
class OcrTextLine:
    """OCR 后端返回的一行文本。"""

    text: str
    confidence: float
    box: Optional[RoiRegion] = None


@dataclass(frozen=True)
class OcrReadResult:
    """单个 ROI 的 OCR 读取结果。"""

    success: bool
    status: str
    message: str
    text: str = ""
    value: Optional[int] = None
    confidence: float = 0.0
    raw_texts: Tuple[str, ...] = ()
    roi: Optional[RoiRegion] = None
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转成可序列化字典。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "text": self.text,
            "value": self.value,
            "confidence": float(self.confidence),
            "raw_texts": list(self.raw_texts),
            "roi": list(self.roi) if self.roi else None,
            "warnings": list(self.warnings),
        }


# ============================================================
# OCR 引擎
# ============================================================


class OcrEngine:
    """PaddleOCR + OpenCV 的延迟加载封装。"""

    DEFAULT_CONFIDENCE_THRESHOLD = 0.8

    def __init__(
        self,
        backend: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        cv2_module: Optional[Any] = None,
        np_module: Optional[Any] = None,
    ) -> None:
        """初始化时不加载 PaddleOCR 模型。"""
        self._injected_backend = backend
        self._backend: Optional[Any] = backend
        self._backend_load_error = ""
        self._backend_loaded = backend is not None
        self.config = config or {}
        self.confidence_threshold = float(self.config.get("confidence_threshold", confidence_threshold))
        self._cv2 = cv2_module
        self._np = np_module

    def check_status(self) -> Dict[str, Any]:
        """检查依赖与本地模型配置状态。"""
        cv2_available = self._get_cv2() is not None
        np_available = self._get_np() is not None
        paddle_available = self._module_available("paddleocr")
        model_dirs = self._resolve_model_dirs()
        backend_injected = self._injected_backend is not None
        available = bool(backend_injected or (cv2_available and np_available and paddle_available and model_dirs))

        warnings: List[str] = []
        if not cv2_available:
            warnings.append("OpenCV(cv2) 不可用，图像预处理与模板匹配将返回 unavailable。")
        if not paddle_available and not backend_injected:
            warnings.append("PaddleOCR 不可用，未注入 backend 时无法执行真实 OCR。")
        if not model_dirs and not backend_injected:
            warnings.append("未配置可用的本地 PaddleOCR 模型目录，已禁止隐式联网下载。")

        return {
            "available": available,
            "backend_injected": backend_injected,
            "dependencies": {
                "opencv_cv2": cv2_available,
                "numpy": np_available,
                "paddleocr": paddle_available,
            },
            "local_model_configured": bool(model_dirs),
            "model_dirs": model_dirs,
            "confidence_threshold": self.confidence_threshold,
            "warnings": warnings,
        }

    def load_image(self, screenshot_path: str | Path) -> Any:
        """从磁盘读取截图，返回 OpenCV BGR 图像。"""
        cv2_module = self._require_cv2()
        path = Path(screenshot_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"截图文件不存在: {path}")
        image = cv2_module.imread(str(path), cv2_module.IMREAD_COLOR)
        if image is None or getattr(image, "size", 0) == 0:
            raise ValueError(f"截图无法读取或已损坏: {path}")
        return image

    def validate_roi(self, image: Any, roi: Sequence[int]) -> RoiRegion:
        """检查 ROI 是否在图像边界内。"""
        if image is None or not hasattr(image, "shape"):
            raise ValueError("图像为空，无法校验 ROI。")
        if len(tuple(roi)) != 4:
            raise ValueError("ROI 必须包含 x, y, w, h 四个整数。")
        x, y, width, height = (int(item) for item in roi)
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError(f"ROI 坐标或尺寸非法: {(x, y, width, height)}")
        if x + width > image_width or y + height > image_height:
            raise ValueError(f"ROI 越界: {(x, y, width, height)} 超出图像 {(image_width, image_height)}")
        return x, y, width, height

    def crop_roi(self, image: Any, roi: Sequence[int]) -> Any:
        """裁剪 ROI。"""
        x, y, width, height = self.validate_roi(image, roi)
        return image[y:y + height, x:x + width]

    def preprocess_for_ocr(self, image: Any) -> Any:
        """灰度化、降噪和二值化，提升数字 OCR 稳定性。"""
        cv2_module = self._require_cv2()
        if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
            raise ValueError("ROI 图像为空，无法预处理。")

        if len(image.shape) == 3:
            gray = cv2_module.cvtColor(image, cv2_module.COLOR_BGR2GRAY)
        else:
            gray = image.copy() if hasattr(image, "copy") else image

        if min(int(gray.shape[0]), int(gray.shape[1])) >= 3:
            gray = cv2_module.GaussianBlur(gray, (3, 3), 0)

        if hasattr(cv2_module, "equalizeHist"):
            try:
                gray = cv2_module.equalizeHist(gray)
            except Exception:
                pass

        min_side = min(int(gray.shape[0]), int(gray.shape[1]))
        if min_side < 11:
            _, binary = cv2_module.threshold(gray, 0, 255, cv2_module.THRESH_BINARY + cv2_module.THRESH_OTSU)
            return binary

        mean_value = float(getattr(gray, "mean", lambda: 0.0)())
        adaptive_mode = cv2_module.THRESH_BINARY_INV if mean_value < 128.0 else cv2_module.THRESH_BINARY
        processed = cv2_module.adaptiveThreshold(
            gray,
            255,
            cv2_module.ADAPTIVE_THRESH_GAUSSIAN_C,
            adaptive_mode,
            11,
            2,
        )
        if hasattr(cv2_module, "morphologyEx") and self._get_np() is not None:
            kernel = _np.ones((2, 2), dtype=_np.uint8)
            try:
                processed = cv2_module.morphologyEx(processed, cv2_module.MORPH_OPEN, kernel)
            except Exception:
                pass
        return processed

    def recognize_text(
        self,
        image: Any,
        roi: Optional[Sequence[int]] = None,
        confidence_threshold: Optional[float] = None,
        preprocess: bool = True,
    ) -> OcrReadResult:
        """识别文本，返回置信度最高的一条。"""
        threshold = self._safe_threshold(confidence_threshold)
        try:
            target, safe_roi = self._prepare_target_image(image, roi, preprocess)
            lines = self._run_backend(target)
        except OcrUnavailableError as exc:
            return self._unavailable(str(exc), roi)
        except Exception as exc:
            return OcrReadResult(False, "error", str(exc), roi=self._coerce_roi_or_none(roi))

        raw_texts = tuple(line.text for line in lines)
        if not lines:
            return OcrReadResult(False, "empty", "OCR 未返回文本。", raw_texts=raw_texts, roi=safe_roi)

        accepted = [line for line in lines if line.text.strip() and line.confidence >= threshold]
        if not accepted:
            return OcrReadResult(
                False,
                "low_confidence",
                f"OCR 文本置信度低于阈值 {threshold:.2f}。",
                raw_texts=raw_texts,
                roi=safe_roi,
                warnings=("低置信度文本已过滤。",),
            )

        best = max(accepted, key=lambda line: line.confidence)
        return OcrReadResult(
            True,
            "success",
            "OCR 文本识别完成。",
            text=best.text.strip(),
            confidence=float(best.confidence),
            raw_texts=raw_texts,
            roi=safe_roi,
        )

    def recognize_lines(
        self,
        image: Any,
        roi: Optional[Sequence[int]] = None,
        preprocess: bool = True,
    ) -> Tuple[OcrTextLine, ...]:
        """
        识别文本行并保留坐标，供文本点击和列表匹配使用。
        输入：
            image: OpenCV 图像或截图路径。
            roi: 可选裁剪区域。
            preprocess: 是否做预处理。
        输出：
            Tuple[OcrTextLine, ...]：保留 OCR 原始行和坐标。
        使用示例：
            lines = engine.recognize_lines(image)
        """
        try:
            target, _safe_roi = self._prepare_target_image(image, roi, preprocess)
            return self._run_backend(target)
        except OcrUnavailableError:
            return ()
        except Exception:
            return ()

    def recognize_digits(
        self,
        image: Any,
        roi: Optional[Sequence[int]] = None,
        confidence_threshold: Optional[float] = None,
        preprocess: bool = True,
    ) -> OcrReadResult:
        """识别数字，并尽量保守地避免把无关字符拼进去。"""
        threshold = self._safe_threshold(confidence_threshold)
        try:
            target, safe_roi = self._prepare_target_image(image, roi, preprocess)
            lines = self._run_backend(target)
        except OcrUnavailableError as exc:
            return self._unavailable(str(exc), roi)
        except Exception as exc:
            return OcrReadResult(False, "error", str(exc), roi=self._coerce_roi_or_none(roi))

        raw_texts = tuple(line.text for line in lines)
        if not lines:
            return OcrReadResult(False, "empty", "OCR 未返回文本。", raw_texts=raw_texts, roi=safe_roi)

        candidates, filtered_low_confidence = self._build_digit_candidates(lines, threshold)
        if not candidates:
            status = "low_confidence" if filtered_low_confidence else "empty"
            warning = "低置信度数字已过滤。" if filtered_low_confidence else "OCR 文本中没有可用数字。"
            return OcrReadResult(
                False,
                status,
                warning,
                raw_texts=raw_texts,
                roi=safe_roi,
                warnings=(warning,),
            )

        best = max(
            candidates,
            key=lambda item: (
                float(item["score"]),
                float(item["confidence"]),
                len(str(item["text"])),
            ),
        )
        text_value = str(best["text"])
        value = self.normalize_number(text_value)
        if value is None:
            return OcrReadResult(
                False,
                "error",
                f"无法把 OCR 数字转换为整数: {text_value}",
                raw_texts=raw_texts,
                roi=safe_roi,
            )

        return OcrReadResult(
            True,
            "success",
            "OCR 数字识别完成。",
            text=text_value,
            value=int(value),
            confidence=float(best["confidence"]),
            raw_texts=raw_texts,
            roi=safe_roi,
        )

    @classmethod
    def normalize_digit_text(cls, text: str) -> str:
        """把 OCR 文本规范化为纯数字字符串。"""
        if not text:
            return ""
        translation = str.maketrans({
            "O": "0",
            "o": "0",
            "０": "0",
            "１": "1",
            "２": "2",
            "３": "3",
            "４": "4",
            "５": "5",
            "６": "6",
            "７": "7",
            "８": "8",
            "９": "9",
            ",": "",
            "，": "",
            ".": "",
            "。": "",
            "、": "",
            " ": "",
            "\u3000": "",
            "\t": "",
            "\n": "",
            "\r": "",
            "+": "",
            "＋": "",
            ":": "",
            "：": "",
            "/": "",
            "\\": "",
            "|": "",
            "-": "",
            "_": "",
        })
        normalized = str(text).translate(translation)
        return "".join(re.findall(r"\d+", normalized))

    @classmethod
    def normalize_number(cls, text: str) -> Optional[int]:
        """把 OCR 文本规范化为整数。"""
        digits = cls.normalize_digit_text(text)
        return int(digits) if digits else None

    @classmethod
    def extract_integer_sequence(cls, text: str) -> Tuple[int, ...]:
        """Extract ordered integer groups while preserving slash-like meaning.

        Fragment cards often show text such as ``65/50`` where the left value is
        the owned fragment count and the right value is the synthesis
        requirement. This parser keeps those values separate while still
        normalizing OCR noise such as ``O``/``o`` and full-width digits.
        """
        if not text:
            return ()

        normalized_chars: List[str] = []
        for char in str(text):
            codepoint = ord(char)
            if "0" <= char <= "9":
                normalized_chars.append(char)
                continue
            if 0xFF10 <= codepoint <= 0xFF19:
                normalized_chars.append(chr(ord("0") + codepoint - 0xFF10))
                continue
            if char in {"O", "o"}:
                normalized_chars.append("0")
                continue
            if char in {",", "，", " ", "\u3000", "\t", "\n", "\r", ".", "．", "。"}:
                continue
            normalized_chars.append("/")

        numbers: List[int] = []
        for group in re.findall(r"\d+", "".join(normalized_chars)):
            try:
                numbers.append(int(group))
            except ValueError:
                continue
        return tuple(numbers)

    def _prepare_target_image(
        self,
        image: Any,
        roi: Optional[Sequence[int]],
        preprocess: bool,
    ) -> Tuple[Any, Optional[RoiRegion]]:
        """裁剪并按需预处理目标图像。"""
        target = image
        safe_roi = self._coerce_roi_or_none(roi)
        if roi is not None:
            target = self.crop_roi(image, roi)
            safe_roi = self.validate_roi(image, roi)
        if preprocess:
            target = self.preprocess_for_ocr(target)
        return target, safe_roi

    def _run_backend(self, image: Any) -> Tuple[OcrTextLine, ...]:
        """调用后端 OCR 并整理为统一行对象。"""
        backend = self._get_backend()
        image = self._ensure_backend_image(image)
        try:
            if hasattr(backend, "ocr"):
                try:
                    raw_result = backend.ocr(image, cls=True)
                except TypeError:
                    raw_result = backend.ocr(image)
            elif hasattr(backend, "predict"):
                raw_result = backend.predict(image)
            elif callable(backend):
                raw_result = backend(image)
            else:
                raise OcrUnavailableError("OCR backend 不包含 ocr/predict/callable 入口。")
        except OcrUnavailableError:
            raise
        except Exception as exc:
            raise RuntimeError(f"OCR backend 执行失败: {type(exc).__name__}: {exc}") from exc
        return tuple(self._parse_ocr_lines(raw_result))

    def _ensure_backend_image(self, image: Any) -> Any:
        """确保送入 PaddleOCR 的图像是 HWC 三通道，兼容二值化后的数字 ROI。"""
        if image is None or not hasattr(image, "shape"):
            return image
        if len(image.shape) != 2:
            return image
        cv2_module = self._get_cv2()
        if cv2_module is None:
            return image
        return cv2_module.cvtColor(image, cv2_module.COLOR_GRAY2BGR)

    def _get_backend(self) -> Any:
        """延迟加载 PaddleOCR，只允许本地模型目录。"""
        if self._backend_loaded:
            if self._backend is None:
                raise OcrUnavailableError(self._backend_load_error or "OCR backend 不可用。")
            return self._backend

        self._backend_loaded = True
        if not self._module_available("paddleocr"):
            self._backend_load_error = "PaddleOCR 未安装，且未注入 OCR backend。"
            raise OcrUnavailableError(self._backend_load_error)

        model_dirs = self._resolve_model_dirs()
        if not model_dirs:
            self._backend_load_error = "未配置可用的本地 PaddleOCR 模型目录。"
            raise OcrUnavailableError(self._backend_load_error)

        try:
            paddleocr_module = importlib.import_module("paddleocr")
            paddle_ocr = getattr(paddleocr_module, "PaddleOCR")
            kwargs = self._paddle_kwargs(model_dirs, paddle_ocr)
            self._backend = paddle_ocr(**kwargs)
            return self._backend
        except Exception as exc:
            self._backend = None
            self._backend_load_error = f"PaddleOCR 本地模型加载失败: {type(exc).__name__}: {exc}"
            raise OcrUnavailableError(self._backend_load_error) from exc

    def _paddle_kwargs(self, model_dirs: Dict[str, str], paddle_ocr_class: Any) -> Dict[str, Any]:
        """生成 PaddleOCR 初始化参数。"""
        paddle_config = self.config.get("paddleocr", {})
        if not isinstance(paddle_config, dict):
            paddle_config = {}
        try:
            signature = inspect.signature(paddle_ocr_class)
        except (TypeError, ValueError):
            signature = None
        supports_paddleocr_3 = bool(signature and "text_detection_model_dir" in signature.parameters)

        if supports_paddleocr_3:
            has_explicit_models = any(
                paddle_config.get(key) or self.config.get(key) or model_dirs.get(key)
                for key in (
                    "text_detection_model_name",
                    "text_recognition_model_name",
                    "text_detection_model_dir",
                    "text_recognition_model_dir",
                    "det_model_dir",
                    "rec_model_dir",
                )
            )
            kwargs: Dict[str, Any] = {
                "use_doc_orientation_classify": bool(paddle_config.get("use_doc_orientation_classify", False)),
                "use_doc_unwarping": bool(paddle_config.get("use_doc_unwarping", False)),
                "use_textline_orientation": bool(
                    paddle_config.get("use_textline_orientation", paddle_config.get("use_angle_cls", False))
                ),
                "device": paddle_config.get("device", self.config.get("device", "cpu")),
                "enable_mkldnn": bool(paddle_config.get("enable_mkldnn", self.config.get("enable_mkldnn", False))),
                "enable_cinn": bool(paddle_config.get("enable_cinn", self.config.get("enable_cinn", False))),
                "cpu_threads": int(paddle_config.get("cpu_threads", self.config.get("cpu_threads", 4))),
            }
            if not has_explicit_models:
                kwargs["lang"] = paddle_config.get("lang", self.config.get("lang", "ch"))
            optional_keys = (
                "text_detection_model_name",
                "text_recognition_model_name",
                "textline_orientation_model_name",
                "text_det_limit_side_len",
                "text_det_limit_type",
                "text_det_thresh",
                "text_det_box_thresh",
                "text_det_unclip_ratio",
                "text_rec_score_thresh",
                "text_rec_input_shape",
            )
            for key in optional_keys:
                value = paddle_config.get(key, self.config.get(key))
                if value not in (None, ""):
                    kwargs[key] = value
            for key, paddle_key in (
                ("det_model_dir", "text_detection_model_dir"),
                ("rec_model_dir", "text_recognition_model_dir"),
                ("cls_model_dir", "textline_orientation_model_dir"),
                ("text_detection_model_dir", "text_detection_model_dir"),
                ("text_recognition_model_dir", "text_recognition_model_dir"),
                ("textline_orientation_model_dir", "textline_orientation_model_dir"),
            ):
                if model_dirs.get(key) and paddle_key not in kwargs:
                    kwargs[paddle_key] = model_dirs[key]
            return kwargs

        kwargs = {
            "lang": paddle_config.get("lang", self.config.get("lang", "ch")),
            "use_angle_cls": bool(paddle_config.get("use_angle_cls", False)),
            "use_gpu": bool(paddle_config.get("use_gpu", False)),
            "show_log": False,
        }
        for key, paddle_key in (
            ("det_model_dir", "det_model_dir"),
            ("rec_model_dir", "rec_model_dir"),
            ("cls_model_dir", "cls_model_dir"),
            ("model_dir", "model_dir"),
        ):
            if model_dirs.get(key):
                kwargs[paddle_key] = model_dirs[key]
        return kwargs

    def _resolve_model_dirs(self) -> Dict[str, str]:
        """从配置中解析本地模型目录，只返回真实存在的路径。"""
        candidate_config: Dict[str, Any] = {}
        if isinstance(self.config.get("paddleocr"), dict):
            candidate_config.update(self.config["paddleocr"])
        candidate_config.update(self.config)

        resolved: Dict[str, str] = {}
        for key in (
            "det_model_dir",
            "rec_model_dir",
            "cls_model_dir",
            "text_detection_model_dir",
            "text_recognition_model_dir",
            "textline_orientation_model_dir",
            "model_dir",
            "local_model_dir",
        ):
            value = candidate_config.get(key)
            if not value:
                continue
            path = self._resolve_local_path(str(value))
            if path.exists() and path.is_dir():
                normalized_key = "model_dir" if key == "local_model_dir" else key
                resolved[normalized_key] = str(self._resolve_inference_model_dir(path))

        model_root = candidate_config.get("model_root") or candidate_config.get("local_model_root")
        if model_root:
            root = self._resolve_local_path(str(model_root))
            if root.exists() and root.is_dir():
                for child_name, key in (("det", "det_model_dir"), ("rec", "rec_model_dir"), ("cls", "cls_model_dir")):
                    child = root / child_name
                    if child.exists() and child.is_dir() and key not in resolved:
                        resolved[key] = str(self._resolve_inference_model_dir(child))
        return resolved

    @staticmethod
    def _resolve_local_path(value: str) -> Path:
        """解析模型路径；相对路径优先按项目根目录计算。"""
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return PathManager.get_project_root() / path

    @classmethod
    def _resolve_inference_model_dir(cls, path: Path) -> Path:
        """兼容 tar 解压后一层目录包裹模型文件的情况。"""
        if cls._looks_like_inference_model_dir(path):
            return path
        children = [child for child in path.iterdir() if child.is_dir()]
        if len(children) == 1 and cls._looks_like_inference_model_dir(children[0]):
            return children[0]
        return path

    @staticmethod
    def _looks_like_inference_model_dir(path: Path) -> bool:
        """判断目录内是否含 PaddleOCR/PaddleX 推理模型文件。"""
        markers = ("inference.json", "inference.yml", "inference.pdmodel", "model.pdmodel")
        return any((path / marker).exists() for marker in markers)

    def _parse_ocr_lines(self, raw_result: Any) -> List[OcrTextLine]:
        """兼容 PaddleOCR classic .ocr() 与 3.x .predict() 输出。"""
        parsed: List[OcrTextLine] = []

        def add_line(text: Any, confidence: Any, box: Any = None) -> None:
            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError):
                confidence_value = 0.0
            parsed.append(
                OcrTextLine(
                    str(text),
                    max(0.0, min(1.0, confidence_value)),
                    self._coerce_box_or_none(box),
                )
            )

        def walk(node: Any) -> None:
            if node is None:
                return
            if isinstance(node, dict):
                texts = node.get("rec_texts") or node.get("texts")
                scores = node.get("rec_scores") or node.get("scores")
                boxes = node.get("rec_boxes")
                if boxes is None:
                    boxes = node.get("boxes")
                if isinstance(texts, Iterable) and not isinstance(texts, (str, bytes)):
                    score_list = list(scores) if isinstance(scores, Iterable) and not isinstance(scores, (str, bytes)) else []
                    box_list = list(boxes) if isinstance(boxes, Iterable) and not isinstance(boxes, (str, bytes)) else []
                    for index, text in enumerate(list(texts)):
                        add_line(
                            text,
                            score_list[index] if index < len(score_list) else 0.0,
                            box_list[index] if index < len(box_list) else None,
                        )
                for key in ("res", "result", "ocr_result", "data"):
                    if key in node:
                        walk(node[key])
                return
            if isinstance(node, (list, tuple)):
                if len(node) >= 2 and isinstance(node[0], str):
                    add_line(node[0], node[1])
                    return
                if (
                    len(node) >= 2
                    and isinstance(node[1], (list, tuple))
                    and len(node[1]) >= 2
                    and isinstance(node[1][0], str)
                ):
                    add_line(node[1][0], node[1][1], node[0])
                    return
                for item in node:
                    walk(item)

        walk(raw_result)
        return parsed

    def _build_digit_candidates(
        self,
        lines: Sequence[OcrTextLine],
        threshold: float,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """把 OCR 数字整理成候选，供后续保守选择。"""
        accepted: List[Dict[str, Any]] = []
        filtered_low_confidence = False
        for index, line in enumerate(lines):
            if line.confidence < threshold:
                filtered_low_confidence = True
                continue
            digits = self.normalize_digit_text(line.text)
            if not digits:
                continue
            try:
                canonical = str(int(digits))
            except ValueError:
                continue
            accepted.append(
                {
                    "text": canonical,
                    "confidence": float(line.confidence),
                    "box": line.box,
                    "index": index,
                }
            )

        if not accepted:
            return [], filtered_low_confidence

        candidates: List[Dict[str, Any]] = [
            {
                "text": item["text"],
                "confidence": float(item["confidence"]),
                "score": float(item["confidence"]) + min(len(str(item["text"])), 8) * 0.015,
            }
            for item in accepted
        ]
        for cluster in self._cluster_digit_candidates(accepted):
            merged = self._merge_digit_cluster(cluster)
            if merged is not None:
                candidates.append(merged)
        return candidates, filtered_low_confidence

    @classmethod
    def _cluster_digit_candidates(cls, candidates: Sequence[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], ...]]:
        """按阅读顺序把相邻且足够接近的数字线条聚成组。"""
        ordered = sorted(candidates, key=cls._digit_sort_key)
        clusters: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        for candidate in ordered:
            if not current:
                current.append(candidate)
                continue
            if cls._can_merge_digit_lines(current[-1], candidate):
                current.append(candidate)
                continue
            clusters.append(current)
            current = [candidate]
        if current:
            clusters.append(current)
        return [tuple(cluster) for cluster in clusters]

    @staticmethod
    def _digit_sort_key(candidate: Dict[str, Any]) -> Tuple[int, int, int]:
        """按从上到下、从左到右排序。"""
        box = candidate.get("box")
        index = int(candidate.get("index", 0))
        if box is None:
            return 10_000, index, index
        x, y, _, _ = box
        return int(y), int(x), index

    @classmethod
    def _can_merge_digit_lines(cls, first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        """判断两个数字候选是否足够接近，可以安全拼接。"""
        first_box = first.get("box")
        second_box = second.get("box")
        if first_box is None or second_box is None:
            return False

        fx, fy, fw, fh = (int(item) for item in first_box)
        sx, sy, sw, sh = (int(item) for item in second_box)
        if sx < fx:
            return False

        first_bottom = fy + fh
        second_bottom = sy + sh
        vertical_overlap = min(first_bottom, second_bottom) - max(fy, sy)
        if vertical_overlap <= 0:
            return False

        overlap_ratio = vertical_overlap / float(max(1, min(fh, sh)))
        if overlap_ratio < 0.4:
            return False

        height_scale = max(fh, sh, 1)
        gap = sx - (fx + fw)
        if gap > height_scale * 1.5:
            return False
        if gap < -height_scale * 0.2:
            return False

        center_delta = abs((fy + fh / 2) - (sy + sh / 2))
        if center_delta > height_scale * 0.75:
            return False
        return True

    @classmethod
    def _merge_digit_cluster(cls, cluster: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """把同一行里的多个数字片段合并成一个候选。"""
        if len(cluster) < 2:
            return None
        texts = [str(item.get("text", "")).strip() for item in cluster]
        texts = [text for text in texts if text]
        if len(texts) < 2:
            return None

        merged_text = "".join(texts)
        confidences = [float(item.get("confidence", 0.0)) for item in cluster]
        confidence = min(confidences) if confidences else 0.0
        score = confidence + 0.03 * (len(cluster) - 1) - cls._digit_cluster_gap_penalty(cluster)
        return {
            "text": merged_text,
            "confidence": confidence,
            "score": score,
        }

    @classmethod
    def _digit_cluster_gap_penalty(cls, cluster: Sequence[Dict[str, Any]]) -> float:
        """把明显过大的间距转成轻微惩罚，避免乱拼接。"""
        if len(cluster) < 2:
            return 0.0

        total_penalty = 0.0
        counted_pairs = 0
        for first, second in zip(cluster, cluster[1:]):
            first_box = first.get("box")
            second_box = second.get("box")
            if first_box is None or second_box is None:
                continue
            fx, fy, fw, fh = (int(item) for item in first_box)
            sx, sy, sw, sh = (int(item) for item in second_box)
            gap = max(0, sx - (fx + fw))
            scale = max(1.0, (fh + sh) / 2.0)
            total_penalty += min(0.25, gap / (scale * 30.0))
            counted_pairs += 1

        if counted_pairs == 0:
            return 0.0
        return min(0.3, total_penalty / float(counted_pairs))

    def _require_cv2(self) -> Any:
        """返回 cv2 模块，不可用时抛出结构化异常。"""
        cv2_module = self._get_cv2()
        if cv2_module is None:
            raise OcrUnavailableError("OpenCV(cv2) 不可用，无法读取或预处理截图。")
        return cv2_module

    def _get_cv2(self) -> Optional[Any]:
        """获取 cv2 模块。"""
        if self._cv2 is not None:
            return self._cv2
        return _cv2

    def _get_np(self) -> Optional[Any]:
        """获取 numpy 模块。"""
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

    def _safe_threshold(self, threshold: Optional[float]) -> float:
        """限制阈值在 0.0~1.0。"""
        value = self.confidence_threshold if threshold is None else float(threshold)
        return max(0.0, min(1.0, value))

    def _unavailable(self, message: str, roi: Optional[Sequence[int]]) -> OcrReadResult:
        """构造 unavailable 结果。"""
        return OcrReadResult(False, "unavailable", message, roi=self._coerce_roi_or_none(roi), warnings=(message,))

    @staticmethod
    def _coerce_roi_or_none(roi: Optional[Sequence[int]]) -> Optional[RoiRegion]:
        """尽量把 ROI 输入转成四元组。"""
        if roi is None:
            return None
        try:
            if len(tuple(roi)) != 4:
                return None
            x, y, width, height = (int(item) for item in roi)
            return x, y, width, height
        except Exception:
            return None

    @staticmethod
    def _coerce_box_or_none(box: Any) -> Optional[RoiRegion]:
        """把 OCR 的四点框或边界框折叠成 x, y, w, h。"""
        if box is None:
            return None
        try:
            if hasattr(box, "tolist"):
                box = box.tolist()
            if isinstance(box, (list, tuple)):
                if len(box) == 4 and all(isinstance(item, (int, float)) for item in box):
                    x1, y1, x2, y2 = (float(item) for item in box)
                    left, right = sorted((x1, x2))
                    top, bottom = sorted((y1, y2))
                    return (
                        int(round(left)),
                        int(round(top)),
                        max(1, int(round(right - left))),
                        max(1, int(round(bottom - top))),
                    )
                points: List[Tuple[float, float]] = []
                for point in box:
                    if isinstance(point, (list, tuple)) and len(point) >= 2:
                        points.append((float(point[0]), float(point[1])))
                if points:
                    xs = [item[0] for item in points]
                    ys = [item[1] for item in points]
                    left = min(xs)
                    right = max(xs)
                    top = min(ys)
                    bottom = max(ys)
                    return (
                        int(round(left)),
                        int(round(top)),
                        max(1, int(round(right - left))),
                        max(1, int(round(bottom - top))),
                    )
        except Exception:
            return None
        return None


# ============================================================
# 便捷函数
# ============================================================


def normalize_number_text(text: str) -> Optional[int]:
    """兼容旧调用风格的数字归一化函数。"""
    return OcrEngine.normalize_number(text)
