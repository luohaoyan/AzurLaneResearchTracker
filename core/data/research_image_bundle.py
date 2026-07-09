#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════╗
║        科研图片整理包 (ResearchPhaseImageBundle)          ║
║   把 research_phases_stage 中的装备图片按 S0/S1/...        ║
║   整理到 manifests/s/ 下，方便人工核对对应图片是否正确。   ║
║   数据流：research stage CSV -> 名称匹配 -> 图片复制 -> manifest ║
╚════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..utils.config_loader import get_config_loader
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager


# ============================================================
# 第一部分：默认配置
# ============================================================

DEFAULT_WORKSPACE_BASE_DIR = "workdir/crawler/research"
DEFAULT_RUNS_DIR_NAME = "runs"
DEFAULT_MANIFESTS_DIR_NAME = "manifests"
DEFAULT_PHASE_STAGE_NAME = "research_phases_stage.csv"
DEFAULT_EQUIPMENT_STAGE_NAME = "research_equipment_stage.csv"
DEFAULT_OUTPUT_FOLDER_NAME = "s"
DEFAULT_MANIFEST_NAME = "research_image_bundle_manifest.json"
DEFAULT_CONFIG_NAME = "research_image_bundle"


# ============================================================
# 第二部分：数据结构
# ============================================================


@dataclass(frozen=True)
class ResearchImageBundleSettings:
    """科研图片整理脚本的运行参数。"""

    research_run_dir: Optional[str] = None
    source_library_csv: Optional[str] = None
    source_images_csv: Optional[str] = None
    output_folder_name: str = DEFAULT_OUTPUT_FOLDER_NAME
    manifests_dir_name: str = DEFAULT_MANIFESTS_DIR_NAME
    phase_stage_name: str = DEFAULT_PHASE_STAGE_NAME
    equipment_stage_name: str = DEFAULT_EQUIPMENT_STAGE_NAME
    manifest_name: str = DEFAULT_MANIFEST_NAME

    @classmethod
    def from_mapping(cls, payload: Optional[Dict[str, Any]] = None) -> "ResearchImageBundleSettings":
        """从 JSON 映射构建配置对象。"""
        data = payload or {}
        source_cfg = data.get("source", {})
        output_cfg = data.get("output", {})
        workspace_cfg = data.get("workspace", {})

        return cls(
            research_run_dir=_coerce_optional_text(source_cfg.get("research_run_dir")),
            source_library_csv=_coerce_optional_text(source_cfg.get("source_library_csv")),
            source_images_csv=_coerce_optional_text(source_cfg.get("source_images_csv")),
            output_folder_name=_coerce_text(output_cfg.get("output_folder_name"), DEFAULT_OUTPUT_FOLDER_NAME),
            manifests_dir_name=_coerce_text(workspace_cfg.get("manifests_dir_name"), DEFAULT_MANIFESTS_DIR_NAME),
            phase_stage_name=_coerce_text(output_cfg.get("phase_stage_name"), DEFAULT_PHASE_STAGE_NAME),
            equipment_stage_name=_coerce_text(output_cfg.get("equipment_stage_name"), DEFAULT_EQUIPMENT_STAGE_NAME),
            manifest_name=_coerce_text(output_cfg.get("manifest_name"), DEFAULT_MANIFEST_NAME),
        )


@dataclass(frozen=True)
class ResearchImageBundleItem:
    """单张科研图片的整理记录。"""

    phase_number: int
    phase_name: str
    equipment_id: str
    equipment_name: str
    source_equipment_id: str
    source_image_path: Path
    review_image_path: Path

    def to_row(self, project_root: Path) -> Dict[str, str]:
        """转成便于写入 JSON 的字典。"""
        return {
            "phase_number": str(self.phase_number),
            "phase_name": self.phase_name,
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment_name,
            "source_equipment_id": self.source_equipment_id,
            "source_image_path": _relative_text(self.source_image_path, project_root),
            "review_image_path": _relative_text(self.review_image_path, project_root),
        }


@dataclass(frozen=True)
class ResearchImageBundleResult:
    """科研图片整理结果。"""

    workspace_dir: Path
    manifests_dir: Path
    output_dir: Path
    manifest_json_path: Path
    research_phase_path: Path
    research_equipment_path: Path
    source_library_csv: Path
    source_images_csv: Path
    copied_items: List[ResearchImageBundleItem]
    warnings: List[str]

    @property
    def copied_count(self) -> int:
        """成功复制的图片数量。"""
        return len(self.copied_items)

    def to_manifest(self) -> Dict[str, Any]:
        """生成可写入 JSON 的摘要。"""
        project_root = PathManager.get_project_root()
        return {
            "workspace_dir": str(self.workspace_dir),
            "manifests_dir": str(self.manifests_dir),
            "output_dir": str(self.output_dir),
            "manifest_json_path": str(self.manifest_json_path),
            "research_phase_path": str(self.research_phase_path),
            "research_equipment_path": str(self.research_equipment_path),
            "source_library_csv": str(self.source_library_csv),
            "source_images_csv": str(self.source_images_csv),
            "copied_count": self.copied_count,
            "warnings": list(self.warnings),
            "items": [item.to_row(project_root) for item in self.copied_items],
        }


