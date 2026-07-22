"""Contract tests for optional local NN inference."""
from __future__ import annotations

from pathlib import Path

from nn_training_lab.inference.equipment_icon_nn import (
    EquipmentIconNN,
    NNCandidate,
    NNInferenceResult,
    should_use_nn_fallback,
)


def test_missing_checkpoint_is_reported_without_network_or_crash(tmp_path: Path) -> None:
    """An absent local checkpoint remains a friendly unavailable state."""
    detector = EquipmentIconNN(tmp_path / "model", tmp_path / "dataset")
    status = detector.check_status()
    assert status["checkpoint_exists"] is False
    result = detector.predict_file(tmp_path / "missing.png")
    assert result.status in {"error", "unavailable"}


def test_partial_icon_is_rejected_before_model_load(tmp_path: Path) -> None:
    """A non-square crop cannot silently enter the classifier."""
    from PIL import Image

    image = tmp_path / "partial.png"
    Image.new("RGB", (120, 80), (0, 0, 0)).save(image)
    detector = EquipmentIconNN(tmp_path / "model", tmp_path / "dataset")
    result = detector.predict_file(image)
    assert result.status == "rejected"


def test_fallback_policy_only_targets_uncertain_opencv_results() -> None:
    """Confident OpenCV matches do not pay the NN inference cost."""
    assert should_use_nn_fallback("success", 0.95, threshold=0.82) is False
    assert should_use_nn_fallback("ambiguous", 0.95, threshold=0.82) is True
    assert should_use_nn_fallback("success", 0.60, threshold=0.82) is True


def test_nn_serialization_uses_equipment_name_as_primary_identity() -> None:
    """The model result remains stable when the runtime ID mapping changes."""
    result = NNInferenceResult(
        status="success",
        message="ok",
        candidates=(
            NNCandidate(
                equipment_name="五联装533mm鱼雷Mk17#T0",
                confidence=0.91,
                rank=1,
                equipment_id="G0103",
            ),
        ),
    ).to_dict()
    candidate = result["candidates"][0]
    assert candidate["equipment_name"] == "五联装533mm鱼雷Mk17#T0"
    assert candidate["equipment_id"] == "G0103"
    assert candidate["resolved_equipment_id"] == "G0103"
