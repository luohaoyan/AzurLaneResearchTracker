#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║               爬虫同步器测试 (test_crawler_sync.py)             ║
║                                                                  ║
║   【一句话解释】验证装备爬虫 + 科研爬虫的 stage 结果能否         ║
║   正确同步到正式 data/，并且保留特殊装备。                     ║
║                                                                  ║
║   【类比理解】                                                   ║
║   这就像验收总装好的成品：编号要对，图片要对，旧件不能丢。     ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.crawler_sync import CrawlerDataSynchronizer


# ============================================================
# 第一部分：测试辅助函数
# ============================================================


def _write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    """写一份临时 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_bytes(path: Path, content: bytes) -> None:
    """写一份临时图片文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read_rows(path: Path) -> List[Dict[str, str]]:
    """读取 CSV 行。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


# ============================================================
# 第二部分：同步测试
# ============================================================


def test_sync_latest_merges_equipment_research_and_special_rows(tmp_path: Path) -> None:
    """同步器应覆盖科研命名、保留特殊装备，并复制相对路径图片。"""
    project_root = tmp_path / "project"
    data_root = project_root / "data"
    workdir_root = project_root / "workdir"
    equipment_run_dir = workdir_root / "crawler" / "runs" / "20260710_010000"
    research_run_dir = workdir_root / "crawler" / "research" / "runs" / "20260710_020000"

    # 先准备项目当前数据，保留两个特殊装备。
    _write_csv(
        data_root / "equipment_library.csv",
        ["equipment_id", "name", "rarity_id", "type"],
        [
            {"equipment_id": "G0001", "name": "BR.810 剑鱼", "rarity_id": "4", "type": "战斗机"},
            {"equipment_id": "G0002", "name": "B-13", "rarity_id": "4", "type": "轻巡炮"},
            {"equipment_id": "G0099", "name": "旧装备", "rarity_id": "1", "type": "测试"},
        ],
    )
    _write_csv(
        data_root / "equipment_images.csv",
        ["equipment_id", "image_path"],
        [
            {"equipment_id": "G0099", "image_path": "images/common/G0099.jpg"},
        ],
    )
    _write_csv(
        data_root / "research_phases.csv",
        ["phase_number", "name", "equipment_list"],
        [
            {"phase_number": "1", "name": "旧一期", "equipment_list": "S1-001"},
        ],
    )
    _write_csv(
        data_root / "special_equipment.csv",
        ["equipment_id", "equipment_name", "notes"],
        [
            {"equipment_id": "G0001", "equipment_name": "BR.810 剑鱼", "notes": "special"},
            {"equipment_id": "G0002", "equipment_name": "B-13", "notes": "special"},
        ],
    )

    # 装备爬虫 stage：3 件装备，对应 3 张图片。
    _write_csv(
        equipment_run_dir / "manifests" / "equipment_library_stage.csv",
        ["equipment_id", "name", "rarity_id", "type"],
        [
            {"equipment_id": "G0003", "name": "公共装备", "rarity_id": "5", "type": "战列炮"},
            {"equipment_id": "G0004", "name": "一期装备", "rarity_id": "4", "type": "轻巡炮"},
            {"equipment_id": "G0005", "name": "普通装备", "rarity_id": "3", "type": "驱逐炮"},
        ],
    )
    _write_csv(
        equipment_run_dir / "manifests" / "equipment_images_stage.csv",
        ["equipment_id", "image_path"],
        [
            {"equipment_id": "G0003", "image_path": str((equipment_run_dir / "images" / "ultra_rare" / "G0003.jpg").as_posix())},
            {"equipment_id": "G0004", "image_path": str((equipment_run_dir / "images" / "rare" / "G0004.jpg").as_posix())},
            {"equipment_id": "G0005", "image_path": str((equipment_run_dir / "images" / "elite" / "G0005.jpg").as_posix())},
        ],
    )
    _write_bytes(equipment_run_dir / "images" / "ultra_rare" / "G0003.jpg", b"img-3")
    _write_bytes(equipment_run_dir / "images" / "rare" / "G0004.jpg", b"img-4")
    _write_bytes(equipment_run_dir / "images" / "elite" / "G0005.jpg", b"img-5")

    # 科研 stage：公共装备优先使用 S0，其他期数用对应 Sx。
    _write_csv(
        research_run_dir / "manifests" / "research_phases_stage.csv",
        ["phase_number", "name", "equipment_list"],
        [
            {"phase_number": "0", "name": "通用科研装备(S0)", "equipment_list": "S0-001"},
            {"phase_number": "1", "name": "第一期", "equipment_list": "S1-001,S1-002"},
        ],
    )
    _write_csv(
        research_run_dir / "manifests" / "research_equipment_stage.csv",
        ["equipment_id", "name", "phase_number", "phase_name", "source_scope", "order_index"],
        [
            {"equipment_id": "S0-001", "name": "公共装备", "phase_number": "0", "phase_name": "通用科研装备(S0)", "source_scope": "common", "order_index": "1"},
            {"equipment_id": "S1-001", "name": "一期装备", "phase_number": "1", "phase_name": "第一期", "source_scope": "phase", "order_index": "1"},
            {"equipment_id": "S1-002", "name": "一期专属", "phase_number": "1", "phase_name": "第一期", "source_scope": "phase", "order_index": "2"},
        ],
    )

    synchronizer = CrawlerDataSynchronizer(
        config_data={
            "source": {
                "equipment_run_dir": str(equipment_run_dir),
                "research_run_dir": str(research_run_dir),
            },
            "output": {
                "workdir_base_dir": "workdir/crawler/sync",
                "backup_dir_name": "backups",
                "output_dir_name": "latest",
                "data_images_dir_name": "images",
                "crawler_images_dir_name": "images",
            },
        },
        project_root=project_root,
        data_root=data_root,
        workdir_root=workdir_root,
    )

    result = synchronizer.sync(workspace_name="20260710_030000")

    library_rows = _read_rows(result.equipment_library_path)
    image_rows = _read_rows(result.equipment_images_path)
    phase_rows = _read_rows(result.research_phases_path)

    assert result.backup_dir.exists()
    assert result.workspace_dir.exists()
    assert [row["equipment_id"] for row in library_rows] == ["S0-001", "S1-001", "G0001", "G0002", "G0005"]
    assert [row["equipment_id"] for row in image_rows] == ["S0-001", "S1-001", "G0005"]
    assert phase_rows[0]["equipment_list"] == "S0-001"
    assert phase_rows[1]["equipment_list"] == "S1-001,S1-002"
    assert result.copied_image_paths and len(result.copied_image_paths) == 3
    assert (data_root / "images" / "ultra_rare" / "S0-001.jpg").exists()
    assert (data_root / "images" / "super_rare" / "S1-001.jpg").exists()
    assert (data_root / "images" / "elite" / "G0005.jpg").exists()
    assert image_rows[0]["image_path"].replace("\\", "/").endswith("data/images/ultra_rare/S0-001.jpg")
    assert image_rows[1]["image_path"].replace("\\", "/").endswith("data/images/super_rare/S1-001.jpg")

    manifest_path = result.workspace_dir / "crawler_sync_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["equipment_count"] == 5
    assert manifest["phase_count"] == 2
    assert manifest["copied_image_count"] == 3
