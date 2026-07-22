#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        Equipment card digit reader                          ║
║  Reads only semantically safe number areas from warehouse    ║
║  cards: right-bottom stack counts and fragment pair counts.  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# Imports
# ============================================================

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.recognition.ocr_engine import OcrEngine, OcrReadResult


# ============================================================
# Result objects
# ============================================================

RoiRegion = Tuple[int, int, int, int]
RatioRegion = Tuple[float, float, float, float]


@dataclass(frozen=True)
class FragmentQuantityReadResult:
    """Structured result for a fragment card's ``owned/required`` text."""

    success: bool
    status: str
    message: str
    fragment_count: Optional[int] = None
    required_count: Optional[int] = None
    confidence: float = 0.0
    text: str = ""
    raw_texts: Tuple[str, ...] = ()
    roi: Optional[RoiRegion] = None
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to plain Python values for tests and payloads."""
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "fragment_count": self.fragment_count,
            "required_count": self.required_count,
            "confidence": float(self.confidence),
            "text": self.text,
            "raw_texts": list(self.raw_texts),
            "roi": list(self.roi) if self.roi else None,
            "warnings": list(self.warnings),
        }


# ============================================================
# Card digit reader
# ============================================================

class EquipmentCardDigitReader:
    """Read count digits from warehouse card ROIs without scanning unsafe areas."""

    STACK_COUNT_RATIOS: Tuple[RatioRegion, ...] = (
        (0.70, 0.57, 0.28, 0.36),
        (0.62, 0.50, 0.36, 0.46),
    )
    FRAGMENT_PAIR_RATIOS: Tuple[RatioRegion, ...] = (
        (0.72, 0.04, 0.26, 0.42),
        (0.66, 0.00, 0.32, 0.50),
    )

    def __init__(self, ocr_engine: OcrEngine, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize with an OCR engine; PaddleOCR is still loaded lazily."""
        self.ocr_engine = ocr_engine
        self.config = config or {}
        self.stack_count_ratios = self._ratios_from_config("stack_count_ratios", self.STACK_COUNT_RATIOS)
        self.fragment_pair_ratios = self._ratios_from_config("fragment_pair_ratios", self.FRAGMENT_PAIR_RATIOS)

    def read_equipment_count(
        self,
        image: Any,
        card_roi: Optional[Sequence[int]] = None,
        quantity_roi: Optional[Sequence[int | float]] = None,
        confidence_threshold: Optional[float] = None,
    ) -> OcrReadResult:
        """Read the right-bottom stack quantity and avoid left-bottom enhancement level."""
        return self.read_stack_quantity(
            image,
            card_roi=card_roi,
            quantity_roi=quantity_roi,
            confidence_threshold=confidence_threshold,
        )

    def read_stack_quantity(
        self,
        image: Any,
        card_roi: Optional[Sequence[int]] = None,
        quantity_roi: Optional[Sequence[int | float]] = None,
        confidence_threshold: Optional[float] = None,
    ) -> OcrReadResult:
        """Read equipment stack quantity from the card's right-bottom corner only."""
        try:
            candidates = self._candidate_rois(image, card_roi, quantity_roi, self.stack_count_ratios)
        except Exception as exc:
            return OcrReadResult(False, "error", str(exc), roi=self._coerce_roi_or_none(card_roi))

        last_result: Optional[OcrReadResult] = None
        for roi in candidates:
            result = self.ocr_engine.recognize_digits(
                image,
                roi=roi,
                confidence_threshold=confidence_threshold,
                preprocess=True,
            )
            if result.success and result.value is not None:
                return result
            last_result = result

        if last_result is not None:
            return last_result
        return OcrReadResult(False, "empty", "No stack quantity ROI candidate was available.")

    def read_fragment_counts(
        self,
        image: Any,
        card_roi: Optional[Sequence[int]] = None,
        quantity_roi: Optional[Sequence[int | float]] = None,
        confidence_threshold: Optional[float] = None,
    ) -> FragmentQuantityReadResult:
        """Read ``owned/required`` fragment text; the first number is the owned count."""
        try:
            candidates = self._candidate_rois(image, card_roi, quantity_roi, self.fragment_pair_ratios)
        except Exception as exc:
            return FragmentQuantityReadResult(False, "error", str(exc), roi=self._coerce_roi_or_none(card_roi))

        last_result: Optional[OcrReadResult] = None
        for roi in candidates:
            # 设计图碎片数量本身是白色描边大号数字，PaddleOCR 在原图 ROI 上通常更稳定；
            # 二值化会把斜杠和描边打碎，因此只在原图失败后再把预处理作为兜底。
            for preprocess in (False, True):
                result = self.ocr_engine.recognize_text(
                    image,
                    roi=roi,
                    confidence_threshold=confidence_threshold,
                    preprocess=preprocess,
                )
                if not result.success:
                    last_result = result
                    continue

                numbers = self._numbers_from_ocr_result(result)
                if numbers:
                    required = numbers[1] if len(numbers) >= 2 else None
                    warnings = () if required is not None else ("Only owned fragment count was recognized.",)
                    return FragmentQuantityReadResult(
                        True,
                        "success",
                        "Fragment quantity OCR completed.",
                        fragment_count=int(numbers[0]),
                        required_count=required,
                        confidence=float(result.confidence),
                        text=result.text,
                        raw_texts=result.raw_texts,
                        roi=result.roi,
                        warnings=warnings,
                    )
                last_result = result

        if last_result is None:
            return FragmentQuantityReadResult(False, "empty", "No fragment count ROI candidate was available.")
        return FragmentQuantityReadResult(
            False,
            last_result.status,
            last_result.message,
            confidence=float(last_result.confidence),
            text=last_result.text,
            raw_texts=last_result.raw_texts,
            roi=last_result.roi,
            warnings=last_result.warnings,
        )

    def _candidate_rois(
        self,
        image: Any,
        parent_roi: Optional[Sequence[int]],
        child_roi: Optional[Sequence[int | float]],
        ratios: Sequence[RatioRegion],
    ) -> Tuple[RoiRegion, ...]:
        """Resolve explicit child ROI or ratio candidates into absolute image ROIs."""
        parent = self._parent_roi(image, parent_roi)
        if child_roi is not None:
            return (self._child_roi(parent, child_roi),)
        return tuple(self._ratio_roi(parent, ratio) for ratio in ratios)

    def _parent_roi(self, image: Any, parent_roi: Optional[Sequence[int]]) -> RoiRegion:
        """Return the validated card ROI, or the whole image when omitted."""
        if image is None or not hasattr(image, "shape"):
            raise ValueError("Image is empty; card digit ROI cannot be resolved.")
        if parent_roi is None:
            height, width = int(image.shape[0]), int(image.shape[1])
            parent = (0, 0, width, height)
        else:
            parent = tuple(int(item) for item in parent_roi)
        return self.ocr_engine.validate_roi(image, parent)

    def _child_roi(self, parent: RoiRegion, child_roi: Sequence[int | float]) -> RoiRegion:
        """Resolve an explicit child ROI relative to the parent card ROI."""
        values = tuple(child_roi)
        if len(values) != 4:
            raise ValueError("Child ROI must contain x, y, width and height.")
        if all(isinstance(item, float) and 0.0 <= item <= 1.0 for item in values):
            return self._ratio_roi(parent, values)  # type: ignore[arg-type]
        parent_x, parent_y, parent_width, parent_height = parent
        x, y, width, height = (int(round(float(item))) for item in values)
        roi = (parent_x + x, parent_y + y, max(1, width), max(1, height))
        return self._clamp_to_parent(roi, parent_width, parent_height, parent_x, parent_y)

    def _ratio_roi(self, parent: RoiRegion, ratio: RatioRegion) -> RoiRegion:
        """Convert a relative ROI ratio into an absolute image ROI."""
        parent_x, parent_y, parent_width, parent_height = parent
        rel_x, rel_y, rel_width, rel_height = ratio
        roi = (
            parent_x + int(round(parent_width * rel_x)),
            parent_y + int(round(parent_height * rel_y)),
            max(1, int(round(parent_width * rel_width))),
            max(1, int(round(parent_height * rel_height))),
        )
        return self._clamp_to_parent(roi, parent_width, parent_height, parent_x, parent_y)

    @staticmethod
    def _clamp_to_parent(
        roi: RoiRegion,
        parent_width: int,
        parent_height: int,
        parent_x: int,
        parent_y: int,
    ) -> RoiRegion:
        """Keep a child ROI inside its parent card bounds."""
        x, y, width, height = roi
        max_x = parent_x + parent_width
        max_y = parent_y + parent_height
        x = min(max(parent_x, x), max_x - 1)
        y = min(max(parent_y, y), max_y - 1)
        width = max(1, min(width, max_x - x))
        height = max(1, min(height, max_y - y))
        return x, y, width, height

    @staticmethod
    def _numbers_from_ocr_result(result: OcrReadResult) -> Tuple[int, ...]:
        """Parse ordered integers from best text first, then from all raw OCR texts."""
        texts: List[str] = []
        for text in (result.text, *result.raw_texts):
            if text and text not in texts:
                texts.append(text)

        for text in texts:
            numbers = OcrEngine.extract_integer_sequence(text)
            if len(numbers) >= 2:
                return numbers

        combined_numbers = OcrEngine.extract_integer_sequence("/".join(texts))
        if combined_numbers:
            return combined_numbers
        return ()

    def _ratios_from_config(
        self,
        key: str,
        default: Tuple[RatioRegion, ...],
    ) -> Tuple[RatioRegion, ...]:
        """Read optional ratio candidates from config, falling back to safe defaults."""
        raw = self.config.get(key)
        if not isinstance(raw, list):
            return default
        ratios: List[RatioRegion] = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) != 4:
                continue
            values = tuple(float(value) for value in item)
            if all(0.0 <= value <= 1.0 for value in values) and values[2] > 0 and values[3] > 0:
                ratios.append(values)  # type: ignore[arg-type]
        return tuple(ratios) or default

    @staticmethod
    def _coerce_roi_or_none(roi: Optional[Sequence[int]]) -> Optional[RoiRegion]:
        """Best-effort ROI coercion for friendly error results."""
        if roi is None:
            return None
        try:
            if len(tuple(roi)) != 4:
                return None
            return tuple(int(item) for item in roi)  # type: ignore[return-value]
        except Exception:
            return None