# ============================================================
# 第三部分：辅助函数
# ============================================================


def _load_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    """读取 CSV 为字典列表。"""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json_config() -> Dict[str, Any]:
    """读取项目中的配置文件。"""
    loader = get_config_loader()
    config = loader.get_config("crawler", DEFAULT_CONFIG_NAME)
    return config or {}


def _sanitize_text(value: str) -> str:
    """去掉多余空白，保证名称匹配稳定。"""
    return " ".join(str(value or "").split()).strip()


def _normalize_equipment_name(value: str) -> str:
    """把页面名和装备库名压缩成同一套可匹配格式。"""
    text = _sanitize_text(value)
    text = text.replace("#", "")
    text = text.replace("（", "(").replace("）", ")")
    return text.replace(" ", "").lower()


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


def _relative_text(path: Path, project_root: Path) -> str:
    """把路径转成相对文本，便于跨机器查看。"""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _discover_latest_directory(root: Path) -> Path:
    """从一个目录中找出最新的子目录。"""
    candidates = [item for item in root.iterdir() if item.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"未找到可用目录: {root}")
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _discover_latest_research_run_dir() -> Path:
    """自动定位最近一次科研爬虫运行目录。"""
    runs_root = PathManager.get_crawler_dir() / "research" / DEFAULT_RUNS_DIR_NAME
    return _discover_latest_directory(runs_root)


def _discover_latest_source_archive_dir() -> Path:
    """自动定位最近一次装备爬虫归档目录。"""
    archive_root = PathManager.get_crawler_dir() / "archive"
    return _discover_latest_directory(archive_root)


def _resolve_existing_path(raw_path: str) -> Path:
    """把配置中的路径转换成真实文件路径。"""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PathManager.get_project_root() / path


