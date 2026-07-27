#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             🧭 截图场景分析器 (scene_analyzer.py)            ║
║                                                              ║
║  【一句话解释】按场景 ROI 配置生成 v0.6.0 冻结识别契约。      ║
║  【类比理解】它像把截图分成标好编号的小格，再逐格交给 OCR。   ║
║  【数据流说明】截图路径 → 场景 ROI → OCR/模板匹配 → 契约结果。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.contracts import (
    EquipmentRecognitionRecord,
    RecognitionDetection,
    RecognitionDetectionType,
    RecognitionResult,
    RecognitionScene,
    ResourceRecognitionRecord,
    TaskExecutionContext,
)
from core.recognition.equipment_card_reader import EquipmentCardDigitReader
from core.recognition.ocr_engine import OcrEngine, OcrReadResult
from core.recognition.template_matcher import TemplateMatcher
from core.utils.path_manager import PathManager


# ============================================================
# 🏗️ 第二部分：场景分析器
# ============================================================

class SceneAnalyzer:
    """
    游戏截图场景分析器。
    输入：
        ocr_engine/template_matcher/config/config_path。
    输出：
        RecognitionResult，字段完全使用 core.contracts 冻结契约。
    使用示例：
        result = SceneAnalyzer().analyze("shot.png", RecognitionScene.HARBOR)
    """

    DEFAULT_CONFIG_PATH = PathManager.get_config_dir() / "recognition" / "roi_config.json"

    def __init__(
        self,
        ocr_engine: Optional[OcrEngine] = None,
        template_matcher: Optional[TemplateMatcher] = None,
        card_reader: Optional[EquipmentCardDigitReader] = None,
        screen_state_detector: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str | Path] = None,
    ) -> None:
        """初始化分析器，配置只读加载，不写回正式配置。"""
        self.config_path = Path(config_path) if config_path is not None else self.DEFAULT_CONFIG_PATH
        self.config = config if config is not None else self._load_config(self.config_path)
        ocr_config = self.config.get("ocr", {}) if isinstance(self.config.get("ocr", {}), dict) else {}
        template_config = self.config.get("template_matching", {})
        if not isinstance(template_config, dict):
            template_config = {}
        self.ocr_engine = ocr_engine or OcrEngine(config=ocr_config)
        self.template_matcher = template_matcher or TemplateMatcher(
            threshold=float(template_config.get("threshold", 0.8)),
            scales=tuple(template_config.get("scales", [1.0])),
            iou_threshold=float(template_config.get("iou_threshold", 0.3)),
        )
        card_config = self.config.get("card_digits", {})
        if not isinstance(card_config, dict):
            card_config = {}
        self.card_reader = card_reader or EquipmentCardDigitReader(self.ocr_engine, config=card_config)
        self._screen_state_detector = screen_state_detector

    def get_scene_config(self, scene: RecognitionScene | str) -> Dict[str, Any]:
        """
        获取指定场景配置。
        输入：
            scene: harbor/equipment_list/research/phase_select。
        输出：
            dict: 场景配置副本样式的普通字典。
        使用示例：
            config = analyzer.get_scene_config("harbor")
        """
        normalized = RecognitionScene.normalize(scene)
        scenes = self.config.get("scenes", {})
        if not isinstance(scenes, dict):
            return {"scene": normalized.value, "rois": []}
        scene_config = scenes.get(normalized.value, {})
        if not isinstance(scene_config, dict):
            return {"scene": normalized.value, "rois": []}
        result = dict(scene_config)
        result.setdefault("scene", normalized.value)
        result.setdefault("rois", [])
        return result

    def get_scene_rois(self, scene: RecognitionScene | str) -> Tuple[Dict[str, Any], ...]:
        """
        获取场景 ROI 列表。
        输入：
            scene: 场景名称。
        输出：
            tuple[dict, ...]。
        使用示例：
            rois = analyzer.get_scene_rois(RecognitionScene.EQUIPMENT_LIST)
        """
        rois = self.get_scene_config(scene).get("rois", [])
        if not isinstance(rois, list):
            return ()
        return tuple(item for item in rois if isinstance(item, dict))

    def analyze(
        self,
        screenshot_path: str | Path,
        scene: RecognitionScene | str,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> RecognitionResult:
        """
        分析截图并生成标准 RecognitionResult。
        输入：
            screenshot_path/scene/task_context。
        输出：
            RecognitionResult。
        使用示例：
            result = analyzer.analyze("shot.png", "equipment_list")
        """
        normalized_scene = RecognitionScene.normalize(scene)
        path_text = str(screenshot_path)
        if task_context is not None:
            task_context.raise_if_cancelled("OCR 场景分析已取消。")
            task_context.report_progress(5, "正在读取截图。", normalized_scene.value)

        try:
            image = self.ocr_engine.load_image(screenshot_path)
        except FileNotFoundError as exc:
            return self._failure(normalized_scene, path_text, "截图文件不存在，无法执行 OCR。", str(exc))
        except ValueError as exc:
            return self._failure(normalized_scene, path_text, "截图无法读取或已损坏。", str(exc))
        except Exception as exc:
            return self._failure(normalized_scene, path_text, "OCR 引擎不可用，无法读取截图。", str(exc))

        scene_config = self.get_scene_config(normalized_scene)
        warnings: List[str] = self._calibration_warnings(scene_config)
        capture_warning = self._capture_frame_warning(image, scene_config)
        if capture_warning:
            warnings.append(capture_warning)
            return RecognitionResult(
                False,
                normalized_scene,
                screenshot_path=path_text,
                warnings=tuple(warnings),
                message="截图尺寸疑似不完整，已跳过 OCR 识别。",
                detail=capture_warning,
            )

        if self._screen_state_probe_enabled(normalized_scene):
            state_result = self._get_screen_state_detector().detect(image, task_context=task_context)
            if state_result.screen_state != "harbor":
                warnings.extend(state_result.warnings)
                warning = f"screen_state={state_result.screen_state}; confidence={state_result.confidence:.3f}"
                warnings.append(warning)
                return RecognitionResult(
                    True,
                    RecognitionScene.UNKNOWN,
                    screenshot_path=path_text,
                    detections=(),
                    warnings=tuple(warnings),
                    message=state_result.message,
                    detail=(
                        f"{warning}; suggested_action={state_result.suggested_action}; "
                        f"state_detail={state_result.detail}"
                    ),
                )
            warnings.extend(state_result.warnings)

        rois = self.get_scene_rois(normalized_scene)
        detections: List[RecognitionDetection] = []
        equipment_state: Dict[str, Dict[str, Any]] = {}
        resource_numbers: Dict[str, int] = {}
        resource_confidences: List[float] = []
        player_name = ""
        processed = 0
        hard_failures = 0

        if not rois:
            warnings.append(f"{normalized_scene.value} 场景尚未配置 ROI。")

        for index, roi_config in enumerate(rois):
            if task_context is not None:
                task_context.raise_if_cancelled("OCR 任务已在 ROI 安全点取消。")
                progress = 10 + int((index / max(1, len(rois))) * 80)
                task_context.report_progress(progress, "正在识别 ROI。", str(roi_config.get("name", index)))

            roi_name = str(roi_config.get("name") or roi_config.get("field") or f"roi_{index}")
            try:
                scaled_roi = self.scale_roi(self._roi_from_config(roi_config), image)
            except ValueError as exc:
                hard_failures += 1
                warnings.append(f"{roi_name}: {exc}")
                continue

            mode = str(roi_config.get("mode", "digits"))
            if mode in {"static", "position"}:
                confidence = float(roi_config.get("confidence", 1.0))
                value = int(roi_config.get("value", 1))
                processed += 1
                roi_type = str(roi_config.get("kind") or roi_config.get("type") or "ui_element")
                detections.append(self._static_detection(roi_name, roi_type, value, confidence, scaled_roi))
                continue
            if mode == "state":
                confidence = float(roi_config.get("confidence", 0.75))
                value, state_confidence = self._detect_roi_state(image, scaled_roi, roi_config, confidence)
                processed += 1
                roi_type = str(roi_config.get("kind") or roi_config.get("type") or "ui_element")
                detections.append(self._static_detection(roi_name, roi_type, value, state_confidence, scaled_roi))
                continue
            fragment_required_value: Optional[int] = None
            if mode in {"equipment_stack_count", "stack_count"}:
                ocr_result = self.card_reader.read_stack_quantity(
                    image,
                    card_roi=scaled_roi,
                    quantity_roi=roi_config.get("quantity_bbox") or roi_config.get("quantity_roi"),
                    confidence_threshold=self._roi_threshold(roi_config),
                )
            elif mode in {"fragment_pair", "fragment_counts"}:
                fragment_result = self.card_reader.read_fragment_counts(
                    image,
                    card_roi=scaled_roi,
                    quantity_roi=roi_config.get("quantity_bbox") or roi_config.get("quantity_roi"),
                    confidence_threshold=self._roi_threshold(roi_config),
                )
                if fragment_result.success and fragment_result.fragment_count is not None:
                    fragment_required_value = fragment_result.required_count
                    ocr_result = OcrReadResult(
                        True,
                        "success",
                        fragment_result.message,
                        text=str(fragment_result.fragment_count),
                        value=int(fragment_result.fragment_count),
                        confidence=float(fragment_result.confidence),
                        raw_texts=fragment_result.raw_texts,
                        roi=fragment_result.roi,
                        warnings=fragment_result.warnings,
                    )
                else:
                    ocr_result = OcrReadResult(
                        False,
                        fragment_result.status,
                        fragment_result.message,
                        text=fragment_result.text,
                        confidence=float(fragment_result.confidence),
                        raw_texts=fragment_result.raw_texts,
                        roi=fragment_result.roi,
                        warnings=fragment_result.warnings,
                    )
            elif mode == "text":
                ocr_result = self.ocr_engine.recognize_text(
                    image,
                    roi=scaled_roi,
                    confidence_threshold=self._roi_threshold(roi_config),
                )
            else:
                ocr_result = self.ocr_engine.recognize_digits(
                    image,
                    roi=scaled_roi,
                    confidence_threshold=self._roi_threshold(roi_config),
                )

            if not ocr_result.success:
                if ocr_result.status in {"error", "unavailable"}:
                    hard_failures += 1
                warnings.extend(self._roi_warnings(roi_name, ocr_result))
                continue

            processed += 1
            roi_type = str(roi_config.get("kind") or roi_config.get("type") or "ui_element")
            field = str(roi_config.get("field") or roi_name)
            if roi_type == "resource" and field == "player_name":
                player_name = ocr_result.text
                resource_confidences.append(ocr_result.confidence)
                continue
            if roi_type == "resource":
                if ocr_result.value is not None:
                    resource_numbers[field] = int(ocr_result.value)
                    resource_confidences.append(ocr_result.confidence)
                    detections.append(self._detection(roi_name, roi_type, int(ocr_result.value), ocr_result))
                continue
            if roi_type in {"equipment_count", "fragment_count"}:
                equipment_id = str(roi_config.get("equipment_id", "")).strip()
                if not equipment_id:
                    warnings.append(f"{roi_name}: 装备 ROI 缺少 equipment_id，已跳过记录生成。")
                    continue
                state = equipment_state.setdefault(
                    equipment_id,
                    {"equipment_count": 0, "fragment_count": 0, "confidences": []},
                )
                state[roi_type] = int(ocr_result.value or 0)
                state["confidences"].append(float(ocr_result.confidence))
                detections.append(self._detection(roi_name, roi_type, int(ocr_result.value or 0), ocr_result))
                if roi_type == "fragment_count" and fragment_required_value is not None:
                    detections.append(
                        self._static_detection(
                            f"{roi_name}_required",
                            "ui_element",
                            int(fragment_required_value),
                            float(ocr_result.confidence),
                            ocr_result.roi or scaled_roi,
                        )
                    )
                continue
            if ocr_result.value is not None:
                detections.append(self._detection(roi_name, roi_type, int(ocr_result.value), ocr_result))

        equipment_records = self._equipment_records(equipment_state, warnings)
        resource_status = self._resource_status(player_name, resource_numbers, resource_confidences, warnings)
        if task_context is not None:
            task_context.raise_if_cancelled("OCR 任务已在完成安全点取消。")
            task_context.report_progress(100, "OCR 场景分析完成。", normalized_scene.value)

        success = bool(processed or equipment_records or resource_status or (not rois and hard_failures == 0))
        if rois and hard_failures >= len(rois):
            success = False
        message = "OCR 场景分析完成。" if success else "OCR 场景分析未获得可用结果。"
        return RecognitionResult(
            success,
            normalized_scene,
            screenshot_path=path_text,
            detections=tuple(detections),
            equipment_records=tuple(equipment_records),
            resource_status=resource_status,
            warnings=tuple(warnings),
            message=message,
        )

    def scale_roi(self, roi: Sequence[int], image: Any) -> Tuple[int, int, int, int]:
        """
        按基准分辨率缩放 ROI，并校验越界。
        输入：
            roi/image。
        输出：
            tuple[int, int, int, int]。
        使用示例：
            actual_roi = analyzer.scale_roi((100, 100, 200, 50), image)
        """
        base_width, base_height = self._base_resolution()
        if image is None or not hasattr(image, "shape"):
            raise ValueError("图像为空，无法缩放 ROI。")
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        x, y, width, height = (int(item) for item in roi)
        scale_x = image_width / float(base_width)
        scale_y = image_height / float(base_height)
        scaled = (
            int(round(x * scale_x)),
            int(round(y * scale_y)),
            max(1, int(round(width * scale_x))),
            max(1, int(round(height * scale_y))),
        )
        self.ocr_engine.validate_roi(image, scaled)
        return scaled

    def _failure(
        self,
        scene: RecognitionScene,
        screenshot_path: str,
        message: str,
        detail: str,
    ) -> RecognitionResult:
        """构造失败 RecognitionResult。"""
        return RecognitionResult(
            False,
            scene,
            screenshot_path=screenshot_path,
            warnings=(detail,),
            message=message,
            detail=detail,
        )

    def _base_resolution(self) -> Tuple[int, int]:
        """读取配置中的基准分辨率，默认 1280x720。"""
        value = self.config.get("base_resolution", {})
        if isinstance(value, dict):
            return int(value.get("width", 1280)), int(value.get("height", 720))
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return int(value[0]), int(value[1])
        return 1280, 720

    def _roi_threshold(self, roi_config: Dict[str, Any]) -> float:
        """读取 ROI 自定义阈值，缺省使用引擎阈值。"""
        return float(roi_config.get("confidence_threshold", self.ocr_engine.confidence_threshold))

    @staticmethod
    def _roi_from_config(roi_config: Dict[str, Any]) -> Tuple[int, int, int, int]:
        """从 ROI 配置读取 bbox/roi/region 字段。"""
        raw = roi_config.get("bbox") or roi_config.get("roi") or roi_config.get("region")
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            raise ValueError("ROI 配置必须包含 bbox=[x,y,w,h]。")
        return tuple(int(item) for item in raw)  # type: ignore[return-value]

    @staticmethod
    def _detection(
        label: str,
        roi_type: str,
        value: int,
        ocr_result: OcrReadResult,
    ) -> RecognitionDetection:
        """把 ROI OCR 结果转换为冻结检测契约。"""
        detection_type = {
            "equipment_count": RecognitionDetectionType.EQUIPMENT_COUNT,
            "fragment_count": RecognitionDetectionType.FRAGMENT_COUNT,
            "resource": RecognitionDetectionType.RESOURCE,
        }.get(roi_type, RecognitionDetectionType.UI_ELEMENT)
        return RecognitionDetection(
            label,
            detection_type,
            int(value),
            float(ocr_result.confidence),
            ocr_result.roi or (0, 0, 1, 1),
        )

    @staticmethod
    def _static_detection(
        label: str,
        roi_type: str,
        value: int,
        confidence: float,
        roi: Tuple[int, int, int, int],
    ) -> RecognitionDetection:
        """把固定 UI 区块或状态判断结果转成标准检测记录。"""
        detection_type = {
            "equipment_count": RecognitionDetectionType.EQUIPMENT_COUNT,
            "fragment_count": RecognitionDetectionType.FRAGMENT_COUNT,
            "resource": RecognitionDetectionType.RESOURCE,
        }.get(roi_type, RecognitionDetectionType.UI_ELEMENT)
        return RecognitionDetection(
            label,
            detection_type,
            int(value),
            max(0.0, min(1.0, float(confidence))),
            roi,
        )

    def _detect_roi_state(
        self,
        image: Any,
        roi: Sequence[int],
        roi_config: Dict[str, Any],
        fallback_confidence: float,
    ) -> Tuple[int, float]:
        """用 ROI 的颜色倾向判断按钮/筛选项是否处于选中态。"""
        rule = roi_config.get("state_rule", {})
        if not isinstance(rule, dict):
            rule = {}
        default_value = int(roi_config.get("default_value", roi_config.get("value", 0)))
        try:
            crop = self.ocr_engine.crop_roi(image, roi)
            red, green, blue = self._mean_rgb(crop, str(rule.get("channel_order", "bgr")))
        except Exception:
            return default_value, fallback_confidence

        color = str(rule.get("color", "warm")).lower()
        threshold = float(rule.get("threshold", 30.0))
        if color in {"warm", "gold", "orange", "yellow"}:
            score = ((red + green) / 2.0) - blue
        elif color in {"blue", "cool"}:
            score = blue - ((red + green) / 2.0)
        elif color == "bright":
            score = (red + green + blue) / 3.0
        else:
            score = ((red + green) / 2.0) - blue

        selected = score >= threshold
        expected = bool(roi_config.get("selected", True))
        value = 1 if selected == expected else 0
        confidence = min(1.0, max(0.0, fallback_confidence + min(abs(score - threshold) / 255.0, 0.2)))
        return value, confidence

    @staticmethod
    def _mean_rgb(image: Any, channel_order: str = "bgr") -> Tuple[float, float, float]:
        """计算 ROI 的 RGB 均值，兼容 OpenCV BGR 与普通 RGB 数组。"""
        if image is None or not hasattr(image, "shape") or len(image.shape) < 2:
            raise ValueError("ROI 图像为空，无法判断状态。")
        if len(image.shape) == 2:
            value = float(image.mean())
            return value, value, value
        order = channel_order.lower()
        first = float(image[:, :, 0].mean())
        second = float(image[:, :, 1].mean())
        third = float(image[:, :, 2].mean())
        if order == "rgb":
            return first, second, third
        return third, second, first

    @staticmethod
    def _equipment_records(
        equipment_state: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> List[EquipmentRecognitionRecord]:
        """从装备 ROI 状态生成 EquipmentRecognitionRecord。"""
        records: List[EquipmentRecognitionRecord] = []
        for equipment_id, state in equipment_state.items():
            confidences = [float(item) for item in state.get("confidences", [])]
            if not confidences:
                continue
            try:
                records.append(
                    EquipmentRecognitionRecord(
                        equipment_id,
                        int(state.get("equipment_count", 0)),
                        int(state.get("fragment_count", 0)),
                        min(confidences),
                    )
                )
            except ValueError as exc:
                warnings.append(f"{equipment_id}: {exc}")
        return records

    @staticmethod
    def _resource_status(
        player_name: str,
        resource_numbers: Dict[str, int],
        confidences: Iterable[float],
        warnings: List[str],
    ) -> Optional[ResourceRecognitionRecord]:
        """从港区资源 ROI 生成 ResourceRecognitionRecord。"""
        required = ("oil", "coins", "gems")
        missing = [field for field in required if field not in resource_numbers]
        if missing:
            if resource_numbers:
                warnings.append(f"资源字段缺失: {', '.join(missing)}。")
            return None
        confidence_values = [float(item) for item in confidences]
        confidence = min(confidence_values) if confidence_values else 0.0
        return ResourceRecognitionRecord(
            player_name,
            int(resource_numbers["oil"]),
            int(resource_numbers["coins"]),
            int(resource_numbers["gems"]),
            confidence,
        )

    def _calibration_warnings(self, scene_config: Dict[str, Any]) -> List[str]:
        """根据全局和场景校准状态生成 warning。"""
        warnings: List[str] = []
        calibration = self.config.get("calibration", {})
        if isinstance(calibration, dict) and calibration.get("status") != "calibrated":
            warnings.append(str(calibration.get("message", "ROI 配置待校准，当前结果不可宣称准确率。")))
        scene_calibration = scene_config.get("calibration", {})
        if isinstance(scene_calibration, dict) and scene_calibration.get("status") == "pending":
            warnings.append(str(scene_calibration.get("message", "当前场景 ROI 待真实截图标注校准。")))
        return warnings

    def _capture_frame_warning(self, image: Any, scene_config: Dict[str, Any]) -> str:
        """检查模拟器截图是否明显被裁半；不完整截图直接跳过识别。"""
        scene_capture = scene_config.get("capture_validation", {})
        if not isinstance(scene_capture, dict):
            scene_capture = {}
        global_capture = self.config.get("capture_validation", {})
        if not isinstance(global_capture, dict):
            global_capture = {}

        allow_partial = bool(scene_capture.get("allow_partial_image", global_capture.get("allow_partial_image", False)))
        if allow_partial:
            return ""
        if image is None or not hasattr(image, "shape") or len(image.shape) < 2:
            return "截图为空或维度异常，已跳过 OCR 识别。"

        base_width, base_height = self._base_resolution()
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        min_width_ratio = float(scene_capture.get("min_width_ratio", global_capture.get("min_width_ratio", 0.85)))
        min_height_ratio = float(scene_capture.get("min_height_ratio", global_capture.get("min_height_ratio", 0.85)))
        max_aspect_delta = float(scene_capture.get("max_aspect_delta", global_capture.get("max_aspect_delta", 0.12)))

        width_ratio = image_width / float(max(1, base_width))
        height_ratio = image_height / float(max(1, base_height))
        expected_aspect = base_width / float(max(1, base_height))
        actual_aspect = image_width / float(max(1, image_height))
        aspect_delta = abs(actual_aspect - expected_aspect) / float(max(expected_aspect, 1e-6))

        if width_ratio < min_width_ratio or height_ratio < min_height_ratio:
            return (
                f"截图尺寸疑似不完整: actual={image_width}x{image_height}, "
                f"base={base_width}x{base_height}, "
                f"width_ratio={width_ratio:.2f}, height_ratio={height_ratio:.2f}。"
            )
        if aspect_delta > max_aspect_delta:
            return (
                f"截图宽高比异常: actual={image_width}x{image_height}, "
                f"base={base_width}x{base_height}, aspect_delta={aspect_delta:.2f}。"
            )
        return ""

    def _screen_state_probe_enabled(self, scene: RecognitionScene) -> bool:
        """判断是否在港区分析前先做登录/加载/港区状态探针。"""
        if scene is not RecognitionScene.HARBOR:
            return False
        state_config = self.config.get("screen_state_detection", {})
        if not isinstance(state_config, dict):
            return False
        return bool(state_config.get("enabled", False))

    def _get_screen_state_detector(self) -> Any:
        """延迟创建页面状态识别器，避免循环导入和 GUI 启动负担。"""
        if self._screen_state_detector is None:
            from core.recognition.screen_state_detector import ScreenStateDetector

            self._screen_state_detector = ScreenStateDetector(config=self.config, ocr_engine=self.ocr_engine)
        return self._screen_state_detector

    @staticmethod
    def _roi_warnings(roi_name: str, result: OcrReadResult) -> List[str]:
        """把 ROI 结果压缩成 warnings。"""
        warnings = [f"{roi_name}: {result.message}"]
        warnings.extend(f"{roi_name}: {item}" for item in result.warnings)
        return warnings

    @staticmethod
    def _load_config(path: Path) -> Dict[str, Any]:
        """只读加载 ROI 配置，缺失时返回最小配置。"""
        if not path.exists():
            return {
                "schema_version": "0.6.0",
                "base_resolution": {"width": 1280, "height": 720},
                "calibration": {"status": "pending", "message": "ROI 配置文件缺失，识别待校准。"},
                "scenes": {scene.value: {"rois": []} for scene in RecognitionScene},
            }
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
