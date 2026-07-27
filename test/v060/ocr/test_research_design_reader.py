#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 科研设计图 OCR 对接测试                            ║
║                                                              ║
║  【测试目标】验证 research 场景、ADB manifest、去重和保守过滤。║
║  【类比理解】像给科研设计图流水线装几个保险扣，错的宁可复核。  ║
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
from core.contracts import EquipmentRecognitionRecord, RecognitionResult, RecognitionScene
from core.recognition.design_fragment_detector import (
    DesignFragmentCardCandidate,
    DesignFragmentDetectionResult,
)
from core.recognition.equipment_card_reader import FragmentQuantityReadResult
from core.recognition.equipment_icon_matcher import EquipmentIconCandidate, EquipmentIconMatchResult
from core.recognition.equipment_name_resolver import EquipmentNameCandidate, EquipmentNameResolveResult
from core.recognition.ocr_engine import OcrReadResult
from core.recognition.ocr_task_api import OCRResult, OcrDetection, OcrTaskApi, run_ocr_task
from core.recognition.research_design_reader import ResearchDesignReader


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeDesignDetector:
    """稳定返回设计图卡片候选的 fake detector。"""

    def __init__(self, cards: Sequence[DesignFragmentCardCandidate]) -> None:
        self.cards = tuple(cards)
        self.loaded_paths: list[Path] = []

    def load_image(self, screenshot_path: str | Path) -> Any:
        """模拟读取截图。"""
        self.loaded_paths.append(Path(screenshot_path))
        return _image()

    def detect(self, _image: Any) -> DesignFragmentDetectionResult:
        """返回预置卡片候选。"""
        return DesignFragmentDetectionResult(
            True,
            "success",
            "ok",
            (1280, 720),
            candidates=self.cards,
        )


class FakeIconMatcher:
    """稳定返回图标 top-N 候选。"""

    def __init__(self, status: str = "success", equipment_id: str = "G0001", confidence: float = 0.91) -> None:
        self.status = status
        self.equipment_id = equipment_id
        self.confidence = confidence

    def match_icon(self, _image: Any, icon_roi: Sequence[int] | None = None) -> EquipmentIconMatchResult:
        """模拟 OpenCV 图标识别。"""
        del icon_roi
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
    """按测试指定状态返回运行时装备名称→ID映射结果。"""

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
        candidate_ids = tuple(candidate_equipment_ids or ())
        self.calls.append((raw_text, candidate_ids))
        if not self.success:
            return EquipmentNameResolveResult(
                False,
                self.status,
                "fake ambiguous",
                normalized_text=raw_text,
                candidates=(
                    EquipmentNameCandidate("G0001", "试作型三联装305mmSKC39主炮#T0", 0.96, "base_exact"),
                    EquipmentNameCandidate("G0002", "试作型三联装305mm主炮#T0", 0.95, "base_exact"),
                ),
            )
        return EquipmentNameResolveResult(
            True,
            self.status,
            "fake resolved",
            "G0001",
            "试作型三联装305mmSKC39主炮#T0",
            0.98,
            raw_text,
            (EquipmentNameCandidate("G0001", "试作型三联装305mmSKC39主炮#T0", 0.98, "exact"),),
        )


class FakeCardReader:
    """稳定返回科研设计图碎片数量。"""

    def __init__(self, fragment_count: int | None = 42, success: bool = True) -> None:
        self.fragment_count = fragment_count
        self.success = success
        self.quantity_rois: list[Sequence[int] | None] = []

    def read_fragment_counts(
        self,
        _image: Any,
        card_roi: Sequence[int] | None = None,
        quantity_roi: Sequence[int] | None = None,
        confidence_threshold: float | None = None,
    ) -> FragmentQuantityReadResult:
        """模拟碎片 owned/required 数量 OCR。"""
        del card_roi, confidence_threshold
        self.quantity_rois.append(quantity_roi)
        if not self.success or self.fragment_count is None:
            return FragmentQuantityReadResult(False, "empty", "no fragment digits", confidence=0.0)
        return FragmentQuantityReadResult(
            True,
            "success",
            "ok",
            fragment_count=self.fragment_count,
            required_count=50,
            confidence=0.87,
            roi=(540, 120, 90, 42),
        )


