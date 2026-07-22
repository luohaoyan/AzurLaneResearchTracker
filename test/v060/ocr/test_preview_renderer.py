"""Tests for OCR preview rendering helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from core.recognition.preview_renderer import _ascii_preview_text, draw_unicode_labels
from nn_training_lab.scripts.run_screenshot_pipeline import process_image


class _FakeCandidate:
    """Small card candidate stub used by process_image()."""

    index = 1
    visibility = "full"
    bbox = (10, 10, 120, 80)
    icon_roi = (18, 20, 48, 48)
    quantity_roi = (90, 55, 32, 18)


class _FakeDetection:
    """Small detection stub that mimics DesignFragmentDetectionResult."""

    success = True
    message = "ok"
    candidates = (_FakeCandidate(),)

    def to_dict(self) -> Dict[str, Any]:
        """Return the minimal serializable detection payload."""
        return {"success": True, "candidates": [{"index": 1}]}


class _FakeDetector:
    """Detector stub that prevents process_image() from touching real screenshots."""

    def __init__(self) -> None:
        """Create one black image for every fake screenshot."""
        self.image = np.zeros((120, 180, 3), dtype=np.uint8)

    def detect(self, image_path: Path, image_mode: str = "viewport_full") -> _FakeDetection:
        """Return one full card regardless of input path."""
        return _FakeDetection()

    def load_image(self, image_path: Path) -> Any:
        """Return a copy because annotation mutates the preview image."""
        return self.image.copy()


def test_unicode_preview_renderer_keeps_image_shape() -> None:
    """中文标签应能画到 OpenCV 图像上，不改变图像尺寸。"""
    image = np.zeros((80, 240, 3), dtype=np.uint8)
    rendered = draw_unicode_labels(image, [("试作型三联装305mmSKC39主炮#T0", (4, 24), (0, 255, 0), 16.0)])

    assert rendered.shape == image.shape


def test_ascii_fallback_does_not_emit_question_marks() -> None:
    """缺字体或 Pillow 时也不应继续生成一串问号占位。"""
    text = _ascii_preview_text("高性能舵机#T0", "unicode preview unavailable")

    assert "?" not in text
    assert text


def test_screenshot_pipeline_no_preview_keeps_structured_rows(tmp_path: Path) -> None:
    """关闭预览图时仍输出卡片结构，但不创建 annotated 文件。"""
    image_path = tmp_path / "design_super_rare_001.png"
    image_path.write_bytes(b"placeholder")

    result = process_image(
        image_path=image_path,
        output_dir=tmp_path,
        detector=_FakeDetector(),  # type: ignore[arg-type]
        reader=None,
        matcher=None,
        nn_detector=None,
        names={},
        name_resolver=None,
        name_config={},
        opencv_threshold=0.82,
        nn_min_confidence=0.55,
        nn_min_margin=0.08,
        disable_nn=True,
        image_mode="viewport_full",
        write_preview=False,
    )

    assert result["annotated_output"] == ""
    assert len(result["cards"]) == 1
    assert not (tmp_path / "annotated").exists()
