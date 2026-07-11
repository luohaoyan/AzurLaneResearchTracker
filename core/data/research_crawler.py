#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║               科研爬虫模块 (ResearchCrawler)                         ║
║  负责解析「军部研究室」页面，生成科研期数索引与 ID 覆盖计划。         ║
║  类比理解：像项目的资料员，先把页内装备名单抄出来，再做归类编号。     ║
║  数据流：HTML -> 期数/装备解析 -> s0/sx 编号 -> stage CSV / manifest。 ║
╚══════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import csv
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ..utils.config_loader import get_config_loader
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager
from .equipment_manager import get_equipment_manager


# ============================================================
# 第一部分：默认配置
# ============================================================

DEFAULT_SOURCE_URL = "https://wiki.biligame.com/blhx/%E5%86%9B%E9%83%A8%E7%A0%94%E7%A9%B6%E5%AE%A4"
DEFAULT_TIMEOUT = (10.0, 30.0)
DEFAULT_USER_AGENT = "AzurLaneResearchTrackerCrawler/0.5.0"
DEFAULT_WORKSPACE_BASE_DIR = "workdir/crawler/research"
DEFAULT_RUNS_DIR_NAME = "runs"
DEFAULT_RAW_DIR_NAME = "raw"
DEFAULT_MANIFESTS_DIR_NAME = "manifests"
DEFAULT_RAW_HTML_NAME = "research_room.html"
DEFAULT_PHASE_STAGE_NAME = "research_phases_stage.csv"
DEFAULT_EQUIPMENT_STAGE_NAME = "research_equipment_stage.csv"
DEFAULT_OVERRIDE_STAGE_NAME = "equipment_id_overrides_stage.csv"
DEFAULT_MANIFEST_NAME = "crawl_manifest.json"
DEFAULT_PHASE_LIMIT = None
DEFAULT_COMMON_LIMIT = None

COMMON_PHASE_NUMBER = 0
COMMON_PHASE_NAME = "通用科研装备(S0)"
COMMON_PREFIX = "以下为往期科研已有装备"

CSV_PHASE_FIELDNAMES = [
    "phase_number",
    "name",
    "equipment_list",
]

CSV_EQUIPMENT_FIELDNAMES = [
    "equipment_id",
    "name",
    "phase_number",
    "phase_name",
    "source_scope",
    "order_index",
]

CSV_OVERRIDE_FIELDNAMES = [
    "old_equipment_id",
    "new_equipment_id",
    "name",
]

PHASE_HEADING_RE = re.compile(r"^第([0-9一二三四五六七八九十百]+)期$")
ITEM_SPLIT_RE = re.compile(r"[、,，;；]+")

CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


# ============================================================
# 第二部分：数据结构
# ============================================================