class FakeOcrEngine:
    """默认不返回名称 OCR，让 reader 走图标 ID → 当前库名称 → 运行时 ID 映射。"""

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


class FakeResearchReader:
    """供 run_ocr_task 测试使用的轻量 reader。"""

    def __init__(self, recognition: RecognitionResult) -> None:
        self.recognition = recognition
        self.calls: list[Path] = []

    def analyze(self, path: Path, task_context: Any = None) -> RecognitionResult:
        """记录调用并返回预置 RecognitionResult。"""
        del task_context
        self.calls.append(Path(path))
        return self.recognition


def _image() -> Any:
    """构造一张有纹理的 1280x720 BGR 假截图。"""
    base = np.indices((720, 1280)).sum(axis=0).astype("uint8")
    return np.stack([base, np.roll(base, 5, axis=1), np.roll(base, 11, axis=0)], axis=2)


def _card(index: int = 1, visibility: str = "full") -> DesignFragmentCardCandidate:
    """构造一张设计图卡片候选。"""
    return DesignFragmentCardCandidate(
        index=index,
        row_index=1,
        column_index=index,
        bbox=(100 + index * 10, 80, 541, 135),
        raw_bbox=(100 + index * 10, 80, 541, 135),
        icon_roi=(120 + index * 10, 90, 108, 108),
        quantity_roi=(520 + index * 10, 105, 100, 45),
        visibility=visibility,
        confidence=0.90,
    )


def _touch(path: Path) -> Path:
    """创建截图占位文件。"""
    path.write_bytes(b"fake image placeholder")
    return path


def _library(root: Path) -> None:
    """创建最小运行时装备库；ID 必须由这里按名称映射得到。"""
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "equipment_library.csv").write_text(
        "equipment_id,name,rarity_id,type,research_phase,owned_quantity,fragment_quantity\n"
        "G0001,试作型三联装305mmSKC39主炮#T0,5,主炮,0,0,0\n",
        encoding="utf-8-sig",
    )


