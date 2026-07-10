#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║         爬虫数据同步器 (CrawlerDataSynchronizer)                ║
║                                                                  ║
║   【一句话解释】把 equipment/research 两个爬虫的 stage 结果      ║
║   同步到项目正式的 data/ 目录，并保留特殊装备清单。             ║
║                                                                  ║
║   【类比理解】                                                   ║
║   这像是“总装车间”里的合并工位：先拿到装备爬虫的原始零件，      ║
║   再拿到科研爬虫的编号规则，最后把成品装回项目正式库。         ║
║                                                                  ║
║   【数据流】                                                     ║
║   workdir/crawler/runs          → equipment_library.csv          ║
║   workdir/crawler/research/runs → research_phases.csv            ║
║   source images                 → data/images/<rarity>/          ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
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

DEFAULT_CONFIG_NAME = "crawler_sync"
DEFAULT_WORKDIR_BASE = "workdir/crawler/sync"
DEFAULT_BACKUP_DIR_NAME = "backups"
DEFAULT_SYNC_OUTPUT_DIR_NAME = "latest"
DEFAULT_EQUIPMENT_RUNS_DIR = "workdir/crawler/runs"
DEFAULT_RESEARCH_RUNS_DIR = "workdir/crawler/research/runs"
DEFAULT_DATA_IMAGES_DIR_NAME = "images"
DEFAULT_CRAWLER_IMAGES_DIR_NAME = "images"

DEFAULT_RARITY_FOLDER_MAP = {
    "白色": "common",
    "蓝色": "rare",
    "紫色": "elite",
    "金色": "super_rare",
    "彩色": "ultra_rare",
}

CSV_LIBRARY_FIELDNAMES = ["equipment_id", "name", "rarity_id", "type"]
CSV_IMAGE_FIELDNAMES = ["equipment_id", "image_path"]
CSV_PHASE_FIELDNAMES = ["phase_number", "name", "equipment_list"]
CSV_SPECIAL_FIELDNAMES = ["equipment_id", "equipment_name", "notes"]


# ============================================================
# 第二部分：数据结构
# ============================================================


@dataclass(frozen=True)
class CrawlerSyncSettings:
    """爬虫同步器运行参数。"""

    equipment_run_dir: Optional[str] = None
    research_run_dir: Optional[str] = None
    backup_dir_name: str = DEFAULT_BACKUP_DIR_NAME
    output_dir_name: str = DEFAULT_SYNC_OUTPUT_DIR_NAME
    workdir_base_dir: str = DEFAULT_WORKDIR_BASE
    data_images_dir_name: str = DEFAULT_DATA_IMAGES_DIR_NAME
    crawler_images_dir_name: str = DEFAULT_CRAWLER_IMAGES_DIR_NAME

    @classmethod
    def from_mapping(cls, payload: Optional[Dict[str, Any]] = None) -> "CrawlerSyncSettings":
        """从 JSON 映射构建同步参数。"""
        data = payload or {}
        source_cfg = data.get("source", {})
        output_cfg = data.get("output", {})

        return cls(
            equipment_run_dir=_coerce_optional_text(source_cfg.get("equipment_run_dir")),
            research_run_dir=_coerce_optional_text(source_cfg.get("research_run_dir")),
            backup_dir_name=_coerce_text(output_cfg.get("backup_dir_name"), DEFAULT_BACKUP_DIR_NAME),
            output_dir_name=_coerce_text(output_cfg.get("output_dir_name"), DEFAULT_SYNC_OUTPUT_DIR_NAME),
            workdir_base_dir=_coerce_text(output_cfg.get("workdir_base_dir"), DEFAULT_WORKDIR_BASE),
            data_images_dir_name=_coerce_text(output_cfg.get("data_images_dir_name"), DEFAULT_DATA_IMAGES_DIR_NAME),
            crawler_images_dir_name=_coerce_text(
                output_cfg.get("crawler_images_dir_name"),
                DEFAULT_CRAWLER_IMAGES_DIR_NAME,
            ),
        )


