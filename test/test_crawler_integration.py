#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬虫工作区整合器测试。"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.crawler_integration import CrawlerWorkspaceMerger


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    """写临时 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_merge_prefers_s0_and_updates_images(tmp_path: Path) -> None:
    """整合时应优先使用 S0，并同步更新图片表。"""
    archive_dir = tmp_path / "archive" / "run_001"
    research_dir = tmp_path / "research" / "run_001"

    _write_csv(
        archive_dir / "equipment_library_stage.csv",
        ["equipment_id", "name", "rarity_id", "type"],
        [
            {"equipment_id": "G0001", "name": "共享炮", "rarity_id": "5", "type": "战列炮"},
            {"equipment_id": "G0002", "name": "通用炮", "rarity_id": "4", "type": "轻巡炮"},
            {"equipment_id": "G0003", "name": "一期炮", "rarity_id": "5", "type": "重巡炮"},
        ],
    )
    _write_csv(
        archive_dir / "equipment_images_stage.csv",
        ["equipment_id", "image_path"],
        [
            {"equipment_id": "G0001", "image_path": "images/ultra_rare/G0001.jpg"},
            {"equipment_id": "G0002", "image_path": "images/rare/G0002.jpg"},
            {"equipment_id": "G0003", "image_path": "images/ultra_rare/G0003.jpg"},
        ],
    )

    research_manifests = research_dir / "manifests"
    _write_csv(
        research_manifests / "research_phases_stage.csv",
        ["phase_number", "name", "equipment_list"],
        [
            {"phase_number": "0", "name": "通用科研装备(S0)", "equipment_list": "S0-001,S0-002"},
            {"phase_number": "1", "name": "科研一期", "equipment_list": "S1-001,S1-002"},
        ],
    )
    _write_csv(
        research_manifests / "research_equipment_stage.csv",
        ["equipment_id", "name", "phase_number", "phase_name", "source_scope", "order_index"],
        [
            {"equipment_id": "S0-001", "name": "共享炮", "phase_number": "0", "phase_name": "通用科研装备(S0)", "source_scope": "common", "order_index": "1"},
            {"equipment_id": "S0-002", "name": "通用炮", "phase_number": "0", "phase_name": "通用科研装备(S0)", "source_scope": "common", "order_index": "2"},
            {"equipment_id": "S1-001", "name": "共享炮", "phase_number": "1", "phase_name": "科研一期", "source_scope": "phase", "order_index": "1"},
            {"equipment_id": "S1-002", "name": "一期炮", "phase_number": "1", "phase_name": "科研一期", "source_scope": "phase", "order_index": "2"},
        ],
    )

    merger = CrawlerWorkspaceMerger(
        config_data={
            "source": {
                "equipment_archive_dir": str(archive_dir.parent),
                "research_run_dir": str(research_dir),
            },
            "output": {
                "output_base_dir": "merged_output",
                "output_dir_name": "bundle",
            },
        },
        workspace_root=tmp_path,
    )

    result = merger.merge(workspace_name="20260710_130000")

    assert result.equipment_library_path.exists()
    assert result.research_phases_path.exists()
    assert result.equipment_images_path.exists()
    assert result.overrides_path.exists()
    assert [row["equipment_id"] for row in result.merged_library_rows] == ["S0-001", "S0-002", "S1-002"]
    assert [row["equipment_id"] for row in result.merged_image_rows] == ["S0-001", "S0-002", "S1-002"]
    assert [row["new_equipment_id"] for row in result.override_rows] == ["S0-001", "S0-002", "S1-002"]
    assert result.merged_phase_rows[0]["equipment_list"] == "S0-001,S0-002"
