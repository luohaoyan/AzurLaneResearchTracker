"""Tests for the ADB manifest to design-fragment recognition bridge."""
from __future__ import annotations

import argparse
from pathlib import Path

from core.recognition.adb_frame_order import order_manifest_frames
import recognition_workbench.run_adb_design_fragment_recognition as adb_workbench
from recognition_workbench.run_adb_design_fragment_recognition import collect_frame_paths, detect_empty_design_page


def test_collect_frame_paths_skips_duplicates_and_missing_files(tmp_path: Path) -> None:
    """默认只把存在且非重复的截图交给 OCR，避免重复统计。"""
    first = tmp_path / "frame_0000.png"
    duplicate = tmp_path / "frame_0001.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
    duplicate.write_bytes(b"\x89PNG\r\n\x1a\nduplicate")
    manifest = {
        "frames": [
            {"screenshot_path": str(first), "frame_index": 0, "success": True},
            {"screenshot_path": str(duplicate), "frame_index": 1, "success": True, "is_duplicate_frame": True},
            {"screenshot_path": str(tmp_path / "missing.png"), "frame_index": 2, "success": True},
            {"screenshot_path": "", "frame_index": 3, "success": False},
        ]
    }

    paths, frames = collect_frame_paths(manifest)

    assert paths == [first.resolve()]
    assert [frame["frame_index"] for frame in frames] == [0]


def test_collect_frame_paths_can_include_duplicate_frames(tmp_path: Path) -> None:
    """人工排查时允许把重复帧也送入 OCR。"""
    first = tmp_path / "frame_0000.png"
    second = tmp_path / "frame_0001.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
    second.write_bytes(b"\x89PNG\r\n\x1a\nsecond")
    manifest = {
        "frames": [
            {"screenshot_path": str(first), "frame_index": 0, "success": True},
            {"screenshot_path": str(second), "frame_index": 1, "success": True, "is_duplicate_frame": True},
        ]
    }

    paths, frames = collect_frame_paths(manifest, include_duplicates=True)

    assert paths == [first.resolve(), second.resolve()]
    assert [frame["frame_index"] for frame in frames] == [0, 1]


def test_manifest_frame_order_uses_frame_scroll_and_offset_fields(tmp_path: Path) -> None:
    """即使 manifest 原始数组乱序，也要按采集顺序交给 OCR。"""
    files = []
    for name in ("frame_a.png", "frame_b.png", "frame_c.png"):
        path = tmp_path / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode("ascii"))
        files.append(path)

    order = order_manifest_frames(
        {
            "frames": [
                {
                    "screenshot_path": str(files[2]),
                    "frame_index": 2,
                    "scroll_index": 2,
                    "scroll_offset_px": 936,
                    "success": True,
                },
                {
                    "screenshot_path": str(files[0]),
                    "frame_index": 0,
                    "scroll_index": 0,
                    "scroll_offset_px": 0,
                    "success": True,
                },
                {
                    "screenshot_path": str(files[1]),
                    "frame_index": 1,
                    "scroll_index": 1,
                    "scroll_offset_px": 320,
                    "success": True,
                },
            ],
            "next_resume_cursor": 3,
            "bottom_reached": True,
        }
    )

    assert list(order.image_paths) == [path.resolve() for path in files]
    assert order.resume_cursor == 3
    assert order.bottom_reached is True


def test_capture_adb_design_frames_passes_top_and_scroll_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """工作台应把顶部回卷和显式像素步长传给科研页 ADB 层。"""

    class FakeSession:
        def __init__(self) -> None:
            self.manifest_path = "C:/tmp/manifest.json"

        def to_dict(self) -> dict[str, object]:
            return {"success": True, "status": "ready"}

    class FakeApi:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def capture_design_chart_sequence(self, **kwargs: object) -> FakeSession:
            self.calls.append(dict(kwargs))
            return FakeSession()

    fake_api = FakeApi()
    monkeypatch.setattr(adb_workbench, "get_research_page_adb_api", lambda: fake_api)

    args = argparse.Namespace(
        frame_count=3,
        overlap_ratio=0.35,
        scroll_step_px=512,
        scroll_settle_ms=800,
        resume_cursor=2,
        prepare_page=False,
        no_stop_on_repeat=False,
        ensure_top=True,
        until_bottom=False,
        notify_actions=False,
        device_message_mode="none",
        capture_session_id="",
        filter_state="all",
        rarity_state="ultra_rare",
        sort_state="default",
    )

    manifest_path, session_dict = adb_workbench.capture_adb_design_frames(args)

    assert manifest_path.name == "manifest.json"
    assert session_dict["success"] is True
    assert fake_api.calls
    call = fake_api.calls[0]
    assert call["ensure_top"] is True
    assert call["scroll_step_px"] == 512
    assert call["resume_cursor"] == 2
    assert call["rarity_state"] == "ultra_rare"


def test_empty_design_page_skips_recognition_when_all_probe_frames_are_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """空稀有度页面只做卡片预检，不应进入 OCR/OpenCV/NN。"""
    first = tmp_path / "frame_0000.png"
    second = tmp_path / "frame_0001.png"
    first.write_bytes(b"placeholder")
    second.write_bytes(b"placeholder")

    class FakeResult:
        status = "empty"
        candidates: tuple[object, ...] = ()

    class FakeDetector:
        def detect(self, path: Path, image_mode: str = "viewport_full") -> FakeResult:
            return FakeResult()

    monkeypatch.setattr(
        "core.recognition.design_fragment_detector.DesignFragmentDetector",
        lambda: FakeDetector(),
    )

    assert detect_empty_design_page([first, second]) is True


def test_empty_design_page_does_not_skip_when_any_probe_has_cards(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """只要探针帧中有一张检测到卡片，就必须继续正式识别。"""
    first = tmp_path / "frame_0000.png"
    second = tmp_path / "frame_0001.png"
    first.write_bytes(b"placeholder")
    second.write_bytes(b"placeholder")

    class EmptyResult:
        status = "empty"
        candidates: tuple[object, ...] = ()

    class CardResult:
        status = "success"
        candidates = (object(),)

    class FakeDetector:
        def __init__(self) -> None:
            self.calls = 0

        def detect(self, path: Path, image_mode: str = "viewport_full") -> object:
            self.calls += 1
            return EmptyResult() if self.calls == 1 else CardResult()

    monkeypatch.setattr(
        "core.recognition.design_fragment_detector.DesignFragmentDetector",
        lambda: FakeDetector(),
    )

    assert detect_empty_design_page([first, second]) is False