def _resolve_path_with_fallback(raw_path: str, base_dir: Path) -> Path:
    """优先按 CSV 所在目录解析相对路径，再回退到项目根目录。"""
    path = Path(raw_path)
    if path.is_absolute():
        return path

    candidates = [
        base_dir / path,
        base_dir.parent / path,
        PathManager.get_project_root() / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _build_source_image_index(library_csv: Path, images_csv: Path) -> Dict[str, Tuple[str, Path]]:
    """根据装备名建立 源装备ID -> 图片路径 的检索索引。"""
    library_rows = _load_csv_rows(library_csv)
    image_rows = _load_csv_rows(images_csv)

    name_to_id: Dict[str, str] = {}
    for row in library_rows:
        equipment_id = _sanitize_text(row.get("equipment_id", ""))
        name = _sanitize_text(row.get("name", ""))
        normalized_name = _normalize_equipment_name(name)
        if equipment_id and normalized_name and normalized_name not in name_to_id:
            name_to_id[normalized_name] = equipment_id

    id_to_image: Dict[str, Path] = {}
    for row in image_rows:
        equipment_id = _sanitize_text(row.get("equipment_id", ""))
        image_path = _sanitize_text(row.get("image_path", ""))
        if not equipment_id or not image_path:
            continue
        id_to_image[equipment_id] = _resolve_path_with_fallback(image_path, images_csv.parent)

    source_index: Dict[str, Tuple[str, Path]] = {}
    for normalized_name, equipment_id in name_to_id.items():
        image_path = id_to_image.get(equipment_id)
        if image_path is not None:
            source_index[normalized_name] = (equipment_id, image_path)
    return source_index


def _copy_image(source_path: Path, target_path: Path) -> Path:
    """复制单张图片到目标位置。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return target_path


# ============================================================
# 第四部分：核心程序
# ============================================================


class ResearchPhaseImageBundle:
    """把科研阶段图片整理到 manifests/s/ 下的独立工具。"""

    def __init__(
        self,
        config_data: Optional[Dict[str, Any]] = None,
        workspace_root: Optional[Path] = None,
    ) -> None:
        self.logger = get_logger()
        self.settings = ResearchImageBundleSettings.from_mapping(config_data or _load_json_config())
        default_workspace_root = PathManager.get_crawler_dir() / "research" / DEFAULT_RUNS_DIR_NAME
        self.workspace_root = workspace_root or default_workspace_root

    def _resolve_research_run_dir(self) -> Path:
        """找到本次要整理的科研爬虫运行目录。"""
        if self.settings.research_run_dir:
            return _resolve_existing_path(self.settings.research_run_dir)
        return _discover_latest_research_run_dir()

    def _resolve_source_csvs(self) -> Tuple[Path, Path]:
        """找到源装备库 CSV 和图片 CSV。"""
        if self.settings.source_library_csv and self.settings.source_images_csv:
            return (
                _resolve_existing_path(self.settings.source_library_csv),
                _resolve_existing_path(self.settings.source_images_csv),
            )

        archive_dir = _discover_latest_source_archive_dir()
        return (
            archive_dir / "equipment_library_stage.csv",
            archive_dir / "equipment_images_stage.csv",
        )

    def _read_research_tables(self, manifests_dir: Path) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """读取科研阶段导出的两张 CSV。"""
        phase_path = manifests_dir / self.settings.phase_stage_name
        equipment_path = manifests_dir / self.settings.equipment_stage_name
        return _load_csv_rows(phase_path), _load_csv_rows(equipment_path)

    def _build_equipment_map(self, equipment_rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        """把科研装备表按 ID 建立索引。"""
        result: Dict[str, Dict[str, str]] = {}
        for row in equipment_rows:
            equipment_id = _sanitize_text(row.get("equipment_id", ""))
            if equipment_id:
                result[equipment_id] = dict(row)
        return result

    def collect(self) -> ResearchImageBundleResult:
        """执行图片整理，并返回结果对象。"""
        run_dir = self._resolve_research_run_dir()
        manifests_dir = run_dir / self.settings.manifests_dir_name
        output_dir = manifests_dir / self.settings.output_folder_name
        output_dir.mkdir(parents=True, exist_ok=True)

        research_phase_path = manifests_dir / self.settings.phase_stage_name
        research_equipment_path = manifests_dir / self.settings.equipment_stage_name
        source_library_csv, source_images_csv = self._resolve_source_csvs()
        source_index = _build_source_image_index(source_library_csv, source_images_csv)

        phase_rows, equipment_rows = self._read_research_tables(manifests_dir)
        equipment_map = self._build_equipment_map(equipment_rows)

        warnings: List[str] = []
        copied_items: List[ResearchImageBundleItem] = []
        project_root = PathManager.get_project_root()

        for phase_row in sorted(phase_rows, key=lambda item: int(item.get("phase_number", "0") or 0)):
            phase_number = int(phase_row.get("phase_number", "0") or 0)
            phase_name = _sanitize_text(phase_row.get("name", f"S{phase_number}"))
            equipment_ids = [
                _sanitize_text(item)
                for item in str(phase_row.get("equipment_list", "")).split(",")
                if _sanitize_text(item)
            ]
            phase_output_dir = output_dir / f"s{phase_number}"
            phase_output_dir.mkdir(parents=True, exist_ok=True)

            for equipment_id in equipment_ids:
                equipment_row = equipment_map.get(equipment_id)
                if equipment_row is None:
                    warnings.append(f"未找到科研装备行: {equipment_id}")
                    continue

                equipment_name = _sanitize_text(equipment_row.get("name", ""))
                source_entry = source_index.get(_normalize_equipment_name(equipment_name))
                if source_entry is None:
                    warnings.append(f"未找到源图片: {equipment_name} -> {equipment_id}")
                    continue

                source_equipment_id, source_image_path = source_entry
                if not source_image_path.exists():
                    warnings.append(f"源图片不存在: {source_image_path.as_posix()}")
                    continue

                suffix = source_image_path.suffix or ".jpg"
                review_image_path = phase_output_dir / f"{equipment_id}{suffix}"
                _copy_image(source_image_path, review_image_path)
                copied_items.append(
                    ResearchImageBundleItem(
                        phase_number=phase_number,
                        phase_name=phase_name,
                        equipment_id=equipment_id,
                        equipment_name=equipment_name,
                        source_equipment_id=source_equipment_id,
                        source_image_path=source_image_path,
                        review_image_path=review_image_path,
                    )
                )

        manifest_json_path = manifests_dir / self.settings.manifest_name
        result = ResearchImageBundleResult(
            workspace_dir=run_dir,
            manifests_dir=manifests_dir,
            output_dir=output_dir,
            manifest_json_path=manifest_json_path,
            research_phase_path=research_phase_path,
            research_equipment_path=research_equipment_path,
            source_library_csv=source_library_csv,
            source_images_csv=source_images_csv,
            copied_items=copied_items,
            warnings=warnings,
        )

        with manifest_json_path.open("w", encoding="utf-8") as handle:
            json.dump(result.to_manifest(), handle, ensure_ascii=False, indent=2)

        self.logger.info(
            "科研图片整理完成: %s 张, 目录: %s",
            result.copied_count,
            result.output_dir.as_posix(),
        )
        return result


def get_research_phase_image_bundle() -> ResearchPhaseImageBundle:
    """获取科研图片整理工具实例。"""
    return ResearchPhaseImageBundle()
