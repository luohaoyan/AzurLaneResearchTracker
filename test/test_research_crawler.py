#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║             科研爬虫测试 (test_research_crawler.py)                  ║
║  验证科研页解析、s0 去重、期数编号、覆盖计划与 stage 落盘。           ║
║  类比理解：先拿一张小样页做验收，再决定要不要接正式表。               ║
╚══════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import os
import sys
from csv import DictReader
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.research_crawler import (  # noqa: E402
    ResearchCrawler,
    build_default_crawler_config,
)


# ============================================================
# 第一部分：测试数据
# ============================================================


def build_sample_html() -> str:
    """构造一个足够小的科研页面片段。"""
    return """
    <html>
      <body>
        <div class="mw-parser-output">
          <h3>科研装备设计图</h3>
          <h4>第一期</h4>
          <p>战列炮： 试作型三联装406mm主炮T0、 试作型三联装305mmSKC39主炮T0
             防空炮： 高性能舵机T0、 高性能火控雷达T0</p>
          <p>以下为往期科研已有装备 设备： 高性能舵机T0、 高性能对空雷达T0</p>
          <h4>第二期</h4>
          <p>驱逐炮： 双联装114mm高平两用炮Mark IVT0
             重巡炮： 试作型三联装234mm主炮T0、 试作型双联装234mm主炮T0</p>
          <p>以下为往期科研已有装备 防空炮： 双联装40mm博福斯STAAGT0、 双联装40mm博福斯海兹梅耶T0</p>
          <h3>其他装备设计图</h3>
        </div>
      </body>
    </html>
    """


def build_issue_html() -> str:
    """鏋勯€犱竴涓甫鏈夌涔濇湡鍒嗗彿鏉傚瓧绗︾殑绉戠爺椤甸瑙嗗浘銆?"""
    return """
    <html>
      <body>
        <div class="mw-parser-output">
          <h3>科研装备设计图</h3>
          <h4>第九期</h4>
          <p>驱逐炮：试作型双联装127mm主炮Mle1948T0 }、试作型双联装127mm高平两用炮Mk16T0</p>
          <h3>其他装备设计图</h3>
        </div>
      </body>
    </html>
    """


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """读取 stage CSV，方便断言行内容。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(DictReader(handle))


class FakeEquipmentManager:
    """用于覆盖计划测试的假装备库。"""

    def get_all(self) -> List[Dict[str, str]]:
        return [
            {"equipment_id": "G0009", "name": "高性能舵机T0"},
            {"equipment_id": "G0010", "name": "试作型三联装406mm主炮T0"},
            {"equipment_id": "G0011", "name": "高性能火控雷达T0"},
        ]


# ============================================================
# 第二部分：解析测试
# ============================================================


def test_parse_page_extracts_common_and_phase_items() -> None:
    """科研页应按「通用 + 各期」拆分，并去掉重复通用条目。"""
    crawler = ResearchCrawler(config_data=build_default_crawler_config())
    common_names, phase_items, warnings = crawler._parse_page(build_sample_html())

    assert warnings == []
    assert common_names == [
        "高性能舵机T0",
        "高性能对空雷达T0",
        "双联装40mm博福斯STAAGT0",
        "双联装40mm博福斯海兹梅耶T0",
    ]
    assert [item[0] for item in phase_items] == [1, 2]
    assert phase_items[0][2] == [
        "试作型三联装406mm主炮T0",
        "试作型三联装305mmSKC39主炮T0",
        "高性能舵机T0",
        "高性能火控雷达T0",
    ]
    assert phase_items[1][2] == [
        "双联装114mm高平两用炮Mark IVT0",
        "试作型三联装234mm主炮T0",
        "试作型双联装234mm主炮T0",
    ]


def test_assign_ids_gives_common_priority_over_phase_items() -> None:
    """同名装备应优先落入 s0，再跳过后续期数重复。"""
    crawler = ResearchCrawler(config_data=build_default_crawler_config())
    common_names, phase_items, _ = crawler._parse_page(build_sample_html())
    equipment_records, phase_records = crawler._assign_ids(common_names, phase_items)

    assert [item.equipment_id for item in equipment_records[:4]] == [
        "S0-001",
        "S0-002",
        "S0-003",
        "S0-004",
    ]
    assert [item.name for item in equipment_records[:4]] == [
        "高性能舵机T0",
        "高性能对空雷达T0",
        "双联装40mm博福斯STAAGT0",
        "双联装40mm博福斯海兹梅耶T0",
    ]
    assert [item.equipment_ids for item in phase_records] == [
        ["S1-001", "S1-002", "S1-003"],
        ["S2-001", "S2-002", "S2-003"],
    ]


def test_parse_page_cleans_trailing_brace_in_phase_nine_items() -> None:
    """第九期若混入右花括号，解析后也应自动清掉，避免影响后续同步。"""
    crawler = ResearchCrawler(config_data=build_default_crawler_config())
    common_names, phase_items, warnings = crawler._parse_page(build_issue_html())

    assert warnings == []
    assert common_names == []
    assert [item[0] for item in phase_items] == [9]
    assert phase_items[0][2] == [
        "试作型双联装127mm主炮Mle1948T0",
        "试作型双联装127mm高平两用炮Mk16T0",
    ]


# ============================================================
# 第三部分：落盘测试
# ============================================================


def test_crawl_stage_writes_isolated_stage_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """科研爬虫应写入独立工作区，并生成覆盖计划。"""
    crawler = ResearchCrawler(config_data=build_default_crawler_config(), workspace_root=tmp_path)
    monkeypatch.setattr(crawler, "fetch_page_html", lambda: build_sample_html())
    monkeypatch.setattr("core.data.research_crawler.get_equipment_manager", lambda: FakeEquipmentManager())
    monkeypatch.setattr("core.data.research_crawler.time.sleep", lambda *_args, **_kwargs: None)

    result = crawler.crawl_sample(phase_limit=1, common_limit=2, workspace_name="20260710_120000")

    assert result.workspace_dir == tmp_path / "20260710_120000"
    assert result.mode == "sample"
    assert result.parsed_phase_count == 1
    assert result.common_equipment_count == 2
    assert result.total_equipment_count == 5
    assert result.raw_html_path.exists()
    assert result.phase_stage_path.exists()
    assert result.equipment_stage_path.exists()
    assert result.override_stage_path.exists()
    assert result.manifest_json_path.exists()

    phase_rows = read_csv_rows(result.phase_stage_path)
    equipment_rows = read_csv_rows(result.equipment_stage_path)
    override_rows = read_csv_rows(result.override_stage_path)

    assert [row["phase_number"] for row in phase_rows] == ["0", "1"]
    assert phase_rows[0]["name"] == "通用科研装备(S0)"
    assert phase_rows[0]["equipment_list"] == "S0-001,S0-002"
    assert phase_rows[1]["equipment_list"] == "S1-001,S1-002,S1-003"
    assert [row["equipment_id"] for row in equipment_rows] == [
        "S0-001",
        "S0-002",
        "S1-001",
        "S1-002",
        "S1-003",
    ]
    assert [row["new_equipment_id"] for row in override_rows] == ["S0-001", "S1-001", "S1-003"]

    manifest = result.to_manifest()
    assert "config" not in manifest
    assert manifest["parsed_phase_count"] == 1
    assert manifest["common_equipment_count"] == 2
    assert manifest["total_equipment_count"] == 5
    assert manifest["phase_numbers"] == [1]
    assert len(manifest["warnings"]) == 2
