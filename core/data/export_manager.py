#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              📤 数据导出管理器 (ExportManager)                   ║
║                                                                  ║
║   【一句话解释】把装备库、科研期数、用户记录和欧非汇总统一导出。 ║
║   支持 CSV 和 Excel 两种格式，给 CLI 和后续 GUI 共用。           ║
║                                                                  ║
║   【类比理解】                                                    ║
║   导出管理器就像"整理文件的秘书"。                                ║
║   平时散在各个管理器里的数据，最后由它统一排版并写成文件。       ║
║                                                                  ║
║   【输出目录】                                                    ║
║   data/exports/                                                   ║
║   ├── equipment_library_YYYYMMDD_HHMMSS.csv                       ║
║   ├── research_phases_YYYYMMDD_HHMMSS.csv                         ║
║   ├── today_YYYYMMDD.csv                                          ║
║   ├── all_records_YYYYMMDD.csv                                    ║
║   ├── luck_summary_YYYYMMDD.csv                                   ║
║   └── full_report_YYYYMMDD_HHMMSS.xlsx                            ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openpyxl import Workbook
from openpyxl.styles import Font

from ..calculation.fragment_calculator import get_fragment_calculator
from ..calculation.luck_calculator import get_luck_calculator
from ..calculation.user_data_manager import get_user_data_manager
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager
from .equipment_manager import EquipmentManager, get_equipment_manager
from .research_manager import get_research_manager


