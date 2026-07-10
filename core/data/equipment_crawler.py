#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║                🕸️ 装备图鉴爬虫 (EquipmentCrawler)                ║
║                                                                  ║
║   【一句话解释】                                                 ║
║   从碧蓝航线 Wiki 的装备图鉴页抓取装备条目、下载图片，并把      ║
║   结果写入独立的临时工作区，避免污染正式 data/。                 ║
║                                                                  ║
║   【类比理解】                                                   ║
║   它像一个“临时资料员”。先把网页里的装备信息抄下来，           ║
║   再把图片和清单分门别类放进独立文件夹，最后交给后续导入流程。 ║
║                                                                  ║
║   【数据存储位置】                                               ║
║   workdir/crawler/runs/<timestamp>/                               ║
║   ├── raw/                                                       ║
║   ├── images/common|rare|elite|super_rare|ultra_rare/            ║
║   └── manifests/                                                 ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ..utils.config_loader import get_config_loader
from ..utils.logger import get_logger
from ..utils.path_manager import PathManager
from .equipment_manager import EquipmentManager, get_equipment_manager


# ============================================================
# 🧩 第一部分：默认配置与常量
# ============================================================

DEFAULT_SOURCE_URL = "https://wiki.biligame.com/blhx/%E8%A3%85%E5%A4%87%E5%9B%BE%E9%89%B4"
DEFAULT_SAMPLE_SIZE_PER_RARITY = {
    "白色": 4,
    "蓝色": 4,
    "紫色": 4,
    "金色": 4,
    "彩色": 4,
}
DEFAULT_RARITY_FOLDER_MAP = {
    "白色": "common",
    "蓝色": "rare",
    "紫色": "elite",
    "金色": "super_rare",
    "彩色": "ultra_rare",
}
DEFAULT_RARITY_ID_MAP = {
    "白色": 1,
    "蓝色": 2,
    "紫色": 3,
    "金色": 4,
    "彩色": 5,
}
DEFAULT_RARITY_ORDER = ("白色", "蓝色", "紫色", "金色", "彩色")
DEFAULT_EXCLUDE_KEYWORDS = ("特殊兵装",)
DEFAULT_TIMEOUT = (10.0, 30.0)
DEFAULT_USER_AGENT = "AzurLaneResearchTrackerCrawler/0.5.0"
DEFAULT_IMAGE_DOWNLOAD_WORKERS = 8
DEFAULT_IMAGE_DOWNLOAD_DELAY_SECONDS = 0.05

CSV_LIBRARY_FIELDNAMES = [
    "equipment_id",
    "name",
    "rarity_id",
    "type",
]
CSV_IMAGE_FIELDNAMES = [
    "equipment_id",
    "image_path",
]


# ============================================================
# 🧾 第二部分：数据结构
# ============================================================


