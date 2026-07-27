#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 装备页 OCR 对接测试                                ║
║                                                              ║
║  【测试目标】验证 ADB 分帧、名称映射、去重和保守过滤契约。     ║
║  【类比理解】像在正式识别前先核对仓库清点流水线的每个交接口。  ║
║  【数据流说明】fake frame/manifest → reader/API → OCRResult。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

import core.recognition.ocr_task_api as ocr_task_api_module
from core.recognition.adb_frame_order import order_manifest_frames
from core.recognition.equipment_icon_matcher import (
    EquipmentIconCandidate,
    EquipmentIconMatchResult,
)
from core.recognition.equipment_name_resolver import (
    EquipmentNameCandidate,
    EquipmentNameResolveResult,
)
from core.recognition.equipment_page_reader import EquipmentPageReader
from core.recognition.ocr_engine import OcrReadResult
from core.recognition.ocr_task_api import OCRResult, OcrDetection, OcrTaskApi, run_ocr_task


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeCv2:
    """只提供 imread 的 fake cv2，避免测试依赖真实 PNG 编码。"""

    IMREAD_COLOR = 1

    def __init__(self, image: Any) -> None:
        self.image = image
        self.reads: list[str] = []

    def imread(self, path: str, _flags: int = 1) -> Any:
        """记录读取路径并返回测试图像副本。"""
        self.reads.append(path)
        return self.image.copy()


class FakeIconMatcher:
    """稳定返回同一个图标候选。"""

    def __init__(self, status: str = "success", equipment_id: str = "G0001", confidence: float = 0.91) -> None:
        self.status = status
        self.equipment_id = equipment_id
        self.confidence = confidence

    def match_card(self, _card_image: Any, card_type: str = "equipment") -> EquipmentIconMatchResult:
        """模拟 OpenCV 图标匹配输出。"""
        candidate = EquipmentIconCandidate(
            self.equipment_id,
            self.confidence,
            "fake.png",
            1,
            "fake",
            {"structure": self.confidence},
        )
        return EquipmentIconMatchResult(
            True,
            self.status,
            "fake icon result",
            equipment_id=self.equipment_id if self.status == "success" else "unknown",
            confidence=self.confidence,
            candidates=(candidate,),
        )


class FakeNameResolver:
    """按测试指定状态返回运行时装备 ID 映射结果。"""

    def __init__(self, success: bool = True, status: str = "icon_candidates_exact") -> None:
        self.success = success
        self.status = status
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def resolve(
        self,
        raw_text: str,
        candidate_equipment_ids: Sequence[str] | None = None,
        min_score: float | None = None,
    ) -> EquipmentNameResolveResult:
        """记录名称解析输入并返回预置结果。"""
        del min_score
        candidates = tuple(candidate_equipment_ids or ())
        self.calls.append((raw_text, candidates))
        if not self.success:
            return EquipmentNameResolveResult(
                False,
                self.status,
                "fake ambiguous",
                normalized_text=raw_text,
                candidates=(
                    EquipmentNameCandidate("G0001", "高性能对空雷达#T0", 0.96, "base_exact"),
                    EquipmentNameCandidate("G0002", "高性能对空雷达#T1", 0.95, "base_exact"),
                ),
            )
        return EquipmentNameResolveResult(
            True,
            self.status,
            "fake resolved",
            "G0001",
            "高性能对空雷达#T0",
            0.98,
            raw_text,
            (EquipmentNameCandidate("G0001", "高性能对空雷达#T0", 0.98, "exact"),),
        )


class FakeCardReader:
    """稳定返回装备右下角堆叠数量。"""

    def __init__(self, value: int | None = 7, success: bool = True) -> None:
        self.value = value
        self.success = success

    def read_equipment_count(self, _image: Any, confidence_threshold: float | None = None) -> OcrReadResult:
        """模拟数量 OCR。"""
        del confidence_threshold
        if not self.success or self.value is None:
            return OcrReadResult(False, "empty", "no digits", confidence=0.0)
        return OcrReadResult(True, "success", "ok", value=self.value, text=str(self.value), confidence=0.88, roi=(92, 74, 37, 47))


class FakeOcrEngine:
    """名称 OCR 默认不可用，让 reader 走图标 ID → 名称 → 运行时 ID 映射。"""

    def recognize_text(
        self,
        _image: Any,
        roi: Sequence[int] | None = None,
        confidence_threshold: float | None = None,
        preprocess: bool = False,
    ) -> OcrReadResult:
        """模拟名称 OCR 无结果。"""
        del confidence_threshold, preprocess
        return OcrReadResult(False, "empty", "name not read", roi=tuple(roi) if roi else None)


class FakeEquipmentPageReader:
    """供 run_ocr_task 测试使用的轻量 reader。"""

    def __init__(self, recognition: Any) -> None:
        self.recognition = recognition

    def analyze(self, _path: Path, task_context: Any = None) -> Any:
        """返回预置 RecognitionResult。"""
        del task_context
        return self.recognition


def _image() -> Any:
    """构造一张有纹理的 1280x720 BGR 假截图，避免被低质量过滤。"""
    base = np.indices((720, 1280)).sum(axis=0).astype("uint8")
    return np.stack([base, np.roll(base, 7, axis=1), np.roll(base, 13, axis=0)], axis=2)


def _touch(path: Path) -> Path:
    """创建截图占位文件。"""
    path.write_bytes(b"fake image placeholder")
    return path


def _library(root: Path) -> None:
    """创建最小运行时装备库，reader 必须经由这里的名称再映射 ID。"""
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "equipment_library.csv").write_text(
        "equipment_id,name,rarity_id,type,research_phase,owned_quantity,fragment_quantity\n"
        "G0001,高性能对空雷达#T0,5,设备,0,0,0\n",
        encoding="utf-8-sig",
    )


