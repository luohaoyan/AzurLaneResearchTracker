#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════╗
║         爬虫工作区整合器 (CrawlerWorkspaceMerger)        ║
║   把装备图鉴爬虫与科研爬虫的输出整合到同一份 workdir       ║
║   中，生成可审阅的 equipment_library / research_phases     ║
║   / equipment_images 三张表。                             ║
╚════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..utils.config_loader import get_config_loader
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager


# ============================================================
# 第一部分：默认配置
# ============================================================

DEFAULT_OUTPUT_BASE_DIR = "workdir/crawler/integration"
DEFAULT_OUTPUT_DIR_NAME = "merged"
DEFAULT_EQUIPMENT_ARCHIVE_DIR = "workdir/crawler/archive"
DEFAULT_RESEARCH_RUNS_DIR = "workdir/crawler/research/runs"
DEFAULT_EQUIPMENT_LIBRARY_NAME = "equipment_library_stage.csv"
DEFAULT_EQUIPMENT_IMAGES_NAME = "equipment_images_stage.csv"
DEFAULT_RESEARCH_PHASES_NAME = "research_phases_stage.csv"
DEFAULT_RESEARCH_EQUIPMENT_NAME = "research_equipment_stage.csv"
DEFAULT_OUTPUT_LIBRARY_NAME = "equipment_library.csv"
DEFAULT_OUTPUT_IMAGES_NAME = "equipment_images.csv"
DEFAULT_OUTPUT_PHASES_NAME = "research_phases.csv"
DEFAULT_OUTPUT_OVERRIDES_NAME = "equipment_id_overrides.csv"
DEFAULT_OUTPUT_MANIFEST_NAME = "crawler_integration_manifest.json"
DEFAULT_CONFIG_NAME = "crawler_integration"


# ============================================================
# 第二部分：数据结构
# ============================================================


@dataclass(frozen=True)
class CrawlerIntegrationSettings:
    """爬虫工作区整合参数。"""

    equipment_archive_dir: Optional[str] = None
    research_run_dir: Optional[str] = None
    output_base_dir: str = DEFAULT_OUTPUT_BASE_DIR
    output_dir_name: str = DEFAULT_OUTPUT_DIR_NAME
    equipment_library_name: str = DEFAULT_EQUIPMENT_LIBRARY_NAME
    equipment_images_name: str = DEFAULT_EQUIPMENT_IMAGES_NAME
    research_phases_name: str = DEFAULT_RESEARCH_PHASES_NAME
    research_equipment_name: str = DEFAULT_RESEARCH_EQUIPMENT_NAME
    output_library_name: str = DEFAULT_OUTPUT_LIBRARY_NAME
    output_images_name: str = DEFAULT_OUTPUT_IMAGES_NAME
    output_phases_name: str = DEFAULT_OUTPUT_PHASES_NAME
    output_overrides_name: str = DEFAULT_OUTPUT_OVERRIDES_NAME
    output_manifest_name: str = DEFAULT_OUTPUT_MANIFEST_NAME

    @classmethod
    def from_mapping(cls, payload: Optional[Dict[str, Any]] = None) -> "CrawlerIntegrationSettings":
        """从配置字典构建整合参数。"""
        data = payload or {}
        source_cfg = data.get("source", {})
        output_cfg = data.get("output", {})

        return cls(
            equipment_archive_dir=_coerce_optional_text(source_cfg.get("equipment_archive_dir")),
            research_run_dir=_coerce_optional_text(source_cfg.get("research_run_dir")),
            output_base_dir=_coerce_text(output_cfg.get("output_base_dir"), DEFAULT_OUTPUT_BASE_DIR),
            output_dir_name=_coerce_text(output_cfg.get("output_dir_name"), DEFAULT_OUTPUT_DIR_NAME),
            equipment_library_name=_coerce_text(output_cfg.get("equipment_library_name"), DEFAULT_EQUIPMENT_LIBRARY_NAME),
            equipment_images_name=_coerce_text(output_cfg.get("equipment_images_name"), DEFAULT_EQUIPMENT_IMAGES_NAME),
            research_phases_name=_coerce_text(output_cfg.get("research_phases_name"), DEFAULT_RESEARCH_PHASES_NAME),
            research_equipment_name=_coerce_text(output_cfg.get("research_equipment_name"), DEFAULT_RESEARCH_EQUIPMENT_NAME),
            output_library_name=_coerce_text(output_cfg.get("output_library_name"), DEFAULT_OUTPUT_LIBRARY_NAME),
            output_images_name=_coerce_text(output_cfg.get("output_images_name"), DEFAULT_OUTPUT_IMAGES_NAME),
            output_phases_name=_coerce_text(output_cfg.get("output_phases_name"), DEFAULT_OUTPUT_PHASES_NAME),
            output_overrides_name=_coerce_text(output_cfg.get("output_overrides_name"), DEFAULT_OUTPUT_OVERRIDES_NAME),
            output_manifest_name=_coerce_text(output_cfg.get("output_manifest_name"), DEFAULT_OUTPUT_MANIFEST_NAME),
        )