@dataclass(frozen=True)
class CrawlerSettings:
    """爬虫运行参数。

    Args:
        source_url: 装备图鉴页地址。
        sample_size_per_rarity: 每种稀有度保留多少个样本。
        rarity_folder_map: 稀有度中文 -> 英文文件夹名。
        rarity_id_map: 稀有度中文 -> 现有系统里的 rarity_id。
        exclude_keywords: 需要排除的关键词。
        rarity_order: 输出顺序。
        timeout: 单次请求的连接/读取超时。
        retry_total: 重试次数。
        backoff_factor: 重试退避系数。
        request_delay_seconds: 请求之间的礼貌等待时间。
        user_agent: 默认 User-Agent。
        referer: 图片下载时附带的来源页。
    """

    source_url: str = DEFAULT_SOURCE_URL
    sample_size_per_rarity: Dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_SAMPLE_SIZE_PER_RARITY)
    )
    rarity_folder_map: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_RARITY_FOLDER_MAP)
    )
    rarity_id_map: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_RARITY_ID_MAP))
    rarity_order: Tuple[str, ...] = DEFAULT_RARITY_ORDER
    exclude_keywords: Tuple[str, ...] = DEFAULT_EXCLUDE_KEYWORDS
    timeout: Tuple[float, float] = DEFAULT_TIMEOUT
    retry_total: int = 3
    retry_backoff_factor: float = 0.8
    request_delay_seconds: float = 1.0
    image_download_workers: int = DEFAULT_IMAGE_DOWNLOAD_WORKERS
    image_download_delay_seconds: float = DEFAULT_IMAGE_DOWNLOAD_DELAY_SECONDS
    user_agent: str = DEFAULT_USER_AGENT
    referer: str = DEFAULT_SOURCE_URL
    workspace_base_dir: str = "workdir/crawler"
    runs_dir_name: str = "runs"
    raw_dir_name: str = "raw"
    manifests_dir_name: str = "manifests"
    images_dir_name: str = "images"

    @classmethod
    def from_mapping(cls, payload: Optional[Dict[str, Any]] = None) -> "CrawlerSettings":
        """从 JSON 配置字典构建设置对象。"""
        data = payload or {}
        request_cfg = data.get("request", {})
        workspace_cfg = data.get("workspace", {})
        image_cfg = data.get("image", {})

        sample_map = dict(DEFAULT_SAMPLE_SIZE_PER_RARITY)
        sample_map.update({str(key): int(value) for key, value in data.get("sample_size_per_rarity", {}).items()})

        folder_map = dict(DEFAULT_RARITY_FOLDER_MAP)
        folder_map.update({str(key): str(value) for key, value in data.get("rarity_folder_map", {}).items()})

        rarity_id_map = dict(DEFAULT_RARITY_ID_MAP)
        rarity_id_map.update({str(key): int(value) for key, value in data.get("rarity_id_map", {}).items()})

        rarity_order = tuple(data.get("rarity_order", list(DEFAULT_RARITY_ORDER)))
        exclude_keywords = tuple(data.get("exclude_keywords", list(DEFAULT_EXCLUDE_KEYWORDS)))
        timeout_value = request_cfg.get("timeout", list(DEFAULT_TIMEOUT))
        timeout = (float(timeout_value[0]), float(timeout_value[1]))

        return cls(
            source_url=str(data.get("source_url", DEFAULT_SOURCE_URL)),
            sample_size_per_rarity=sample_map,
            rarity_folder_map=folder_map,
            rarity_id_map=rarity_id_map,
            rarity_order=rarity_order,
            exclude_keywords=exclude_keywords,
            timeout=timeout,
            retry_total=int(request_cfg.get("retry_total", 3)),
            retry_backoff_factor=float(request_cfg.get("backoff_factor", 0.8)),
            request_delay_seconds=float(request_cfg.get("delay_seconds", 1.0)),
            image_download_workers=max(1, int(image_cfg.get("download_workers", DEFAULT_IMAGE_DOWNLOAD_WORKERS))),
            image_download_delay_seconds=max(
                0.0,
                float(image_cfg.get("delay_seconds", DEFAULT_IMAGE_DOWNLOAD_DELAY_SECONDS)),
            ),
            user_agent=str(request_cfg.get("user_agent", DEFAULT_USER_AGENT)),
            referer=str(image_cfg.get("referer", data.get("source_url", DEFAULT_SOURCE_URL))),
            workspace_base_dir=str(workspace_cfg.get("base_dir", "workdir/crawler")),
            runs_dir_name=str(workspace_cfg.get("runs_dir_name", "runs")),
            raw_dir_name=str(workspace_cfg.get("raw_dir_name", "raw")),
            manifests_dir_name=str(workspace_cfg.get("manifests_dir_name", "manifests")),
            images_dir_name=str(workspace_cfg.get("images_dir_name", "images")),
        )

    def sample_size_for(self, rarity_name: str, override: Optional[Dict[str, int]] = None) -> int:
        """读取某个稀有度的样本数量。"""
        source = dict(self.sample_size_per_rarity)
        if override:
            source.update({str(key): int(value) for key, value in override.items()})
        return int(source.get(rarity_name, 0))


