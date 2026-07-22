#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工确认 icon 归档器的幂等和库校验测试。"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from nn_training_lab.scripts.archive_confirmed_icon_cases import archive_cases


def _fixture_root(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "equipment_library.csv").write_text(
        "equipment_id,name,rarity_id,type\nS3-005,试作型三联装305mmSKC39主炮#T0,4,战列炮\n",
        encoding="utf-8",
    )
    screenshot = tmp_path / "source.png"
    Image.new("RGB", (1280, 720), (220, 180, 80)).save(screenshot)
    icon = tmp_path / "icon.png"
    Image.new("RGB", (108, 108), (40, 50, 60)).save(icon)
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [{
        "case_id": "case_one", "equipment_id": "S3-005", "equipment_name": "试作型三联装305mmSKC39主炮#T0",
        "source_screenshot": "source.png", "source_icon_crop": "icon.png", "card_no": 1,
        "bbox": [100, 100, 541, 135], "icon_roi": [115, 113, 108, 108], "rarity": "super_rare", "rarity_id": "4"
    }]}), encoding="utf-8")
    return cases, tmp_path / "archive"


def test_archive_confirmed_case_is_idempotent(tmp_path: Path) -> None:
    cases, archive = _fixture_root(tmp_path)
    first = archive_cases(tmp_path, cases, archive)
    second = archive_cases(tmp_path, cases, archive)
    assert first["manifest_rows_added"] == 1
    assert second["manifest_rows_added"] == 0
    assert (archive / "human_label_archive" / "confirmed_cases" / "case_one" / "card_crop.png").is_file()
    assert (archive / "reviewed_icon_gallery" / "S3-005" / "confirmed_case_one_S3-005_icon.png").is_file()


def test_archive_can_crop_icon_from_full_screenshot(tmp_path: Path) -> None:
    cases, archive = _fixture_root(tmp_path)
    payload = json.loads(cases.read_text(encoding="utf-8"))
    payload["cases"][0]["source_icon_crop"] = ""
    payload["cases"][0]["icon_roi"] = [115, 113, 108, 108]
    cases.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    archive_cases(tmp_path, cases, archive)
    generated = archive / "human_label_archive" / "confirmed_cases" / "case_one" / "source_icon_crop.png"
    assert Image.open(generated).size == (108, 108)