@dataclass(frozen=True)
class CrawlerSettings:
    """科研爬虫运行参数。"""

    source_url: str = DEFAULT_SOURCE_URL
    phase_limit: Optional[int] = DEFAULT_PHASE_LIMIT
    common_limit: Optional[int] = DEFAULT_COMMON_LIMIT
    timeout: Tuple[float, float] = DEFAULT_TIMEOUT
    retry_total: int = 3
    retry_backoff_factor: float = 0.8
    request_delay_seconds: float = 1.0
    user_agent: str = DEFAULT_USER_AGENT
    workspace_base_dir: str = DEFAULT_WORKSPACE_BASE_DIR
    runs_dir_name: str = DEFAULT_RUNS_DIR_NAME
    raw_dir_name: str = DEFAULT_RAW_DIR_NAME
    manifests_dir_name: str = DEFAULT_MANIFESTS_DIR_NAME
    raw_html_name: str = DEFAULT_RAW_HTML_NAME
    phase_stage_name: str = DEFAULT_PHASE_STAGE_NAME
    equipment_stage_name: str = DEFAULT_EQUIPMENT_STAGE_NAME
    override_stage_name: str = DEFAULT_OVERRIDE_STAGE_NAME
    manifest_name: str = DEFAULT_MANIFEST_NAME

    @classmethod
    def from_mapping(cls, payload: Optional[Dict[str, Any]] = None) -> "CrawlerSettings":
        """从配置字典构建设置对象。"""
        data = payload or {}
        request_cfg = data.get("request", {})
        workspace_cfg = data.get("workspace", {})
        crawl_cfg = data.get("crawl", {})
        output_cfg = data.get("output", {})

        timeout_value = request_cfg.get("timeout", list(DEFAULT_TIMEOUT))
        timeout = (float(timeout_value[0]), float(timeout_value[1]))

        phase_limit_value = crawl_cfg.get("phase_limit", DEFAULT_PHASE_LIMIT)
        common_limit_value = crawl_cfg.get("common_limit", DEFAULT_COMMON_LIMIT)

        phase_limit = None if phase_limit_value in (None, "", 0) else max(1, int(phase_limit_value))
        common_limit = None if common_limit_value in (None, "", 0) else max(1, int(common_limit_value))

        return cls(
            source_url=str(data.get("source_url", DEFAULT_SOURCE_URL)),
            phase_limit=phase_limit,
            common_limit=common_limit,
            timeout=timeout,
            retry_total=int(request_cfg.get("retry_total", 3)),
            retry_backoff_factor=float(request_cfg.get("backoff_factor", 0.8)),
            request_delay_seconds=float(request_cfg.get("delay_seconds", 1.0)),
            user_agent=str(request_cfg.get("user_agent", DEFAULT_USER_AGENT)),
            workspace_base_dir=str(workspace_cfg.get("base_dir", DEFAULT_WORKSPACE_BASE_DIR)),
            runs_dir_name=str(workspace_cfg.get("runs_dir_name", DEFAULT_RUNS_DIR_NAME)),
            raw_dir_name=str(workspace_cfg.get("raw_dir_name", DEFAULT_RAW_DIR_NAME)),
            manifests_dir_name=str(workspace_cfg.get("manifests_dir_name", DEFAULT_MANIFESTS_DIR_NAME)),
            raw_html_name=str(output_cfg.get("raw_html_name", DEFAULT_RAW_HTML_NAME)),
            phase_stage_name=str(output_cfg.get("phase_stage_name", DEFAULT_PHASE_STAGE_NAME)),
            equipment_stage_name=str(output_cfg.get("equipment_stage_name", DEFAULT_EQUIPMENT_STAGE_NAME)),
            override_stage_name=str(output_cfg.get("override_stage_name", DEFAULT_OVERRIDE_STAGE_NAME)),
            manifest_name=str(output_cfg.get("manifest_name", DEFAULT_MANIFEST_NAME)),
        )


@dataclass(frozen=True)
class ResearchEquipmentRecord:
    """科研装备的最终编号与来源记录。"""

    equipment_id: str
    name: str
    phase_number: int
    phase_name: str
    source_scope: str
    order_index: int

    def to_row(self) -> Dict[str, Any]:
        """转换为 stage CSV 行。"""
        return {
            "equipment_id": self.equipment_id,
            "name": self.name,
            "phase_number": self.phase_number,
            "phase_name": self.phase_name,
            "source_scope": self.source_scope,
            "order_index": self.order_index,
        }


@dataclass(frozen=True)
class ResearchPhaseRecord:
    """科研期数的阶段索引记录。"""

    phase_number: int
    name: str
    equipment_ids: List[str]

    def to_row(self) -> Dict[str, Any]:
        """转换为 research_phases.csv 风格的一行。"""
        return {
            "phase_number": self.phase_number,
            "name": self.name,
            "equipment_list": ",".join(self.equipment_ids),
        }