class ExportManager:
    """📤 数据导出管理器 - 把现有管理器数据整理成文件。"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        """单例模式：整个程序只保留一个导出管理器实例。"""
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self._equipment_manager = None
        self._research_manager = None
        self._user_data_manager = None
        self._fragment_calculator = None
        self._luck_calculator = None
        self.export_dir = PathManager.get_data_dir() / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    # ══════════════════════════════════════════════════════════════
    #  延迟加载属性
    # ══════════════════════════════════════════════════════════════

    @property
    def equipment_manager(self):
        """延迟加载装备管理器。"""
        if self._equipment_manager is None:
            self._equipment_manager = get_equipment_manager()
        return self._equipment_manager

    @property
    def research_manager(self):
        """延迟加载科研管理器。"""
        if self._research_manager is None:
            self._research_manager = get_research_manager()
        return self._research_manager

    @property
    def user_data_manager(self):
        """延迟加载用户数据管理器。"""
        if self._user_data_manager is None:
            self._user_data_manager = get_user_data_manager()
        return self._user_data_manager

    @property
    def fragment_calculator(self):
        """延迟加载碎片计算器。"""
        if self._fragment_calculator is None:
            self._fragment_calculator = get_fragment_calculator()
        return self._fragment_calculator

    @property
    def luck_calculator(self):
        """延迟加载欧非值计算器。"""
        if self._luck_calculator is None:
            self._luck_calculator = get_luck_calculator()
        return self._luck_calculator

    # ══════════════════════════════════════════════════════════════
    #  内部工具
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _timestamp() -> str:
        """获取用于文件名的时间戳。"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def _date_stamp() -> str:
        """获取仅包含日期的时间戳。"""
        return date.today().strftime("%Y%m%d")

    @staticmethod
    def _normalize_date_string(date_str: Optional[str] = None) -> str:
        """把日期统一校验成 YYYY-MM-DD，避免错误日期生成无意义导出。"""
        target = date_str or date.today().isoformat()
        try:
            return date.fromisoformat(target).isoformat()
        except ValueError as exc:
            raise ValueError("日期格式应为 YYYY-MM-DD，例如 2026-07-08") from exc

    def _resolve_file_path(self, output_path: Optional[str], default_filename: str) -> Path:
        """把用户传入路径规范化为最终文件路径。"""
        if output_path:
            candidate = Path(output_path).expanduser()
            if candidate.exists() and candidate.is_dir():
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate / default_filename
            if candidate.suffix:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                return candidate
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate / default_filename

        self.export_dir.mkdir(parents=True, exist_ok=True)
        return self.export_dir / default_filename

    @staticmethod
    def _ensure_parent_dir(file_path: Path) -> None:
        """确保文件上级目录存在。"""
        file_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_text(value: Any) -> str:
        """把任意值转成适合写入 CSV/Excel 的文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            return "；".join(str(item) for item in value)
        return str(value)

    def _write_csv(self, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str], file_path: Path) -> str:
        """统一写 CSV 的内部方法。"""
        self._ensure_parent_dir(file_path)
        with open(file_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
            writer.writeheader()
            for row in rows:
                writer.writerow({key: self._safe_text(row.get(key, "")) for key in fieldnames})
        self.logger.info(f"已导出 CSV: {file_path}")
        return str(file_path)

    @staticmethod
    def _normalize_sheet_name(sheet_name: str) -> str:
        """Excel 的 sheet 名称最多 31 个字符。"""
        cleaned = sheet_name.strip() or "Sheet"
        return cleaned[:31]

    def _write_excel(self, sheets: Sequence[Tuple[str, Sequence[Dict[str, Any]], Sequence[str]]], file_path: Path) -> str:
        """统一写 Excel 的内部方法。"""
        self._ensure_parent_dir(file_path)
        workbook = Workbook()
        workbook.remove(workbook.active)
        header_font = Font(bold=True)

        for sheet_name, rows, fieldnames in sheets:
            worksheet = workbook.create_sheet(title=self._normalize_sheet_name(sheet_name))
            worksheet.append(list(fieldnames))
            for cell in worksheet[1]:
                cell.font = header_font
            for row in rows:
                worksheet.append([row.get(field, "") for field in fieldnames])
            worksheet.freeze_panes = "A2"

        workbook.save(file_path)
        self.logger.info(f"已导出 Excel: {file_path}")
        return str(file_path)

    @staticmethod
    def _sort_equipment_key(equipment_id: str) -> Tuple[int, int, int, str]:
        """尽量让科研装备排在前面，普通数字 ID 排在后面。"""
        parsed = EquipmentManager.parse_research_id(equipment_id)
        if parsed:
            phase, seq = parsed
            return (0, phase, seq, equipment_id)
        if str(equipment_id).isdigit():
            return (1, 0, int(equipment_id), equipment_id)
        return (2, 0, 0, equipment_id)

    def _build_equipment_library_rows(self) -> List[Dict[str, Any]]:
        """整理装备库导出数据。"""
        rows: List[Dict[str, Any]] = []
        equipments = sorted(
            self.equipment_manager.get_equipment_with_image(),
            key=lambda item: self._sort_equipment_key(str(item.get("equipment_id", ""))),
        )
        for item in equipments:
            rows.append({
                "equipment_id": item.get("equipment_id", ""),
                "name": item.get("name", ""),
                "rarity_id": item.get("rarity_id", ""),
                "rarity_name": item.get("rarity_name", ""),
                "rarity_color": item.get("rarity_color", ""),
                "type": item.get("type", ""),
                "image_path": item.get("image_path", ""),
            })
        return rows

    def _build_research_phase_rows(self) -> List[Dict[str, Any]]:
        """整理科研期数导出数据。"""
        rows: List[Dict[str, Any]] = []
        phases = sorted(self.research_manager.get_all(), key=lambda item: int(item.get("phase_number", 0)))
        for phase in phases:
            phase_number = int(phase.get("phase_number", 0))
            equipment_details: List[str] = []
            for equipment in self.research_manager.get_phase_equipment(phase_number):
                equipment_details.append(f"{equipment.get('equipment_id', '')}:{equipment.get('name', '')}")
            rows.append({
                "phase_number": phase_number,
                "name": phase.get("name", ""),
                "equipment_list": phase.get("equipment_list", ""),
                "equipment_count": self.research_manager.get_phase_equipment_count(phase_number),
                "equipment_details": "；".join(equipment_details),
            })
        return rows

    def _build_user_record_rows(self, target_date: str) -> List[Dict[str, Any]]:
        """整理单日用户记录导出数据。"""
        target_date = self._normalize_date_string(target_date)
        rows: List[Dict[str, Any]] = []
        data = self.user_data_manager.get_data_by_date(target_date)
        for equipment_id in sorted(data.keys(), key=self._sort_equipment_key):
            record = data[equipment_id]
            calculated = self.fragment_calculator.calculate_single(
                equipment_id,
                record.get("equipment_count", 0),
                record.get("fragment_count", 0),
            )
            rows.append({
                "date": target_date,
                "equipment_id": equipment_id,
                "equipment_name": calculated.get("equipment_name", ""),
                "rarity_name": calculated.get("rarity_name", ""),
                "category": calculated.get("category", ""),
                "equipment_count": record.get("equipment_count", 0),
                "fragment_count": record.get("fragment_count", 0),
                "equivalent": calculated.get("equivalent", ""),
                "score": calculated.get("score", ""),
            })
        return rows

    def _build_all_user_record_rows(self) -> List[Dict[str, Any]]:
        """整理全部历史用户记录导出数据。"""
        rows: List[Dict[str, Any]] = []
        for record_date in self.user_data_manager.list_available_dates():
            try:
                rows.extend(self._build_user_record_rows(record_date))
            except ValueError:
                self.logger.warning(f"已跳过日期格式异常的历史记录文件: {record_date}")
        rows.sort(key=lambda item: (item.get("date", ""), self._sort_equipment_key(str(item.get("equipment_id", "")))))
        return rows

    def _build_luck_summary_rows(self) -> List[Dict[str, Any]]:
        """整理欧非汇总导出数据。"""
        result = self.luck_calculator.calculate_today_all_luck()
        rows: List[Dict[str, Any]] = []

        for phase in result.get("phases", []):
            rows.append({
                "scope": "phase",
                "phase_number": phase.get("phase_number", ""),
                "phase_name": phase.get("phase_name", ""),
                "rainbow_count": len(phase.get("rainbow_equipments", [])),
                "gold_count": len(phase.get("gold_equipments", [])),
                "rainbow_total": phase.get("rainbow_total", 0),
                "gold_total": phase.get("gold_total", 0),
                "luck_value": phase.get("luck_value", ""),
                "luck_level": phase.get("luck_level", ""),
                "warnings": "；".join(phase.get("warnings", [])),
            })

        rows.append({
            "scope": "overall",
            "phase_number": "",
            "phase_name": "全期汇总",
            "rainbow_count": "",
            "gold_count": "",
            "rainbow_total": result.get("overall_rainbow_total", 0),
            "gold_total": result.get("overall_gold_total", 0),
            "luck_value": result.get("overall_luck_value", ""),
            "luck_level": result.get("overall_luck_level", ""),
            "warnings": "",
        })
        return rows

    # ══════════════════════════════════════════════════════════════
    #  公开导出接口
    # ══════════════════════════════════════════════════════════════

    def export_equipment_library(self, output_path: Optional[str] = None) -> str:
        """导出装备库。"""
        default_filename = f"equipment_library_{self._timestamp()}.csv"
        file_path = self._resolve_file_path(output_path, default_filename)
        return self._write_csv(
            self._build_equipment_library_rows(),
            ["equipment_id", "name", "rarity_id", "rarity_name", "rarity_color", "type", "image_path"],
            file_path,
        )

    def export_research_phases(self, output_path: Optional[str] = None) -> str:
        """导出科研期数表。"""
        default_filename = f"research_phases_{self._timestamp()}.csv"
        file_path = self._resolve_file_path(output_path, default_filename)
        return self._write_csv(
            self._build_research_phase_rows(),
            ["phase_number", "name", "equipment_list", "equipment_count", "equipment_details"],
            file_path,
        )

    def export_user_records(self, date_str: Optional[str] = None, output_path: Optional[str] = None) -> str:
        """导出指定日期的用户记录。"""
        target_date = self._normalize_date_string(date_str)
        default_filename = f"today_{target_date.replace('-', '')}.csv"
        file_path = self._resolve_file_path(output_path, default_filename)
        return self._write_csv(
            self._build_user_record_rows(target_date),
            ["date", "equipment_id", "equipment_name", "rarity_name", "category", "equipment_count", "fragment_count", "equivalent", "score"],
            file_path,
        )

    def export_all_user_records(self, output_path: Optional[str] = None) -> str:
        """导出全部历史用户记录。"""
        default_filename = f"all_records_{self._date_stamp()}.csv"
        file_path = self._resolve_file_path(output_path, default_filename)
        return self._write_csv(
            self._build_all_user_record_rows(),
            ["date", "equipment_id", "equipment_name", "rarity_name", "category", "equipment_count", "fragment_count", "equivalent", "score"],
            file_path,
        )

    def export_luck_summary(self, output_path: Optional[str] = None) -> str:
        """导出今日欧非汇总。"""
        default_filename = f"luck_summary_{self._date_stamp()}.csv"
        file_path = self._resolve_file_path(output_path, default_filename)
        return self._write_csv(
            self._build_luck_summary_rows(),
            ["scope", "phase_number", "phase_name", "rainbow_count", "gold_count", "rainbow_total", "gold_total", "luck_value", "luck_level", "warnings"],
            file_path,
        )

    def export_full_report(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """一次性导出完整报告，包含 CSV 和 Excel。"""
        if output_dir:
            export_dir = Path(output_dir).expanduser()
            if export_dir.suffix:
                export_dir = export_dir.parent
        else:
            export_dir = self.export_dir / f"full_report_{self._timestamp()}"
        export_dir.mkdir(parents=True, exist_ok=True)

        equipment_rows = self._build_equipment_library_rows()
        research_rows = self._build_research_phase_rows()
        today_rows = self._build_user_record_rows(date.today().isoformat())
        all_rows = self._build_all_user_record_rows()
        luck_rows = self._build_luck_summary_rows()

        results: Dict[str, str] = {
            "equipment_library": self._write_csv(
                equipment_rows,
                ["equipment_id", "name", "rarity_id", "rarity_name", "rarity_color", "type", "image_path"],
                export_dir / "equipment_library.csv",
            ),
            "research_phases": self._write_csv(
                research_rows,
                ["phase_number", "name", "equipment_list", "equipment_count", "equipment_details"],
                export_dir / "research_phases.csv",
            ),
            "today_records": self._write_csv(
                today_rows,
                ["date", "equipment_id", "equipment_name", "rarity_name", "category", "equipment_count", "fragment_count", "equivalent", "score"],
                export_dir / f"today_{self._date_stamp()}.csv",
            ),
            "all_records": self._write_csv(
                all_rows,
                ["date", "equipment_id", "equipment_name", "rarity_name", "category", "equipment_count", "fragment_count", "equivalent", "score"],
                export_dir / f"all_records_{self._date_stamp()}.csv",
            ),
            "luck_summary": self._write_csv(
                luck_rows,
                ["scope", "phase_number", "phase_name", "rainbow_count", "gold_count", "rainbow_total", "gold_total", "luck_value", "luck_level", "warnings"],
                export_dir / f"luck_summary_{self._date_stamp()}.csv",
            ),
        }

        workbook_path = export_dir / f"full_report_{self._timestamp()}.xlsx"
        results["workbook"] = self._write_excel(
            [
                ("Equipment Library", equipment_rows, ["equipment_id", "name", "rarity_id", "rarity_name", "rarity_color", "type", "image_path"]),
                ("Research Phases", research_rows, ["phase_number", "name", "equipment_list", "equipment_count", "equipment_details"]),
                ("Today Records", today_rows, ["date", "equipment_id", "equipment_name", "rarity_name", "category", "equipment_count", "fragment_count", "equivalent", "score"]),
                ("All Records", all_rows, ["date", "equipment_id", "equipment_name", "rarity_name", "category", "equipment_count", "fragment_count", "equivalent", "score"]),
                ("Luck Summary", luck_rows, ["scope", "phase_number", "phase_name", "rainbow_count", "gold_count", "rainbow_total", "gold_total", "luck_value", "luck_level", "warnings"]),
            ],
            workbook_path,
        )
        results["output_dir"] = str(export_dir)
        return results


# ──────────────────────────────────────────────────────────────
#  全局访问函数
# ──────────────────────────────────────────────────────────────

_instance_cache: Optional[ExportManager] = None


def get_export_manager() -> ExportManager:
    """获取全局唯一的 ExportManager 实例。"""
    global _instance_cache
    if _instance_cache is None:
        _instance_cache = ExportManager()
    return _instance_cache
