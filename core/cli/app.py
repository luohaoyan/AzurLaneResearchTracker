#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              🚀 碧蓝航线科研装备统计器 CLI 入口                  ║
║                                                                  ║
║   【一句话解释】把数据层和计算层接到一个真正能给人用的命令行。  ║
║   支持交互菜单和三个核心子命令：status / record / export。     ║
║                                                                  ║
║   【类比理解】                                                    ║
║   core.cli.app 就像"前台接待员"。                                ║
║   用户来了以后先找它，它再把请求分发给各个管理器去处理。         ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prettytable import PrettyTable
from rich.console import Console
from rich.panel import Panel

from core.calculation.fragment_calculator import get_fragment_calculator
from core.calculation.luck_calculator import get_luck_calculator
from core.calculation.user_data_manager import get_user_data_manager
from core.data.equipment_manager import get_equipment_manager
from core.data.export_manager import get_export_manager
from core.data.research_manager import get_research_manager
from core.utils.config_loader import get_config_loader


console = Console()


@dataclass(frozen=True)
class RecordEntry:
    """单条非交互录入数据。"""

    equipment_id: str
    equipment_count: int
    fragment_count: int


# ============================================================
# 🧩 第二部分：CLI 辅助函数
# ============================================================


def _parse_iso_date(value: str) -> str:
    """解析 YYYY-MM-DD 日期字符串，给 argparse 提供清晰错误。"""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期格式应为 YYYY-MM-DD，例如 2026-07-08") from exc


def _get_app_version() -> str:
    """从配置中读取当前版本号，找不到时返回 v0.4.0。"""
    config = get_config_loader().get_main_config()
    version = config.get("app", {}).get("version", "0.4.0")
    return f"v{version}" if not str(version).startswith("v") else str(version)


def _print_banner() -> None:
    """打印程序欢迎页。"""
    version = _get_app_version()
    panel = Panel.fit(
        f"[bold cyan]{version}[/bold cyan]\n"
        "status | record | export\n"
        "输入数字可进入交互菜单，直接输入子命令也可以快速执行。",
        title="碧蓝航线科研装备统计器",
        border_style="cyan",
    )
    console.print(panel)


def _table_from_rows(title: str, field_names: Sequence[str], rows: Sequence[Sequence[Any]]) -> PrettyTable:
    """把二维数据整理成 PrettyTable。"""
    table = PrettyTable()
    table.title = title
    table.field_names = list(field_names)
    for row in rows:
        table.add_row(list(row))
    table.align = "l"
    return table