@dataclass(frozen=True)
class ResearchCrawlerResult:
    """一次科研爬虫运行的输出。"""

    workspace_dir: Path
    raw_html_path: Path
    phase_stage_path: Path
    equipment_stage_path: Path
    override_stage_path: Path
    manifest_json_path: Path
    common_records: List[ResearchEquipmentRecord]
    phase_records: List[ResearchPhaseRecord]
    override_rows: List[Dict[str, Any]]
    warnings: List[str]
    mode: str

    @property
    def parsed_phase_count(self) -> int:
        """页面里解析到的科研期数数量。"""
        return len(self.phase_records)

    @property
    def common_equipment_count(self) -> int:
        """通用科研装备数量。"""
        return len(self.common_records)

    @property
    def total_equipment_count(self) -> int:
        """总科研装备数量。"""
        return self.common_equipment_count + sum(len(item.equipment_ids) for item in self.phase_records)

    def to_manifest(self) -> Dict[str, Any]:
        """整理成适合写入 JSON 的摘要。"""
        return {
            "workspace_dir": str(self.workspace_dir),
            "raw_html_path": str(self.raw_html_path),
            "phase_stage_path": str(self.phase_stage_path),
            "equipment_stage_path": str(self.equipment_stage_path),
            "override_stage_path": str(self.override_stage_path),
            "source_url": DEFAULT_SOURCE_URL,
            "mode": self.mode,
            "parsed_phase_count": self.parsed_phase_count,
            "common_equipment_count": self.common_equipment_count,
            "total_equipment_count": self.total_equipment_count,
            "phase_numbers": [item.phase_number for item in self.phase_records],
            "warnings": list(self.warnings),
        }


# ============================================================
# 第三部分：辅助函数
# ============================================================


def build_default_crawler_config() -> Dict[str, Any]:
    """构造默认配置，便于落盘为 JSON。"""
    return {
        "source_url": DEFAULT_SOURCE_URL,
        "crawl": {
            "phase_limit": None,
            "common_limit": None,
        },
        "request": {
            "timeout": list(DEFAULT_TIMEOUT),
            "retry_total": 3,
            "backoff_factor": 0.8,
            "delay_seconds": 1.0,
            "user_agent": DEFAULT_USER_AGENT,
        },
        "workspace": {
            "base_dir": DEFAULT_WORKSPACE_BASE_DIR,
            "runs_dir_name": DEFAULT_RUNS_DIR_NAME,
            "raw_dir_name": DEFAULT_RAW_DIR_NAME,
            "manifests_dir_name": DEFAULT_MANIFESTS_DIR_NAME,
        },
        "output": {
            "raw_html_name": DEFAULT_RAW_HTML_NAME,
            "phase_stage_name": DEFAULT_PHASE_STAGE_NAME,
            "equipment_stage_name": DEFAULT_EQUIPMENT_STAGE_NAME,
            "override_stage_name": DEFAULT_OVERRIDE_STAGE_NAME,
            "manifest_name": DEFAULT_MANIFEST_NAME,
        },
    }


def load_crawler_config() -> Dict[str, Any]:
    """从仓库配置中加载科研爬虫配置。"""
    loader = get_config_loader()
    config = loader.get_config("crawler", "research_crawler")
    if config:
        return config
    return build_default_crawler_config()


def _sanitize_text(value: str) -> str:
    """压缩空白字符并保留装备名本体。"""
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    return cleaned.replace("\u3000", " ")


def _clean_equipment_name(value: str) -> str:
    cleaned = _sanitize_text(value)
    cleaned = re.sub(r"^[\s,，。;；:：、{}【】\[\]（）()<>《》]+", "", cleaned)
    cleaned = re.sub(r"[\s,，。;；:：、{}【】\[\]（）()<>《》]+$", "", cleaned)
    return cleaned


def _chinese_numeral_to_int(token: str) -> Optional[int]:
    """把中文数字转换为整数。"""
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if "十" in token:
        left, right = token.split("十", 1)
        tens = CN_DIGITS.get(left, 1 if left == "" else None)
        ones = CN_DIGITS.get(right, 0 if right == "" else None)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    if token in CN_DIGITS:
        return CN_DIGITS[token]
    return None


def _parse_phase_number(text: str) -> Optional[int]:
    """从标题「第一期」解析出期数。"""
    match = PHASE_HEADING_RE.match(_sanitize_text(text))
    if not match:
        return None
    return _chinese_numeral_to_int(match.group(1))


def _split_equipment_items(segment: str) -> List[str]:
    """把一个类别段拆分为若干装备名。"""
    items: List[str] = []
    for raw_item in ITEM_SPLIT_RE.split(segment):
        item = _clean_equipment_name(raw_item)
        if item:
            items.append(item)
    return items


