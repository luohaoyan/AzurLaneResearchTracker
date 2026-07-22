#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the isolated missing-equipment image refresher."""
from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image

from nn_training_lab.scripts.refresh_missing_equipment_images import (
    build_page_index,
    missing_targets,
    refresh_missing_images,
)


SOURCE_URL = "https://wiki.example/atlas"


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _make_icon(path: Path, color: tuple[int, int, int] = (10, 20, 30)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (115, 115), color).save(path, format="JPEG")


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/html; charset=UTF-8") -> None:
        self.content = body
        self.headers = {"content-type": content_type}
        self.encoding = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, html: str) -> None:
        self.html = html
        self.urls: list[str] = []

    def get(self, url: str, **_: object) -> _FakeResponse:
        self.urls.append(url)
        if url == SOURCE_URL:
            return _FakeResponse(self.html.encode("utf-8"))
        return _FakeResponse(b"not-an-image", "image/jpeg")


def test_build_page_index_uses_fragment_and_full_srcset() -> None:
    """The Wiki URL supplies the canonical T-level when title text is unreliable."""
    html = """
    <div class="divsort">
      <a href="/blhx/%E5%8F%8C%E8%81%94%E8%A3%85134mm%E9%AB%98%E7%82%AE#T1">
        <img src="https://example/thumb.jpg"
          srcset="https://example/thumb90.jpg 1.5x, https://example/full.jpg 2x">
      </a>
    </div>
    """

    index = build_page_index(html, SOURCE_URL)

    assert index["双联装134mm高炮#T1"] == "https://example/full.jpg"


def test_missing_targets_ignores_existing_files(tmp_path: Path) -> None:
    """Only absent paths are candidates; the formal CSV remains read-only."""
    _write_csv(
        tmp_path / "data" / "equipment_library.csv",
        ["equipment_id", "name", "rarity_id"],
        [{"equipment_id": "G0751", "name": "装备A", "rarity_id": "1"}, {"equipment_id": "G0752", "name": "装备B", "rarity_id": "1"}],
    )
    _write_csv(
        tmp_path / "data" / "equipment_images.csv",
        ["equipment_id", "image_path"],
        [{"equipment_id": "G0751", "image_path": "data/images/common/G0751.jpg"}, {"equipment_id": "G0752", "image_path": "data/images/common/G0752.jpg"}],
    )
    _make_icon(tmp_path / "data" / "images" / "common" / "G0751.jpg")

    targets = missing_targets(tmp_path)

    assert [item.equipment_id for item in targets] == ["G0752"]


def test_refresh_uses_reference_snapshot_when_current_wiki_has_no_old_item(tmp_path: Path) -> None:
    """Removed Wiki entries can be recovered from a prior crawler snapshot."""
    _write_csv(
        tmp_path / "data" / "equipment_library.csv",
        ["equipment_id", "name", "rarity_id"],
        [{"equipment_id": "G0751", "name": "旧装备#T1", "rarity_id": "1"}],
    )
    _write_csv(
        tmp_path / "data" / "equipment_images.csv",
        ["equipment_id", "image_path"],
        [{"equipment_id": "G0751", "image_path": "data/images/common/G0751.jpg"}],
    )
    reference = tmp_path / "reference" / "common" / "G0751.jpg"
    _make_icon(reference)
    session = _FakeSession('<div class="divsort"></div>')

    results = refresh_missing_images(tmp_path, missing_targets(tmp_path), SOURCE_URL, [tmp_path / "reference"], session=session)

    assert results[0].status == "success"
    assert results[0].source.startswith("reference:")
    assert (tmp_path / "data" / "images" / "common" / "G0751.jpg").is_file()
    assert (tmp_path / "nn_training_lab" / "archive" / "equipment_image_refresh").is_dir()
