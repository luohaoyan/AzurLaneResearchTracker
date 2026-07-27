#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🔬 科研设计图识别器 (research_design_reader.py)        ║
║                                                              ║
║  【一句话解释】把 ADB 科研页分帧截图识别成设计图碎片记录。      ║
║  【类比理解】它像只负责读清单的仓库文员：只认图、不点击、不写表。║
║  【数据流说明】manifest/截图 → 设计图卡片 → 图标/名称/数量 → ID。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.contracts import (
    EquipmentRecognitionRecord,
    RecognitionDetection,
    RecognitionDetectionType,
    RecognitionResult,
    RecognitionScene,
    TaskCancelledError,
    TaskExecutionContext,
)
from core.recognition.adb_frame_order import build_frame_order, order_manifest_frames
from core.recognition.design_fragment_detector import (
    DesignFragmentCardCandidate,
    DesignFragmentDetector,
)
from core.recognition.equipment_card_reader import EquipmentCardDigitReader, FragmentQuantityReadResult
from core.recognition.equipment_icon_matcher import EquipmentIconMatcher, EquipmentIconMatchResult
from core.recognition.equipment_name_resolver import EquipmentNameResolver, EquipmentNameResolveResult
from core.recognition.ocr_engine import OcrEngine, OcrReadResult
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager


# ============================================================
# 🧱 第二部分：数据结构
# ============================================================

RoiRegion = Tuple[int, int, int, int]
RatioRegion = Tuple[float, float, float, float]