@dataclass(frozen=True)
class EquipmentCard:
    """抓取到的一条装备条目。"""

    crawl_id: str
    name: str
    rarity_name: str
    rarity_id: int
    rarity_folder: str
    equipment_type: str
    source_url: str
    image_url: str
    page_order: int
    ship_classes: str = ""

    def to_compact_dict(self) -> Dict[str, Any]:
        """导出给 manifest 的精简字典，避免保存过程性字段。"""
        return {
            "crawl_id": self.crawl_id,
            "name": self.name,
            "rarity_name": self.rarity_name,
            "rarity_id": self.rarity_id,
            "rarity_folder": self.rarity_folder,
            "equipment_type": self.equipment_type,
            "source_url": self.source_url,
            "image_url": self.image_url,
        }

    def to_library_row(self) -> Dict[str, Any]:
        """导出为项目正式装备表风格的阶段性清单。"""
        return {
            "equipment_id": self.crawl_id,
            "name": self.name,
            "rarity_id": self.rarity_id,
            "type": self.equipment_type,
        }


@dataclass(frozen=True)
class CrawlerResult:
    """一次抓取运行的最终结果。"""

    workspace_dir: Path
    raw_html_path: Path
    library_csv_path: Path
    images_csv_path: Path
    manifest_json_path: Path
    selected_cards: List[EquipmentCard]
    image_paths: List[Path]
    counts_by_rarity: Dict[str, int]
    warnings: List[str]

    @property
    def selected_count(self) -> int:
        """已保留的样本数量。"""
        return len(self.selected_cards)

    def to_manifest(self) -> Dict[str, Any]:
        """把结果整理成可写入 JSON 的字典。"""
        return {
            "workspace_dir": str(self.workspace_dir),
            "library_csv_path": str(self.library_csv_path),
            "images_csv_path": str(self.images_csv_path),
            "selected_count": self.selected_count,
            "counts_by_rarity": self.counts_by_rarity,
            "warnings": list(self.warnings),
        }


# ============================================================
# 🧰 第三部分：辅助函数
# ============================================================


def build_default_crawler_config() -> Dict[str, Any]:
    """返回可直接保存到 JSON 的默认爬虫配置。"""
    return {
        "source_url": DEFAULT_SOURCE_URL,
        "sample_size_per_rarity": dict(DEFAULT_SAMPLE_SIZE_PER_RARITY),
        "rarity_folder_map": dict(DEFAULT_RARITY_FOLDER_MAP),
        "rarity_id_map": dict(DEFAULT_RARITY_ID_MAP),
        "rarity_order": list(DEFAULT_RARITY_ORDER),
        "exclude_keywords": list(DEFAULT_EXCLUDE_KEYWORDS),
        "request": {
            "timeout": list(DEFAULT_TIMEOUT),
            "retry_total": 3,
            "backoff_factor": 0.8,
            "delay_seconds": 1.0,
            "user_agent": DEFAULT_USER_AGENT,
        },
        "image": {
            "referer": DEFAULT_SOURCE_URL,
            "download_workers": DEFAULT_IMAGE_DOWNLOAD_WORKERS,
            "delay_seconds": DEFAULT_IMAGE_DOWNLOAD_DELAY_SECONDS,
        },
        "workspace": {
            "base_dir": "workdir/crawler",
            "runs_dir_name": "runs",
            "raw_dir_name": "raw",
            "manifests_dir_name": "manifests",
            "images_dir_name": "images",
        },
    }


def load_crawler_config() -> Dict[str, Any]:
    """从仓库配置中读取爬虫配置，缺失时回退到默认值。"""
    loader = get_config_loader()
    config = loader.get_config("crawler", "equipment_crawler")
    if config:
        return config
    return build_default_crawler_config()


def _sanitize_text(value: str) -> str:
    """把网页文本清理成适合存档的格式。"""
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    cleaned = cleaned.replace("\u3000", " ")
    return cleaned


def _clean_equipment_name(value: str) -> str:
    cleaned = _sanitize_text(value)
    cleaned = re.sub(r"^[\s,，。;；:：、{}【】\[\]（）()<>《》]+", "", cleaned)
    cleaned = re.sub(r"[\s,，。;；:：、{}【】\[\]（）()<>《》]+$", "", cleaned)
    return cleaned