def _extract_items_from_text(text: str) -> List[str]:
    """从一个科研段落中提取装备名称列表。"""
    cleaned = _sanitize_text(text)
    if not cleaned:
        return []
    if cleaned.startswith(COMMON_PREFIX):
        cleaned = cleaned[len(COMMON_PREFIX) :].strip()

    label_matches = list(re.finditer(r"(?P<label>[^\s：:、，,;；]{1,20})[：:]", cleaned))
    if not label_matches:
        return _split_equipment_items(cleaned)

    items: List[str] = []
    for index, match in enumerate(label_matches):
        start = match.end()
        end = label_matches[index + 1].start("label") if index + 1 < len(label_matches) else len(cleaned)
        body = _sanitize_text(cleaned[start:end])
        if body:
            items.extend(_split_equipment_items(body))
    return items


def _find_research_section_root(soup: BeautifulSoup) -> Optional[Tag]:
    """定位「科研装备设计图」所在的小节。"""
    for heading in soup.find_all("h3"):
        title = _sanitize_text(heading.get_text(" ", strip=True))
        if "科研装备设计图" in title:
            return heading
    return None


def _iter_phase_blocks(root: Tag) -> List[Tuple[int, str, List[str], List[str]]]:
    """遍历科研装备设计图内的期数块。"""
    phase_blocks: List[Tuple[int, str, List[str], List[str]]] = []
    current_phase_number: Optional[int] = None
    current_phase_title = ""
    current_items: List[str] = []
    common_items: List[str] = []

    for sibling in root.find_next_siblings():
        sibling_name = getattr(sibling, "name", None)
        if sibling_name == "h3":
            break
        if sibling_name == "h4":
            if current_phase_number is not None:
                phase_blocks.append(
                    (
                        current_phase_number,
                        current_phase_title,
                        list(current_items),
                        list(common_items),
                    )
                )
            current_phase_title = _sanitize_text(sibling.get_text(" ", strip=True))
            current_phase_number = _parse_phase_number(current_phase_title)
            current_items = []
            continue
        if sibling_name != "p" or current_phase_number is None:
            continue

        text = _sanitize_text(sibling.get_text(" ", strip=True))
        if not text:
            continue
        if text.startswith(COMMON_PREFIX):
            common_items.extend(_extract_items_from_text(text))
        else:
            current_items.extend(_extract_items_from_text(text))

    if current_phase_number is not None:
        phase_blocks.append(
            (
                current_phase_number,
                current_phase_title,
                list(current_items),
                list(common_items),
            )
        )
    return phase_blocks


def _deduplicate_in_order(items: Sequence[str]) -> List[str]:
    """按首次出现顺序去重。"""
    seen: OrderedDict[str, None] = OrderedDict()
    for item in items:
        name = _sanitize_text(item)
        if name and name not in seen:
            seen[name] = None
    return list(seen.keys())


def _make_phase_name(phase_number: int) -> str:
    """生成统一的科研期数名称。"""
    return f"科研{phase_number}期(PR{phase_number})"