@dataclass(frozen=True)
class ResearchDesignCardRead:
    """
    单张科研设计图卡片识别结果。
    输入：
        card/record/status/equipment_name/debug。
    输出：
        record 为空表示该卡片只供复核，不进入自动写入链路。
    使用示例：
        if read.record is not None: records.append(read.record)
    """

    frame_index: int
    scroll_index: int
    card: DesignFragmentCardCandidate
    record: Optional[EquipmentRecognitionRecord]
    detections: Tuple[RecognitionDetection, ...] = ()
    confidence: float = 0.0
    status: str = "unknown"
    equipment_name: str = ""
    fragment_count: Optional[int] = None
    required_count: Optional[int] = None
    warnings: Tuple[str, ...] = ()
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换成 payload/debug 友好的字典。"""
        return {
            "frame_index": int(self.frame_index),
            "scroll_index": int(self.scroll_index),
            "card": self.card.to_dict(),
            "record": self.record.to_dict() if self.record else None,
            "detections": [item.to_dict() for item in self.detections],
            "confidence": float(self.confidence),
            "status": self.status,
            "equipment_name": self.equipment_name,
            "fragment_count": self.fragment_count,
            "required_count": self.required_count,
            "warnings": list(self.warnings),
            "debug": dict(self.debug or {}),
        }


# ============================================================
# 🏗️ 第三部分：科研设计图识别器
# ============================================================

class ResearchDesignReader:
    """
    科研设计图页识别主流程。
    输入：
        单张截图、ADB manifest，或 ADB ResearchFrame 序列。
    输出：
        RecognitionResult(scene=research)，equipment_records 只包含可自动写入候选。
    使用示例：
        result = ResearchDesignReader().analyze("workdir/.../manifest.json")
    """

    DEFAULT_CONFIG: Dict[str, Any] = {
        "thresholds": {
            "icon_auto_min_confidence": 0.82,
            "name_only_min_score": 0.94,
            "ocr_name_confidence": 0.50,
            "fragment_count_confidence": 0.45,
        },
        "name_roi_ratio": [0.245, 0.075, 0.455, 0.55],
        "quality": {
            "min_image_width": 600,
            "min_image_height": 360,
        },
    }

    def __init__(
        self,
        *,
        detector: Optional[DesignFragmentDetector] = None,
        icon_matcher: Optional[EquipmentIconMatcher] = None,
        name_resolver: Optional[EquipmentNameResolver] = None,
        card_reader: Optional[EquipmentCardDigitReader] = None,
        ocr_engine: Optional[OcrEngine] = None,
        nn_classifier: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str | Path] = None,
        project_root: Optional[str | Path] = None,
    ) -> None:
        """初始化 reader；图标图库、OCR 和 ONNX fallback 均保持延迟加载。"""
        self.logger = get_logger()
        self.project_root = Path(project_root) if project_root is not None else PathManager.get_project_root()
        self.config_path = Path(config_path) if config_path is not None else self.project_root / "config" / "recognition" / "roi_config.json"
        self.config = self._merge_config(self._load_project_config() if config is None else config)
        ocr_config = self._roi_config_section("ocr")
        card_config = self._roi_config_section("card_digits")
        self.ocr_engine = ocr_engine or OcrEngine(config=ocr_config)
        self.detector = detector or DesignFragmentDetector()
        self.icon_matcher = icon_matcher or EquipmentIconMatcher(project_root=self.project_root)
        self.name_resolver = name_resolver or EquipmentNameResolver(project_root=self.project_root)
        self.card_reader = card_reader or EquipmentCardDigitReader(self.ocr_engine, config=card_config)
        # nn_classifier 是可选兜底注入点：正式部署可传 ONNX FP16 adapter；缺失时不影响 OpenCV/OCR 主链路。
        self.nn_classifier = nn_classifier
        self._name_by_id = self._load_equipment_names()

    def analyze(
        self,
        screenshot_or_manifest_path: str | Path,
        *,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> RecognitionResult:
        """
        识别单张科研设计图截图或 ADB manifest。
        输入：
            screenshot_or_manifest_path: 图片路径或 manifest.json。
        输出：
            RecognitionResult(scene=research)，失败时返回结构化错误而不抛普通异常。
        使用示例：
            reader.analyze("G:/workdir/automation/adb_capture_runs/run_x/manifest.json")
        """
        path = Path(screenshot_or_manifest_path).expanduser()
        if task_context is not None:
            task_context.raise_if_cancelled("科研设计图 OCR 已取消。")
        if not path.is_file():
            message = f"科研设计图截图或 manifest 不存在：{path}"
            return self._failure(str(path), message, warnings=(message,))

        try:
            if path.suffix.lower() == ".json":
                return self.analyze_manifest(path, task_context=task_context)
            return self.analyze_frames([{"screenshot_path": str(path), "frame_index": 0, "scroll_index": 0}], task_context=task_context)
        except TaskCancelledError:
            raise
        except Exception as exc:
            message = "科研设计图 OCR 执行失败。"
            detail = f"{type(exc).__name__}: {exc}"
            self.logger.exception(message)
            return self._failure(str(path), message, detail=detail, warnings=(detail,))

    def analyze_manifest(
        self,
        manifest_path: str | Path,
        *,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> RecognitionResult:
        """
        识别 ADB 科研页分帧 manifest。
        输入：
            manifest_path: ADB 输出的 manifest.json。
        输出：
            已按 frame/scroll 顺序过滤重复帧后的 RecognitionResult。
        使用示例：
            reader.analyze_manifest("run_xxx/manifest.json")
        """
        path = Path(manifest_path).expanduser().resolve()
        order = build_frame_order(path)
        warnings = list(order.warnings)
        if not order.selected_frames:
            message = "ADB manifest 中没有可供 OCR 消费的科研设计图截图。"
            warnings.append(message)
            return self._failure(str(path), message, warnings=tuple(warnings))
        result = self.analyze_frames(
            [item.frame for item in order.selected_frames],
            screenshot_path=str(path),
            task_context=task_context,
        )
        return RecognitionResult(
            result.success,
            RecognitionScene.RESEARCH,
            screenshot_path=str(path),
            detections=result.detections,
            equipment_records=result.equipment_records,
            warnings=tuple([*warnings, *result.warnings]),
            message=result.message,
            detail=f"{result.detail}; selected_frames={len(order.selected_frames)}; total_frames={len(order.selections)}",
        )

    def analyze_frames(
        self,
        frames: Sequence[Any],
        *,
        screenshot_path: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> RecognitionResult:
        """
        识别 ADB ResearchFrame 序列。
        输入：
            frames: dict、dataclass、或带 to_dict() 的 ADB frame 对象。
        输出：
            按 equipment_id 去重后的科研设计图碎片记录。
        使用示例：
            reader.analyze_frames(session.frames)
        """
        normalized_frames = self._normalize_frames(frames)
        if not normalized_frames:
            return self._failure(screenshot_path, "没有传入科研设计图截图帧。", warnings=("没有传入科研设计图截图帧。",))

        all_reads: List[ResearchDesignCardRead] = []
        warnings: List[str] = []
        processed_frames = 0
        for order_index, frame in enumerate(normalized_frames):
            if task_context is not None:
                task_context.raise_if_cancelled("科研设计图 OCR 已取消。")
                progress = 5 + int(order_index / max(1, len(normalized_frames)) * 85)
                task_context.report_progress(progress, "正在识别科研设计图截图。", str(frame.get("screenshot_path", "")))
            frame_reads, frame_warnings = self._analyze_single_frame(frame)
            all_reads.extend(frame_reads)
            warnings.extend(frame_warnings)
            if frame_reads:
                processed_frames += 1

        records, merge_warnings = self._merge_card_reads(all_reads)
        warnings.extend(merge_warnings)
        detections = tuple(detection for read in all_reads for detection in read.detections if read.record is not None)
        success = bool(records)
        if success:
            message = "科研设计图 OCR 识别完成。"
        elif processed_frames > 0:
            message = "科研设计图 OCR 完成，但没有可自动写入的高置信记录。"
        else:
            message = "科研设计图 OCR 未处理到有效截图帧。"
        if task_context is not None:
            task_context.raise_if_cancelled("科研设计图 OCR 已在完成安全点取消。")
            task_context.report_progress(100, "科研设计图 OCR 完成。", f"records={len(records)}")
        return RecognitionResult(
            success,
            RecognitionScene.RESEARCH,
            screenshot_path=screenshot_path or self._first_frame_path(normalized_frames),
            detections=detections,
            equipment_records=tuple(records),
            warnings=tuple(warnings),
            message=message,
            detail=f"frames={processed_frames}; cards={len(all_reads)}; records={len(records)}",
        )

    def _analyze_single_frame(self, frame: Mapping[str, Any]) -> Tuple[List[ResearchDesignCardRead], List[str]]:
        """识别一张科研设计图截图中的所有完整卡片。"""
        screenshot_path = Path(str(frame.get("screenshot_path", "") or "")).expanduser()
        frame_index = self._safe_int(frame.get("frame_index", 0), 0)
        scroll_index = self._safe_int(frame.get("scroll_index", frame_index), frame_index)
        if not screenshot_path.is_file():
            return [], [f"frame={frame_index}: screenshot_missing: {screenshot_path}"]

        try:
            image = self.detector.load_image(screenshot_path)
        except Exception as exc:
            return [], [f"frame={frame_index}: screenshot_unreadable: {exc}"]
        quality_warning = self._image_quality_warning(image, screenshot_path)
        if quality_warning:
            return [], [f"frame={frame_index}: {quality_warning}"]

        detection = self.detector.detect(image)
        if not detection.success:
            return [], [f"frame={frame_index}: {detection.message}", *detection.warnings]

        reads: List[ResearchDesignCardRead] = []
        warnings: List[str] = []
        for card in detection.candidates:
            read = self._read_card(image, card, frame_index, scroll_index)
            reads.append(read)
            warnings.extend(read.warnings)
        if not reads:
            warnings.append(f"frame={frame_index}: 没有检测到科研设计图卡片。")
        return reads, warnings

    def _read_card(
        self,
        image: Any,
        card: DesignFragmentCardCandidate,
        frame_index: int,
        scroll_index: int,
    ) -> ResearchDesignCardRead:
        """识别单张设计图卡片，不确定时只进入 warning，不生成 record。"""
        position_key = f"frame{frame_index}:scroll{scroll_index}:card{card.index:02d}"
        warnings: List[str] = []
        debug: Dict[str, Any] = {"card": card.to_dict()}
        if card.visibility != "full":
            warning = f"{position_key}: rejected_partial: visibility={card.visibility}"
            warnings.append(warning)
            return ResearchDesignCardRead(
                frame_index,
                scroll_index,
                card,
                None,
                confidence=float(card.confidence),
                status="rejected_partial",
                warnings=tuple(warnings),
                debug=debug,
            )

        icon_result = self.icon_matcher.match_icon(image, icon_roi=card.icon_roi)
        debug["icon_match"] = icon_result.to_dict() if hasattr(icon_result, "to_dict") else {}
        nn_result = self._maybe_run_nn_fallback(image, card, icon_result)
        if nn_result is not None:
            debug["nn_fallback"] = nn_result

        candidate_ids = self._candidate_ids(icon_result)
        name_ocr = self._read_name_text(image, card)
        debug["name_ocr"] = name_ocr.to_dict() if hasattr(name_ocr, "to_dict") else {}
        resolved = self._resolve_equipment_name(icon_result, name_ocr, candidate_ids, nn_result)
        debug["name_resolve"] = resolved.to_dict()
        if not self._is_auto_resolvable(icon_result, name_ocr, resolved, nn_result):
            warning = (
                f"{position_key}: needs_review: icon={icon_result.status} "
                f"name={resolved.status} message={resolved.message}"
            )
            warnings.append(warning)
            return ResearchDesignCardRead(
                frame_index,
                scroll_index,
                card,
                None,
                confidence=float(resolved.score or icon_result.confidence),
                status=resolved.status or icon_result.status,
                equipment_name=resolved.equipment_name,
                warnings=tuple(warnings),
                debug=debug,
            )

        quantity = self.card_reader.read_fragment_counts(
            image,
            card_roi=card.bbox,
            quantity_roi=self._relative_child_roi(card.bbox, card.quantity_roi),
            confidence_threshold=float(self.config["thresholds"]["fragment_count_confidence"]),
        )
        debug["fragment_count_ocr"] = quantity.to_dict() if hasattr(quantity, "to_dict") else {}
        if not quantity.success or quantity.fragment_count is None:
            warning = f"{position_key}: needs_review: fragment_count unreadable: {quantity.message}"
            warnings.append(warning)
            return ResearchDesignCardRead(
                frame_index,
                scroll_index,
                card,
                None,
                confidence=float(resolved.score or icon_result.confidence),
                status="count_unreadable",
                equipment_name=resolved.equipment_name,
                warnings=tuple(warnings),
                debug=debug,
            )

        fragment_count = int(quantity.fragment_count)
        equipment_count = 0
        confidence = self._combined_confidence(icon_result.confidence, resolved.score, quantity.confidence)
        record = EquipmentRecognitionRecord(resolved.equipment_id, equipment_count, fragment_count, confidence)
        detections = (
            RecognitionDetection(
                resolved.equipment_id,
                RecognitionDetectionType.FRAGMENT_COUNT,
                fragment_count,
                self._clamp(quantity.confidence),
                quantity.roi or card.quantity_roi,
            ),
        )
        warnings.extend(f"{position_key}: {item}" for item in quantity.warnings)
        return ResearchDesignCardRead(
            frame_index,
            scroll_index,
            card,
            record,
            detections=detections,
            confidence=confidence,
            status="success",
            equipment_name=resolved.equipment_name,
            fragment_count=fragment_count,
            required_count=quantity.required_count,
            warnings=tuple(warnings),
            debug=debug,
        )

    def _resolve_equipment_name(
        self,
        icon_result: EquipmentIconMatchResult,
        name_ocr: OcrReadResult,
        candidate_ids: Sequence[str],
        nn_result: Optional[Dict[str, Any]],
    ) -> EquipmentNameResolveResult:
        """按“OCR 名称 → ONNX 名称 → 图标 ID 反查名称”的顺序解析运行时 ID。"""
        if name_ocr.success and name_ocr.text.strip():
            return self.name_resolver.resolve(name_ocr.text, candidate_equipment_ids=candidate_ids)

        nn_name = self._best_nn_equipment_name(nn_result)
        if nn_name:
            return self.name_resolver.resolve(nn_name, candidate_equipment_ids=candidate_ids)

        if icon_result.status == "success" and icon_result.equipment_id:
            equipment_name = self._name_by_id.get(icon_result.equipment_id, "")
            if equipment_name:
                return self.name_resolver.resolve(equipment_name, candidate_equipment_ids=(icon_result.equipment_id,))
        return EquipmentNameResolveResult(
            False,
            icon_result.status or "unresolved",
            icon_result.message or "图标、名称和 ONNX fallback 都无法唯一解析。",
            candidates=(),
        )

    def _is_auto_resolvable(
        self,
        icon_result: EquipmentIconMatchResult,
        name_ocr: OcrReadResult,
        resolved: EquipmentNameResolveResult,
        nn_result: Optional[Dict[str, Any]],
    ) -> bool:
        """判断科研设计图卡片是否允许进入自动写入候选链路。"""
        if not resolved.success or not resolved.equipment_id:
            return False
        if resolved.status in {"ambiguous", "outside_icon_candidates", "too_short", "unresolved"}:
            return False
        if icon_result.status == "success":
            return True
        if name_ocr.success:
            return float(resolved.score) >= float(self.config["thresholds"]["name_only_min_score"])
        if nn_result and nn_result.get("status") == "success":
            return float(resolved.score) >= float(self.config["thresholds"]["name_only_min_score"])
        return False

    def _read_name_text(self, image: Any, card: DesignFragmentCardCandidate) -> OcrReadResult:
        """读取设计图卡片中部名称；失败只作为辅助缺失，不阻塞图标高置信路径。"""
        roi = self._name_roi(card.raw_bbox, image)
        try:
            return self.ocr_engine.recognize_text(
                image,
                roi=roi,
                confidence_threshold=float(self.config["thresholds"]["ocr_name_confidence"]),
                preprocess=False,
            )
        except Exception as exc:
            return OcrReadResult(False, "error", str(exc), roi=roi, warnings=(str(exc),))

    def _maybe_run_nn_fallback(
        self,
        image: Any,
        card: DesignFragmentCardCandidate,
        icon_result: EquipmentIconMatchResult,
    ) -> Optional[Dict[str, Any]]:
        """
        在 OpenCV 低置信/ambiguous 时调用可选 ONNX/PyTorch fallback。

        这里不默认创建模型对象，避免 OCR 核心层强依赖训练目录；正式整合可注入
        ``OnnxEquipmentIconClassifier``，测试也可注入轻量 fake。
        """
        if self.nn_classifier is None:
            return None
        threshold = float(self.config["thresholds"]["icon_auto_min_confidence"])
        if icon_result.status == "success" and float(icon_result.confidence) >= threshold:
            return None
        predict_image = getattr(self.nn_classifier, "predict_image", None)
        if not callable(predict_image):
            return {"status": "unavailable", "message": "NN fallback does not expose predict_image()."}
        try:
            result = predict_image(image, icon_roi=card.icon_roi, top_k=3)
        except Exception as exc:
            return {"status": "error", "message": f"NN fallback failed: {type(exc).__name__}: {exc}"}
        if hasattr(result, "to_dict"):
            return result.to_dict()
        return dict(result) if isinstance(result, Mapping) else {"status": "unknown", "message": str(result)}

    @staticmethod
    def _best_nn_equipment_name(nn_result: Optional[Dict[str, Any]]) -> str:
        """从 NN/ONNX fallback 字典中取最高置信 equipment_name。"""
        if not nn_result or nn_result.get("status") != "success":
            return ""
        candidates = nn_result.get("candidates", [])
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or not candidates:
            return ""
        first = candidates[0]
        if not isinstance(first, Mapping):
            return ""
        return str(first.get("equipment_name", "") or "").strip()

    def _merge_card_reads(self, reads: Sequence[ResearchDesignCardRead]) -> Tuple[List[EquipmentRecognitionRecord], List[str]]:
        """按 equipment_id 跨帧去重；同装备取更高置信记录，不重复累计。"""
        best_by_id: Dict[str, EquipmentRecognitionRecord] = {}
        warnings: List[str] = []
        for read in reads:
            if read.record is None:
                continue
            current = best_by_id.get(read.record.equipment_id)
            if current is None:
                best_by_id[read.record.equipment_id] = read.record
                continue
            if current.fragment_count != read.record.fragment_count:
                warnings.append(
                    f"{read.record.equipment_id}: duplicate_conflicting_fragment_count "
                    f"{current.fragment_count}!={read.record.fragment_count}; kept_higher_confidence"
                )
            if read.record.confidence > current.confidence:
                best_by_id[read.record.equipment_id] = read.record
        return [best_by_id[key] for key in sorted(best_by_id)], warnings

    def _normalize_frames(self, frames: Sequence[Any]) -> List[Dict[str, Any]]:
        """把 ADB ResearchFrame dataclass、dict 或 session dict 统一成 frame 字典。"""
        if hasattr(frames, "frames"):
            frames = getattr(frames, "frames")
        normalized: List[Dict[str, Any]] = []
        for index, frame in enumerate(frames):
            if hasattr(frame, "to_dict"):
                item = dict(frame.to_dict())
            elif isinstance(frame, Mapping):
                item = dict(frame)
            elif hasattr(frame, "__dict__"):
                item = dict(vars(frame))
            else:
                item = {"screenshot_path": str(frame)}
            item.setdefault("frame_index", index)
            item.setdefault("scroll_index", item.get("frame_index", index))
            if item.get("success") is False or str(item.get("status", "")).lower() in {"error", "failed", "unavailable"}:
                continue
            normalized.append(item)
        ordered = order_manifest_frames({"frames": normalized}, require_existing_files=True)
        return [item.frame for item in ordered.selected_frames]

    def _name_roi(self, raw_bbox: RoiRegion, image: Any) -> RoiRegion:
        """把设计图卡片中部名称比例 ROI 转成绝对截图 ROI。"""
        ratio = self.config.get("name_roi_ratio", self.DEFAULT_CONFIG["name_roi_ratio"])
        if not isinstance(ratio, (list, tuple)) or len(ratio) != 4:
            ratio = self.DEFAULT_CONFIG["name_roi_ratio"]
        x, y, width, height = raw_bbox
        rx, ry, rw, rh = (float(item) for item in ratio)
        roi = (
            x + int(round(width * rx)),
            y + int(round(height * ry)),
            max(1, int(round(width * rw))),
            max(1, int(round(height * rh))),
        )
        image_height, image_width = int(image.shape[0]), int(image.shape[1])
        return self._clip_roi(roi, image_width, image_height)

    def _image_quality_warning(self, image: Any, screenshot_path: Path) -> str:
        """过滤空帧、异常分辨率和低质量图片。"""
        if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
            return f"empty_frame: {screenshot_path}"
        height, width = int(image.shape[0]), int(image.shape[1])
        quality = self.config["quality"]
        if width < int(quality["min_image_width"]) or height < int(quality["min_image_height"]):
            return f"low_quality_frame: resolution={width}x{height}"
        return ""

    def _load_project_config(self) -> Dict[str, Any]:
        """读取项目 ROI 配置；文件缺失时使用科研设计图默认坐标。"""
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _merge_config(self, raw: Mapping[str, Any]) -> Dict[str, Any]:
        """把默认科研设计图配置和项目配置合并，允许后续标注逐步覆盖。"""
        merged = json.loads(json.dumps(self.DEFAULT_CONFIG))
        reader_config = raw.get("research_design_reader", {}) if isinstance(raw, Mapping) else {}
        if isinstance(reader_config, Mapping):
            self._deep_update(merged, dict(reader_config))
        return merged

    def _roi_config_section(self, key: str) -> Dict[str, Any]:
        """读取 roi_config.json 中复用组件所需的小节。"""
        project_config = self._load_project_config()
        section = project_config.get(key, {}) if isinstance(project_config, dict) else {}
        return dict(section) if isinstance(section, dict) else {}

    def _load_equipment_names(self) -> Dict[str, str]:
        """只读加载当前装备库名称，保证 ID 是运行时由名称映射得到。"""
        path = self.project_root / "data" / "equipment_library.csv"
        if not path.is_file():
            return {}
        names: Dict[str, str] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                equipment_id = str(row.get("equipment_id", "") or "").strip()
                name = str(row.get("name", "") or "").strip()
                if equipment_id and name:
                    names[equipment_id] = name
        return names

    @staticmethod
    def _relative_child_roi(parent: RoiRegion, child: RoiRegion) -> RoiRegion:
        """把绝对截图 ROI 转为相对卡片 ROI，匹配 EquipmentCardDigitReader 语义。"""
        parent_x, parent_y, _parent_width, _parent_height = parent
        child_x, child_y, child_width, child_height = child
        return child_x - parent_x, child_y - parent_y, child_width, child_height

    @staticmethod
    def _candidate_ids(icon_result: EquipmentIconMatchResult) -> Tuple[str, ...]:
        """从 OpenCV 图标 top-N 候选中提取去重 equipment_id。"""
        ids: List[str] = []
        seen: set[str] = set()
        for candidate in icon_result.candidates:
            equipment_id = str(candidate.equipment_id or "").strip()
            if equipment_id and equipment_id != "unknown" and equipment_id not in seen:
                ids.append(equipment_id)
                seen.add(equipment_id)
        if icon_result.equipment_id and icon_result.equipment_id != "unknown" and icon_result.equipment_id not in seen:
            ids.insert(0, icon_result.equipment_id)
        return tuple(ids)

    @staticmethod
    def _deep_update(target: Dict[str, Any], patch: Mapping[str, Any]) -> None:
        """递归合并配置字典。"""
        for key, value in patch.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                ResearchDesignReader._deep_update(target[key], value)  # type: ignore[index]
            else:
                target[key] = value

    @staticmethod
    def _clip_roi(roi: RoiRegion, image_width: int, image_height: int) -> RoiRegion:
        """把 ROI 限制在图像边界内。"""
        x, y, width, height = (int(item) for item in roi)
        x = min(max(0, x), max(0, image_width - 1))
        y = min(max(0, y), max(0, image_height - 1))
        width = max(1, min(width, image_width - x))
        height = max(1, min(height, image_height - y))
        return x, y, width, height

    @staticmethod
    def _combined_confidence(icon_confidence: float, name_score: float, count_confidence: float) -> float:
        """融合图标、名称映射和数量 OCR 置信度，任一环偏低都会拉低结果。"""
        values = [float(icon_confidence or 0.0), float(name_score or 0.0), float(count_confidence or 0.0)]
        return ResearchDesignReader._clamp(min(values) * 0.70 + (sum(values) / len(values)) * 0.30)

    @staticmethod
    def _clamp(value: float) -> float:
        """把置信度限制在契约允许范围。"""
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        """安全转换 int。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _first_frame_path(frames: Sequence[Mapping[str, Any]]) -> Optional[str]:
        """返回第一张帧截图路径。"""
        for frame in frames:
            path = str(frame.get("screenshot_path", "") or "").strip()
            if path:
                return path
        return None

    @staticmethod
    def _failure(
        screenshot_path: Optional[str],
        message: str,
        *,
        detail: str = "",
        warnings: Tuple[str, ...] = (),
    ) -> RecognitionResult:
        """构造失败 RecognitionResult，保持不抛普通异常的 OCR 契约。"""
        return RecognitionResult(
            False,
            RecognitionScene.RESEARCH,
            screenshot_path=screenshot_path,
            warnings=warnings or (message,),
            message=message,
            detail=detail,
        )


__all__ = [
    "ResearchDesignCardRead",
    "ResearchDesignReader",
]
