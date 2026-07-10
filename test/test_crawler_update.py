#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════╗
║            资料更新入口测试 (test_crawler_update.py)       ║
║  重点确认：装备爬虫 -> 科研爬虫 -> 同步 这条链路是否成立    ║
║  GUI/Bridge 必须命中正式入口，而不是任何旧的抽样逻辑      ║
╚════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 第一部分：导入依赖
# ============================================================

import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from core.data import crawler_update
from core.state.runtime_state import get_runtime_state_manager
from ui.automation_bridge import AutomationBridge


# ============================================================
# 第二部分：测试辅助对象
# ============================================================

@dataclass
class _FakeEquipmentResult:
    workspace_dir: Path = Path("data/workdir/crawler/runs/20260710_010000")
    library_csv_path: Path = Path("data/workdir/crawler/runs/20260710_010000/manifests/equipment_library_stage.csv")
    images_csv_path: Path = Path("data/workdir/crawler/runs/20260710_010000/manifests/equipment_images_stage.csv")
    selected_count: int = 752
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


@dataclass
class _FakeResearchResult:
    workspace_dir: Path = Path("data/workdir/crawler/research/runs/20260710_020000")
    phase_stage_path: Path = Path("data/workdir/crawler/research/runs/20260710_020000/manifests/research_phases_stage.csv")
    equipment_stage_path: Path = Path("data/workdir/crawler/research/runs/20260710_020000/manifests/research_equipment_stage.csv")
    override_stage_path: Path = Path("data/workdir/crawler/research/runs/20260710_020000/manifests/equipment_id_overrides_stage.csv")
    parsed_phase_count: int = 9
    common_equipment_count: int = 6
    total_equipment_count: int = 61
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


@dataclass
class _FakeSyncResult:
    workspace_dir: Path = Path("data/workdir/crawler/sync/latest/20260710_030000")
    backup_dir: Path = Path("data/workdir/crawler/sync/latest/20260710_030000/backups")
    equipment_library_path: Path = Path("data/equipment_library.csv")
    equipment_images_path: Path = Path("data/equipment_images.csv")
    research_phases_path: Path = Path("data/research_phases.csv")
    data_images_dir: Path = Path("data/images")
    final_library_rows: list[dict[str, str]] = None  # type: ignore[assignment]
    final_image_rows: list[dict[str, str]] = None  # type: ignore[assignment]
    final_phase_rows: list[dict[str, str]] = None  # type: ignore[assignment]
    copied_image_paths: list[Path] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]
    expected_equipment_run_dir: Path | None = None
    expected_research_run_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.final_library_rows is None:
            self.final_library_rows = [{"equipment_id": "S0-001"}, {"equipment_id": "S1-001"}]
        if self.final_image_rows is None:
            self.final_image_rows = [{"equipment_id": "S0-001"}, {"equipment_id": "S1-001"}]
        if self.final_phase_rows is None:
            self.final_phase_rows = [{"phase_number": "0"}, {"phase_number": "1"}]
        if self.copied_image_paths is None:
            self.copied_image_paths = [Path("data/images/common/S0-001.jpg")]
        if self.warnings is None:
            self.warnings = []


class _FakeEquipmentCrawler:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def crawl_all(self, workspace_name: str | None = None) -> _FakeEquipmentResult:
        self.calls.append(f"equipment:{workspace_name}")
        assert workspace_name == "20260710_030000"
        return _FakeEquipmentResult()


class _FakeResearchCrawler:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def crawl_all(self, workspace_name: str | None = None) -> _FakeResearchResult:
        self.calls.append(f"research:{workspace_name}")
        assert workspace_name == "20260710_030000"
        return _FakeResearchResult()


class _FakeSynchronizer:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def sync(
        self,
        workspace_name: str | None = None,
        equipment_run_dir: Path | str | None = None,
        research_run_dir: Path | str | None = None,
    ) -> _FakeSyncResult:
        self.calls.append(f"sync:{workspace_name}")
        assert workspace_name == "20260710_030000"
        assert Path(equipment_run_dir or "").as_posix().endswith("data/workdir/crawler/runs/20260710_010000")
        assert Path(research_run_dir or "").as_posix().endswith("data/workdir/crawler/research/runs/20260710_020000")
        result = _FakeSyncResult()
        result.expected_equipment_run_dir = Path(equipment_run_dir) if equipment_run_dir is not None else None
        result.expected_research_run_dir = Path(research_run_dir) if research_run_dir is not None else None
        return result


# ============================================================
# 第三部分：测试用例
# ============================================================

def test_crawler_update_run_update_executes_full_pipeline(monkeypatch) -> None:
    """run_update 应该按装备爬虫 -> 科研爬虫 -> 同步的顺序执行，并返回 GUI 友好摘要。"""
    calls: list[str] = []
    monkeypatch.setattr(crawler_update, "get_equipment_crawler", lambda: _FakeEquipmentCrawler(calls))
    monkeypatch.setattr(crawler_update, "get_research_crawler", lambda: _FakeResearchCrawler(calls))
    monkeypatch.setattr(crawler_update, "get_crawler_data_synchronizer", lambda: _FakeSynchronizer(calls))

    payload = crawler_update.run_update(workspace_name="20260710_030000")

    assert calls == ["equipment:20260710_030000", "research:20260710_030000", "sync:20260710_030000"]
    assert payload["message"] == "资料更新完成，装备 2 条、图片 2 张、科研期数 2 期，正式表已同步到 data/。"
    assert payload["workspace_name"] == "20260710_030000"
    assert payload["equipment_workspace_dir"].replace("\\", "/").endswith("data/workdir/crawler/runs/20260710_010000")
    assert payload["research_workspace_dir"].replace("\\", "/").endswith("data/workdir/crawler/research/runs/20260710_020000")
    assert payload["equipment_library_path"].replace("\\", "/").endswith("data/equipment_library.csv")
    assert payload["research_phases_path"].replace("\\", "/").endswith("data/research_phases.csv")
    assert payload["equipment_crawl_count"] == 752
    assert payload["research_parsed_phase_count"] == 9
    assert payload["research_total_count"] == 61
    assert payload["equipment_count"] == 2
    assert payload["image_count"] == 2
    assert payload["phase_count"] == 2
    assert payload["copied_image_count"] == 1


def test_automation_bridge_prefers_formal_crawler_update_module(monkeypatch) -> None:
    """桥接层应优先命中 crawler_update，而不是抽样爬虫。"""
    module = ModuleType("core.data.crawler_update")
    module.run_update = lambda: {"message": "formal sync done"}
    monkeypatch.setitem(sys.modules, "core.data.crawler_update", module)
    monkeypatch.setattr(AutomationBridge, "CRAWLER_MODULE_CANDIDATES", ("core.data.crawler_update",))
    bridge = AutomationBridge()

    result = bridge.run_crawler_update()

    assert result.success is True
    assert result.status == "success"
    assert result.message == "formal sync done"
    assert get_runtime_state_manager().get_full_state()["task"]["kind"] == "idle"
