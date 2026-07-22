#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        Equipment card reader tests                          ║
║  Verifies that stack quantity and fragment quantity OCR use  ║
║  semantically safe ROIs instead of scanning the whole card.  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# Imports
# ============================================================

from pathlib import Path
from typing import Any, Optional

import numpy as np

from core.contracts import RecognitionScene
from core.recognition.equipment_card_reader import EquipmentCardDigitReader
from core.recognition.ocr_engine import OcrEngine, OcrReadResult
from core.recognition.scene_analyzer import SceneAnalyzer


# ============================================================
# Test helpers
# ============================================================

class FakeCardOcrEngine:
    """Minimal OCR engine that records requested ROIs and returns queued results."""

    confidence_threshold = 0.8

    def __init__(
        self,
        digit_results: Optional[list[OcrReadResult]] = None,
        text_results: Optional[list[OcrReadResult]] = None,
    ) -> None:
        self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.digit_results = list(digit_results or [])
        self.text_results = list(text_results or [])
        self.digit_rois: list[tuple[int, int, int, int]] = []
        self.text_rois: list[tuple[int, int, int, int]] = []

    def load_image(self, screenshot_path: str | Path) -> np.ndarray:
        """Return a synthetic screenshot; the file is only an API placeholder."""
        return self.image

    def validate_roi(self, image: np.ndarray, roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Validate that an ROI stays within the synthetic image."""
        x, y, width, height = (int(item) for item in roi)
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("ROI is invalid")
        if x + width > image.shape[1] or y + height > image.shape[0]:
            raise ValueError("ROI is out of bounds")
        return x, y, width, height

    def crop_roi(self, image: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
        """Crop an ROI for SceneAnalyzer state tests."""
        x, y, width, height = self.validate_roi(image, roi)
        return image[y:y + height, x:x + width]

    def recognize_digits(self, image: Any, roi=None, **kwargs: Any) -> OcrReadResult:
        """Return the next queued digit result and attach the requested ROI."""
        safe_roi = tuple(int(item) for item in roi)
        self.digit_rois.append(safe_roi)
        result = self.digit_results.pop(0)
        return OcrReadResult(
            result.success,
            result.status,
            result.message,
            text=result.text,
            value=result.value,
            confidence=result.confidence,
            raw_texts=result.raw_texts,
            roi=safe_roi,
            warnings=result.warnings,
        )

    def recognize_text(self, image: Any, roi=None, **kwargs: Any) -> OcrReadResult:
        """Return the next queued text result and attach the requested ROI."""
        safe_roi = tuple(int(item) for item in roi)
        self.text_rois.append(safe_roi)
        result = self.text_results.pop(0)
        return OcrReadResult(
            result.success,
            result.status,
            result.message,
            text=result.text,
            value=result.value,
            confidence=result.confidence,
            raw_texts=result.raw_texts,
            roi=safe_roi,
            warnings=result.warnings,
        )


def _ok_digit(value: int, confidence: float = 0.94) -> OcrReadResult:
    """Build a successful digit OCR result."""
    return OcrReadResult(True, "success", "ok", text=str(value), value=value, confidence=confidence)


def _ok_text(text: str, confidence: float = 0.93) -> OcrReadResult:
    """Build a successful text OCR result."""
    return OcrReadResult(True, "success", "ok", text=text, confidence=confidence, raw_texts=(text,))


def _touch(tmp_path: Path) -> Path:
    """Create a placeholder image path for fake engine based SceneAnalyzer tests."""
    path = tmp_path / "shot.png"
    path.write_bytes(b"fake")
    return path


# ============================================================
# Tests
# ============================================================

def test_stack_quantity_reads_right_bottom_roi_and_avoids_enhancement_area() -> None:
    """Equipment count OCR must inspect the right-bottom stack number, not left ``+10`` text."""
    engine = FakeCardOcrEngine(digit_results=[_ok_digit(1)])
    reader = EquipmentCardDigitReader(engine)  # type: ignore[arg-type]
    card = np.zeros((167, 142, 3), dtype=np.uint8)

    result = reader.read_stack_quantity(card)

    roi = engine.digit_rois[0]
    assert result.success is True
    assert result.value == 1
    assert roi[0] > int(card.shape[1] * 0.55)
    assert roi[1] > int(card.shape[0] * 0.45)


def test_fragment_pair_returns_owned_left_count_and_required_auxiliary() -> None:
    """For text like ``65/50``, the owned left value must become fragment_count."""
    engine = FakeCardOcrEngine(text_results=[_ok_text("65/50")])
    reader = EquipmentCardDigitReader(engine)  # type: ignore[arg-type]
    fragment_row = np.zeros((112, 438, 3), dtype=np.uint8)

    result = reader.read_fragment_counts(fragment_row)

    assert result.success is True
    assert result.fragment_count == 65
    assert result.required_count == 50
    assert engine.text_rois[0][0] > int(fragment_row.shape[1] * 0.60)


def test_integer_sequence_parser_keeps_fragment_sides_separate() -> None:
    """Numeric parsing should fix OCR noise but keep ``owned/required`` groups separate."""
    assert OcrEngine.extract_integer_sequence("O5/5O") == (5, 50)
    assert OcrEngine.extract_integer_sequence("1,234 / 50") == (1234, 50)
    assert OcrEngine.extract_integer_sequence("abc") == ()


def test_scene_analyzer_card_modes_build_frozen_equipment_records(tmp_path: Path) -> None:
    """SceneAnalyzer should route card-aware modes into equipment_count/fragment_count records."""
    config = {
        "schema_version": "0.6.0",
        "base_resolution": {"width": 1280, "height": 720},
        "calibration": {"status": "pending", "message": "pending calibration"},
        "scenes": {scene.value: {"rois": []} for scene in RecognitionScene},
    }
    config["scenes"]["equipment_list"] = {
        "rois": [
            {
                "name": "g0124_stack",
                "kind": "equipment_count",
                "equipment_id": "G0124",
                "mode": "equipment_stack_count",
                "bbox": [0, 0, 142, 167],
            },
            {
                "name": "g0116_fragment",
                "kind": "fragment_count",
                "equipment_id": "G0116",
                "mode": "fragment_pair",
                "bbox": [200, 0, 438, 112],
            },
        ]
    }
    engine = FakeCardOcrEngine(
        digit_results=[_ok_digit(9)],
        text_results=[_ok_text("65/50")],
    )
    analyzer = SceneAnalyzer(ocr_engine=engine, config=config)  # type: ignore[arg-type]

    result = analyzer.analyze(_touch(tmp_path), RecognitionScene.EQUIPMENT_LIST)

    records = {record.equipment_id: record.to_dict() for record in result.equipment_records}
    assert records["G0124"]["equipment_count"] == 9
    assert records["G0124"]["fragment_count"] == 0
    assert records["G0116"]["equipment_count"] == 0
    assert records["G0116"]["fragment_count"] == 65
    assert all("owned_quantity" not in record for record in records.values())
    assert any(detection.label == "g0116_fragment_required" and detection.value == 50 for detection in result.detections)