def _format_value(value: Any) -> str:
    """把数值整理成适合显示的文本。"""
    if value is None:
        return "-"
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _print_table(title: str, field_names: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    """统一打印表格。"""
    if not rows:
        console.print(f"[yellow]{title}：暂无数据[/yellow]")
        return
    console.print(_table_from_rows(title, field_names, rows))


def _sort_equipment_key(equipment_id: str) -> Tuple[int, int, int, str]:
    """让科研装备优先、数字装备其次、其他 ID 最后。"""
    parsed = get_equipment_manager().parse_research_id(equipment_id)
    if parsed:
        phase, seq = parsed
        return (0, phase, seq, equipment_id)
    if str(equipment_id).isdigit():
        return (1, 0, int(equipment_id), equipment_id)
    return (2, 0, 0, equipment_id)



def _safe_console_input(prompt: str) -> Optional[str]:
    """安全读取一行输入，输入流关闭时返回 None。"""
    try:
        return console.input(prompt)
    except EOFError:
        return None


def _show_luck_trend(phase_number: int) -> None:
    """显示某一期的历史趋势数字列表和 ASCII 图。"""
    luck_calc = get_luck_calculator()
    trend = luck_calc.get_luck_trend(phase_number)
    if not trend:
        console.print(f"[yellow]第 {phase_number} 期没有可用的历史趋势数据。[/yellow]")
        return

    numeric_rows: List[List[Any]] = []
    finite_values: List[float] = []
    for item in trend:
        luck_value = item.get("luck_value")
        display_value = _format_value(luck_value)
        if isinstance(luck_value, (int, float)) and not math.isinf(luck_value):
            finite_values.append(float(luck_value))
        numeric_rows.append([
            item.get("date", ""),
            display_value,
            item.get("luck_level", "未知"),
            item.get("rainbow_total", 0),
            item.get("gold_total", 0),
        ])

    _print_table(
        f"第 {phase_number} 期历史趋势 - 数字列表",
        ["日期", "欧非值", "等级", "彩总分", "金总分"],
        numeric_rows,
    )

    console.print("\n[bold cyan]ASCII 趋势图[/bold cyan]")
    if not finite_values:
        console.print("没有足够的有限数值来绘制趋势图。")
        return

    max_value = max(finite_values)
    min_value = min(finite_values)
    span = max(max_value - min_value, 0.001)
    width = 24
    for item in trend:
        luck_value = item.get("luck_value")
        if not isinstance(luck_value, (int, float)) or math.isinf(luck_value):
            bar = ""
            display_value = "inf" if isinstance(luck_value, float) and math.isinf(luck_value) else "-"
        else:
            normalized = (float(luck_value) - min_value) / span
            bar = "#" * max(1, int(round(normalized * width)))
            display_value = f"{float(luck_value):.3f}".rstrip("0").rstrip(".")
        console.print(f"{item.get('date', '')} | {bar:<24} {display_value}")


def command_status(trend_phase: int = 0) -> None:
    """展示当前整体状态。"""
    equipment_mgr = get_equipment_manager()
    research_mgr = get_research_manager()
    user_data_mgr = get_user_data_manager()
    fragment_calc = get_fragment_calculator()
    luck_calc = get_luck_calculator()

    equipment_stats = equipment_mgr.get_statistics()
    research_stats = research_mgr.get_statistics()
    today_data = user_data_mgr.get_today_data()
    fragment_summary = fragment_calc.get_summary(today_data)
    luck_summary = luck_calc.calculate_today_all_luck()

    console.print(Panel.fit("今天的总览", border_style="green"))

    _print_table(
        "基础统计",
        ["项目", "数量"],
        [
            ["装备总数", equipment_stats.get("total", 0)],
            ["科研装备", equipment_stats.get("research", 0)],
            ["普通装备", equipment_stats.get("general", 0)],
            ["科研期数", research_stats.get("total_phases", 0)],
            ["科研装备总量", research_stats.get("total_equipment", 0)],
            ["今日录入装备数", len(today_data)],
        ],
    )

    rarity_rows: List[List[Any]] = []
    for rarity_name, count in equipment_stats.get("by_rarity", {}).items():
        rarity_rows.append([rarity_name, count])
    rarity_rows.sort(key=lambda row: str(row[0]))
    _print_table("装备稀有度分布", ["稀有度", "数量"], rarity_rows)

    phase_rows: List[List[Any]] = []
    for phase in luck_summary.get("phases", []):
        phase_rows.append([
            phase.get("phase_number", 0),
            phase.get("phase_name", ""),
            phase.get("rainbow_total", 0),
            phase.get("gold_total", 0),
            _format_value(phase.get("luck_value")),
            phase.get("luck_level", ""),
        ])
    _print_table("今日欧非值", ["期数", "名称", "彩总分", "金总分", "欧非值", "等级"], phase_rows)

    _print_table(
        "今日碎片汇总",
        ["项目", "数量"],
        [
            ["总等值分", fragment_summary.get("overview", {}).get("total_score", 0)],
            ["总装备数", fragment_summary.get("overview", {}).get("total_equipments", 0)],
            ["可计算分类", len(fragment_summary.get("by_category", {}))],
        ],
    )

    if trend_phase <= 0 and sys.stdin.isatty():
        raw_phase = _safe_console_input("\n输入期数查看历史趋势（1-6，0 跳过）: ")
        if raw_phase is None:
            raw_phase = "0"
        raw_phase = raw_phase.strip()
        try:
            trend_phase = int(raw_phase)
        except ValueError:
            trend_phase = 0

    if trend_phase > 0:
        _show_luck_trend(trend_phase)


# ============================================================
# 🚀 第三部分：命令处理
# ============================================================

def _parse_record_input(raw: str) -> Optional[Tuple[str, Optional[int], Optional[int]]]:
    """解析录入时的一行输入。"""
    text = raw.strip()
    lowered = text.lower()
    if lowered in {"done", "skip", "q", "quit", "exit"}:
        return (lowered, None, None)

    parts = text.split()
    if not parts:
        return None

    if parts[0].lower() == "batch":
        if len(parts) != 3:
            return None
        try:
            return ("batch", int(parts[1]), int(parts[2]))
        except ValueError:
            return None

    if len(parts) == 2:
        try:
            return ("set", int(parts[0]), int(parts[1]))
        except ValueError:
            return None

    return None


def _build_record_entry(equipment_id: Any, equipment_count: Any, fragment_count: Any) -> Tuple[Optional[RecordEntry], Optional[str]]:
    """校验并组装一条非交互录入数据。"""
    eq_id = str(equipment_id).strip()
    if not eq_id:
        return None, "装备 ID 不能为空"
    if get_equipment_manager().get_by_id(eq_id) is None:
        return None, f"装备 ID 不存在：{eq_id}"

    try:
        count = int(str(equipment_count).strip())
        fragment = int(str(fragment_count).strip())
    except ValueError:
        return None, "件数和碎片数必须是整数"

    if count < 0 or fragment < 0:
        return None, "件数和碎片数不能是负数"
    return RecordEntry(eq_id, count, fragment), None


def _load_record_batch_file(batch_file: str) -> Tuple[Dict[str, Dict[str, int]], List[str]]:
    """读取批量录入 CSV，并返回可直接交给 UserDataManager 的记录字典。"""
    path = Path(batch_file).expanduser()
    records: Dict[str, Dict[str, int]] = {}
    errors: List[str] = []
    required_fields = {"equipment_id", "equipment_count", "fragment_count"}

    if not path.exists():
        return records, [f"批量文件不存在：{path}"]
    if not path.is_file():
        return records, [f"批量路径不是文件：{path}"]

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing_fields = sorted(required_fields - set(reader.fieldnames or []))
            if missing_fields:
                return records, [f"批量文件缺少字段：{', '.join(missing_fields)}"]

            for row_number, row in enumerate(reader, start=2):
                entry, error = _build_record_entry(
                    row.get("equipment_id", ""),
                    row.get("equipment_count", ""),
                    row.get("fragment_count", ""),
                )
                if error:
                    errors.append(f"第 {row_number} 行：{error}")
                    continue
                if entry is not None and entry.equipment_id in records:
                    errors.append(f"第 {row_number} 行：装备 ID 重复：{entry.equipment_id}")
                    continue
                if entry is not None:
                    records[entry.equipment_id] = {
                        "equipment_count": entry.equipment_count,
                        "fragment_count": entry.fragment_count,
                    }
    except OSError as exc:
        return records, [f"读取批量文件失败：{exc}"]

    if not records and not errors:
        errors.append("批量文件没有可导入记录")
    return records, errors


def _print_record_errors(errors: Sequence[str]) -> None:
    """统一打印非交互录入错误，避免长批量文件刷屏。"""
    for error in list(errors)[:10]:
        console.print(f"[red]{error}[/red]")
    if len(errors) > 10:
        console.print(f"[red]还有 {len(errors) - 10} 条错误未显示。[/red]")


def command_record(record_values: Optional[Sequence[str]] = None, batch_file: Optional[str] = None, dry_run: bool = False) -> int:
    """录入今天的数据，支持交互式和非交互式两种入口。"""
    user_data_mgr = get_user_data_manager()

    if record_values is not None:
        entry, error = _build_record_entry(record_values[0], record_values[1], record_values[2])
        if error:
            console.print(f"[red]{error}[/red]")
            return 1
        if entry is None:
            console.print("[red]录入数据解析失败。[/red]")
            return 1
        if dry_run:
            console.print(f"[green]校验通过：{entry.equipment_id}，未写入数据。[/green]")
            return 0
        if not user_data_mgr.update_record(entry.equipment_id, entry.equipment_count, entry.fragment_count):
            console.print(f"[red]保存失败：{entry.equipment_id}[/red]")
            return 1
        console.print(f"[green]已保存：{entry.equipment_id}[/green]")
        _print_record_summary(user_data_mgr)
        return 0

    if batch_file:
        records, errors = _load_record_batch_file(batch_file)
        if errors:
            _print_record_errors(errors)
            return 1
        if dry_run:
            console.print(f"[green]校验通过：{len(records)} 条记录，未写入数据。[/green]")
            return 0
        result = user_data_mgr.update_batch(records)
        console.print(
            f"[green]批量录入完成：成功 {result.get('success', 0)} 条，失败 {result.get('failed', 0)} 条。[/green]"
        )
        if result.get("failed", 0):
            _print_record_errors([f"保存失败：{eq_id}" for eq_id in result.get("failed_ids", [])])
            return 1
        _print_record_summary(user_data_mgr)
        return 0

    if dry_run:
        console.print("[red]--dry-run 需要搭配 --set 或 --batch-file 使用。[/red]")
        return 1

    if not sys.stdin.isatty():
        console.print("[yellow]record 命令需要交互式终端。[/yellow]")
        return 0

    equipment_mgr = get_equipment_manager()
    today_data = user_data_mgr.get_today_data()

    all_equipment = sorted(equipment_mgr.get_all(), key=lambda item: _sort_equipment_key(str(item.get("equipment_id", ""))))
    pending_equipment = [item for item in all_equipment if item.get("equipment_id", "") not in today_data]

    console.print(Panel.fit("今日数据录入", border_style="magenta"))
    console.print(f"今天已有 {len(today_data)} 件记录，待录入 {len(pending_equipment)} 件。")

    if not pending_equipment:
        console.print("[green]今天的记录已经录完了。[/green]")
        return 0

    for equipment in pending_equipment:
        equipment_id = str(equipment.get("equipment_id", ""))
        equipment_name = str(equipment.get("name", ""))
        rarity_name = equipment_mgr.get_with_rarity_name(equipment).get("rarity_name", "未知")
        console.print(f"\n[bold cyan]{equipment_id}[/bold cyan] {equipment_name} [{rarity_name}]")
        console.print("输入格式：`件数 碎片数`，或 `batch 件数 碎片数`，`skip` 跳过，`done` 结束。")

        while True:
            raw = _safe_console_input(">>> ")
            if raw is None:
                console.print("\n[yellow]输入已结束，自动退出录入。[/yellow]")
                _print_record_summary(user_data_mgr)
                return 0
            raw = raw.strip()
            parsed = _parse_record_input(raw)
            if parsed is None:
                console.print("[red]输入格式不对，请重新输入。[/red]")
                continue

            action, count, frag = parsed
            if action == "done":
                console.print("[yellow]录入提前结束。[/yellow]")
                _print_record_summary(user_data_mgr)
                return 0
            if action == "skip":
                console.print("[dim]已跳过。[/dim]")
                break

            if count is None or frag is None:
                console.print("[red]件数和碎片数都需要填写。[/red]")
                continue
            if count < 0 or frag < 0:
                console.print("[red]件数和碎片数不能是负数。[/red]")
                continue

            if user_data_mgr.update_record(equipment_id, count, frag):
                console.print("[green]已保存。[/green]")
            else:
                console.print("[red]保存失败。[/red]")
            break

    _print_record_summary(user_data_mgr)
    return 0


def _print_record_summary(user_data_mgr: Any) -> None:
    """录入后输出今日汇总。"""
    fragment_calc = get_fragment_calculator()
    luck_calc = get_luck_calculator()
    today_data = user_data_mgr.get_today_data()
    fragment_summary = fragment_calc.get_summary(today_data)
    luck_summary = luck_calc.calculate_today_all_luck()

    _print_table(
        "今日录入结果",
        ["项目", "数量"],
        [
            ["已录入装备数", len(today_data)],
            ["总等值分", fragment_summary.get("overview", {}).get("total_score", 0)],
            ["今日欧非值期数", len(luck_summary.get("phases", []))],
            ["整体欧非值", _format_value(luck_summary.get("overall_luck_value"))],
            ["整体等级", luck_summary.get("overall_luck_level", "")],
        ],
    )


def _export_kind_to_method(kind: str) -> str:
    """把导出类型映射到实际方法名。"""
    mapping = {
        "equipment": "equipment",
        "research": "research",
        "today": "today",
        "all": "all",
        "luck": "luck",
        "full": "full",
    }
    return mapping[kind]


def command_export(kind: Optional[str] = None, output: Optional[str] = None, date_str: Optional[str] = None, output_dir: Optional[str] = None) -> None:
    """导出数据。"""
    export_mgr = get_export_manager()
    export_target = output_dir or output

    if kind is None and sys.stdin.isatty():
        console.print(Panel.fit("数据导出", border_style="blue"))
        console.print("1. 导出装备库")
        console.print("2. 导出科研期数")
        console.print("3. 导出今日记录")
        console.print("4. 导出全部历史记录")
        console.print("5. 导出欧非汇总")
        console.print("6. 导出完整报告")
        console.print("0. 返回")
        choice_raw = _safe_console_input("请选择: ")
        if choice_raw is None:
            return
        choice = choice_raw.strip()
        kind_map = {
            "1": "equipment",
            "2": "research",
            "3": "today",
            "4": "all",
            "5": "luck",
            "6": "full",
        }
        if choice == "0":
            return
        kind = kind_map.get(choice)

    if not kind:
        console.print("[red]没有选择导出类型。[/red]")
        return

    resolved = _export_kind_to_method(kind)
    if resolved == "equipment":
        path = export_mgr.export_equipment_library(export_target)
        console.print(f"[green]已导出装备库：{path}[/green]")
        return
    if resolved == "research":
        path = export_mgr.export_research_phases(export_target)
        console.print(f"[green]已导出科研期数：{path}[/green]")
        return
    if resolved == "today":
        target_date = date_str or date.today().isoformat()
        path = export_mgr.export_user_records(target_date, export_target)
        console.print(f"[green]已导出 {target_date} 记录：{path}[/green]")
        return
    if resolved == "all":
        path = export_mgr.export_all_user_records(export_target)
        console.print(f"[green]已导出全部历史记录：{path}[/green]")
        return
    if resolved == "luck":
        path = export_mgr.export_luck_summary(export_target)
        console.print(f"[green]已导出欧非汇总：{path}[/green]")
        return
    if resolved == "full":
        result = export_mgr.export_full_report(export_target)
        console.print("[green]已导出完整报告：[/green]")
        for key, value in result.items():
            console.print(f"  - {key}: {value}")
        return

    console.print("[red]未知的导出类型。[/red]")


def _show_menu() -> None:
    """打印交互式主菜单。"""
    console.print(Panel.fit("主菜单", border_style="cyan"))
    console.print("1. 查看当前状态")
    console.print("2. 录入今日数据")
    console.print("3. 导出数据")
    console.print("0. 退出")


def interactive_menu() -> int:
    """交互式主循环。"""
    try:
        while True:
            _show_menu()
            choice_raw = _safe_console_input("请选择: ")
            if choice_raw is None:
                console.print("\n[yellow]输入已结束，安全退出。[/yellow]")
                return 0
            choice = choice_raw.strip()
            if choice == "0":
                console.print("再见，提督！")
                return 0
            if choice == "1":
                command_status()
                continue
            if choice == "2":
                command_record()
                continue
            if choice == "3":
                command_export()
                continue
            console.print("[red]请输入 0-3 的数字。[/red]")
    except KeyboardInterrupt:
        console.print("\n[yellow]已取消，安全退出。[/yellow]")
        return 130
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="AzurLaneResearchTracker",
        description="碧蓝航线科研装备统计器 CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser("status", help="查看当前状态")
    status_parser.add_argument("--trend-phase", type=int, default=0, help="显示指定期数的历史趋势，0 表示不显示")

    record_parser = subparsers.add_parser("record", help="录入今日数据")
    record_source = record_parser.add_mutually_exclusive_group()
    record_source.add_argument(
        "--set",
        dest="record_values",
        nargs=3,
        metavar=("EQUIPMENT_ID", "EQUIPMENT_COUNT", "FRAGMENT_COUNT"),
        help="非交互录入单件装备，例如 --set S1-001 2 30",
    )
    record_source.add_argument(
        "--batch-file",
        help="从 CSV 批量录入，字段为 equipment_id,equipment_count,fragment_count",
    )
    record_parser.add_argument("--dry-run", action="store_true", help="只校验录入数据，不写入文件")

    export_parser = subparsers.add_parser("export", help="导出数据")
    export_parser.add_argument("--kind", choices=["equipment", "research", "today", "all", "luck", "full"], help="导出类型")
    export_parser.add_argument("--output", help="CSV 输出文件或目录")
    export_parser.add_argument("--date", dest="date_str", type=_parse_iso_date, help="导出某一天的用户记录，格式 YYYY-MM-DD")
    export_parser.add_argument("--output-dir", help="导出输出目录，优先于 --output")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """程序入口。"""
    _print_banner()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.command:
        if sys.stdin.isatty():
            return interactive_menu()
        parser.print_help()
        return 0

    try:
        if args.command == "status":
            command_status(args.trend_phase)
            return 0
        if args.command == "record":
            return command_record(
                record_values=args.record_values,
                batch_file=args.batch_file,
                dry_run=args.dry_run,
            )
        if args.command == "export":
            command_export(
                kind=args.kind,
                output=args.output,
                date_str=args.date_str,
                output_dir=args.output_dir,
            )
            return 0

        parser.print_help()
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]已取消，安全退出。[/yellow]")
        return 130