@dataclass(frozen=True)
class CrawlerIntegrationResult:
    """整合后的工作区结果。"""

    workspace_dir: Path
    output_dir: Path
    equipment_library_path: Path
    research_phases_path: Path
    equipment_images_path: Path
    overrides_path: Path
    manifest_path: Path
    merged_library_rows: List[Dict[str, str]]
    merged_phase_rows: List[Dict[str, str]]
    merged_image_rows: List[Dict[str, str]]
    override_rows: List[Dict[str, str]]
    warnings: List[str]

    def to_manifest(self) -> Dict[str, Any]:
        """生成可写入 JSON 的结果摘要。"""
        return {
            "workspace_dir": str(self.workspace_dir),
            "output_dir": str(self.output_dir),
            "equipment_library_path": str(self.equipment_library_path),
            "research_phases_path": str(self.research_phases_path),
            "equipment_images_path": str(self.equipment_images_path),
            "overrides_path": str(self.overrides_path),
            "merged_library_count": len(self.merged_library_rows),
            "merged_phase_count": len(self.merged_phase_rows),
            "merged_image_count": len(self.merged_image_rows),
            "override_count": len(self.override_rows),
            "warnings": list(self.warnings),
        }


# ============================================================
# 第三部分：辅助函数
# ============================================================


def _coerce_text(value: Any, default: str) -> str:
    """把配置项统一转成普通字符串。"""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coerce_optional_text(value: Any) -> Optional[str]:
    """把配置项统一转成可空字符串。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sanitize_text(value: Any) -> str:
    """去掉多余空白，保证名称匹配稳定。"""
    return " ".join(str(value or "").split()).strip()


def _normalize_equipment_name(value: Any) -> str:
    """把名称压缩成便于匹配的统一形式。"""
    text = _sanitize_text(value)
    text = text.replace("#", "")
    text = text.replace("（", "(").replace("）", ")")
    return text.replace(" ", "").lower()


def _load_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    """读取 CSV 为字典列表。"""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(csv_path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> Path:
    """把字典列表写成 UTF-8-SIG 的 CSV。"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return csv_path


def _write_json(json_path: Path, payload: Dict[str, Any]) -> Path:
    """把字典写入 JSON。"""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return json_path


def _discover_latest_directory(root: Path) -> Path:
    """从目录中找出最新的子目录。"""
    candidates = [item for item in root.iterdir() if item.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"未找到可用目录: {root}")
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _resolve_csv_from_root(root: Path, filename: str) -> Path:
    """从一个工作区根目录里定位 CSV，兼容根目录与 manifests 子目录。"""
    direct_csv = root / filename
    if direct_csv.exists():
        return direct_csv

    nested_csv = root / "manifests" / filename
    if nested_csv.exists():
        return nested_csv

    candidate_root = _discover_latest_directory(root)
    return _resolve_csv_from_root(candidate_root, filename)


def _resolve_existing_path(raw_path: str) -> Path:
    """把配置中的路径转换为真实文件路径。"""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PathManager.get_project_root() / path


