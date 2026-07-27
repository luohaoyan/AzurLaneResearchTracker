#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧰 装备仓库列表页识别器 (equipment_page_reader.py)  ║
║                                                              ║
║  【一句话解释】把 ADB 装备页分帧截图识别成可写入候选记录。     ║
║  【类比理解】它像逐格清点仓库货架，认不准的格子先贴复核条。    ║
║  【数据流说明】截图/manifest → 卡片网格 → 图标/名称/数量 → ID。║
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
from core.recognition.equipment_card_reader import EquipmentCardDigitReader
from core.recognition.equipment_icon_matcher import EquipmentIconMatcher, EquipmentIconMatchResult
from core.recognition.equipment_name_resolver import EquipmentNameResolver, EquipmentNameResolveResult
from core.recognition.ocr_engine import OcrEngine, OcrReadResult
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager

try:
    import cv2 as _cv2
except Exception:  # pragma: no cover - 没装 OpenCV 时入口仍应返回 unavailable
    _cv2 = None


# ============================================================
# 🧱 第二部分：数据结构
# ============================================================

RoiRegion = Tuple[int, int, int, int]
RatioRegion = Tuple[float, float, float, float]


@dataclass(frozen=True)
class EquipmentPageCard:
    """
    装备页上的一个卡片格子。
    输入：
        frame_index/card_index/card_roi/name_roi/position_key。
    输出：
        只描述几何位置，不携带识别结论。
    使用示例：
        card = EquipmentPageCard(0, 3, (614, 84, 132, 132), (614, 220, 132, 28), "r0c3")
    """

    frame_index: int
    card_index: int
    row_index: int
    column_index: int
    card_roi: RoiRegion
    name_roi: RoiRegion
    position_key: str

    def to_dict(self) -> Dict[str, Any]:
        """转换成调试 payload 可读的字典。"""
        return {
            "frame_index": self.frame_index,
            "card_index": self.card_index,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "card_roi": list(self.card_roi),
            "name_roi": list(self.name_roi),
            "position_key": self.position_key,
        }