def _reader(
    root: Path,
    *,
    resolver: FakeNameResolver | None = None,
    cv2: FakeCv2 | None = None,
    rows: int = 1,
    columns: int = 1,
) -> EquipmentPageReader:
    """构造注入 fake 依赖的装备页 reader。"""
    _library(root)
    return EquipmentPageReader(
        icon_matcher=FakeIconMatcher(),  # type: ignore[arg-type]
        name_resolver=resolver or FakeNameResolver(),  # type: ignore[arg-type]
        card_reader=FakeCardReader(),  # type: ignore[arg-type]
        ocr_engine=FakeOcrEngine(),  # type: ignore[arg-type]
        config={"equipment_page_reader": {"card_grid": {"rows": rows, "columns": columns}}},
        project_root=root,
        cv2_module=cv2 or FakeCv2(_image()),
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_equipment_page_single_frame_maps_name_to_runtime_equipment_id(tmp_path: Path) -> None:
    """单张装备页截图应通过装备名称映射出运行时 equipment_id。"""
    resolver = FakeNameResolver()
    screenshot = _touch(tmp_path / "frame_0000.png")
    reader = _reader(tmp_path, resolver=resolver)

    result = reader.analyze(screenshot)

    assert result.success is True
    assert len(result.equipment_records) == 1
    record = result.equipment_records[0]
    assert record.equipment_id == "G0001"
    assert record.equipment_count == 7
    assert record.fragment_count == 0
    assert isinstance(record.equipment_count, int)
    assert isinstance(record.fragment_count, int)
    assert resolver.calls[0] == ("高性能对空雷达#T0", ("G0001",))


def test_equipment_page_ambiguous_name_does_not_enter_auto_records(tmp_path: Path) -> None:
    """名称无法唯一映射时只输出 warning，不进入自动写入候选。"""
    screenshot = _touch(tmp_path / "frame_0000.png")
    reader = _reader(tmp_path, resolver=FakeNameResolver(success=False, status="ambiguous"))

    result = reader.analyze(screenshot)

    assert result.success is False
    assert result.equipment_records == ()
    assert any("needs_review" in warning and "ambiguous" in warning for warning in result.warnings)


def test_equipment_page_manifest_accepts_adb_artifacts_and_skips_duplicate_sha1(tmp_path: Path) -> None:
    """装备页 capture_manifest.json 的 artifacts 应可被 OCR 消费并按 sha1 去重。"""
    first = _touch(tmp_path / "frame_0000.png")
    duplicate = _touch(tmp_path / "frame_0001.png")
    manifest = tmp_path / "capture_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "session_id": "session_x",
                "artifacts": [
                    {"screenshot_path": str(first), "frame_index": 0, "sha1": "same", "success": True},
                    {"screenshot_path": str(duplicate), "frame_index": 1, "sha1": "same", "success": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fake_cv2 = FakeCv2(_image())
    reader = _reader(tmp_path, cv2=fake_cv2)

    result = reader.analyze_manifest(manifest)

    assert result.success is True
    assert len(result.equipment_records) == 1
    assert fake_cv2.reads == [str(first.resolve())]


def test_same_equipment_id_cards_are_summed_after_card_level_dedup(tmp_path: Path) -> None:
    """同一装备 ID 的不同卡片要累加，不能像滚动重复帧一样只保留一条。"""
    screenshot = _touch(tmp_path / "frame_0000.png")
    reader = _reader(tmp_path, rows=1, columns=2)

    result = reader.analyze(screenshot)

    assert result.success is True
    assert len(result.equipment_records) == 1
    assert result.equipment_records[0].equipment_id == "G0001"
    assert result.equipment_records[0].equipment_count == 14


def test_order_manifest_frames_supports_equipment_artifacts(tmp_path: Path) -> None:
    """通用 ADB 帧排序器应兼容装备页只有 artifacts 的 manifest。"""
    first = _touch(tmp_path / "frame_0000.png")
    second = _touch(tmp_path / "frame_0001.png")

    order = order_manifest_frames(
        {
            "artifacts": [
                {"screenshot_path": str(second), "frame_index": 1, "success": True},
                {"screenshot_path": str(first), "frame_index": 0, "success": True},
            ],
            "next_resume_cursor": 2,
        }
    )

    assert list(order.image_paths) == [first.resolve(), second.resolve()]
    assert order.resume_cursor == 2


def test_run_ocr_task_returns_equipment_contract_and_invalid_path_is_safe(tmp_path: Path) -> None:
    """run_ocr_task 应返回 OCRResult/OcrDetection 契约，坏路径不抛异常。"""
    from core.contracts import EquipmentRecognitionRecord, RecognitionResult, RecognitionScene

    screenshot = _touch(tmp_path / "frame_0000.png")
    recognition = RecognitionResult(
        True,
        RecognitionScene.EQUIPMENT_LIST,
        screenshot_path=str(screenshot),
        equipment_records=(EquipmentRecognitionRecord("G0001", 3, 0, 0.93),),
    )
    OcrTaskApi.reset_for_tests()
    ocr_task_api_module._ocr_task_api = OcrTaskApi(  # noqa: SLF001 - 测试注入全局入口替身。
        equipment_page_reader=FakeEquipmentPageReader(recognition),  # type: ignore[arg-type]
        use_singleton=False,
    )

    result = run_ocr_task(screenshot, "equipment_list")
    missing = run_ocr_task(tmp_path / "missing.png", "equipment_list")

    assert isinstance(result, OCRResult)
    assert result.scene == "equipment_list"
    assert result.detections == (OcrDetection("G0001", 3, 0, 0.93),)
    assert missing.success is False
    assert missing.detections == ()
    OcrTaskApi.reset_for_tests()