def _resolve_path_with_fallback(raw_path: str, base_dir: Path) -> Path:
    """优先按来源目录解析，再回退到项目根目录。"""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    candidates = [base_dir / path, base_dir.parent / path, PathManager.get_project_root() / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _load_json_config() -> Dict[str, Any]:
    """读取整合器配置。"""
    loader = get_config_loader()
    config = loader.get_config("crawler", DEFAULT_CONFIG_NAME)
    return config or {}


def _build_research_index(research_rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    """根据科研装备表建立 名称 -> 新ID 的索引，S0 优先。"""
    index: Dict[str, Dict[str, Any]] = {}
    for row in research_rows:
        equipment_id = _sanitize_text(row.get("equipment_id", ""))
        name = _sanitize_text(row.get("name", ""))
        normalized = _normalize_equipment_name(name)
        if not equipment_id or not normalized:
            continue
        phase_number = int(_sanitize_text(row.get("phase_number", "0")) or 0)
        source_scope = _sanitize_text(row.get("source_scope", "phase"))
        priority = (0 if source_scope == "common" or equipment_id.startswith("S0-") else 1, phase_number, equipment_id)
        current = index.get(normalized)
        if current is None or priority < current["priority"]:
            index[normalized] = {
                "equipment_id": equipment_id,
                "name": name,
                "phase_number": phase_number,
                "source_scope": source_scope,
                "priority": priority,
            }
    return index


def _build_source_name_map(library_rows: Sequence[Dict[str, str]]) -> Dict[str, str]:
    """建立 原始装备ID -> 装备名 的索引。"""
    result: Dict[str, str] = {}
    for row in library_rows:
        equipment_id = _sanitize_text(row.get("equipment_id", ""))
        name = _sanitize_text(row.get("name", ""))
        if equipment_id and name:
            result[equipment_id] = name
    return result


# ============================================================
# 第四部分：核心整合器
# ============================================================


class CrawlerWorkspaceMerger:
    """把装备爬虫与科研爬虫的输出整合到同一份工作区。"""

    def __init__(
        self,
        config_data: Optional[Dict[str, Any]] = None,
        workspace_root: Optional[Path] = None,
    ) -> None:
        self.logger = get_logger()
        self.settings = CrawlerIntegrationSettings.from_mapping(config_data or _load_json_config())
        self.workspace_root = workspace_root or (PathManager.get_project_root() / self.settings.output_base_dir)

    def _resolve_equipment_archive_dir(self) -> Path:
        """找到最新的装备爬虫归档目录。"""
        root = _resolve_existing_path(self.settings.equipment_archive_dir) if self.settings.equipment_archive_dir else (PathManager.get_crawler_dir() / "archive")
        direct_csv = root / self.settings.equipment_library_name
        nested_csv = root / "manifests" / self.settings.equipment_library_name
        if direct_csv.exists() or nested_csv.exists():
            return root
        return _discover_latest_directory(root)

    def _resolve_research_run_dir(self) -> Path:
        """找到最新的科研爬虫运行目录。"""
        root = _resolve_existing_path(self.settings.research_run_dir) if self.settings.research_run_dir else (PathManager.get_crawler_dir() / "research" / "runs")
        csv_path = root / "manifests" / self.settings.research_phases_name
        if csv_path.exists():
            return root
        return _discover_latest_directory(root)

    def _prepare_workspace(self, workspace_name: Optional[str] = None) -> Path:
        """创建本次整合输出目录。"""
        timestamp = workspace_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.workspace_root / (self.settings.output_dir_name or "merged") / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def merge(self, workspace_name: Optional[str] = None) -> CrawlerIntegrationResult:
        """执行整合，生成三张可审阅的 CSV。"""
        equipment_archive_dir = self._resolve_equipment_archive_dir()
        research_run_dir = self._resolve_research_run_dir()
        output_dir = self._prepare_workspace(workspace_name)

        equipment_library_path = output_dir / self.settings.output_library_name
        research_phases_path = output_dir / self.settings.output_phases_name
        equipment_images_path = output_dir / self.settings.output_images_name
        overrides_path = output_dir / self.settings.output_overrides_name
        manifest_path = output_dir / self.settings.output_manifest_name

        source_library_csv = _resolve_csv_from_root(equipment_archive_dir, self.settings.equipment_library_name)
        source_images_csv = _resolve_csv_from_root(equipment_archive_dir, self.settings.equipment_images_name)
        research_phases_csv = _resolve_csv_from_root(research_run_dir, self.settings.research_phases_name)
        research_equipment_csv = _resolve_csv_from_root(research_run_dir, self.settings.research_equipment_name)

        source_library_rows = _load_csv_rows(source_library_csv)
        source_image_rows = _load_csv_rows(source_images_csv)
        research_phase_rows = _load_csv_rows(research_phases_csv)
        research_equipment_rows = _load_csv_rows(research_equipment_csv)

        source_name_map = _build_source_name_map(source_library_rows)
        research_index = _build_research_index(research_equipment_rows)

        override_rows: List[Dict[str, str]] = []
        merged_library_rows: List[Dict[str, str]] = []
        merged_image_rows: List[Dict[str, str]] = []
        warnings: List[str] = []

        seen_overrides: set[Tuple[str, str]] = set()
        for row in source_library_rows:
            old_equipment_id = _sanitize_text(row.get("equipment_id", ""))
            name = _sanitize_text(row.get("name", ""))
            normalized_name = _normalize_equipment_name(name)
            new_equipment_id = research_index.get(normalized_name, {}).get("equipment_id", old_equipment_id)
            merged_row = dict(row)
            merged_row["equipment_id"] = new_equipment_id
            merged_library_rows.append(merged_row)

            if new_equipment_id != old_equipment_id:
                key = (old_equipment_id, new_equipment_id)
                if key not in seen_overrides:
                    seen_overrides.add(key)
                    override_rows.append(
                        {
                            "old_equipment_id": old_equipment_id,
                            "new_equipment_id": new_equipment_id,
                            "name": name,
                        }
                    )

        for row in source_image_rows:
            old_equipment_id = _sanitize_text(row.get("equipment_id", ""))
            name = _sanitize_text(source_name_map.get(old_equipment_id, ""))
            normalized_name = _normalize_equipment_name(name)
            new_equipment_id = research_index.get(normalized_name, {}).get("equipment_id", old_equipment_id)
            merged_row = dict(row)
            merged_row["equipment_id"] = new_equipment_id
            merged_image_rows.append(merged_row)

        _write_csv(
            equipment_library_path,
            merged_library_rows,
            ["equipment_id", "name", "rarity_id", "type"],
        )
        _write_csv(
            research_phases_path,
            research_phase_rows,
            ["phase_number", "name", "equipment_list"],
        )
        _write_csv(
            equipment_images_path,
            merged_image_rows,
            ["equipment_id", "image_path"],
        )
        _write_csv(
            overrides_path,
            override_rows,
            ["old_equipment_id", "new_equipment_id", "name"],
        )

        result = CrawlerIntegrationResult(
            workspace_dir=output_dir,
            output_dir=output_dir,
            equipment_library_path=equipment_library_path,
            research_phases_path=research_phases_path,
            equipment_images_path=equipment_images_path,
            overrides_path=overrides_path,
            manifest_path=manifest_path,
            merged_library_rows=merged_library_rows,
            merged_phase_rows=research_phase_rows,
            merged_image_rows=merged_image_rows,
            override_rows=override_rows,
            warnings=warnings,
        )

        _write_json(manifest_path, result.to_manifest())
        self.logger.info(
            "爬虫工作区整合完成: 装备库%s条, 科研期数%s条, 图片%s条, 覆盖%s条",
            len(merged_library_rows),
            len(research_phase_rows),
            len(merged_image_rows),
            len(override_rows),
        )
        return result


def get_crawler_workspace_merger() -> CrawlerWorkspaceMerger:
    """获取工作区整合器实例。"""
    return CrawlerWorkspaceMerger()