def _pick_best_srcset_url(srcset: str) -> Optional[str]:
    """从 srcset 中挑出分辨率最高的图片地址。"""
    candidates: List[Tuple[float, str]] = []
    for entry in srcset.split(","):
        chunk = entry.strip()
        if not chunk:
            continue
        parts = chunk.split()
        if len(parts) == 1:
            candidates.append((0.0, parts[0]))
            continue
        url_part = parts[0]
        descriptor = parts[-1]
        score = 0.0
        if descriptor.endswith("x"):
            try:
                score = float(descriptor[:-1])
            except ValueError:
                score = 0.0
        elif descriptor.endswith("w"):
            try:
                score = float(descriptor[:-1])
            except ValueError:
                score = 0.0
        candidates.append((score, url_part))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def resolve_image_url(image_tag: Any, base_url: str) -> Optional[str]:
    """从 `<img>` 标签中解析出最高质量的图片链接。"""
    if image_tag is None:
        return None
    srcset = image_tag.get("srcset", "")
    if srcset:
        best_url = _pick_best_srcset_url(srcset)
        if best_url:
            return urljoin(base_url, best_url)
    src = image_tag.get("src") or image_tag.get("data-src")
    if not src:
        return None
    return urljoin(base_url, src)


def extract_equipment_cards(html: str, settings: CrawlerSettings) -> List[EquipmentCard]:
    """从图鉴页 HTML 中提取装备条目。"""
    soup = BeautifulSoup(html, "html.parser")
    cards: List[EquipmentCard] = []
    seen_urls: set[str] = set()

    for page_order, container in enumerate(soup.select("div.divsort"), start=1):
        rarity_name = _sanitize_text(container.get("data-param3", ""))
        equipment_type = _sanitize_text(container.get("data-param1", ""))
        if not rarity_name or rarity_name not in settings.rarity_id_map:
            continue
        if equipment_type == "特殊兵装":
            continue

        raw_text = _sanitize_text(container.get_text(" ", strip=True))
        if any(keyword and keyword in raw_text for keyword in settings.exclude_keywords):
            continue

        anchors = container.find_all("a", href=True)
        image_tag = container.find("img")
        if not anchors or image_tag is None:
            continue

        anchor = anchors[0]
        source_url = urljoin(settings.source_url, anchor.get("href", ""))
        if not source_url or source_url in seen_urls:
            continue
        seen_urls.add(source_url)

        image_url = resolve_image_url(image_tag, settings.source_url)
        if not image_url:
            continue

        title_text = ""
        name_text = ""
        for candidate in anchors:
            candidate_title = _clean_equipment_name(candidate.get("title", ""))
            if candidate_title:
                title_text = candidate_title
                break
        if not title_text:
            for candidate in anchors:
                candidate_text = _clean_equipment_name(candidate.get_text(" ", strip=True))
                if candidate_text:
                    name_text = candidate_text
                    break
        else:
            name_text = title_text
        if not name_text:
            continue

        cards.append(
            EquipmentCard(
                crawl_id="",
                name=name_text,
                rarity_name=rarity_name,
                rarity_id=int(settings.rarity_id_map[rarity_name]),
                rarity_folder=settings.rarity_folder_map.get(rarity_name, "unknown"),
                equipment_type=equipment_type,
                source_url=source_url,
                image_url=image_url,
                page_order=page_order,
                ship_classes=_sanitize_text(container.get("data-param2", "")),
            )
        )

    return cards


def select_sample_cards(
    cards: Sequence[EquipmentCard],
    settings: CrawlerSettings,
    sample_size_override: Optional[Dict[str, int]] = None,
) -> List[EquipmentCard]:
    """按稀有度对装备做分层抽样。"""
    grouped: Dict[str, List[EquipmentCard]] = {}
    for card in cards:
        grouped.setdefault(card.rarity_name, []).append(card)

    selected: List[EquipmentCard] = []
    for rarity_name in settings.rarity_order:
        limit = settings.sample_size_for(rarity_name, sample_size_override)
        if limit <= 0:
            continue
        selected.extend(grouped.get(rarity_name, [])[:limit])
    return selected


def assign_crawl_ids(cards: Sequence[EquipmentCard]) -> List[EquipmentCard]:
    """给抽样后的装备条目分配项目风格的 ID。"""
    equipment_manager = get_equipment_manager()
    known_ids = {
        str(item.get("name", "")).strip(): str(item.get("equipment_id", "")).strip()
        for item in equipment_manager.get_all()
        if str(item.get("name", "")).strip() and str(item.get("equipment_id", "")).strip()
    }
    seed_general_id = equipment_manager._generate_id(False)
    next_general_number = int(seed_general_id[1:]) if seed_general_id.startswith("G") and seed_general_id[1:].isdigit() else 1

    output: List[EquipmentCard] = []
    for card in cards:
        equipment_id = known_ids.get(card.name)
        if not equipment_id:
            equipment_id = f"G{next_general_number:04d}"
            next_general_number += 1
            known_ids[card.name] = equipment_id
        output.append(replace(card, crawl_id=equipment_id))
    return output


