#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🔎 OCR 识别任务接口 (ocr_task_api.py)            ║
║                                                              ║
║  【一句话解释】为 v0.6.0 装备与资源 OCR 提供稳定调用入口。     ║
║  【类比理解】它像港区识别镜架，镜片没装好也会温和提示原因。    ║
║  【数据流说明】截图路径 → 场景分析 → 标准识别结果 → GUI/数据层。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.contracts import (
    RecognitionDetection,
    RecognitionDetectionType,
    RecognitionResult,
    RecognitionScene,
    ResourceRecognitionRecord,
    StructuredTaskResult,
    TaskCancelledError,
    TaskExecutionContext,
)
from core.recognition.harbor_resource_detector import HarborResourceDetector, HarborResourceResult
from core.recognition.ocr_engine import OcrEngine
from core.recognition.equipment_page_reader import EquipmentPageReader
from core.recognition.research_design_reader import ResearchDesignReader
from core.recognition.scene_analyzer import SceneAnalyzer
from core.recognition.screen_state_detector import ScreenStateDetector, ScreenStateResult
from core.recognition.template_matcher import TemplateMatcher
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class OcrDetection:
    """
    装备页 OCR 可写入候选。
    输入：
        equipment_id/equipment_count/fragment_count/confidence。
    输出：
        Integration 层可直接映射到 UserDataManager 的稳定字段。
    使用示例：
        detection = OcrDetection("S1-001", 2, 0, 0.91)
    """

    equipment_id: str
    equipment_count: int
    fragment_count: int
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        """转换成基础 Python 字典，便于 GUI、日志和测试断言。"""
        return {
            "equipment_id": self.equipment_id,
            "equipment_count": int(self.equipment_count),
            "fragment_count": int(self.fragment_count),
            "confidence": float(self.confidence),
        }