@dataclass(frozen=True)
class EquipmentPageCardRead:
    """
    单张卡片识别结果。
    输入：
        record/detections/confidence/warnings/debug。
    输出：
        record 为空时表示本卡片不会进入自动写入链路。
    使用示例：
        read.record is not None
    """

    card: EquipmentPageCard
    record: Optional[EquipmentRecognitionRecord]
    detections: Tuple[RecognitionDetection, ...] = ()
    confidence: float = 0.0
    status: str = "unknown"
    equipment_name: str = ""
    warnings: Tuple[str, ...] = ()
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换成 payload 友好的字典，便于人工复核。"""
        return {
            "card": self.card.to_dict(),
            "record": self.record.to_dict() if self.record else None,
            "detections": [item.to_dict() for item in self.detections],
            "confidence": float(self.confidence),
            "status": self.status,
            "equipment_name": self.equipment_name,
            "warnings": list(self.warnings),
            "debug": dict(self.debug or {}),
        }


# ============================================================
# 🏗️ 第三部分：装备页识别器
# ============================================================

class EquipmentPageReader:
    """
    装备仓库列表页识别主流程。
    输入：
        单张截图、ADB manifest，或 ADB frame/session 对象。
    输出：
        RecognitionResult，equipment_records 只包含可自动写入候选。
    使用示例：
        result = EquipmentPageReader().analyze("capture_manifest.json")
    """

    DEFAULT_CONFIG: Dict[str, Any] = {
        "base_resolution": [1280, 720],
        "card_grid": {
            "origin": [134, 84],
            "card_size": [132, 132],
            "pitch": [159, 177],
            "columns": 7,
            "rows": 4,
            "visible_bottom": 637,
            "name_height": 30,
            "name_gap": 4,
        },
        "quality": {
            "min_image_width": 600,
            "min_image_height": 360,
            "min_card_stddev": 4.0,
        },
        "thresholds": {
            "name_only_min_score": 0.94,
            "ocr_name_confidence": 0.55,
            "count_confidence": 0.50,
        },
    }

    def __init__(
        self,
        *,
        icon_matcher: Optional[EquipmentIconMatcher] = None,
        name_resolver: Optional[EquipmentNameResolver] = None,
        card_reader: Optional[EquipmentCardDigitReader] = None,
        ocr_engine: Optional[OcrEngine] = None,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[str | Path] = None,
        project_root: Optional[str | Path] = None,
        cv2_module: Optional[Any] = None,
    ) -> None:
        """初始化识别器；OCR 和图库均延迟加载，便于 GUI 启动。"""
        self.logger = get_logger()
        self.project_root = Path(project_root) if project_root is not None else PathManager.get_project_root()
        self.config_path = Path(config_path) if config_path is not None else self.project_root / "config" / "recognition" / "roi_config.json"
        self.config = self._merge_config(self._load_project_config() if config is None else config)
        ocr_config = self._roi_config_section("ocr")
        card_config = self._roi_config_section("card_digits")
        self.ocr_engine = ocr_engine or OcrEngine(config=ocr_config)
        self.icon_matcher = icon_matcher or EquipmentIconMatcher(project_root=self.project_root)
        self.name_resolver = name_resolver or EquipmentNameResolver(project_root=self.project_root)
        self.card_reader = card_reader or EquipmentCardDigitReader(self.ocr_engine, config=card_config)
        self._cv2 = cv2_module if cv2_module is not None else _cv2
        self._name_by_id = self._load_equipment_names()

    def analyze(
        self,
        screenshot_or_manifest_path: str | Path,
        *,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> RecognitionResult:
        """
        识别单张截图或 ADB manifest。
        输入：
            screenshot_or_manifest_path: 图片路径、capture_manifest.json 或 scroll_session.json。
        输出：
            RecognitionResult，失败时不抛普通异常。
        使用示例：
            reader.analyze("G:/run/capture_manifest.json")
        """
        path = Path(screenshot_or_manifest_path).expanduser()
        if task_context is not None:
            task_context.raise_if_cancelled("装备页 OCR 已取消。")
        if not path.is_file():
            message = f"截图或 manifest 不存在：{path}"
            return self._failure(str(path), message, warnings=(message,))

        try:
            if path.suffix.lower() == ".json":
                return self.analyze_manifest(path, task_context=task_context)
            return self.analyze_frames([{"screenshot_path": str(path), "frame_index": 0}], task_context=task_context)
        except TaskCancelledError:
            raise
        except Exception as exc:
            message = "装备页 OCR 执行失败。"
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
        识别 ADB 输出的 manifest。
        输入：
            manifest_path: 支持 top-level frames、artifacts 或 scroll_session.json。
        输出：
            合并去重后的 RecognitionResult。
        使用示例：
            reader.analyze_manifest("scroll_session.json")
        """
        path = Path(manifest_path).expanduser().resolve()
        order = build_frame_order(path)
        warnings = list(order.warnings)
        if not order.selected_frames:
            message = "ADB manifest 中没有可供 OCR 消费的装备页截图。"
            warnings.append(message)
            return self._failure(str(path), message, warnings=tuple(warnings))
        result = self.analyze_frames(
            [item.frame for item in order.selected_frames],
            screenshot_path=str(path),
            task_context=task_context,
        )
        return RecognitionResult(
            result.success,
            result.scene,
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
        识别 ADB frame/session 对象序列。
        输入：
            frames: dict、dataclass、或带 to_dict() 的 ADB frame 对象。
        输出：
            已按 equipment_id 合并去重的 RecognitionResult。
        使用示例：
            reader.analyze_frames(session.frames)
        """
        normalized_frames = self._normalize_frames(frames)
        if not normalized_frames:
            return self._failure(screenshot_path, "没有传入装备页截图帧。", warnings=("没有传入装备页截图帧。",))

        all_reads: List[EquipmentPageCardRead] = []
        warnings: List[str] = []
        seen_sha1: set[str] = set()
        processed_frames = 0
        for order_index, frame in enumerate(normalized_frames):
            if task_context is not None:
                task_context.raise_if_cancelled("装备页 OCR 已取消。")
                progress = 5 + int(order_index / max(1, len(normalized_frames)) * 85)
                task_context.report_progress(progress, "正在识别装备页截图。", str(frame.get("screenshot_path", "")))

            sha1 = str(frame.get("sha1", "") or "").strip()
            if sha1 and sha1 in seen_sha1:
                warnings.append(f"frame={frame.get('frame_index', order_index)}: duplicate_frame 已跳过。")
                continue
            if sha1:
                seen_sha1.add(sha1)

            frame_reads, frame_warnings = self._analyze_single_frame(frame)
            all_reads.extend(frame_reads)
            warnings.extend(frame_warnings)
            if frame_reads:
                processed_frames += 1

        records, merge_warnings = self._merge_card_reads(all_reads)
        warnings.extend(merge_warnings)
        detections = tuple(detection for read in all_reads for detection in read.detections if read.record is not None)
        success = bool(records)
        if not success and processed_frames > 0:
            message = "装备页 OCR 完成，但没有可自动写入的高置信记录。"
        elif success:
            message = "装备页 OCR 识别完成。"
        else:
            message = "装备页 OCR 未处理到有效截图帧。"
        return RecognitionResult(
            success,
            RecognitionScene.EQUIPMENT_LIST,
            screenshot_path=screenshot_path or self._first_frame_path(normalized_frames),
            detections=detections,
            equipment_records=tuple(records),
            warnings=tuple(warnings),
            message=message,
            detail=f"frames={processed_frames}; cards={len(all_reads)}; records={len(records)}",
        )

    def _analyze_single_frame(self, frame: Mapping[str, Any]) -> Tuple[List[EquipmentPageCardRead], List[str]]:
        """识别一张装备页截图内的所有完整卡片。"""
        screenshot_path = Path(str(frame.get("screenshot_path", "") or "")).expanduser()
        frame_index = self._safe_int(frame.get("frame_index", 0), 0)
        warnings: List[str] = []
        if not screenshot_path.is_file():
            return [], [f"frame={frame_index}: screenshot_missing: {screenshot_path}"]
        image = self._load_image(screenshot_path)
        quality_warning = self._image_quality_warning(image, screenshot_path)
        if quality_warning:
            return [], [f"frame={frame_index}: {quality_warning}"]

        reads: List[EquipmentPageCardRead] = []
        for card in self._iter_cards(image, frame_index):
            crop = self._crop(image, card.card_roi)
            if not self._card_has_content(crop):
                continue
            read = self._read_card(image, crop, card)
            reads.append(read)
            warnings.extend(read.warnings)
        if not reads:
            warnings.append(f"frame={frame_index}: 没有检测到完整装备卡片。")
        return reads, warnings

    def _read_card(self, image: Any, card_image: Any, card: EquipmentPageCard) -> EquipmentPageCardRead:
        """识别单张装备卡，任何不确定状态都只进 warnings，不进 record。"""
        warnings: List[str] = []
        debug: Dict[str, Any] = {}
        icon_result = self.icon_matcher.match_card(card_image, card_type="equipment")
        debug["icon_match"] = icon_result.to_dict() if hasattr(icon_result, "to_dict") else {}
        candidate_ids = tuple(candidate.equipment_id for candidate in icon_result.candidates)

        name_ocr = self._read_name_text(image, card.name_roi)
        debug["name_ocr"] = name_ocr.to_dict() if hasattr(name_ocr, "to_dict") else {}
        resolved = self._resolve_equipment_name(icon_result, name_ocr, candidate_ids)
        debug["name_resolve"] = resolved.to_dict()
        debug["card_signature"] = self._card_signature(card_image)
        if not self._is_auto_resolvable(icon_result, name_ocr, resolved):
            status = resolved.status if resolved.status else icon_result.status
            warnings.append(
                f"{card.position_key}: needs_review: icon={icon_result.status} "
                f"name={resolved.status} message={resolved.message}"
            )
            return EquipmentPageCardRead(card, None, confidence=float(resolved.score or icon_result.confidence), status=status, equipment_name=resolved.equipment_name, warnings=tuple(warnings), debug=debug)

        count_result = self.card_reader.read_equipment_count(
            card_image,
            confidence_threshold=float(self.config["thresholds"]["count_confidence"]),
        )
        debug["equipment_count_ocr"] = count_result.to_dict() if hasattr(count_result, "to_dict") else {}
        if not count_result.success or count_result.value is None:
            warnings.append(f"{card.position_key}: needs_review: equipment_count unreadable: {count_result.message}")
            return EquipmentPageCardRead(card, None, confidence=float(resolved.score or icon_result.confidence), status="count_unreadable", equipment_name=resolved.equipment_name, warnings=tuple(warnings), debug=debug)

        equipment_count = int(count_result.value)
        # 装备仓库“装备”页展示的是完整装备堆叠；碎片属于“设计图”页，故这里按业务规则写 0。
        fragment_count = 0
        confidence = self._combined_confidence(icon_result.confidence, resolved.score, count_result.confidence)
        record = EquipmentRecognitionRecord(resolved.equipment_id, equipment_count, fragment_count, confidence)
        detections = (
            RecognitionDetection(
                resolved.equipment_id,
                RecognitionDetectionType.EQUIPMENT_COUNT,
                equipment_count,
                self._clamp(count_result.confidence),
                count_result.roi or card.card_roi,
            ),
            RecognitionDetection(
                resolved.equipment_id,
                RecognitionDetectionType.FRAGMENT_COUNT,
                fragment_count,
                confidence,
                card.card_roi,
            ),
        )
        return EquipmentPageCardRead(
            card,
            record,
            detections=detections,
            confidence=confidence,
            status="success",
            equipment_name=resolved.equipment_name,
            warnings=tuple(warnings),
            debug=debug,
        )

    def _resolve_equipment_name(
        self,
        icon_result: EquipmentIconMatchResult,
        name_ocr: OcrReadResult,
        candidate_ids: Sequence[str],
    ) -> EquipmentNameResolveResult:
        """优先用可读名称解析；没有名称时用图标候选 ID 反查名称再运行时映射。"""
        if name_ocr.success and name_ocr.text.strip():
            return self.name_resolver.resolve(name_ocr.text, candidate_equipment_ids=candidate_ids)
        if icon_result.status == "success" and icon_result.equipment_id:
            equipment_name = self._name_by_id.get(icon_result.equipment_id, "")
            if equipment_name:
                return self.name_resolver.resolve(equipment_name, candidate_equipment_ids=(icon_result.equipment_id,))
        return EquipmentNameResolveResult(
            False,
            icon_result.status or "unresolved",
            icon_result.message or "图标和名称都无法唯一解析。",
            candidates=(),
        )

    def _is_auto_resolvable(
        self,
        icon_result: EquipmentIconMatchResult,
        name_ocr: OcrReadResult,
        resolved: EquipmentNameResolveResult,
    ) -> bool:
        """判断卡片是否允许进入自动写入候选链路。"""
        if not resolved.success or not resolved.equipment_id:
            return False
        if resolved.status in {"ambiguous", "outside_icon_candidates", "too_short", "unresolved"}:
            return False
        if icon_result.status in {"ambiguous", "unknown", "no_gallery", "unavailable", "error"} and not name_ocr.success:
            return False
        if name_ocr.success and icon_result.status != "success":
            return float(resolved.score) >= float(self.config["thresholds"]["name_only_min_score"])
        return True

    def _read_name_text(self, image: Any, name_roi: RoiRegion) -> OcrReadResult:
        """读取卡片下方名称；失败只作为辅助缺失，不阻塞图标高置信路径。"""
        try:
            return self.ocr_engine.recognize_text(
                image,
                roi=name_roi,
                confidence_threshold=float(self.config["thresholds"]["ocr_name_confidence"]),
                preprocess=False,
            )
        except Exception as exc:
            return OcrReadResult(False, "error", str(exc), roi=name_roi, warnings=(str(exc),))

    def _merge_card_reads(self, reads: Sequence[EquipmentPageCardRead]) -> Tuple[List[EquipmentRecognitionRecord], List[str]]:
        """先按卡片视觉签名跳过滚动重叠，再按 equipment_id 汇总数量。"""
        totals: Dict[str, int] = {}
        fragments: Dict[str, int] = {}
        best_confidence: Dict[str, float] = {}
        seen_cards: set[Tuple[str, str]] = set()
        warnings: List[str] = []
        for read in reads:
            if read.record is None:
                continue
            signature = str((read.debug or {}).get("card_signature", "") or "")
            card_key = (
                read.record.equipment_id,
                signature or f"{read.card.frame_index}:{read.card.row_index}:{read.card.column_index}",
            )
            if signature and card_key in seen_cards:
                warnings.append(f"{read.record.equipment_id}: duplicate_overlap_card_skipped signature={signature[:12]}")
                continue
            seen_cards.add(card_key)
            equipment_id = read.record.equipment_id
            totals[equipment_id] = totals.get(equipment_id, 0) + int(read.record.equipment_count)
            fragments[equipment_id] = fragments.get(equipment_id, 0) + int(read.record.fragment_count)
            best_confidence[equipment_id] = max(best_confidence.get(equipment_id, 0.0), float(read.record.confidence))

        records = [
            EquipmentRecognitionRecord(equipment_id, totals[equipment_id], fragments[equipment_id], best_confidence[equipment_id])
            for equipment_id in sorted(totals)
        ]
        return records, warnings

    def _iter_cards(self, image: Any, frame_index: int) -> Tuple[EquipmentPageCard, ...]:
        """基于装备页独立网格坐标生成完整卡片 ROI，不复用设计图卡片规则。"""
        height, width = int(image.shape[0]), int(image.shape[1])
        scale_x, scale_y = self._scale(width, height)
        grid = self.config["card_grid"]
        origin_x, origin_y = self._scale_point(grid["origin"], scale_x, scale_y)
        card_width, card_height = self._scale_size(grid["card_size"], scale_x, scale_y)
        pitch_x, pitch_y = self._scale_size(grid["pitch"], scale_x, scale_y)
        visible_bottom = int(round(float(grid["visible_bottom"]) * scale_y))
        name_gap = int(round(float(grid["name_gap"]) * scale_y))
        name_height = int(round(float(grid["name_height"]) * scale_y))

        cards: List[EquipmentPageCard] = []
        card_index = 0
        for row in range(int(grid["rows"])):
            for column in range(int(grid["columns"])):
                x = origin_x + column * pitch_x
                y = origin_y + row * pitch_y
                card_roi = self._clip_roi((x, y, card_width, card_height), width, height)
                if card_roi[2] < max(16, card_width * 0.85) or card_roi[3] < max(16, card_height * 0.85):
                    continue
                if card_roi[1] + card_roi[3] > visible_bottom:
                    continue
                name_y = card_roi[1] + card_roi[3] + name_gap
                name_roi = self._clip_roi((card_roi[0], name_y, card_roi[2], name_height), width, height)
                cards.append(
                    EquipmentPageCard(
                        frame_index,
                        card_index,
                        row,
                        column,
                        card_roi,
                        name_roi,
                        f"frame{frame_index}:r{row}c{column}",
                    )
                )
                card_index += 1
        return tuple(cards)

    def _load_image(self, screenshot_path: Path) -> Any:
        """读取装备页截图，OpenCV 不可用或图片损坏时抛出明确错误。"""
        if self._cv2 is None:
            raise RuntimeError("OpenCV(cv2) 不可用，无法读取装备页截图。")
        image = self._cv2.imread(str(screenshot_path), getattr(self._cv2, "IMREAD_COLOR", 1))
        if image is None or getattr(image, "size", 0) == 0:
            raise ValueError(f"截图无法读取或已损坏: {screenshot_path}")
        return image

    def _card_signature(self, card_image: Any) -> str:
        """生成轻量视觉签名，用于滚动重叠卡片去重，不作为装备身份标签。"""
        if self._cv2 is None or card_image is None or not hasattr(card_image, "shape"):
            return ""
        try:
            gray = self._cv2.cvtColor(card_image, self._cv2.COLOR_BGR2GRAY) if len(card_image.shape) == 3 else card_image
            resized = self._cv2.resize(gray, (16, 16))
            mean_value = float(resized.mean())
            bits = (resized > mean_value).astype("uint8").reshape(-1)
            return "".join("1" if int(bit) else "0" for bit in bits)
        except Exception:
            return ""

    def _image_quality_warning(self, image: Any, screenshot_path: Path) -> str:
        """过滤空帧、异常分辨率和低质量图片。"""
        if image is None or not hasattr(image, "shape") or getattr(image, "size", 0) == 0:
            return f"empty_frame: {screenshot_path}"
        height, width = int(image.shape[0]), int(image.shape[1])
        quality = self.config["quality"]
        if width < int(quality["min_image_width"]) or height < int(quality["min_image_height"]):
            return f"low_quality_frame: resolution={width}x{height}"
        return ""

    def _card_has_content(self, card_image: Any) -> bool:
        """判断卡片 ROI 是否像真实装备格子，避免空白区域参与识别。"""
        if card_image is None or not hasattr(card_image, "std") or getattr(card_image, "size", 0) == 0:
            return False
        try:
            return float(card_image.std()) >= float(self.config["quality"]["min_card_stddev"])
        except Exception:
            return True

    def _normalize_frames(self, frames: Sequence[Any]) -> List[Dict[str, Any]]:
        """把 ADB frame dataclass、dict 或 session dict 统一成 frame 字典。"""
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
            if item.get("success") is False or str(item.get("status", "")).lower() in {"error", "failed", "unavailable"}:
                continue
            normalized.append(item)
        ordered = order_manifest_frames({"frames": normalized}, require_existing_files=True)
        return [item.frame for item in ordered.selected_frames]

    def _load_project_config(self) -> Dict[str, Any]:
        """读取项目 ROI 配置；文件缺失时使用装备页默认坐标。"""
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _merge_config(self, raw: Mapping[str, Any]) -> Dict[str, Any]:
        """把默认装备页坐标和项目配置合并，允许后续标注逐步覆盖。"""
        merged = json.loads(json.dumps(self.DEFAULT_CONFIG))
        reader_config = raw.get("equipment_page_reader", {}) if isinstance(raw, Mapping) else {}
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
    def _deep_update(target: Dict[str, Any], patch: Mapping[str, Any]) -> None:
        """递归合并配置字典。"""
        for key, value in patch.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                EquipmentPageReader._deep_update(target[key], value)  # type: ignore[index]
            else:
                target[key] = value

    def _scale(self, image_width: int, image_height: int) -> Tuple[float, float]:
        """根据当前截图分辨率计算 1280x720 坐标缩放比例。"""
        base_width, base_height = self.config["base_resolution"]
        return image_width / float(base_width), image_height / float(base_height)

    @staticmethod
    def _scale_point(point: Sequence[int | float], scale_x: float, scale_y: float) -> Tuple[int, int]:
        """缩放 x/y 坐标。"""
        return int(round(float(point[0]) * scale_x)), int(round(float(point[1]) * scale_y))

    @staticmethod
    def _scale_size(size: Sequence[int | float], scale_x: float, scale_y: float) -> Tuple[int, int]:
        """缩放 width/height 尺寸。"""
        return max(1, int(round(float(size[0]) * scale_x))), max(1, int(round(float(size[1]) * scale_y)))

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
    def _crop(image: Any, roi: RoiRegion) -> Any:
        """按 ROI 裁剪图像。"""
        x, y, width, height = roi
        return image[y:y + height, x:x + width]

    @staticmethod
    def _combined_confidence(icon_confidence: float, name_score: float, count_confidence: float) -> float:
        """融合图标、名称映射和数量 OCR 置信度，任一环偏低都会拉低结果。"""
        values = [float(icon_confidence or 0.0), float(name_score or 0.0), float(count_confidence or 0.0)]
        return EquipmentPageReader._clamp(min(values) * 0.70 + (sum(values) / len(values)) * 0.30)

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
            RecognitionScene.EQUIPMENT_LIST,
            screenshot_path=screenshot_path,
            warnings=warnings or (message,),
            message=message,
            detail=detail,
        )


__all__ = [
    "EquipmentPageCard",
    "EquipmentPageCardRead",
    "EquipmentPageReader",
]
