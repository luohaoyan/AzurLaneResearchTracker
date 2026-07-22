"""Tests for optional ONNX icon deployment helpers."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from nn_training_lab.inference.onnx_icon_classifier import (
    OnnxEquipmentIconClassifier,
    OnnxIconCandidate,
    OnnxIconResult,
    choose_providers,
    preprocess_icon,
)


def test_onnx_missing_model_reports_unavailable(tmp_path: Path) -> None:
    """缺模型文件时 ONNX 后端应友好报告，而不是导入崩溃。"""
    classifier = OnnxEquipmentIconClassifier(
        tmp_path / "missing.onnx",
        tmp_path / "label_map.json",
        tmp_path / "equipment_library.csv",
    )

    status = classifier.check_status()

    assert status["model_exists"] is False
    assert classifier.predict_file(tmp_path / "missing.png").status == "error"


def test_onnx_rejects_partial_icon_before_model_load(tmp_path: Path) -> None:
    """非正方形截图不能进入模型推理。"""
    image = tmp_path / "partial.png"
    Image.new("RGB", (120, 80), (0, 0, 0)).save(image)

    classifier = OnnxEquipmentIconClassifier(
        tmp_path / "missing.onnx",
        tmp_path / "label_map.json",
        tmp_path / "equipment_library.csv",
    )
    result = classifier.predict_file(image)

    assert result.status == "rejected"


def test_preprocess_icon_outputs_nchw_float32(tmp_path: Path) -> None:
    """完整 icon 应转为 ONNX Runtime 使用的 NCHW float32。"""
    image = tmp_path / "icon.png"
    Image.new("RGB", (108, 108), (120, 80, 40)).save(image)

    tensor = preprocess_icon(image)

    assert tensor.shape == (1, 3, 224, 224)
    assert str(tensor.dtype) == "float32"


def test_onnx_result_serializes_equipment_name_first() -> None:
    """ONNX 输出主身份仍是 equipment_name，ID 只是运行时映射。"""
    result = OnnxIconResult(
        status="success",
        message="ok",
        provider="CPUExecutionProvider",
        candidates=(
            OnnxIconCandidate(
                equipment_name="试作型三联装310mm主炮#T0",
                confidence=0.98,
                rank=1,
                equipment_id="S2-002",
            ),
        ),
    ).to_dict()

    candidate = result["candidates"][0]
    assert candidate["equipment_name"] == "试作型三联装310mm主炮#T0"
    assert candidate["equipment_id"] == "S2-002"
    assert result["provider"] == "CPUExecutionProvider"


def test_choose_providers_keeps_cpu_fallback() -> None:
    """无论有没有 GPU provider，都应保留 CPU fallback。"""
    providers = choose_providers(())

    assert isinstance(providers, list)
    if providers:
        assert "CPUExecutionProvider" in providers