def _ensure_parent_dir(file_path: Path) -> None:
    """确保目标文件的父目录存在。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)


def write_csv(file_path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> Path:
    """把行数据写入 UTF-8-SIG 编码的 CSV。"""
    _ensure_parent_dir(file_path)
    with open(file_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return file_path


def write_json(file_path: Path, payload: Dict[str, Any]) -> Path:
    """把字典写入 JSON 文件。"""
    _ensure_parent_dir(file_path)
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return file_path


# ============================================================
# 第四部分：核心爬虫
# ============================================================


class ResearchCrawler:
    """科研装备爬虫。

    目标只覆盖页面解析和 stage 输出，不直接修改正式 data/。
    """

    def __init__(
        self,
        config_data: Optional[Dict[str, Any]] = None,
        workspace_root: Optional[Path] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.logger = get_logger()
        self.settings = CrawlerSettings.from_mapping(config_data or load_crawler_config())
        default_workspace = (
            PathManager.get_project_root()
            / self.settings.workspace_base_dir
            / self.settings.runs_dir_name
        )
        default_workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_root = workspace_root or default_workspace
        self.session = session or self._build_session()
        self._page_cache: Dict[str, str] = {}

    def _build_session(self) -> Session:
        """构建带重试的 HTTP 会话。"""
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": self.settings.source_url,
            }
        )
        retry = Retry(
            total=self.settings.retry_total,
            connect=self.settings.retry_total,
            read=self.settings.retry_total,
            status=self.settings.retry_total,
            backoff_factor=self.settings.retry_backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    @property
    def timeout(self) -> Tuple[float, float]:
        """请求超时时间。"""
        return self.settings.timeout

    def fetch_page_html(self) -> str:
        """抓取科研页面 HTML，并在单次运行中缓存。"""
        cached_html = self._page_cache.get(self.settings.source_url)
        if cached_html is not None:
            return cached_html

        response = self.session.get(self.settings.source_url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        html = response.text
        self._page_cache[self.settings.source_url] = html
        time.sleep(self.settings.request_delay_seconds)
        return html

    def _prepare_workspace(self, workspace_name: Optional[str] = None) -> Dict[str, Path]:
        """为本次运行创建独立工作区。"""
        timestamp = workspace_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.workspace_root / timestamp
        if run_dir.exists():
            suffix = 1
            while True:
                candidate = self.workspace_root / f"{timestamp}_{suffix:02d}"
                if not candidate.exists():
                    run_dir = candidate
                    break
                suffix += 1

        raw_dir = run_dir / self.settings.raw_dir_name
        manifests_dir = run_dir / self.settings.manifests_dir_name
        logs_dir = run_dir / "logs"

        for path in (raw_dir, manifests_dir, logs_dir):
            path.mkdir(parents=True, exist_ok=True)

        return {
            "run_dir": run_dir,
            "raw_dir": raw_dir,
            "manifests_dir": manifests_dir,
            "logs_dir": logs_dir,
        }

    def _parse_page(self, html: str) -> Tuple[List[str], List[Tuple[int, str, List[str]]], List[str]]:
        """解析页面，返回通用装备、期数装备与告警。"""
        soup = BeautifulSoup(html, "html.parser")
        root = _find_research_section_root(soup)
        if root is None:
            return [], [], ["未找到科研装备设计图章节"]

        blocks = _iter_phase_blocks(root)
        if not blocks:
            return [], [], ["未解析到任何科研期数"]

        all_common_items: List[str] = []
        phase_items: List[Tuple[int, str, List[str]]] = []
        for phase_number, phase_title, current_items, common_items in blocks:
            if phase_number is None:
                continue
            all_common_items.extend(common_items)
            phase_items.append((phase_number, phase_title or _make_phase_name(phase_number), current_items))

        common_names = _deduplicate_in_order(all_common_items)
        phase_items = [
            (phase_number, phase_title, _deduplicate_in_order(items))
            for phase_number, phase_title, items in phase_items
        ]
        return common_names, phase_items, []

    def _resolve_limits(self) -> Tuple[Optional[int], Optional[int]]:
        """读取当前运行应使用的限制值。"""
        return self.settings.phase_limit, self.settings.common_limit

    def _assign_ids(
        self,
        common_names: Sequence[str],
        phase_items: Sequence[Tuple[int, str, Sequence[str]]],
    ) -> Tuple[List[ResearchEquipmentRecord], List[ResearchPhaseRecord]]:
        """按 s0 / sx 规则分配 ID。"""
        name_to_id: Dict[str, str] = {}
        equipment_records: List[ResearchEquipmentRecord] = []
        phase_records: List[ResearchPhaseRecord] = []

        common_records: List[ResearchEquipmentRecord] = []
        for index, name in enumerate(common_names, start=1):
            equipment_id = f"S0-{index:03d}"
            name_to_id[name] = equipment_id
            record = ResearchEquipmentRecord(
                equipment_id=equipment_id,
                name=name,
                phase_number=COMMON_PHASE_NUMBER,
                phase_name=COMMON_PHASE_NAME,
                source_scope="common",
                order_index=index,
            )
            equipment_records.append(record)
            common_records.append(record)

        for phase_number, phase_title, items in phase_items:
            phase_equipment_ids: List[str] = []
            sequence = 0
            for name in items:
                if name in name_to_id:
                    equipment_id = name_to_id[name]
                    if equipment_id.startswith("S0-"):
                        continue
                    # 其他期数已出现过的装备，不再重复计入后续期数。
                    continue

                sequence += 1
                equipment_id = f"S{phase_number}-{sequence:03d}"
                name_to_id[name] = equipment_id
                phase_equipment_ids.append(equipment_id)
                equipment_records.append(
                    ResearchEquipmentRecord(
                        equipment_id=equipment_id,
                        name=name,
                        phase_number=phase_number,
                        phase_name=phase_title,
                        source_scope="phase",
                        order_index=sequence,
                    )
                )
            phase_records.append(
                ResearchPhaseRecord(
                    phase_number=phase_number,
                    name=phase_title,
                    equipment_ids=phase_equipment_ids,
                )
            )

        return equipment_records, phase_records

    def _build_override_rows(self, equipment_records: Sequence[ResearchEquipmentRecord]) -> List[Dict[str, Any]]:
        """根据当前装备库，生成旧 ID -> 新 ID 的覆盖计划。"""
        equipment_manager = get_equipment_manager()
        current_rows = equipment_manager.get_all()
        name_to_old_id = {
            _sanitize_text(str(row.get("name", ""))): _sanitize_text(str(row.get("equipment_id", "")))
            for row in current_rows
            if _sanitize_text(str(row.get("name", ""))) and _sanitize_text(str(row.get("equipment_id", "")))
        }

        override_rows: List[Dict[str, Any]] = []
        seen_names: set[str] = set()
        for record in equipment_records:
            if record.name in seen_names:
                continue
            seen_names.add(record.name)
            old_id = name_to_old_id.get(record.name)
            if not old_id or old_id == record.equipment_id:
                continue
            override_rows.append(
                {
                    "old_equipment_id": old_id,
                    "new_equipment_id": record.equipment_id,
                    "name": record.name,
                }
            )
        return override_rows

    def _apply_limits(
        self,
        common_names: Sequence[str],
        phase_items: Sequence[Tuple[int, str, Sequence[str]]],
    ) -> Tuple[List[str], List[Tuple[int, str, Sequence[str]]], List[str]]:
        """根据配置裁剪样本范围。"""
        warnings: List[str] = []
        phase_limit, common_limit = self._resolve_limits()

        selected_common = list(common_names)
        if common_limit is not None:
            selected_common = selected_common[:common_limit]
            if len(selected_common) < len(common_names):
                warnings.append(
                    f"仅保留前 {len(selected_common)} 条通用科研装备，完整通用条目共 {len(common_names)} 条"
                )

        selected_phases = list(phase_items)
        if phase_limit is not None:
            selected_phases = selected_phases[:phase_limit]
            if len(selected_phases) < len(phase_items):
                warnings.append(
                    f"仅保留前 {len(selected_phases)} 期科研数据，完整期数共 {len(phase_items)} 期"
                )

        return selected_common, selected_phases, warnings

    def crawl_stage(
        self,
        phase_limit: Optional[int] = None,
        common_limit: Optional[int] = None,
        workspace_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str, str], object]] = None,
    ) -> ResearchCrawlerResult:
        """执行一次科研爬虫，输出 stage 文件。"""
        original_settings = self.settings
        try:
            if phase_limit is not None or common_limit is not None:
                self.settings = CrawlerSettings(
                    **{
                        **self.settings.__dict__,
                        "phase_limit": phase_limit if phase_limit is not None else self.settings.phase_limit,
                        "common_limit": common_limit if common_limit is not None else self.settings.common_limit,
                    }
                )

            if progress_callback is not None:
                progress_callback(10, "正在下载军部研究室页面。", self.settings.source_url)
            html = self.fetch_page_html()
            workspace = self._prepare_workspace(workspace_name)
            raw_html_path = workspace["raw_dir"] / self.settings.raw_html_name
            raw_html_path.write_text(html, encoding="utf-8")
            if progress_callback is not None:
                progress_callback(30, "科研页面已保存，正在解析期数与装备。", str(raw_html_path))

            common_names, phase_items, parse_warnings = self._parse_page(html)
            selected_common_names, selected_phase_items, limit_warnings = self._apply_limits(common_names, phase_items)
            if progress_callback is not None:
                progress_callback(
                    55,
                    "科研期数解析完成，正在分配 S0/Sx 编号。",
                    f"期数={len(selected_phase_items)}；通用={len(selected_common_names)}",
                )

            equipment_records, phase_records = self._assign_ids(selected_common_names, selected_phase_items)
            override_rows = self._build_override_rows(equipment_records)
            if progress_callback is not None:
                progress_callback(75, "科研装备编号完成，正在写入 stage CSV。", f"装备={len(equipment_records)}")

            phase_stage_path = workspace["manifests_dir"] / self.settings.phase_stage_name
            equipment_stage_path = workspace["manifests_dir"] / self.settings.equipment_stage_name
            override_stage_path = workspace["manifests_dir"] / self.settings.override_stage_name
            manifest_json_path = workspace["manifests_dir"] / self.settings.manifest_name

            common_phase_ids = [record.equipment_id for record in equipment_records if record.source_scope == "common"]
            phase_rows = [ResearchPhaseRecord(COMMON_PHASE_NUMBER, COMMON_PHASE_NAME, common_phase_ids).to_row()]
            phase_rows.extend(item.to_row() for item in phase_records)

            write_csv(phase_stage_path, phase_rows, CSV_PHASE_FIELDNAMES)
            write_csv(equipment_stage_path, [item.to_row() for item in equipment_records], CSV_EQUIPMENT_FIELDNAMES)
            write_csv(override_stage_path, override_rows, CSV_OVERRIDE_FIELDNAMES)
            if progress_callback is not None:
                progress_callback(90, "科研 stage CSV 写入完成，正在生成 manifest。", str(workspace["manifests_dir"]))

            result = ResearchCrawlerResult(
                workspace_dir=workspace["run_dir"],
                raw_html_path=raw_html_path,
                phase_stage_path=phase_stage_path,
                equipment_stage_path=equipment_stage_path,
                override_stage_path=override_stage_path,
                manifest_json_path=manifest_json_path,
                common_records=[item for item in equipment_records if item.source_scope == "common"],
                phase_records=phase_records,
                override_rows=override_rows,
                warnings=parse_warnings + limit_warnings,
                mode="sample" if (self.settings.phase_limit is not None or self.settings.common_limit is not None) else "full",
            )

            write_json(manifest_json_path, result.to_manifest())
            self.logger.info(
                f"科研爬虫完成: 解析{result.parsed_phase_count}期, 通用{result.common_equipment_count}件, 总计{result.total_equipment_count}件, 工作区:{result.workspace_dir}"
            )
            if progress_callback is not None:
                progress_callback(100, "科研爬虫完成。", f"工作区={result.workspace_dir}")
            return result
        finally:
            self.settings = original_settings

    def crawl_sample(
        self,
        phase_limit: Optional[int] = None,
        common_limit: Optional[int] = None,
        workspace_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str, str], object]] = None,
    ) -> ResearchCrawlerResult:
        """执行小规模科研爬虫。"""
        return self.crawl_stage(
            phase_limit=phase_limit,
            common_limit=common_limit,
            workspace_name=workspace_name,
            progress_callback=progress_callback,
        )

    def crawl_all(
        self,
        workspace_name: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str, str], object]] = None,
    ) -> ResearchCrawlerResult:
        """执行全量科研爬虫。"""
        return self.crawl_stage(workspace_name=workspace_name, progress_callback=progress_callback)


def get_research_crawler(
    config_data: Optional[Dict[str, Any]] = None,
    workspace_root: Optional[Path] = None,
    session: Optional[Session] = None,
) -> ResearchCrawler:
    """获取一个方便直接使用的科研爬虫实例。"""
    return ResearchCrawler(config_data=config_data, workspace_root=workspace_root, session=session)


def main() -> int:
    """模块入口。"""
    crawler = get_research_crawler()
    result = crawler.crawl_sample()
    print(f"crawl done: {result.parsed_phase_count} phases")
    print(f"workspace: {result.workspace_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
