#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""科研图片整理包的单元测试。"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.research_image_bundle import ResearchPhaseImageBundle


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    """写一个临时 CSV 给测试用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_bytes(path: Path, content: bytes) -> None:
    """写入一份可复制的假图片文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_collect_copies_images_by_phase_order(tmp_path: Path) -> None:
    """应按 S0/S1 顺序把图片复制到 manifests/s 目录。"""
    source_root = tmp_path / "source_archive"
    source_library_csv = source_root / "equipment_library_stage.csv"
    source_images_csv = source_root / "equipment_images_stage.csv"

    _write_csv(
        source_library_csv,
        ["equipment_id", "name", "rarity_id", "type"],
        [
            {"equipment_id": "G0001", "name": "通用炮A", "rarity_id": "5", "type": "战列炮"},
            {"equipment_id": "G0002", "name": "通用炮B", "rarity_id": "4", "type": "轻巡炮"},
            {"equipment_id": "G0003", "name": "一期炮A", "rarity_id": "5", "type": "战列炮"},
            {"equipment_id": "G0004", "name": "一期炮B", "rarity_id": "4", "type": "轻巡炮"},
        ],
    )
    _write_csv(
        source_images_csv,
        ["equipment_id", "image_path"],
        [
            {"equipment_id": "G0001", "image_path": "source_images/common/G0001.jpg"},
            {"equipment_id": "G0002", "image_path": "source_images/common/G0002.jpg"},
            {"equipment_id": "G0003", "image_path": "source_images/phase1/G0003.jpg"},
            {"equipment_id": "G0004", "image_path": "source_images/phase1/G0004.jpg"},
        ],
    )
    _write_bytes(tmp_path / "source_images" / "common" / "G0001.jpg", b"img-1")
    _write_bytes(tmp_path / "source_images" / "common" / "G0002.jpg", b"img-2")
    _write_bytes(tmp_path / "source_images" / "phase1" / "G0003.jpg", b"img-3")
    _write_bytes(tmp_path / "source_images" / "phase1" / "G0004.jpg", b"img-4")

    run_dir = tmp_path / "research_run"
    manifests_dir = run_dir / "manifests"
    _write_csv(
        manifests_dir / "research_phases_stage.csv",
        ["phase_number", "name", "equipment_list"],
        [
            {"phase_number": "0", "name": "通用科研装备(S0)", "equipment_list": "S0-001,S0-002"},
            {"phase_number": "1", "name": "科研一期", "equipment_list": "S1-001,S1-002"},
        ],
    )
    _write_csv(
        manifests_dir / "research_equipment_stage.csv",
        ["equipment_id", "name", "phase_number", "phase_name", "source_scope", "order_index"],
        [
            {
                "equipment_id": "S0-001",
                "name": "通用炮A",
                "phase_number": "0",
                "phase_name": "通用科研装备(S0)",
                "source_scope": "common",
                "order_index": "1",
            },
            {
                "equipment_id": "S0-002",
                "name": "通用炮B",
                "phase_number": "0",
                "phase_name": "通用科研装备(S0)",
                "source_scope": "common",
                "order_index": "2",
            },
            {
                "equipment_id": "S1-001",
                "name": "一期炮A",
                "phase_number": "1",
                "phase_name": "科研一期",
                "source_scope": "phase",
                "order_index": "1",
            },
            {
                "equipment_id": "S1-002",
                "name": "一期炮B",
                "phase_number": "1",
                "phase_name": "科研一期",
                "source_scope": "phase",
                "order_index": "2",
            },
        ],
    )

    collector = ResearchPhaseImageBundle(
        config_data={
            "source": {
                "research_run_dir": str(run_dir),
                "source_library_csv": str(source_library_csv),
                "source_images_csv": str(source_images_csv),
            },
            "output": {
                "output_folder_name": "s",
                "manifest_name": "research_image_bundle_manifest.json",
            },
            "workspace": {
                "manifests_dir_name": "manifests",
            },
        },
        workspace_root=tmp_path,
    )

    result = collector.collect()

    assert result.copied_count == 4
    assert result.output_dir == manifests_dir / "s"
    assert (result.output_dir / "s0" / "S0-001.jpg").exists()
    assert (result.output_dir / "s0" / "S0-002.jpg").exists()
    assert (result.output_dir / "s1" / "S1-001.jpg").exists()
    assert (result.output_dir / "s1" / "S1-002.jpg").exists()
    assert result.manifest_json_path.exists()

    manifest = json.loads(result.manifest_json_path.read_text(encoding="utf-8"))
    assert manifest["copied_count"] == 4
    assert manifest["items"][0]["equipment_id"] == "S0-001"
    assert manifest["items"][0]["review_image_path"].endswith("manifests/s/s0/S0-001.jpg")
    assert manifest["items"][2]["equipment_id"] == "S1-001"