def _reader(
    root: Path,
    *,
    detector: FakeDesignDetector | None = None,
    resolver: FakeNameResolver | None = None,
    card_reader: FakeCardReader | None = None,
    icon_matcher: FakeIconMatcher | None = None,
) -> ResearchDesignReader:
    """构造注入 fake 依赖的科研设计图 reader。"""
    _library(root)
    return ResearchDesignReader(
        detector=detector or FakeDesignDetector((_card(),)),  # type: ignore[arg-type]
        icon_matcher=icon_matcher or FakeIconMatcher(),  # type: ignore[arg-type]
        name_resolver=resolver or FakeNameResolver(),  # type: ignore[arg-type]
        card_reader=card_reader or FakeCardReader(),  # type: ignore[arg-type]
        ocr_engine=FakeOcrEngine(),  # type: ignore[arg-type]
        project_root=root,
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_research_design_single_frame_maps_name_to_runtime_id_and_fragment_count(tmp_path: Path) -> None:
    """单张科研设计图截图应输出 fragment_count，并且 equipment_count 保持 0。"""
    screenshot = _touch(tmp_path / "frame_0000.png")
    resolver = FakeNameResolver()
    card_reader = FakeCardReader(fragment_count=42)
    reader = _reader(tmp_path, resolver=resolver, card_reader=card_reader)

    result = reader.analyze(screenshot)

    assert result.success is True
    assert result.scene is RecognitionScene.RESEARCH
    assert len(result.equipment_records) == 1
    record = result.equipment_records[0]
    assert record.equipment_id == "G0001"
    assert record.equipment_count == 0
    assert record.fragment_count == 42
    assert resolver.calls[0] == ("试作型三联装305mmSKC39主炮#T0", ("G0001",))
    assert card_reader.quantity_rois[0] == (420, 25, 100, 45)


def test_research_design_rejects_partial_card_before_auto_record(tmp_path: Path) -> None:
    """滚动边缘半截卡片必须 rejected_partial，不进入自动写入记录。"""
    screenshot = _touch(tmp_path / "frame_0000.png")
    reader = _reader(tmp_path, detector=FakeDesignDetector((_card(visibility="partial_bottom"),)))

    result = reader.analyze(screenshot)

    assert result.success is False
    assert result.equipment_records == ()
    assert any("rejected_partial" in warning for warning in result.warnings)


def test_research_design_ambiguous_name_does_not_enter_auto_records(tmp_path: Path) -> None:
    """名称无法唯一映射时只输出 needs_review，不进入 detections/records。"""
    screenshot = _touch(tmp_path / "frame_0000.png")
    reader = _reader(tmp_path, resolver=FakeNameResolver(success=False, status="ambiguous"))

    result = reader.analyze(screenshot)

    assert result.success is False
    assert result.equipment_records == ()
    assert result.detections == ()
    assert any("needs_review" in warning and "ambiguous" in warning for warning in result.warnings)


def test_research_design_manifest_skips_duplicate_frame_and_deduplicates_equipment_id(tmp_path: Path) -> None:
    """ADB manifest 重复帧应跳过，同一装备跨帧出现也不能重复累计。"""
    first = _touch(tmp_path / "frame_0000.png")
    duplicate = _touch(tmp_path / "frame_0001.png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "frames": [
                    {"screenshot_path": str(first), "frame_index": 0, "scroll_index": 0, "success": True},
                    {
                        "screenshot_path": str(duplicate),
                        "frame_index": 1,
                        "scroll_index": 1,
                        "success": True,
                        "is_duplicate_frame": True,
                    },
                ],
                "summary": {"next_resume_cursor": 2, "bottom_reached": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    detector = FakeDesignDetector((_card(),))
    reader = _reader(tmp_path, detector=detector)

    result = reader.analyze_manifest(manifest)

    assert result.success is True
    assert len(result.equipment_records) == 1
    assert detector.loaded_paths == [first.resolve()]
    assert "selected_frames=1" in result.detail


def test_run_ocr_task_research_returns_ocr_result_and_phase_select_is_not_research(tmp_path: Path) -> None:
    """run_ocr_task(research) 应返回 OCRResult；phase_select 不应误产出设计图记录。"""
    screenshot = _touch(tmp_path / "frame_0000.png")
    recognition = RecognitionResult(
        True,
        RecognitionScene.RESEARCH,
        screenshot_path=str(screenshot),
        equipment_records=(EquipmentRecognitionRecord("G0001", 0, 42, 0.93),),
    )
    fake_reader = FakeResearchReader(recognition)
    OcrTaskApi.reset_for_tests()
    ocr_task_api_module._ocr_task_api = OcrTaskApi(  # noqa: SLF001 - 测试注入全局入口替身。
        research_design_reader=fake_reader,  # type: ignore[arg-type]
        use_singleton=False,
    )

    result = run_ocr_task(screenshot, "research")
    phase_select = run_ocr_task(screenshot, "phase_select")

    assert isinstance(result, OCRResult)
    assert result.scene == "research"
    assert result.detections == (OcrDetection("G0001", 0, 42, 0.93),)
    assert fake_reader.calls == [screenshot]
    assert phase_select.scene == "phase_select"
    assert phase_select.detections == ()
    assert "不执行科研设计图" in phase_select.message
    OcrTaskApi.reset_for_tests()


def test_run_ocr_task_research_missing_path_is_safe(tmp_path: Path) -> None:
    """无效科研截图路径应返回 success=False，不抛异常。"""
    result = run_ocr_task(tmp_path / "missing.png", "research")

    assert result.success is False
    assert result.scene == "unknown"
    assert result.detections == ()
    assert "截图文件不存在" in result.message