def _ensure_parent_dir(file_path: Path) -> None:
    """确保目标文件上级目录存在。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)


def write_csv(file_path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> Path:
    """把行数据写成 UTF-8-SIG 编码的 CSV。"""
    _ensure_parent_dir(file_path)
    with open(file_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return file_path


def write_json(file_path: Path, payload: Dict[str, Any]) -> Path:
    """把字典写成 JSON 文件。"""
    _ensure_parent_dir(file_path)
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return file_path


def _relative_path_text(file_path: Path) -> str:
    """把文件路径转换成相对项目根目录的文本。"""
    project_root = PathManager.get_project_root()
    try:
        return file_path.relative_to(project_root).as_posix()
    except ValueError:
        return file_path.as_posix()


# ============================================================
# 🏗️ 第四部分：核心爬虫
# ============================================================


class EquipmentCrawler:
    """装备图鉴爬虫。

    这个类只负责第一阶段的装备图鉴抓取：
    - 从 wiki 页面解析装备条目
    - 按稀有度抽样
    - 下载图片
    - 写入独立工作区
    """

    def __init__(
        self,
        config_data: Optional[Dict[str, Any]] = None,
        workspace_root: Optional[Path] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.logger = get_logger()
        self.settings = CrawlerSettings.from_mapping(config_data or load_crawler_config())
        default_workspace = PathManager.get_project_root() / self.settings.workspace_base_dir / self.settings.runs_dir_name
        default_workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_root = workspace_root or default_workspace
        self.session = session or self._build_session()
        self._image_session_local = threading.local()
        self._image_cache_lock = threading.Lock()
        self._page_cache: Dict[str, str] = {}
        self._image_cache: Dict[str, bytes] = {}

    def _build_session(self) -> Session:
        """构建带重试和默认头部的 HTTP 会话。"""
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": self.settings.referer,
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

    def _get_image_session(self) -> Session:
        """为图片下载线程获取独立的会话，避免共享 Session 的线程安全问题。"""
        cached_session = getattr(self._image_session_local, "session", None)
        if cached_session is None:
            cached_session = self._build_session()
            self._image_session_local.session = cached_session
        return cached_session

    @property
    def timeout(self) -> Tuple[float, float]:
        """请求超时配置。"""
        return self.settings.timeout

    def fetch_page_html(self) -> str:
        """抓取装备图鉴页 HTML。"""
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
        """创建本次运行的独立目录结构。"""
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
        errors_dir = run_dir / "errors"
        images_dir = run_dir / self.settings.images_dir_name

        for path in (raw_dir, manifests_dir, logs_dir, errors_dir, images_dir):
            path.mkdir(parents=True, exist_ok=True)

        for folder_name in self.settings.rarity_folder_map.values():
            (images_dir / folder_name).mkdir(parents=True, exist_ok=True)

        return {
            "run_dir": run_dir,
            "raw_dir": raw_dir,
            "manifests_dir": manifests_dir,
            "logs_dir": logs_dir,
            "errors_dir": errors_dir,
            "images_dir": images_dir,
        }

    def download_image(self, image_url: str, destination: Path) -> Path:
        """下载装备图片到目标路径。"""
        return self._download_image_with_session(self.session, image_url, destination)

    def _download_image_with_session(self, session: Session, image_url: str, destination: Path) -> Path:
        """执行单张图片下载并把结果写入目标文件。"""
        _ensure_parent_dir(destination)
        with self._image_cache_lock:
            cached_bytes = self._image_cache.get(image_url)
        if cached_bytes is not None:
            destination.write_bytes(cached_bytes)
            return destination

        response = session.get(
            image_url,
            timeout=self.timeout,
            headers={"Referer": self.settings.referer},
        )
        response.raise_for_status()
        content = response.content
        with self._image_cache_lock:
            self._image_cache[image_url] = content
        destination.write_bytes(content)
        time.sleep(self.settings.image_download_delay_seconds)
        return destination

    def _download_image_task(self, image_url: str, destination: Path) -> Path:
        """并行下载时的线程任务入口。"""
        return self._download_image_with_session(self._get_image_session(), image_url, destination)

    def _download_images(self, download_plan: Sequence[Tuple[EquipmentCard, Path]]) -> List[Path]:
        """按配置并行下载图片，并保持输出顺序与输入一致。"""
        if not download_plan:
            return []

        if self.settings.image_download_workers <= 1 or len(download_plan) == 1:
            return [self.download_image(card.image_url, destination) for card, destination in download_plan]

        results: Dict[int, Path] = {}
        with ThreadPoolExecutor(
            max_workers=self.settings.image_download_workers,
            thread_name_prefix="equipment-crawler",
        ) as executor:
            future_map = {
                executor.submit(self._download_image_task, card.image_url, destination): index
                for index, (card, destination) in enumerate(download_plan)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                results[index] = future.result()

        return [results[index] for index in range(len(download_plan))]

    def _build_library_rows(self, cards: Sequence[EquipmentCard]) -> List[Dict[str, Any]]:
        """把装备条目整理为装备库 CSV 行。"""
        return [card.to_library_row() for card in cards]

    def _build_image_rows(self, cards: Sequence[EquipmentCard], image_paths: Sequence[Path]) -> List[Dict[str, Any]]:
        """把装备条目整理为图片映射 CSV 行。"""
        rows: List[Dict[str, Any]] = []
        for card, image_path in zip(cards, image_paths):
            rows.append(
                {
                    "equipment_id": card.crawl_id,
                    "image_path": _relative_path_text(image_path),
                }
            )
        return rows

    def crawl_sample(
        self,
        sample_size_override: Optional[Dict[str, int]] = None,
        workspace_name: Optional[str] = None,
    ) -> CrawlerResult:
        """执行一次小批量抓取，返回所有落盘路径和样本信息。"""
        html = self.fetch_page_html()
        workspace = self._prepare_workspace(workspace_name)
        raw_html_path = workspace["raw_dir"] / "equipment_atlas.html"
        raw_html_path.write_text(html, encoding="utf-8")

        cards = extract_equipment_cards(html, self.settings)
        sampled_cards = select_sample_cards(cards, self.settings, sample_size_override)
        sampled_cards = assign_crawl_ids(sampled_cards)

        download_plan: List[Tuple[EquipmentCard, Path]] = []
        for card in sampled_cards:
            rarity_folder = self.settings.rarity_folder_map.get(card.rarity_name, "unknown")
            file_suffix = Path(urlparse(card.image_url).path).suffix.lower() or ".jpg"
            if file_suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                file_suffix = ".jpg"
            destination = workspace["images_dir"] / rarity_folder / f"{card.crawl_id}{file_suffix}"
            download_plan.append((card, destination))

        image_paths = self._download_images(download_plan)

        library_rows = self._build_library_rows(sampled_cards)
        image_rows = self._build_image_rows(sampled_cards, image_paths)

        library_csv_path = workspace["manifests_dir"] / "equipment_library_stage.csv"
        images_csv_path = workspace["manifests_dir"] / "equipment_images_stage.csv"
        manifest_json_path = workspace["manifests_dir"] / "crawl_manifest.json"

        write_csv(library_csv_path, library_rows, CSV_LIBRARY_FIELDNAMES)
        write_csv(images_csv_path, image_rows, CSV_IMAGE_FIELDNAMES)

        counts_by_rarity: Dict[str, int] = {}
        for card in sampled_cards:
            counts_by_rarity[card.rarity_name] = counts_by_rarity.get(card.rarity_name, 0) + 1

        result = CrawlerResult(
            workspace_dir=workspace["run_dir"],
            raw_html_path=raw_html_path,
            library_csv_path=library_csv_path,
            images_csv_path=images_csv_path,
            manifest_json_path=manifest_json_path,
            selected_cards=sampled_cards,
            image_paths=image_paths,
            counts_by_rarity=counts_by_rarity,
            warnings=[],
        )

        write_json(
            manifest_json_path,
            result.to_manifest()
            | {
                "source_url": self.settings.source_url,
                "mode": "sample",
                "selected_card_names": [card.name for card in sampled_cards[:20]],
            },
        )

        self.logger.info(
            f"爬虫完成: 共解析{len(cards)}条, 抽样{result.selected_count}条, 工作区={result.workspace_dir}"
        )
        return result


    def _mirror_all_images(self, cards: Sequence[EquipmentCard], image_paths: Sequence[Path]) -> Path:
        """把本次下载的图片复制到 workdir/all_imgs，方便快速目检。"""
        all_imgs_dir = PathManager.get_work_dir() / "all_imgs"
        all_imgs_dir.mkdir(parents=True, exist_ok=True)
        for card, image_path in zip(cards, image_paths):
            rarity_folder = self.settings.rarity_folder_map.get(card.rarity_name, "unknown")
            target_dir = all_imgs_dir / rarity_folder
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_path, target_dir / image_path.name)
        return all_imgs_dir

    def crawl_all(self, workspace_name: Optional[str] = None) -> CrawlerResult:
        """执行全量装备抓取。"""
        html = self.fetch_page_html()
        workspace = self._prepare_workspace(workspace_name)
        raw_html_path = workspace["raw_dir"] / "equipment_atlas.html"
        raw_html_path.write_text(html, encoding="utf-8")

        cards = extract_equipment_cards(html, self.settings)
        sampled_cards = assign_crawl_ids(cards)

        download_plan: List[Tuple[EquipmentCard, Path]] = []
        for card in sampled_cards:
            rarity_folder = self.settings.rarity_folder_map.get(card.rarity_name, "unknown")
            file_suffix = Path(urlparse(card.image_url).path).suffix.lower() or ".jpg"
            if file_suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                file_suffix = ".jpg"
            destination = workspace["images_dir"] / rarity_folder / f"{card.crawl_id}{file_suffix}"
            download_plan.append((card, destination))

        image_paths = self._download_images(download_plan)
        mirror_dir = self._mirror_all_images(sampled_cards, image_paths)

        library_rows = self._build_library_rows(sampled_cards)
        image_rows = self._build_image_rows(sampled_cards, image_paths)

        library_csv_path = workspace["manifests_dir"] / "equipment_library_stage.csv"
        images_csv_path = workspace["manifests_dir"] / "equipment_images_stage.csv"
        manifest_json_path = workspace["manifests_dir"] / "crawl_manifest.json"

        write_csv(library_csv_path, library_rows, CSV_LIBRARY_FIELDNAMES)
        write_csv(images_csv_path, image_rows, CSV_IMAGE_FIELDNAMES)

        counts_by_rarity: Dict[str, int] = {}
        for card in sampled_cards:
            counts_by_rarity[card.rarity_name] = counts_by_rarity.get(card.rarity_name, 0) + 1

        result = CrawlerResult(
            workspace_dir=workspace["run_dir"],
            raw_html_path=raw_html_path,
            library_csv_path=library_csv_path,
            images_csv_path=images_csv_path,
            manifest_json_path=manifest_json_path,
            selected_cards=sampled_cards,
            image_paths=image_paths,
            counts_by_rarity=counts_by_rarity,
            warnings=[],
        )

        write_json(
            manifest_json_path,
            result.to_manifest()
            | {
                "source_url": self.settings.source_url,
                "mode": "all",
                "mirror_dir": str(mirror_dir),
                "selected_card_names": [card.name for card in sampled_cards[:20]],
            },
        )

        self.logger.info(
            f"full crawl completed: parsed={len(cards)}, downloaded={result.selected_count}, workspace={result.workspace_dir}, mirror={mirror_dir}"
        )
        return result


def get_equipment_crawler(
    config_data: Optional[Dict[str, Any]] = None,
    workspace_root: Optional[Path] = None,
    session: Optional[Session] = None,
) -> EquipmentCrawler:
    """获取一个方便直接使用的爬虫实例。"""
    return EquipmentCrawler(config_data=config_data, workspace_root=workspace_root, session=session)


def main() -> int:
    """模块入口，方便手工试跑。"""
    crawler = get_equipment_crawler()
    result = crawler.crawl_sample()
    print(f"爬虫完成: {result.selected_count} 条样本")
    print(f"工作区: {result.workspace_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