@dataclass(frozen=True)
class CrawlerSyncResult:
    """同步完成后的结果摘要。"""

    workspace_dir: Path
    backup_dir: Path
    equipment_library_path: Path
    equipment_images_path: Path
    research_phases_path: Path
    data_images_dir: Path
    final_library_rows: List[Dict[str, str]]
    final_image_rows: List[Dict[str, str]]
    final_phase_rows: List[Dict[str, str]]
    copied_image_paths: List[Path]
    warnings: List[str]

    def to_manifest(self) -> Dict[str, Any]:
        """整理成可写入 JSON 的摘要。"""
        return {
            "workspace_dir": str(self.workspace_dir),
            "backup_dir": str(self.backup_dir),
            "equipment_library_path": str(self.equipment_library_path),
            "equipment_images_path": str(self.equipment_images_path),
            "research_phases_path": str(self.research_phases_path),
            "data_images_dir": str(self.data_images_dir),
            "equipment_count": len(self.final_library_rows),
            "image_count": len(self.final_image_rows),
            "phase_count": len(self.final_phase_rows),
            "copied_image_count": len(self.copied_image_paths),
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


def _coerce_optional_path(value: Any) -> Optional[Path]:
    """????????? Path????????????? Path?"""
    text = _coerce_optional_text(value)
    if text is None:
        return None
    return Path(text)


def _sanitize_text(value: Any) -> str:
    """去掉多余空白，保留用于匹配的核心文本。"""
    return " ".join(str(value or "").split()).strip()


def _clean_sync_equipment_name(value: Any) -> str:
    """灞忚斀 wiki 鏈夊彲鑳芥販鍏ョ殑澶撮儴/灏鹃儴鏉傚瓧绗︺€?"""
    text = _clean_sync_equipment_name(value)
    text = re.sub(r"^[\s,，。;；:：、{}【】\[\]（）()<>《》]+", "", text)
    text = re.sub(r"[\s,，。;；:：、{}【】\[\]（）()<>《》]+$", "", text)
    return text


def _strip_equipment_artifacts(value: Any) -> str:
    text = _strip_equipment_artifacts(value)
    text = re.sub(r"^[\s,，。;；:：、{}【】\[\]（）()<>《》]+", "", text)
    text = re.sub(r"[\s,，。;；:：、{}【】\[\]（）()<>《》]+$", "", text)
    return text


def _safe_equipment_name(value: Any) -> str:
    """灞忚斀 wiki 鏈夊彲鑳芥販鍏ョ殑澶撮儴/灏鹃儴鏉傚瓧绗︺€?"""
    text = _sanitize_text(value)
    text = re.sub(r"^[\s,，。;；:：、{}【】\[\]（）()<>《》]+", "", text)
    text = re.sub(r"[\s,，。;；:：、{}【】\[\]（）()<>《》]+$", "", text)
    return text


def _normalize_equipment_name(value: Any) -> str:
    """把装备名压缩成稳定的匹配形式。"""
    text = _safe_equipment_name(value)
    text = text.replace("#", "")
    text = text.replace("（", "(").replace("）", ")")
    return text.replace(" ", "").lower()


def _load_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    """读取 CSV 为字典行列表。"""
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 CSV 文件: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(csv_path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> Path:
    """把数据写回 UTF-8-SIG CSV。"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return csv_path


def _atomic_write_csv(csv_path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> Path:
    """先写临时文件，再用原子替换保护正式 CSV。"""
    tmp_path = csv_path.with_suffix(f"{csv_path.suffix}.tmp")
    replaced = False
    try:
        _write_csv(tmp_path, rows, fieldnames)
        os.replace(tmp_path, csv_path)
        replaced = True
        return csv_path
    finally:
        if not replaced and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _write_json(json_path: Path, payload: Dict[str, Any]) -> Path:
    """把字典写入 JSON 文件。"""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return json_path


def _discover_latest_directory(root: Path, required_files: Sequence[str]) -> Path:
    """从目录中找到最新且包含目标文件的子目录。"""
    if not root.exists():
        raise FileNotFoundError(f"目录不存在: {root}")

    candidates = [item for item in root.iterdir() if item.is_dir()]
    candidates.sort(key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    for candidate in candidates:
        if all((candidate / required).exists() for required in required_files):
            return candidate
        manifests_dir = candidate / "manifests"
        if all((manifests_dir / required).exists() for required in required_files):
            return candidate

    raise FileNotFoundError(f"在目录中找不到可用的爬虫结果: {root}")


def _resolve_existing_path(raw_path: str, project_root: Path) -> Path:
    """把配置中的相对路径解析成真实路径。"""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return project_root / path


def _resolve_stage_csv(run_dir: Path, filename: str) -> Path:
    """兼容直接放在目录下和放在 manifests/ 里的两种结构。"""
    direct_csv = run_dir / filename
    if direct_csv.exists():
        return direct_csv
    nested_csv = run_dir / "manifests" / filename
    if nested_csv.exists():
        return nested_csv
    raise FileNotFoundError(f"找不到阶段 CSV: {filename} ({run_dir})")


def _parse_research_id(equipment_id: str) -> Optional[Tuple[int, int]]:
    """解析 Sx-xxx 形式的科研 ID。"""
    text = _sanitize_text(equipment_id)
    if not text.startswith("S") or "-" not in text:
        return None
    phase_text, seq_text = text[1:].split("-", 1)
    if not phase_text.isdigit() or not seq_text.isdigit():
        return None
    return int(phase_text), int(seq_text)


def _sort_equipment_key(equipment_id: str, special_ids: Sequence[str]) -> Tuple[int, int, int, str]:
    """让科研装备排在前面，特殊装备次之，其余 G 装备最后。"""
    parsed = _parse_research_id(equipment_id)
    if parsed:
        phase_number, sequence = parsed
        return (0, phase_number, sequence, equipment_id)

    if equipment_id in special_ids:
        digits = equipment_id[1:]
        return (1, int(digits) if digits.isdigit() else 0, 0, equipment_id)

    if equipment_id.startswith("G") and equipment_id[1:].isdigit():
        return (2, int(equipment_id[1:]), 0, equipment_id)

    return (3, 0, 0, equipment_id)


def _backup_tree(source_dir: Path, target_dir: Path) -> Path:
    """把文件或目录完整备份到目标位置。"""
    if target_dir.exists():
        if target_dir.is_dir():
            shutil.rmtree(target_dir)
        else:
            target_dir.unlink()
    if source_dir.is_dir():
        shutil.copytree(source_dir, target_dir)
    elif source_dir.is_file():
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir, target_dir)
    else:
        if target_dir.suffix:
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            target_dir.write_text("", encoding="utf-8")
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _clean_directory_contents(target_dir: Path) -> None:
    """清空目录内容，但保留目录本身。"""
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        return
    for item in target_dir.iterdir():
        if item.name == "__init__.py" or item.name == "__pycache__" or item.suffix == ".py":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _copy_image(source_path: Path, destination_path: Path) -> Path:
    """复制单张图片到最终位置。"""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    return destination_path


def _relative_text(path: Path, project_root: Path) -> str:
    """把绝对路径转成相对项目根目录的文本。"""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json_config() -> Dict[str, Any]:
    """加载同步器专用配置。"""
    loader = get_config_loader()
    config = loader.get_config("crawler", DEFAULT_CONFIG_NAME)
    return config or {}


def _build_research_index(research_equipment_rows: Sequence[Dict[str, str]]) -> Dict[str, str]:
    """根据科研装备表构建“名称 -> 最终 ID”的索引，S0 优先。"""
    ranked: Dict[str, Tuple[Tuple[int, int, int, str], str]] = {}
    for row in research_equipment_rows:
        equipment_id = _sanitize_text(row.get("equipment_id", ""))
        name = _safe_equipment_name(row.get("name", ""))
        if not equipment_id or not name:
            continue
        normalized_name = _normalize_equipment_name(name)
        phase_number = int(_sanitize_text(row.get("phase_number", "0")) or 0)
        source_scope = _sanitize_text(row.get("source_scope", "phase"))
        priority = (
            0 if source_scope == "common" or equipment_id.startswith("S0-") else 1,
            phase_number,
            int(equipment_id.split("-", 1)[1]) if "-" in equipment_id and equipment_id.split("-", 1)[1].isdigit() else 0,
            equipment_id,
        )
        current = ranked.get(normalized_name)
        if current is None or priority < current[0]:
            ranked[normalized_name] = (priority, equipment_id)

    result: Dict[str, str] = {
        normalized_name: item[1]
        for normalized_name, item in ranked.items()
    }
    return result


def _build_image_source_index(
    source_library_rows: Sequence[Dict[str, str]],
    source_image_rows: Sequence[Dict[str, str]],
    project_root: Path,
    source_run_dir: Path,
) -> Dict[str, Dict[str, str]]:
    """把装备名称映射到它的来源图片和来源 ID。"""
    id_to_name: Dict[str, str] = {}
    for row in source_library_rows:
        equipment_id = _sanitize_text(row.get("equipment_id", ""))
        name = _safe_equipment_name(row.get("name", ""))
        if equipment_id and name:
            id_to_name[equipment_id] = name

    id_to_image: Dict[str, Path] = {}
    for row in source_image_rows:
        equipment_id = _sanitize_text(row.get("equipment_id", ""))
        image_path = _sanitize_text(row.get("image_path", ""))
        if not equipment_id or not image_path:
            continue
        image_file = Path(image_path)
        if not image_file.is_absolute():
            candidates = [
                project_root / image_file,
                source_run_dir / image_file,
                source_run_dir / "manifests" / image_file,
            ]
            image_file = next((item for item in candidates if item.exists()), candidates[0])
        id_to_image[equipment_id] = image_file

    result: Dict[str, Dict[str, str]] = {}
    for equipment_id, equipment_name in id_to_name.items():
        image_path = id_to_image.get(equipment_id)
        if image_path is None:
            continue
        result[_normalize_equipment_name(equipment_name)] = {
            "source_equipment_id": equipment_id,
            "source_image_path": str(image_path),
        }
    return result


# ============================================================
# 第四部分：同步器
# ============================================================


class CrawlerDataSynchronizer:
    """把爬虫 stage 结果同步到项目正式 data/ 目录。"""

    def __init__(
        self,
        config_data: Optional[Dict[str, Any]] = None,
        project_root: Optional[Path] = None,
        data_root: Optional[Path] = None,
        workdir_root: Optional[Path] = None,
    ) -> None:
        self.logger = get_logger()
        self.project_root = project_root or PathManager.get_project_root()
        self.data_root = data_root or PathManager.get_data_dir()
        self.workdir_root = workdir_root or PathManager.get_work_dir()
        self.settings = CrawlerSyncSettings.from_mapping(config_data or _load_json_config())

    def _resolve_equipment_run_dir(self, explicit_run_dir: Optional[Path] = None) -> Path:
        """????????????????"""
        if explicit_run_dir is not None:
            return explicit_run_dir
        if self.settings.equipment_run_dir:
            return _resolve_existing_path(self.settings.equipment_run_dir, self.project_root)
        return _discover_latest_directory(
            self.project_root / DEFAULT_EQUIPMENT_RUNS_DIR,
            ["equipment_library_stage.csv", "equipment_images_stage.csv"],
        )

    def _resolve_research_run_dir(self, explicit_run_dir: Optional[Path] = None) -> Path:
        """????????????????"""
        if explicit_run_dir is not None:
            return explicit_run_dir
        if self.settings.research_run_dir:
            return _resolve_existing_path(self.settings.research_run_dir, self.project_root)
        return _discover_latest_directory(
            self.project_root / DEFAULT_RESEARCH_RUNS_DIR,
            ["research_phases_stage.csv", "research_equipment_stage.csv"],
        )

    def _prepare_workspace(self, workspace_name: Optional[str] = None) -> Path:
        """创建本次同步的存档目录。"""
        timestamp = workspace_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace_dir = self.workdir_root / self.settings.workdir_base_dir.split("/", 1)[-1] / self.settings.output_dir_name / timestamp
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir

    def _load_special_rows(self) -> Tuple[List[Dict[str, str]], set[str]]:
        """从现有装备库里保留特殊装备行。"""
        library_path = self.data_root / "equipment_library.csv"
        special_path = self.data_root / "special_equipment.csv"
        current_rows = _load_csv_rows(library_path) if library_path.exists() else []
        special_rows = _load_csv_rows(special_path) if special_path.exists() else []
        special_ids = {
            _sanitize_text(row.get("equipment_id", ""))
            for row in special_rows
            if _sanitize_text(row.get("equipment_id", ""))
        }
        preserved_rows = [row for row in current_rows if _sanitize_text(row.get("equipment_id", "")) in special_ids]
        return preserved_rows, special_ids

    def _load_current_library_rows(self) -> List[Dict[str, str]]:
        """读取当前正式装备表，用于 stage 缺行时兜底保留旧数据。"""
        library_path = self.data_root / "equipment_library.csv"
        return _load_csv_rows(library_path) if library_path.exists() else []

    def _load_current_image_rows(self) -> Dict[str, str]:
        """读取当前图片映射，用于保留特殊装备的已有路径。"""
        image_path = self.data_root / "equipment_images.csv"
        rows = _load_csv_rows(image_path) if image_path.exists() else []
        result: Dict[str, str] = {}
        for row in rows:
            equipment_id = _sanitize_text(row.get("equipment_id", ""))
            image_value = _sanitize_text(row.get("image_path", ""))
            if equipment_id and image_value:
                result[equipment_id] = image_value
        return result

    def _load_current_image_rows_list(self) -> List[Dict[str, str]]:
        """读取当前正式图片表原始行顺序，便于完整保留遗漏项。"""
        image_path = self.data_root / "equipment_images.csv"
        return _load_csv_rows(image_path) if image_path.exists() else []

    def _collect_final_rows(
        self,
        source_library_rows: Sequence[Dict[str, str]],
        source_image_rows: Sequence[Dict[str, str]],
        research_index: Dict[str, str],
        special_rows: Sequence[Dict[str, str]],
        special_ids: set[str],
        source_run_dir: Path,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Path], List[str]]:
        """把装备爬虫和科研爬虫的结果合成最终 CSV 行。"""
        image_source_index = _build_image_source_index(
            source_library_rows=source_library_rows,
            source_image_rows=source_image_rows,
            project_root=self.project_root,
            source_run_dir=source_run_dir,
        )
        current_library_rows = self._load_current_library_rows()
        current_image_rows = self._load_current_image_rows()
        current_image_row_list = self._load_current_image_rows_list()

        final_library_rows: List[Dict[str, str]] = []
        final_image_rows: List[Dict[str, str]] = []
        copied_paths: List[Path] = []
        warnings: List[str] = []

        seen_ids: set[str] = set()
        replaced_ids: set[str] = set()
        replaced_names: set[str] = set()

        rarity_folder_map = _load_rarity_folder_map()

        for row in source_library_rows:
            old_equipment_id = _sanitize_text(row.get("equipment_id", ""))
            equipment_name = _sanitize_text(row.get("name", ""))
            if not old_equipment_id or not equipment_name:
                continue

            normalized_name = _normalize_equipment_name(equipment_name)
            final_equipment_id = research_index.get(normalized_name, old_equipment_id)
            if final_equipment_id in seen_ids:
                continue
            seen_ids.add(final_equipment_id)
            if final_equipment_id != old_equipment_id:
                replaced_ids.add(old_equipment_id)
                replaced_names.add(normalized_name)

            final_row = dict(row)
            final_row["equipment_id"] = final_equipment_id
            final_library_rows.append(final_row)

            source_entry = image_source_index.get(normalized_name)
            if source_entry is None:
                warnings.append(f"未找到源图片: {equipment_name} -> {final_equipment_id}")
                continue

            source_image_path = Path(source_entry["source_image_path"])
            if not source_image_path.exists():
                warnings.append(f"源图片不存在: {source_image_path.as_posix()}")
                continue

            rarity_name = self._rarity_name_from_id(final_row.get("rarity_id", ""))
            rarity_folder = rarity_folder_map.get(rarity_name, "unknown")
            suffix = source_image_path.suffix.lower() or ".jpg"
            destination_path = self.data_root / self.settings.data_images_dir_name / rarity_folder / f"{final_equipment_id}{suffix}"
            _copy_image(source_image_path, destination_path)
            copied_paths.append(destination_path)

            final_image_rows.append(
                {
                    "equipment_id": final_equipment_id,
                    "image_path": _relative_text(destination_path, self.project_root),
                }
            )

        for row in special_rows:
            equipment_id = _sanitize_text(row.get("equipment_id", ""))
            if not equipment_id or equipment_id in seen_ids:
                continue
            seen_ids.add(equipment_id)
            final_library_rows.append(dict(row))
            image_value = current_image_rows.get(equipment_id, "")
            if image_value:
                final_image_rows.append(
                    {
                        "equipment_id": equipment_id,
                        "image_path": image_value,
                    }
                )

        final_library_rows.sort(
            key=lambda item: _sort_equipment_key(
                _sanitize_text(item.get("equipment_id", "")),
                sorted(special_ids),
            )
        )
        final_image_rows.sort(
            key=lambda item: _sort_equipment_key(
                _sanitize_text(item.get("equipment_id", "")),
                sorted(special_ids),
            )
        )

        for row in current_library_rows:
            equipment_id = _sanitize_text(row.get("equipment_id", ""))
            normalized_name = _normalize_equipment_name(row.get("name", ""))
            if (
                not equipment_id
                or equipment_id in replaced_ids
                or normalized_name in replaced_names
                or any(_sanitize_text(item.get("equipment_id", "")) == equipment_id for item in final_library_rows)
            ):
                continue
            final_library_rows.append(dict(row))
            warnings.append(f"保留旧行: {equipment_id}={_sanitize_text(row.get('name', ''))}")

        for row in current_image_row_list:
            equipment_id = _sanitize_text(row.get("equipment_id", ""))
            if (
                not equipment_id
                or equipment_id in replaced_ids
                or any(_sanitize_text(item.get("equipment_id", "")) == equipment_id for item in final_image_rows)
            ):
                continue
            final_image_rows.append(dict(row))
            warnings.append(f"保留旧图行: {equipment_id}")

        return final_library_rows, final_image_rows, copied_paths, warnings

    def _sync_special_equipment_file(
        self,
        final_library_rows: Sequence[Dict[str, str]],
        warnings: List[str],
    ) -> Optional[Path]:
        """按名称把 special_equipment.csv 的 equipment_id 对齐到最新装备库。"""
        special_path = self.data_root / "special_equipment.csv"
        if not special_path.exists():
            return None

        special_rows = _load_csv_rows(special_path)
        name_to_id: Dict[str, str] = {}
        for row in final_library_rows:
            equipment_name = _sanitize_text(row.get("name", ""))
            equipment_id = _sanitize_text(row.get("equipment_id", ""))
            if not equipment_name or not equipment_id:
                continue
            normalized_name = _normalize_equipment_name(equipment_name)
            if normalized_name not in name_to_id:
                name_to_id[normalized_name] = equipment_id

        updated_rows: List[Dict[str, str]] = []
        updated_count = 0
        for row in special_rows:
            equipment_name = _sanitize_text(row.get("equipment_name", ""))
            if not equipment_name:
                updated_rows.append(dict(row))
                continue

            normalized_name = _normalize_equipment_name(equipment_name)
            new_equipment_id = name_to_id.get(normalized_name)
            if not new_equipment_id:
                warnings.append(f"特殊装备未匹配到新ID: {equipment_name}")
                updated_rows.append(dict(row))
                continue

            updated_row = dict(row)
            old_equipment_id = _sanitize_text(updated_row.get("equipment_id", ""))
            updated_row["equipment_id"] = new_equipment_id
            updated_rows.append(updated_row)
            if old_equipment_id != new_equipment_id:
                updated_count += 1
                warnings.append(f"特殊装备ID已更新: {equipment_name} {old_equipment_id} -> {new_equipment_id}")

        _atomic_write_csv(special_path, updated_rows, CSV_SPECIAL_FIELDNAMES)
        if updated_count:
            self.logger.info("特殊装备表已按名称完成 ID 对齐: %s 条", updated_count)
        return special_path

    def _rarity_name_from_id(self, rarity_id: Any) -> str:
        """把 rarity_id 转成中文稀有度名。"""
        text = str(rarity_id).strip()
        rarity_map = {
            "1": "白色",
            "2": "蓝色",
            "3": "紫色",
            "4": "金色",
            "5": "彩色",
        }
        return rarity_map.get(text, "未知")

    def sync(
        self,
        workspace_name: Optional[str] = None,
        equipment_run_dir: Optional[Path | str] = None,
        research_run_dir: Optional[Path | str] = None,
    ) -> CrawlerSyncResult:
        """????????????????????????????"""
        explicit_equipment_run_dir = _coerce_optional_path(equipment_run_dir)
        explicit_research_run_dir = _coerce_optional_path(research_run_dir)
        equipment_run_dir = self._resolve_equipment_run_dir(explicit_equipment_run_dir)
        research_run_dir = self._resolve_research_run_dir(explicit_research_run_dir)
        workspace_dir = self._prepare_workspace(workspace_name)
        backup_dir = workspace_dir / self.settings.backup_dir_name
        backup_dir.mkdir(parents=True, exist_ok=True)

        equipment_library_path = self.data_root / "equipment_library.csv"
        equipment_images_path = self.data_root / "equipment_images.csv"
        research_phases_path = self.data_root / "research_phases.csv"
        data_images_dir = self.data_root / self.settings.data_images_dir_name

        _backup_tree(equipment_library_path, backup_dir / "equipment_library.csv")
        _backup_tree(equipment_images_path, backup_dir / "equipment_images.csv")
        _backup_tree(research_phases_path, backup_dir / "research_phases.csv")
        _backup_tree(data_images_dir, backup_dir / self.settings.data_images_dir_name)

        source_library_rows = _load_csv_rows(_resolve_stage_csv(equipment_run_dir, "equipment_library_stage.csv"))
        source_image_rows = _load_csv_rows(_resolve_stage_csv(equipment_run_dir, "equipment_images_stage.csv"))
        research_phase_rows = _load_csv_rows(_resolve_stage_csv(research_run_dir, "research_phases_stage.csv"))
        research_equipment_rows = _load_csv_rows(_resolve_stage_csv(research_run_dir, "research_equipment_stage.csv"))

        preserved_special_rows, special_ids = self._load_special_rows()
        research_index = _build_research_index(research_equipment_rows)

        _clean_directory_contents(data_images_dir)
        final_library_rows, final_image_rows, copied_paths, warnings = self._collect_final_rows(
            source_library_rows=source_library_rows,
            source_image_rows=source_image_rows,
            research_index=research_index,
            special_rows=preserved_special_rows,
            special_ids=special_ids,
            source_run_dir=equipment_run_dir,
        )

        _atomic_write_csv(equipment_library_path, final_library_rows, CSV_LIBRARY_FIELDNAMES)
        _atomic_write_csv(equipment_images_path, final_image_rows, CSV_IMAGE_FIELDNAMES)
        _atomic_write_csv(research_phases_path, research_phase_rows, CSV_PHASE_FIELDNAMES)
        special_equipment_path = self._sync_special_equipment_file(final_library_rows, warnings)

        manifest_path = workspace_dir / "crawler_sync_manifest.json"
        result = CrawlerSyncResult(
            workspace_dir=workspace_dir,
            backup_dir=backup_dir,
            equipment_library_path=equipment_library_path,
            equipment_images_path=equipment_images_path,
            research_phases_path=research_phases_path,
            data_images_dir=data_images_dir,
            final_library_rows=final_library_rows,
            final_image_rows=final_image_rows,
            final_phase_rows=research_phase_rows,
            copied_image_paths=copied_paths,
            warnings=warnings,
        )
        manifest_payload = result.to_manifest() | {
            "source_equipment_run_dir": str(equipment_run_dir),
            "source_research_run_dir": str(research_run_dir),
        }
        if special_equipment_path is not None:
            manifest_payload["special_equipment_path"] = str(special_equipment_path)
        _write_json(manifest_path, manifest_payload)

        self.logger.info(
            "爬虫数据同步完成: 装备%s条, 图片%s条, 科研期数%s条, 工作区%s",
            len(final_library_rows),
            len(final_image_rows),
            len(research_phase_rows),
            workspace_dir.as_posix(),
        )
        return result


def _load_rarity_folder_map() -> Dict[str, str]:
    """从配置中读取稀有度文件夹映射，缺省时回退到默认值。"""
    loader = get_config_loader()
    config = loader.get_config("crawler", "equipment_crawler") or {}
    mapping = dict(DEFAULT_RARITY_FOLDER_MAP)
    mapping.update({str(key): str(value) for key, value in config.get("rarity_folder_map", {}).items()})
    return mapping


def get_crawler_data_synchronizer() -> CrawlerDataSynchronizer:
    """获取全局同步器实例。"""
    return CrawlerDataSynchronizer()