@dataclass(frozen=True)
class OCRResult:
    """
    run_ocr_task 顶层返回契约。
    输入：
        scene/detections/success/status/message/warnings/payload。
    输出：
        与用户指定 OCRResult(scene="equipment_list", detections=[...]) 兼容。
    使用示例：
        result = run_ocr_task("shot.png", "equipment_list")
    """

    scene: str
    detections: Tuple[OcrDetection, ...] = ()
    success: bool = True
    status: str = "success"
    message: str = ""
    warnings: Tuple[str, ...] = ()
    payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换成可序列化字典。"""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "scene": self.scene,
            "detections": [item.to_dict() for item in self.detections],
            "warnings": list(self.warnings),
            "payload": self.payload,
        }


class OcrTaskResult(StructuredTaskResult):
    """
    OCR 任务执行结果。
    输入：
        success: 接口是否安全完成。
        status: reserved / success / unavailable / error / cancelled。
        message: 用户可见说明。
        detail: 给测试或开发者看的补充信息。
        payload: 后续真实 OCR 继续沿用的结构化数据。
        warnings: 不阻塞任务完成的识别警告列表。
    输出：
        不可变结果对象，可被 AutomationBridge 转成 GUI 结果。
    使用示例：
        result = get_ocr_task_api().scan_equipment_counts()
    """


class OcrTaskApi:
    """
    OCR 识别任务 API。
    输入：
        可选 scene_analyzer/ocr_engine/config 注入，便于测试和外部模型接入。
    输出：
        无截图时保持预检结果；有截图时执行真实场景分析。
    使用示例：
        api = OcrTaskApi()
        api.scan_resource_status()
    """

    _instance: Optional["OcrTaskApi"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "OcrTaskApi":
        """单例模式：默认复用 API；测试注入时创建独立实例。"""
        use_singleton = bool(kwargs.get("use_singleton", True))
        has_injection = any(
            key in kwargs and kwargs[key] is not None
            for key in (
                "scene_analyzer",
                "ocr_engine",
                "template_matcher",
                "harbor_resource_detector",
                "equipment_page_reader",
                "research_design_reader",
                "screen_state_detector",
                "config",
                "config_path",
            )
        )
        if not use_singleton or has_injection:
            return super().__new__(cls)
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        scene_analyzer: Optional[SceneAnalyzer] = None,
        ocr_engine: Optional[OcrEngine] = None,
        template_matcher: Optional[TemplateMatcher] = None,
        harbor_resource_detector: Optional[HarborResourceDetector] = None,
        equipment_page_reader: Optional[EquipmentPageReader] = None,
        research_design_reader: Optional[ResearchDesignReader] = None,
        screen_state_detector: Optional[ScreenStateDetector] = None,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str | Path] = None,
        use_singleton: bool = True,
    ) -> None:
        """初始化 OCR API，默认不加载 PaddleOCR 模型。"""
        if (
            hasattr(self, "_initialized")
            and scene_analyzer is None
            and ocr_engine is None
            and template_matcher is None
            and harbor_resource_detector is None
            and equipment_page_reader is None
            and research_design_reader is None
            and screen_state_detector is None
            and config is None
        ):
            return
        self.logger = get_logger()
        self.config_loader = get_config_loader()
        self._scene_analyzer = scene_analyzer
        self._ocr_engine = ocr_engine
        self._template_matcher = template_matcher
        self._harbor_resource_detector = harbor_resource_detector
        self._equipment_page_reader = equipment_page_reader
        self._research_design_reader = research_design_reader
        self._screen_state_detector = screen_state_detector
        self._config = config
        self._config_path = Path(config_path) if config_path is not None else None
        self._initialized = True

    def scan_equipment_counts(
        self,
        screenshot_path: Optional[str] = None,
        scene: RecognitionScene | str = RecognitionScene.EQUIPMENT_LIST,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> OcrTaskResult:
        """
        装备数量与碎片数量识别入口。
        输入：
            screenshot_path: 可选截图路径；为空时只返回预检契约。
            scene: 截图所属的稳定游戏场景。
            task_context: 可选任务上下文，用于在安全点响应取消。
        输出：
            OcrTaskResult: 标准装备识别结果结构。
        使用示例：
            result = api.scan_equipment_counts("workdir/automation/screenshots/a.png")
        """
        if task_context is not None:
            task_context.raise_if_cancelled("装备 OCR 任务已取消。")
        normalized_scene = RecognitionScene.normalize(scene)
        if screenshot_path is None:
            return self._reserved_equipment_result(normalized_scene, screenshot_path)
        if normalized_scene is RecognitionScene.RESEARCH:
            return self._scan_research_designs(screenshot_path, normalized_scene, task_context)
        if normalized_scene is RecognitionScene.EQUIPMENT_LIST and self._scene_analyzer is None:
            return self._scan_equipment_page(screenshot_path, normalized_scene, task_context)
        return self._scan_with_analyzer(
            "equipment_counts",
            screenshot_path,
            normalized_scene,
            self._equipment_result_schema(),
            task_context,
        )

    def scan_resource_status(
        self,
        screenshot_path: Optional[str] = None,
        scene: RecognitionScene | str = RecognitionScene.HARBOR,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> OcrTaskResult:
        """
        玩家资源识别入口。
        输入：
            screenshot_path: 可选截图路径；为空时只返回预检契约。
            scene: 截图所属的稳定游戏场景。
            task_context: 可选任务上下文，用于在安全点响应取消。
        输出：
            OcrTaskResult: 标准玩家资源识别结果结构。
        使用示例：
            result = api.scan_resource_status("workdir/automation/screenshots/harbor.png")
        """
        if task_context is not None:
            task_context.raise_if_cancelled("资源 OCR 任务已取消。")
        normalized_scene = RecognitionScene.normalize(scene)
        if screenshot_path is None:
            return self._reserved_resource_result(normalized_scene, screenshot_path)
        if normalized_scene is RecognitionScene.HARBOR:
            return self._scan_harbor_resource_status(screenshot_path, normalized_scene, task_context)
        return self._scan_with_analyzer(
            "resource_status",
            screenshot_path,
            normalized_scene,
            self._resource_result_schema(),
            task_context,
        )

    def run_ocr_task(
        self,
        screenshot_path: str | Path,
        scene: RecognitionScene | str = RecognitionScene.HARBOR,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> OcrTaskResult:
        """
        ADB 截图进入 OCR 层的统一任务入口。
        输入：
            screenshot_path: ADB 层输出的绝对截图路径。
            scene: 期望场景；登录/加载/低置信会保守返回 unknown。
            task_context: 可选任务上下文，用于在安全点响应取消。
        输出：
            OcrTaskResult，payload 中包含 screen_state 和 state_recognition。
        使用示例：
            result = api.run_ocr_task("G:/adb/frame_0001.png", "harbor")
        """
        if task_context is not None:
            task_context.raise_if_cancelled("OCR 任务已取消。")
        normalized_scene, scene_warning = self._safe_normalize_scene(scene)
        path = Path(screenshot_path)
        if not path.exists() or not path.is_file():
            message = "截图文件不存在，无法执行 OCR。"
            payload = self._base_scan_payload("screen_state", RecognitionScene.UNKNOWN, str(screenshot_path), self._resource_result_schema())
            payload["screen_state"] = "unknown"
            payload["state_recognition"] = None
            warnings = self._merge_warnings(scene_warning, message)
            return OcrTaskResult(False, "error", message, str(path), payload, warnings=warnings)

        if normalized_scene is RecognitionScene.EQUIPMENT_LIST:
            return self.scan_equipment_counts(str(path), normalized_scene, task_context=task_context)
        if normalized_scene is RecognitionScene.RESEARCH:
            return self._scan_research_designs(str(path), normalized_scene, task_context)
        if normalized_scene is RecognitionScene.PHASE_SELECT:
            return self._phase_select_result(str(path), scene_warning)
        if normalized_scene in {RecognitionScene.HARBOR, RecognitionScene.UNKNOWN}:
            return self._scan_harbor_screen_state(str(path), task_context, scene_warning)
        return self._scan_with_analyzer(
            "generic_scene",
            str(path),
            normalized_scene,
            self._resource_result_schema(),
            task_context,
        )

    def check_engine(self, task_context: Optional[TaskExecutionContext] = None) -> OcrTaskResult:
        """
        检查 OCR 引擎依赖状态。
        输入：
            task_context: 可选任务上下文，用于在安全点响应取消。
        输出：
            OcrTaskResult: OpenCV/PaddleOCR/本地模型目录是否可用。
        使用示例：
            result = api.check_engine()
        """
        if task_context is not None:
            task_context.raise_if_cancelled("OCR 引擎检查已取消。")
        recognition = self._recognition_config()
        engine = self._ocr_engine or OcrEngine(config=self._roi_ocr_config())
        matcher = self._template_matcher or TemplateMatcher()
        engine_status = engine.check_status()
        matcher_status = matcher.check_status()
        dependencies = {
            "opencv_cv2": bool(engine_status["dependencies"].get("opencv_cv2")),
            "numpy": bool(engine_status["dependencies"].get("numpy")),
            "paddleocr": bool(engine_status["dependencies"].get("paddleocr")),
        }
        threshold = self._roi_ocr_config().get("confidence_threshold", recognition.get("confidence_threshold", 0.8))
        warnings = tuple(engine_status.get("warnings", ()))
        payload = {
            "dependencies": dependencies,
            "template_matching": matcher_status,
            "confidence_threshold": threshold,
            "local_model_configured": bool(engine_status.get("local_model_configured")),
            "real_ocr_enabled": bool(engine_status.get("available")),
            "warnings": list(warnings),
        }
        ready_count = sum(1 for available in dependencies.values() if available)
        detail = f"OCR依赖可用={ready_count}/{len(dependencies)}；置信度阈值={threshold}"
        message = "OCR 引擎预检完成：未在预检阶段加载模型，避免 GUI 启动变慢。"
        self.logger.info(message)
        return OcrTaskResult(True, "reserved", message, detail, payload, warnings)

    def _scan_with_analyzer(
        self,
        target: str,
        screenshot_path: str,
        scene: RecognitionScene,
        result_schema: List[Dict[str, str]],
        task_context: Optional[TaskExecutionContext],
    ) -> OcrTaskResult:
        """执行真实场景分析并转换成 OcrTaskResult。"""
        if task_context is not None:
            task_context.raise_if_cancelled("OCR 任务已取消。")
        path = Path(screenshot_path)
        if not path.exists() or not path.is_file():
            message = "截图文件不存在，无法执行 OCR。"
            payload = self._base_scan_payload(target, scene, screenshot_path, result_schema)
            return OcrTaskResult(False, "error", message, str(path), payload, warnings=(message,))

        try:
            recognition = self._get_scene_analyzer().analyze(path, scene, task_context=task_context)
        except TaskCancelledError:
            raise
        except Exception as exc:
            message = "OCR 识别执行失败，请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.logger.exception(message)
            payload = self._base_scan_payload(target, scene, screenshot_path, result_schema)
            return OcrTaskResult(False, "error", message, detail, payload, warnings=(detail,))

        payload = self._payload_from_recognition(target, result_schema, recognition)
        warnings = tuple(recognition.warnings)
        if recognition.success:
            message = "装备 OCR 识别完成。" if target == "equipment_counts" else "资源 OCR 识别完成。"
            status = "success"
        elif self._looks_unavailable(recognition):
            message = recognition.message or "OCR 引擎不可用，无法完成识别。"
            status = "unavailable"
        else:
            message = recognition.message or "OCR 未获得可用识别结果。"
            status = "error"
        detail = recognition.detail or f"scene={recognition.scene.value}; detections={len(recognition.detections)}"
        return OcrTaskResult(recognition.success, status, message, detail, payload, warnings)

    def _scan_research_designs(
        self,
        screenshot_path: str,
        scene: RecognitionScene,
        task_context: Optional[TaskExecutionContext],
    ) -> OcrTaskResult:
        """使用科研设计图专用 reader 识别单帧或 ADB manifest。"""
        if task_context is not None:
            task_context.raise_if_cancelled("科研设计图 OCR 任务已取消。")
        path = Path(screenshot_path)
        if not path.exists() or not path.is_file():
            message = "科研设计图截图或 manifest 不存在，无法执行 OCR。"
            payload = self._base_scan_payload("research_designs", scene, screenshot_path, self._equipment_result_schema())
            return OcrTaskResult(False, "error", message, str(path), payload, warnings=(message,))

        try:
            recognition = self._get_research_design_reader().analyze(path, task_context=task_context)
        except TaskCancelledError:
            raise
        except Exception as exc:
            message = "科研设计图 OCR 识别执行失败，请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.logger.exception(message)
            payload = self._base_scan_payload("research_designs", scene, screenshot_path, self._equipment_result_schema())
            return OcrTaskResult(False, "error", message, detail, payload, warnings=(detail,))

        payload = self._payload_from_recognition("research_designs", self._equipment_result_schema(), recognition)
        warnings = tuple(recognition.warnings)
        if recognition.success:
            status = "success"
            message = "科研设计图 OCR 识别完成。"
        elif self._looks_unavailable(recognition):
            status = "unavailable"
            message = recognition.message or "OCR 引擎不可用，无法完成科研设计图识别。"
        else:
            status = "needs_review"
            message = recognition.message or "科研设计图 OCR 没有可自动写入的候选。"
        detail = recognition.detail or f"scene={recognition.scene.value}; records={len(recognition.equipment_records)}"
        return OcrTaskResult(recognition.success, status, message, detail, payload, warnings)

    def _scan_equipment_page(
        self,
        screenshot_path: str,
        scene: RecognitionScene,
        task_context: Optional[TaskExecutionContext],
    ) -> OcrTaskResult:
        """使用装备页专用 reader 识别单帧或 ADB manifest。"""
        if task_context is not None:
            task_context.raise_if_cancelled("装备页 OCR 任务已取消。")
        path = Path(screenshot_path)
        if not path.exists() or not path.is_file():
            message = "截图文件不存在，无法执行 OCR。"
            payload = self._base_scan_payload("equipment_counts", scene, screenshot_path, self._equipment_result_schema())
            return OcrTaskResult(False, "error", message, str(path), payload, warnings=(message,))

        try:
            recognition = self._get_equipment_page_reader().analyze(path, task_context=task_context)
        except TaskCancelledError:
            raise
        except Exception as exc:
            message = "装备页 OCR 识别执行失败，请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.logger.exception(message)
            payload = self._base_scan_payload("equipment_counts", scene, screenshot_path, self._equipment_result_schema())
            return OcrTaskResult(False, "error", message, detail, payload, warnings=(detail,))

        payload = self._payload_from_recognition("equipment_counts", self._equipment_result_schema(), recognition)
        warnings = tuple(recognition.warnings)
        if recognition.success:
            status = "success"
            message = "装备 OCR 识别完成。"
        elif self._looks_unavailable(recognition):
            status = "unavailable"
            message = recognition.message or "OCR 引擎不可用，无法完成装备页识别。"
        else:
            status = "needs_review"
            message = recognition.message or "装备页 OCR 没有可自动写入的候选。"
        detail = recognition.detail or f"scene={recognition.scene.value}; records={len(recognition.equipment_records)}"
        return OcrTaskResult(recognition.success, status, message, detail, payload, warnings)

    def _scan_harbor_resource_status(
        self,
        screenshot_path: str,
        scene: RecognitionScene,
        task_context: Optional[TaskExecutionContext],
    ) -> OcrTaskResult:
        """使用港区资源专用检测器识别新旧 UI，并转换成正式 OCR API 结果。"""
        if task_context is not None:
            task_context.raise_if_cancelled("资源 OCR 任务已取消。")
        path = Path(screenshot_path)
        if not path.exists() or not path.is_file():
            message = "截图文件不存在，无法执行 OCR。"
            payload = self._base_scan_payload("resource_status", scene, screenshot_path, self._resource_result_schema())
            return OcrTaskResult(False, "error", message, str(path), payload, warnings=(message,))

        try:
            harbor_result = self._get_harbor_resource_detector().detect(path)
            if task_context is not None:
                task_context.raise_if_cancelled("资源 OCR 任务已取消。")
            recognition = self._recognition_from_harbor_result(harbor_result, scene, str(path))
        except TaskCancelledError:
            raise
        except Exception as exc:
            message = "港区资源 OCR 识别执行失败，请复制运行日志给开发者。"
            detail = f"{type(exc).__name__}: {exc}"
            self.logger.exception(message)
            payload = self._base_scan_payload("resource_status", scene, screenshot_path, self._resource_result_schema())
            return OcrTaskResult(False, "error", message, detail, payload, warnings=(detail,))

        payload = self._payload_from_recognition("resource_status", self._resource_result_schema(), recognition)
        payload["ui_version"] = harbor_result.ui_version
        payload["harbor_status"] = harbor_result.status
        payload["resource_rois"] = {name: list(box) for name, box in harbor_result.rois.items()}
        payload["harbor_fields"] = {name: value.to_dict() for name, value in harbor_result.fields.items()}

        warnings = tuple(recognition.warnings)
        if harbor_result.success:
            status = "success"
            message = "资源 OCR 识别完成。"
        elif harbor_result.status == "unavailable" or self._looks_harbor_unavailable(harbor_result):
            status = "unavailable"
            message = harbor_result.message or "OCR 引擎不可用，无法完成港区资源识别。"
        else:
            status = "error"
            message = harbor_result.message or "港区资源 OCR 未获得完整可用结果。"
        detail = recognition.detail or f"harbor_status={harbor_result.status}; ui={harbor_result.ui_version}"
        return OcrTaskResult(harbor_result.success, status, message, detail, payload, warnings)

    def _get_scene_analyzer(self) -> SceneAnalyzer:
        """延迟创建场景分析器。"""
        if self._scene_analyzer is None:
            self._scene_analyzer = SceneAnalyzer(
                ocr_engine=self._ocr_engine,
                template_matcher=self._template_matcher,
                config=self._config,
                config_path=self._config_path,
            )
        return self._scene_analyzer

    def _get_harbor_resource_detector(self) -> HarborResourceDetector:
        """延迟创建港区资源专用检测器，避免 GUI 启动时加载 OCR 模型。"""
        if self._harbor_resource_detector is None:
            self._harbor_resource_detector = HarborResourceDetector(ocr_engine=self._ocr_engine)
        return self._harbor_resource_detector

    def _get_screen_state_detector(self) -> ScreenStateDetector:
        """延迟创建登录/加载/港区页面状态识别器。"""
        if self._screen_state_detector is None:
            self._screen_state_detector = ScreenStateDetector(config=self._full_roi_config(), ocr_engine=self._ocr_engine)
        return self._screen_state_detector

    def _scan_harbor_screen_state(
        self,
        screenshot_path: str,
        task_context: Optional[TaskExecutionContext],
        scene_warning: str = "",
    ) -> OcrTaskResult:
        """先判断登录/加载/港区，再决定是否执行港区资源 OCR。"""
        state_result = self._get_screen_state_detector().detect(screenshot_path, task_context=task_context)
        if task_context is not None:
            task_context.raise_if_cancelled("OCR 页面状态识别后任务已取消。")

        if not state_result.success:
            payload = self._payload_from_screen_state(state_result, self._resource_result_schema())
            warnings = self._merge_warnings(scene_warning, *state_result.warnings)
            return OcrTaskResult(False, state_result.status, state_result.message, state_result.detail, payload, warnings)

        if state_result.screen_state != "harbor":
            payload = self._payload_from_screen_state(state_result, self._resource_result_schema())
            status = "success" if state_result.screen_state in {"login", "loading"} else "unknown"
            warnings = self._merge_warnings(scene_warning, *state_result.warnings)
            return OcrTaskResult(True, status, state_result.message, state_result.detail, payload, warnings)

        resource_result = self._scan_harbor_resource_status(screenshot_path, RecognitionScene.HARBOR, task_context)
        state_payload = self._payload_from_screen_state(state_result, self._resource_result_schema())
        payload = dict(state_payload)
        payload.update(dict(resource_result.payload or {}))
        payload["screen_state"] = state_result.screen_state
        payload["scene_hint"] = state_result.screen_state
        payload["confidence"] = float(state_result.confidence)
        payload["state_recognition"] = state_payload["state_recognition"]
        payload["state_detections"] = state_payload["state_detections"]
        payload["suggested_action"] = state_result.suggested_action
        payload["target"] = "screen_state"
        payload["scene"] = RecognitionScene.HARBOR.value
        payload["resource_ocr_status"] = resource_result.status
        payload["resource_ocr_message"] = resource_result.message
        payload["real_ocr_enabled"] = bool(resource_result.success)
        warnings = self._merge_warnings(scene_warning, *state_result.warnings, *resource_result.warnings)
        detail = (
            f"screen_state=harbor; confidence={state_result.confidence:.3f}; "
            f"resource_status={resource_result.status}; {state_result.detail}"
        )
        return OcrTaskResult(True, "success", "港区主界面识别完成。", detail, payload, warnings)

    def _get_equipment_page_reader(self) -> EquipmentPageReader:
        """延迟创建装备页专用识别器，避免预检阶段加载图库和 OCR 模型。"""
        if self._equipment_page_reader is None:
            self._equipment_page_reader = EquipmentPageReader(
                ocr_engine=self._ocr_engine,
                config=self._config,
                config_path=self._config_path,
            )
        return self._equipment_page_reader

    def _get_research_design_reader(self) -> ResearchDesignReader:
        """延迟创建科研设计图专用识别器，避免预检阶段加载图库和 OCR 模型。"""
        if self._research_design_reader is None:
            self._research_design_reader = ResearchDesignReader(
                ocr_engine=self._ocr_engine,
                config=self._config,
                config_path=self._config_path,
            )
        return self._research_design_reader

    def _phase_select_result(self, screenshot_path: str, scene_warning: str = "") -> OcrTaskResult:
        """科研期数选择页不是设计图列表，直接返回无检测结果。"""
        message = "phase_select 是科研期数选择页，OCR 不执行科研设计图卡片识别。"
        payload = self._base_scan_payload(
            "phase_select",
            RecognitionScene.PHASE_SELECT,
            screenshot_path,
            self._equipment_result_schema(),
        )
        payload["real_ocr_enabled"] = False
        payload["phase_select_recognition"] = {
            "scene": RecognitionScene.PHASE_SELECT.value,
            "detections": [],
            "equipment_records": [],
        }
        warnings = self._merge_warnings(scene_warning, message)
        return OcrTaskResult(True, "reserved", message, "phase_select_no_research_detection", payload, warnings)

    def _recognition_from_harbor_result(
        self,
        harbor_result: HarborResourceResult,
        scene: RecognitionScene,
        screenshot_path: str,
    ) -> RecognitionResult:
        """把 HarborResourceResult 转换为共享 RecognitionResult 契约。"""
        warnings = tuple(harbor_result.warnings)
        if not harbor_result.success and harbor_result.message and harbor_result.message not in warnings:
            warnings = (harbor_result.message, *warnings)

        resource_status: Optional[ResourceRecognitionRecord] = None
        if harbor_result.success and harbor_result.oil is not None and harbor_result.coins is not None and harbor_result.gems is not None:
            resource_status = ResourceRecognitionRecord(
                harbor_result.player_name,
                int(harbor_result.oil),
                int(harbor_result.coins),
                int(harbor_result.gems),
                self._clamp_confidence(harbor_result.confidence),
            )

        detections: List[RecognitionDetection] = []
        for field_name in ("oil", "coins", "gems"):
            value = getattr(harbor_result, field_name)
            roi = harbor_result.rois.get(field_name)
            if value is None or roi is None:
                continue
            field_result = harbor_result.fields.get(field_name)
            confidence = field_result.confidence if field_result is not None else harbor_result.confidence
            detections.append(
                RecognitionDetection(
                    field_name,
                    RecognitionDetectionType.RESOURCE,
                    int(value),
                    self._clamp_confidence(confidence),
                    tuple(int(item) for item in roi),
                )
            )

        return RecognitionResult(
            harbor_result.success,
            scene,
            screenshot_path=screenshot_path,
            detections=tuple(detections),
            resource_status=resource_status,
            warnings=warnings,
            message=harbor_result.message,
            detail=f"harbor_status={harbor_result.status}; ui={harbor_result.ui_version}; detections={len(detections)}",
        )

    def _payload_from_recognition(
        self,
        target: str,
        result_schema: List[Dict[str, str]],
        recognition: RecognitionResult,
    ) -> Dict[str, Any]:
        """把 RecognitionResult 转换为 OCR API payload。"""
        payload = self._base_scan_payload(target, recognition.scene, recognition.screenshot_path, result_schema)
        recognition_payload = recognition.to_payload()
        payload.update(recognition_payload)
        payload["target"] = target
        payload["result_schema"] = result_schema
        payload["real_ocr_enabled"] = bool(recognition.success)
        return payload

    def _payload_from_screen_state(
        self,
        state_result: ScreenStateResult,
        result_schema: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """把页面状态结果转换成 OCR API payload。"""
        payload = self._base_scan_payload("screen_state", state_result.scene, state_result.screenshot_path, result_schema)
        state_payload = state_result.to_dict()
        payload["scene"] = state_result.scene.value
        payload["screen_state"] = state_result.screen_state
        payload["scene_hint"] = state_result.screen_state
        payload["confidence"] = float(state_result.confidence)
        payload["state_recognition"] = state_payload
        payload["state_detections"] = state_payload["detections"]
        payload["suggested_action"] = state_result.suggested_action
        payload["ui_version"] = state_result.ui_version
        payload["real_ocr_enabled"] = False
        return payload

    def _reserved_equipment_result(
        self,
        scene: RecognitionScene,
        screenshot_path: Optional[str],
    ) -> OcrTaskResult:
        """返回旧接口兼容的装备预检结果。"""
        recognition = self._recognition_config()
        payload = {
            "target": "equipment_counts",
            "scene": scene.value,
            "screenshot_path": screenshot_path,
            "regions": {
                "equipment_region": recognition.get("equipment_region", []),
                "fragment_region": recognition.get("fragment_region", []),
            },
            "result_schema": self._equipment_result_schema(),
            "detections": [],
            "equipment_records": [],
            "warnings": [],
            "real_ocr_enabled": False,
        }
        detail = "字段=equipment_id, equipment_count, fragment_count；真实 OCR=未启用"
        message = "装备 OCR 接口预检完成：已固定结果结构，等待 v0.6.0 接入截图识别。"
        self.logger.info(message)
        return OcrTaskResult(True, "reserved", message, detail, payload)

    def _reserved_resource_result(
        self,
        scene: RecognitionScene,
        screenshot_path: Optional[str],
    ) -> OcrTaskResult:
        """返回旧接口兼容的资源预检结果。"""
        payload = {
            "target": "resource_status",
            "scene": scene.value,
            "screenshot_path": screenshot_path,
            "result_schema": self._resource_result_schema(),
            "detections": [],
            "resource_status": None,
            "warnings": [],
            "real_ocr_enabled": False,
        }
        detail = "字段=player_name, oil, coins, gems；真实 OCR=未启用"
        message = "资源 OCR 接口预检完成：已固定玩家资源结构，后续可直接刷新港区实况。"
        self.logger.info(message)
        return OcrTaskResult(True, "reserved", message, detail, payload)

    def _base_scan_payload(
        self,
        target: str,
        scene: RecognitionScene,
        screenshot_path: Optional[str],
        result_schema: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """构造识别 payload 基础结构。"""
        payload: Dict[str, Any] = {
            "target": target,
            "scene": scene.value,
            "screenshot_path": screenshot_path,
            "result_schema": result_schema,
            "detections": [],
            "equipment_records": [],
            "resource_status": None,
            "warnings": [],
            "real_ocr_enabled": False,
        }
        return payload

    def _recognition_config(self) -> Dict[str, Any]:
        """
        读取旧游戏识别配置。
        输入：
            无。
        输出：
            dict: recognition 配置，缺失时返回空字典。
        使用示例：
            config = self._recognition_config()
        """
        game_config = self.config_loader.get_game_config()
        recognition = game_config.get("recognition", {}) if isinstance(game_config, dict) else {}
        return recognition if isinstance(recognition, dict) else {}

    def _roi_ocr_config(self) -> Dict[str, Any]:
        """读取新 ROI 配置中的 OCR 段，失败时返回空字典。"""
        ocr_config = self._full_roi_config().get("ocr", {})
        return ocr_config if isinstance(ocr_config, dict) else {}

    def _full_roi_config(self) -> Dict[str, Any]:
        """读取完整 ROI 配置，供页面状态探针和 OCR 引擎共用。"""
        if self._config is not None:
            return self._config
        path = self._config_path or SceneAnalyzer.DEFAULT_CONFIG_PATH
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = __import__("json").load(file)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _looks_unavailable(recognition: RecognitionResult) -> bool:
        """根据 detail/warnings 判断失败是否属于依赖或模型不可用。"""
        text = " ".join([recognition.message, recognition.detail, *recognition.warnings])
        markers = ("不可用", "OpenCV", "PaddleOCR", "模型", "unavailable", "cv2")
        return any(marker in text for marker in markers)

    @staticmethod
    def _looks_harbor_unavailable(harbor_result: HarborResourceResult) -> bool:
        """根据港区检测器结果判断失败是否属于依赖或本地模型不可用。"""
        text = " ".join([harbor_result.status, harbor_result.message, *harbor_result.warnings])
        markers = ("不可用", "OpenCV", "PaddleOCR", "模型", "unavailable", "cv2")
        return any(marker in text for marker in markers)

    @staticmethod
    def _clamp_confidence(value: float) -> float:
        """把置信度压回契约允许的 0.0 到 1.0 区间。"""
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _safe_normalize_scene(scene: RecognitionScene | str) -> tuple[RecognitionScene, str]:
        """把外部场景字符串安全转换为 RecognitionScene。"""
        try:
            return RecognitionScene.normalize(scene), ""
        except ValueError:
            return RecognitionScene.UNKNOWN, f"未知场景 {scene}，已按 unknown 处理。"

    @staticmethod
    def _merge_warnings(*items: str) -> tuple[str, ...]:
        """合并 warning 并去重，保持原始顺序。"""
        merged: List[str] = []
        for item in items:
            if item and item not in merged:
                merged.append(item)
        return tuple(merged)

    @staticmethod
    def _equipment_result_schema() -> List[Dict[str, str]]:
        """返回装备识别结果的字段契约。"""
        return [
            {"name": "equipment_id", "type": "str", "description": "装备 ID，如 S9-001 或 G0001"},
            {"name": "equipment_count", "type": "int", "description": "当前已拥有整装数量"},
            {"name": "fragment_count", "type": "int", "description": "当前装备碎片数量"},
            {"name": "confidence", "type": "float", "description": "OCR 或模板匹配置信度"},
        ]

    @staticmethod
    def _resource_result_schema() -> List[Dict[str, str]]:
        """返回玩家资源识别结果的字段契约。"""
        return [
            {"name": "player_name", "type": "str", "description": "玩家名称"},
            {"name": "oil", "type": "int", "description": "石油数量"},
            {"name": "coins", "type": "int", "description": "物资数量"},
            {"name": "gems", "type": "int", "description": "钻石数量"},
            {"name": "confidence", "type": "float", "description": "资源区域识别置信度"},
        ]

    @classmethod
    def reset_for_tests(cls) -> None:
        """清理 OCR API 单例，供测试隔离使用。"""
        global _ocr_task_api
        cls._instance = None
        _ocr_task_api = None


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_ocr_task_api: Optional[OcrTaskApi] = None


def get_ocr_task_api() -> OcrTaskApi:
    """
    获取全局 OCR 任务 API。
    输入：
        无。
    输出：
        OcrTaskApi: 全局共享 API。
    使用示例：
        api = get_ocr_task_api()
    """
    global _ocr_task_api
    if _ocr_task_api is None:
        _ocr_task_api = OcrTaskApi()
    return _ocr_task_api


def run_ocr_task(
    screenshot_path: str | Path,
    scene: RecognitionScene | str = RecognitionScene.HARBOR,
    task_context: Optional[TaskExecutionContext] = None,
) -> OCRResult:
    """
    OCR 顶层任务入口。
    输入：
        screenshot_path: ADB 输出的绝对截图路径，或装备页 manifest/scroll_session.json。
        scene: 期望场景；登录/加载/低置信会返回 scene="unknown"。
        task_context: 可选取消上下文。
    输出：
        OCRResult；payload 中保留 screen_state、资源状态和详细 warnings。
    使用示例：
        result = run_ocr_task("G:/adb/frame_0001.png", "harbor")
    """
    api = get_ocr_task_api()
    task_result = api.run_ocr_task(screenshot_path, scene, task_context=task_context)

    payload = task_result.payload or {}
    detections: List[OcrDetection] = []
    for record in payload.get("equipment_records", []) or []:
        if not isinstance(record, dict):
            continue
        try:
            detections.append(
                OcrDetection(
                    str(record["equipment_id"]),
                    int(record["equipment_count"]),
                    int(record["fragment_count"]),
                    float(record["confidence"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return OCRResult(
        str(payload.get("scene") or RecognitionScene.UNKNOWN.value),
        tuple(detections),
        bool(task_result.success),
        task_result.status,
        task_result.message,
        tuple(task_result.warnings),
        payload,
    )
