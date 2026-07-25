#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🧭 Wiki 装备属性签名抓取与预填充实验工具              ║
║                                                              ║
║  【一句话解释】从碧蓝航线 Wiki 搬运装备初始属性，减少人工标注。║
║  【类比理解】像给识图模型配一本“装备说明书索引”。             ║
║  【数据流说明】equipment_library.csv + Wiki → wiki_out。      ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from bs4 import BeautifulSoup


# ============================================================
# 🧱 第二部分：常量与数据对象
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LIBRARY_CSV = PROJECT_ROOT / "data" / "equipment_library.csv"
DEFAULT_CACHE_DIR = SCRIPT_DIR / "wiki_cache"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "wiki_out"
DEFAULT_ATTRIBUTE_EXP = SCRIPT_DIR / "img_input" / "attribute_exp.txt"
DEFAULT_HUMAN_ARCHIVE_CSV = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "human_label_archive" / "master_human_labels.csv"

WIKI_BASE_URL = "https://wiki.biligame.com/blhx/"
USER_AGENT = "AzurLaneResearchTracker-OCR-lab/0.1 (+local cache; manual OCR labeling helper)"
DEFAULT_TARGET_SECONDS = 90.0

# 这些状态代表真的访问了网络；cache/cache_missing 不参与 90 秒配速。
NETWORK_FETCH_STATUSES = {"fetched", "http_error", "network_error", "page_missing"}

# Wiki 与本地装备库偶尔存在“消歧后缀”差异；这里记录已确认的安全别名。
MANUAL_WIKI_SLUG_ALIASES = {
    "彗星(轰炸机)#T3": ["彗星T3"],
    "彗星(轰炸机)#T2": ["彗星T2"],
}

# 只抓装备详情页里对设计图识别有用的字段；底部导航表即使出现同名字段，也会被过滤。
ATTRIBUTE_LABELS = {
    "伤害",
    "标准射速",
    "射速",
    "炮击",
    "航空",
    "雷装",
    "防空",
    "命中",
    "机动",
    "耐久",
    "反潜",
    "额外侦测范围",
    "弹药",
    "弹药射程",
    "伤害修正比例",
    "伤害属性类型",
    "技能",
    "描述",
}

PRIMARY_STAT_LABELS = ("炮击", "航空", "雷装", "防空", "命中", "机动", "耐久", "反潜")

CSV_FIELDNAMES = [
    "equipment_id",
    "equipment_name",
    "library_type",
    "rarity_id",
    "wiki_slug",
    "wiki_url",
    "wiki_page_title",
    "parse_status",
    "parse_message",
    "attribute_signature",
    "damage_initial",
    "fire_rate_initial",
    "stat_1_label",
    "stat_1_initial",
    "stat_2_label",
    "stat_2_initial",
    "stat_3_label",
    "stat_3_initial",
    "extra_detection_range",
    "ammo_type",
    "skill_name",
    "skill_description",
    "raw_attributes_json",
]


@dataclass(frozen=True)
class EquipmentLibraryRow:
    """
    装备库里的一行基础信息。

    输入：
        equipment_library.csv 的 equipment_id/name/rarity_id/type。
    输出：
        供 Wiki URL 构造和结果回填使用的稳定对象。
    使用示例：
        row = EquipmentLibraryRow("G0477", "基础声呐#T3", "3", "设备")
    """

    equipment_id: str
    equipment_name: str
    rarity_id: str = ""
    library_type: str = ""


@dataclass
class WikiAttributeSignature:
    """
    一件装备从 Wiki 解析出的“属性签名”。

    输入：
        Wiki HTML 页面。
    输出：
        结构化初始属性、技能、原始解析行和可用于相似装备重排的 signature。
    使用示例：
        sig = parse_wiki_equipment_page(html, row)
    """

    equipment_id: str
    equipment_name: str
    library_type: str = ""
    rarity_id: str = ""
    wiki_slug: str = ""
    wiki_url: str = ""
    wiki_page_title: str = ""
    parse_status: str = "parse_empty"
    parse_message: str = ""
    attributes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    raw_rows: List[List[str]] = field(default_factory=list)

    @property
    def damage_initial(self) -> str:
        """返回初始伤害，字段不存在时为空。"""
        return self.attributes.get("伤害", {}).get("初始", "")

    @property
    def fire_rate_initial(self) -> str:
        """返回初始射速，兼容 Wiki 的“标准射速/射速”两种写法。"""
        return self.attributes.get("标准射速", {}).get("初始", "") or self.attributes.get("射速", {}).get("初始", "")

    @property
    def extra_detection_range(self) -> str:
        """返回额外侦测范围；声呐设备常用。"""
        return self.attributes.get("额外侦测范围", {}).get("值", "")

    @property
    def ammo_type(self) -> str:
        """返回弹药类型；炮类装备常用。"""
        return self.attributes.get("弹药", {}).get("值", "")

    @property
    def skill_name(self) -> str:
        """返回技能名称；设备/特殊装备常用。"""
        return self.attributes.get("技能", {}).get("值", "")

    @property
    def skill_description(self) -> str:
        """返回技能描述，主要用于人工排查，不直接参与短字段匹配。"""
        return self.attributes.get("描述", {}).get("值", "")

    def primary_stats(self) -> List[Tuple[str, str]]:
        """
        返回按页面顺序解析到的主要数值属性。

        输入：
            self.attributes。
        输出：
            [(属性名, 初始值或值), ...]，最多由调用方截取前三个。
        使用示例：
            stats = sig.primary_stats()[:3]
        """
        stats: List[Tuple[str, str]] = []
        for label in PRIMARY_STAT_LABELS:
            value = self.attributes.get(label, {}).get("初始", "") or self.attributes.get(label, {}).get("值", "")
            if value:
                stats.append((label, value))
        return stats

    def attribute_signature(self) -> str:
        """
        构造短签名，供 OCR 结果和 Wiki 属性做二次比对。

        输入：
            已解析字段。
        输出：
            例如：伤害=17x4|标准射速=3.43s/轮|炮击=65|弹药=穿甲弹。
        使用示例：
            key = sig.attribute_signature()
        """
        parts: List[str] = []
        if self.damage_initial:
            parts.append(f"伤害={self.damage_initial}")
        if self.fire_rate_initial:
            parts.append(f"标准射速={self.fire_rate_initial}")
        for label, value in self.primary_stats()[:3]:
            parts.append(f"{label}={value}")
        if self.extra_detection_range:
            parts.append(f"额外侦测范围={self.extra_detection_range}")
        if self.ammo_type:
            parts.append(f"弹药={self.ammo_type}")
        if self.skill_name:
            parts.append(f"技能={self.skill_name}")
        return "|".join(parts)

    def to_row(self) -> Dict[str, str]:
        """
        转成 CSV/JSON 友好的扁平行。

        输入：
            WikiAttributeSignature。
        输出：
            Dict[str, str]。
        使用示例：
            writer.writerow(sig.to_row())
        """
        stats = self.primary_stats()
        padded_stats = stats[:3] + [("", "")] * (3 - len(stats[:3]))
        return {
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment_name,
            "library_type": self.library_type,
            "rarity_id": self.rarity_id,
            "wiki_slug": self.wiki_slug,
            "wiki_url": self.wiki_url,
            "wiki_page_title": self.wiki_page_title,
            "parse_status": self.parse_status,
            "parse_message": self.parse_message,
            "attribute_signature": self.attribute_signature(),
            "damage_initial": self.damage_initial,
            "fire_rate_initial": self.fire_rate_initial,
            "stat_1_label": padded_stats[0][0],
            "stat_1_initial": padded_stats[0][1],
            "stat_2_label": padded_stats[1][0],
            "stat_2_initial": padded_stats[1][1],
            "stat_3_label": padded_stats[2][0],
            "stat_3_initial": padded_stats[2][1],
            "extra_detection_range": self.extra_detection_range,
            "ammo_type": self.ammo_type,
            "skill_name": self.skill_name,
            "skill_description": self.skill_description,
            "raw_attributes_json": json.dumps(self.attributes, ensure_ascii=False, sort_keys=True),
        }


@dataclass(frozen=True)
class FetchResult:
    """
    Wiki HTML 获取结果。

    输入：
        URL、缓存路径和 HTTP 状态。
    输出：
        HTML 字符串与来源标记。
    使用示例：
        result = fetch_wiki_html("基础声呐T3", cache_dir)
    """

    html: str
    status: str
    message: str
    url: str
    cache_path: Path


# ============================================================
# 🧰 第三部分：名称规范化与装备库读取
# ============================================================

def normalize_text(value: str) -> str:
    """
    统一 Wiki/OCR 文本的空白和乘号。

    输入：
        原始文本。
    输出：
        去掉多余空白、把 × 统一成 x 的文本。
    使用示例：
        normalize_text("17×4") == "17x4"
    """
    text = str(value or "").replace("\xa0", " ").replace("×", "x")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_equipment_name(value: str) -> str:
    """
    规范化装备名称，但保留 #T0/#T1/#T2/#T3 层级。

    输入：
        用户标注名或装备库名称。
    输出：
        用于字典匹配的名称。
    使用示例：
        normalize_equipment_name(" 基础声呐 #T3 ")。
    """
    text = normalize_text(value)
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+#", "#", text)
    return text


def equipment_name_to_wiki_slug(equipment_name: str) -> str:
    """
    把装备库名称转换成 Wiki 页面 slug。

    输入：
        基础声呐#T3。
    输出：
        基础声呐T3。
    使用示例：
        equipment_name_to_wiki_slug("试作型四联装152mm主炮#T0")
    """
    slug = normalize_text(equipment_name)
    slug = slug.replace("#", "")
    return slug


def equipment_name_to_wiki_slug_candidates(equipment_name: str) -> List[str]:
    """
    为装备名生成 Wiki 页面候选 slug。

    输入：
        装备库名称。
    输出：
        按优先级排列的 Wiki slug 候选；第一个永远是直接转换结果。
    使用示例：
        equipment_name_to_wiki_slug_candidates("彗星(轰炸机)#T3")
    """
    raw_name = normalize_text(equipment_name)
    normalized_name = normalize_equipment_name(equipment_name)
    # Wiki 页面名对括号形态敏感；先保留原始全角/半角括号，再尝试规范化名称。
    candidates = [equipment_name_to_wiki_slug(raw_name), equipment_name_to_wiki_slug(normalized_name)]
    candidates.extend(MANUAL_WIKI_SLUG_ALIASES.get(normalized_name, []))

    # 本地库为了消歧可能写成“彗星(轰炸机)#T3”，但 Wiki 单装备页可能叫“彗星T3”。
    without_type_suffix = re.sub(r"\((轰炸机|鱼雷机|战斗机|设备)\)(#T[0-3])$", r"\2", normalized_name)
    if without_type_suffix != normalized_name:
        candidates.append(equipment_name_to_wiki_slug(without_type_suffix))

    unique_candidates: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)
    return unique_candidates


def load_equipment_library(library_csv: Path) -> List[EquipmentLibraryRow]:
    """
    读取装备库 CSV，不修改正式数据。

    输入：
        data/equipment_library.csv。
    输出：
        EquipmentLibraryRow 列表。
    使用示例：
        rows = load_equipment_library(Path("data/equipment_library.csv"))
    """
    rows: List[EquipmentLibraryRow] = []
    with library_csv.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            equipment_id = str(row.get("equipment_id", "") or "").strip()
            equipment_name = str(row.get("name", "") or "").strip()
            if not equipment_id or not equipment_name:
                continue
            rows.append(
                EquipmentLibraryRow(
                    equipment_id=equipment_id,
                    equipment_name=equipment_name,
                    rarity_id=str(row.get("rarity_id", "") or "").strip(),
                    library_type=str(row.get("type", "") or "").strip(),
                )
            )
    return rows


def load_names_from_human_archive(archive_csv: Path) -> List[str]:
    """
    从 v2 人工标注总档案读取已确认装备名。

    输入：
        master_human_labels.csv。
    输出：
        去重后的 accepted_equipment_name 列表，保持首次出现顺序。
    使用示例：
        names = load_names_from_human_archive(Path("master_human_labels.csv"))
    """
    if not archive_csv.exists():
        return []
    names: List[str] = []
    seen: set[str] = set()
    with archive_csv.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            name = normalize_equipment_name(str(row.get("accepted_equipment_name", "") or ""))
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


# ============================================================
# 🌐 第四部分：Wiki 抓取与缓存
# ============================================================

def build_wiki_url(slug: str) -> str:
    """
    构造 Wiki URL。

    输入：
        Wiki 页面 slug。
    输出：
        百分号编码后的完整 URL。
    使用示例：
        build_wiki_url("基础声呐T3")
    """
    return f"{WIKI_BASE_URL}{quote(slug, safe='')}"


def cache_path_for_slug(slug: str, cache_dir: Path) -> Path:
    """
    为 Wiki 页面生成稳定缓存路径。

    输入：
        slug 和缓存目录。
    输出：
        带哈希前缀的 html 文件路径，避免 Windows 特殊字符冲突。
    使用示例：
        cache_path_for_slug("基础声呐T3", Path("wiki_cache"))
    """
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:12]
    safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", slug, flags=re.UNICODE).strip("_") or "wiki_page"
    return cache_dir / f"{digest}_{safe_name}.html"


def fetch_wiki_html(
    slug: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    *,
    refresh: bool = False,
    cache_only: bool = False,
    timeout_seconds: float = 20.0,
    session: Optional[Any] = None,
) -> FetchResult:
    """
    获取 Wiki HTML，并优先使用本地缓存。

    输入：
        slug/cache_dir/refresh/cache_only。
    输出：
        FetchResult。
    使用示例：
        result = fetch_wiki_html("基础声呐T3")
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = build_wiki_url(slug)
    cache_path = cache_path_for_slug(slug, cache_dir)
    if cache_path.exists() and not refresh:
        return FetchResult(
            html=cache_path.read_text(encoding="utf-8", errors="replace"),
            status="cache",
            message="使用本地缓存。",
            url=url,
            cache_path=cache_path,
        )
    if cache_only:
        return FetchResult(html="", status="cache_missing", message="缓存不存在且启用 cache_only。", url=url, cache_path=cache_path)

    try:
        http = session if session is not None else create_requests_session()
        response = http.get(
            url,
            timeout=(5.0, timeout_seconds),
        )
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - 网络异常类型由 requests 决定，测试只验证上层状态。
        response = getattr(exc, "response", None)
        if response is not None:
            return FetchResult(
                html=getattr(response, "text", "") or "",
                status="page_missing" if response.status_code == 404 else "http_error",
                message=f"HTTP {response.status_code}",
                url=getattr(response, "url", url) or url,
                cache_path=cache_path,
            )
        return FetchResult(html="", status="network_error", message=str(exc), url=url, cache_path=cache_path)

    cache_path.write_text(response.text, encoding="utf-8")
    return FetchResult(html=response.text, status="fetched", message="已从 Wiki 获取并写入缓存。", url=response.url, cache_path=cache_path)


def fetch_wiki_html_with_candidates(
    slugs: Sequence[str],
    cache_dir: Path = DEFAULT_CACHE_DIR,
    *,
    refresh: bool = False,
    cache_only: bool = False,
    timeout_seconds: float = 20.0,
    session: Optional[Any] = None,
) -> FetchResult:
    """
    依次尝试多个 Wiki slug，解决本地名称与 Wiki 页面名不一致的问题。

    输入：
        slug 候选列表。
    输出：
        第一个成功结果；全部失败则返回最后一次结果。
    使用示例：
        fetch_wiki_html_with_candidates(["彗星(轰炸机)T3", "彗星T3"])
    """
    last_result: Optional[FetchResult] = None
    for slug in slugs:
        result = fetch_wiki_html(
            slug,
            cache_dir,
            refresh=refresh,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
            session=session,
        )
        if result.status in {"cache", "fetched"} and result.html:
            return result
        last_result = result
        # page_missing/cache_missing 才继续试别名；HTTP 567/网络错误通常是站点防护，继续撞也没意义。
        if result.status not in {"page_missing", "cache_missing"}:
            break
    return last_result or FetchResult(html="", status="cache_missing", message="没有可尝试的 Wiki slug。", url="", cache_path=cache_dir)


def create_requests_session() -> Any:
    """
    创建带连接复用、默认请求头和轻量重试的 Requests Session。

    输入：
        无。
    输出：
        requests.Session。
    使用示例：
        session = create_requests_session()
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Referer": "https://wiki.biligame.com/blhx/%E8%A3%85%E5%A4%87%E5%9B%BE%E9%89%B4",
        }
    )
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ============================================================
# 🔎 第五部分：Wiki HTML 解析
# ============================================================

def _clean_cells(cells: Iterable[Any]) -> List[str]:
    """把 BeautifulSoup 单元格转成干净文本。"""
    return [normalize_text(cell.get_text(" ", strip=True)) for cell in cells]


def _looks_like_navigation_value(value: str) -> bool:
    """过滤页面底部装备导航表，避免把“反潜 • XXX”误当属性。"""
    if not value:
        return True
    if "•" in value or "·" in value:
        return True
    if len(value) > 120:
        return True
    return False


def _extract_page_title(soup: BeautifulSoup) -> str:
    """从 h1 或 title 提取页面标题。"""
    h1 = soup.find("h1")
    if h1 is not None:
        title = normalize_text(h1.get_text(" ", strip=True))
        if title:
            return title
    title_tag = soup.find("title")
    title = normalize_text(title_tag.get_text(" ", strip=True)) if title_tag is not None else ""
    return title.split(" - ", 1)[0].strip()


def _first_row_label_from_li(li: Any) -> str:
    """
    从 Wiki 属性 li 的第一张表提取字段名。

    Wiki 装备页常见结构是：
        li: 表头=伤害
        next li: 初始=17x4 / 强化+10=30x4
    """
    table = li.find("table")
    if table is None:
        return ""
    row = table.find("tr")
    if row is None:
        return ""
    cells = _clean_cells(row.find_all(["th", "td"]))
    label = cells[0] if cells else ""
    return label if label in ATTRIBUTE_LABELS else ""


def _extract_initial_pairs_from_li(li: Any) -> Dict[str, str]:
    """从属性值 li 中提取 初始/强化+10 等键值。"""
    pairs: Dict[str, str] = {}
    for row in li.find_all("tr"):
        cells = _clean_cells(row.find_all(["th", "td"]))
        if len(cells) < 2:
            continue
        key = cells[0]
        value = cells[1]
        if key and value and not _looks_like_navigation_value(value):
            pairs[key] = value
    return pairs


def _merge_attribute(attributes: Dict[str, Dict[str, str]], label: str, values: Mapping[str, str]) -> None:
    """合并属性；先解析到的装备详情字段优先。"""
    if not label or not values:
        return
    current = attributes.setdefault(label, {})
    for key, value in values.items():
        if value and key not in current:
            current[key] = value


def parse_wiki_equipment_page(html: str, equipment: EquipmentLibraryRow, *, wiki_url: str = "") -> WikiAttributeSignature:
    """
    解析单个装备 Wiki 页面。

    输入：
        Wiki HTML、装备库行和可选 URL。
    输出：
        WikiAttributeSignature。
    使用示例：
        sig = parse_wiki_equipment_page(html, row, wiki_url=url)
    """
    slug = equipment_name_to_wiki_slug(equipment.equipment_name)
    signature = WikiAttributeSignature(
        equipment_id=equipment.equipment_id,
        equipment_name=equipment.equipment_name,
        library_type=equipment.library_type,
        rarity_id=equipment.rarity_id,
        wiki_slug=slug,
        wiki_url=wiki_url or build_wiki_url(slug),
    )
    if not html.strip():
        signature.parse_status = "parse_empty"
        signature.parse_message = "HTML 为空。"
        return signature

    soup = BeautifulSoup(html, "html.parser")
    signature.wiki_page_title = _extract_page_title(soup)
    attributes: Dict[str, Dict[str, str]] = {}
    raw_rows: List[List[str]] = []

    # 1) 解析“字段 li → 数值 li”的嵌套表，这是伤害/射速等初始值最可靠的位置。
    for li in soup.find_all("li"):
        label = _first_row_label_from_li(li)
        if not label:
            continue
        next_li = li.find_next_sibling("li")
        if next_li is None:
            continue
        pairs = _extract_initial_pairs_from_li(next_li)
        if pairs:
            raw_rows.append([label, *[f"{key}:{value}" for key, value in pairs.items()]])
            _merge_attribute(attributes, label, pairs)

    # 2) 解析直接两列表：炮击=65、弹药=穿甲弹、技能=xxx、描述=xxx 等。
    for row in soup.find_all("tr"):
        cells = _clean_cells(row.find_all(["th", "td"]))
        if len(cells) < 2:
            continue
        label = cells[0]
        value = cells[1]
        if label not in ATTRIBUTE_LABELS:
            continue
        if _looks_like_navigation_value(value):
            continue
        raw_rows.append(cells[:3])
        _merge_attribute(attributes, label, {"值": value})

    signature.attributes = attributes
    signature.raw_rows = raw_rows
    if signature.attribute_signature():
        signature.parse_status = "success"
        signature.parse_message = "已解析装备属性。"
    else:
        signature.parse_status = "parse_empty"
        signature.parse_message = "未解析到可用属性；可能页面结构特殊或不是装备详情页。"
    return signature


# ============================================================
# 🧾 第六部分：批量抓取与输出
# ============================================================

def filter_equipment_rows(
    rows: Sequence[EquipmentLibraryRow],
    requested_names: Sequence[str],
    limit: int = 0,
) -> List[EquipmentLibraryRow]:
    """
    按名称列表和 limit 过滤装备。

    输入：
        全量装备、用户指定名称、数量限制。
    输出：
        待抓取装备列表。
    使用示例：
        selected = filter_equipment_rows(rows, ["基础声呐#T3"], 0)
    """
    if requested_names:
        normalized = {normalize_equipment_name(name) for name in requested_names if normalize_equipment_name(name)}
        selected = [row for row in rows if normalize_equipment_name(row.equipment_name) in normalized]
    else:
        selected = list(rows)
    if limit > 0:
        selected = selected[:limit]
    return selected


def crawl_equipment_attributes(
    equipment_rows: Sequence[EquipmentLibraryRow],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    refresh: bool = False,
    cache_only: bool = False,
    sleep_seconds: float = 0.15,
    target_duration_seconds: float = 0.0,
    http_error_cooldown_seconds: float = 0.0,
    max_consecutive_http_errors: int = 0,
    fetcher: Optional[Callable[[str], FetchResult]] = None,
    sleep_func: Callable[[float], None] = time.sleep,
    monotonic_func: Callable[[], float] = time.monotonic,
) -> List[WikiAttributeSignature]:
    """
    批量抓取并解析 Wiki 装备属性。

    输入：
        待抓取装备列表和缓存/网络参数。
    输出：
        WikiAttributeSignature 列表。
    使用示例：
        signatures = crawl_equipment_attributes(rows[:10])
    """
    signatures: List[WikiAttributeSignature] = []
    consecutive_http_errors = 0
    network_plan_total = count_planned_network_fetches(equipment_rows, cache_dir, refresh, cache_only, fetcher)
    network_completed = 0
    started_at = monotonic_func()
    session = None if fetcher is not None or cache_only else create_requests_session()
    for index, equipment in enumerate(equipment_rows, start=1):
        slug_candidates = equipment_name_to_wiki_slug_candidates(equipment.equipment_name)
        slug = slug_candidates[0] if slug_candidates else equipment_name_to_wiki_slug(equipment.equipment_name)
        result = (
            fetcher(slug)
            if fetcher is not None
            else fetch_wiki_html_with_candidates(slug_candidates, cache_dir, refresh=refresh, cache_only=cache_only, session=session)
        )
        used_network = result.status in NETWORK_FETCH_STATUSES
        if result.html and result.status in {"cache", "fetched"}:
            signature = parse_wiki_equipment_page(result.html, equipment, wiki_url=result.url)
            # 成功时记录实际命中的 Wiki slug，方便追踪别名。
            for candidate in slug_candidates:
                if build_wiki_url(candidate) == result.url or cache_path_for_slug(candidate, cache_dir) == result.cache_path:
                    signature.wiki_slug = candidate
                    break
            if signature.parse_status == "success":
                signature.parse_message = f"{signature.parse_message} 来源={result.status}。"
            consecutive_http_errors = 0
        else:
            if result.status in {"http_error", "network_error"}:
                consecutive_http_errors += 1
            else:
                consecutive_http_errors = 0
            signature = WikiAttributeSignature(
                equipment_id=equipment.equipment_id,
                equipment_name=equipment.equipment_name,
                library_type=equipment.library_type,
                rarity_id=equipment.rarity_id,
                wiki_slug=slug,
                wiki_url=result.url,
                parse_status=result.status,
                parse_message=result.message,
            )
        signatures.append(signature)
        if used_network:
            network_completed += 1
        if max_consecutive_http_errors > 0 and consecutive_http_errors >= max_consecutive_http_errors:
            break
        if used_network and result.status == "http_error" and http_error_cooldown_seconds > 0:
            sleep_func(http_error_cooldown_seconds)
        if used_network and index < len(equipment_rows):
            sleep_for_pacing(
                network_completed=network_completed,
                network_total=network_plan_total,
                started_at=started_at,
                target_duration_seconds=target_duration_seconds,
                minimum_sleep_seconds=sleep_seconds,
                sleep_func=sleep_func,
                monotonic_func=monotonic_func,
            )
    return signatures


def count_planned_network_fetches(
    equipment_rows: Sequence[EquipmentLibraryRow],
    cache_dir: Path,
    refresh: bool,
    cache_only: bool,
    fetcher: Optional[Callable[[str], FetchResult]],
) -> int:
    """
    估算本轮需要真实联网的页数，供 90 秒配速使用。

    输入：
        待抓取装备、缓存目录和抓取模式。
    输出：
        预计网络请求数量。
    使用示例：
        total = count_planned_network_fetches(rows, cache_dir, False, False, None)
    """
    if cache_only:
        return 0
    if fetcher is not None or refresh:
        return len(equipment_rows)
    count = 0
    for equipment in equipment_rows:
        candidates = equipment_name_to_wiki_slug_candidates(equipment.equipment_name)
        if not any(cache_path_for_slug(slug, cache_dir).exists() for slug in candidates):
            count += 1
    return count


def sleep_for_pacing(
    *,
    network_completed: int,
    network_total: int,
    started_at: float,
    target_duration_seconds: float,
    minimum_sleep_seconds: float,
    sleep_func: Callable[[float], None] = time.sleep,
    monotonic_func: Callable[[], float] = time.monotonic,
) -> float:
    """
    根据目标总耗时动态睡眠。

    输入：
        已完成网络请求数、计划网络请求数、开始时间和目标总秒数。
    输出：
        实际计划睡眠秒数，便于测试。
    使用示例：
        delay = sleep_for_pacing(network_completed=1, network_total=10, target_duration_seconds=90)
    """
    if network_total <= 0:
        return 0.0
    delay = max(0.0, minimum_sleep_seconds)
    if target_duration_seconds > 0:
        expected_elapsed = target_duration_seconds * min(network_completed, network_total) / network_total
        actual_elapsed = monotonic_func() - started_at
        delay = max(delay, expected_elapsed - actual_elapsed)
    if delay > 0:
        sleep_func(delay)
    return delay


def write_signatures(signatures: Sequence[WikiAttributeSignature], output_dir: Path = DEFAULT_OUTPUT_DIR) -> Dict[str, Path]:
    """
    写出 Wiki 属性签名结果。

    输入：
        signatures 和输出目录。
    输出：
        关键输出文件路径。
    使用示例：
        paths = write_signatures(signatures, Path("wiki_out"))
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "wiki_equipment_attribute_signatures.csv"
    json_path = output_dir / "wiki_equipment_attribute_signatures.json"
    unresolved_path = output_dir / "wiki_attribute_unresolved.csv"
    summary_path = output_dir / "wiki_attribute_summary.json"

    rows = [signature.to_row() for signature in signatures]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    unresolved_rows = [row for row in rows if row["parse_status"] != "success"]
    with unresolved_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(unresolved_rows)

    summary = {
        "total": len(signatures),
        "success": sum(1 for item in signatures if item.parse_status == "success"),
        "unresolved": sum(1 for item in signatures if item.parse_status != "success"),
        "statuses": _count_statuses(signatures),
        "note": "该结果来自 Wiki 页面解析，用于 OCR 实验提示；未写入正式 CSV。",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "csv": csv_path,
        "json": json_path,
        "unresolved": unresolved_path,
        "summary": summary_path,
    }


def _count_statuses(signatures: Sequence[WikiAttributeSignature]) -> Dict[str, int]:
    """统计 parse_status 分布。"""
    counts: Dict[str, int] = {}
    for signature in signatures:
        counts[signature.parse_status] = counts.get(signature.parse_status, 0) + 1
    return counts


# ============================================================
# 🪄 第七部分：attribute_exp Wiki 提示生成
# ============================================================

def build_signature_index(signatures: Sequence[WikiAttributeSignature]) -> Dict[str, WikiAttributeSignature]:
    """
    按规范化装备名构建签名索引。

    输入：
        WikiAttributeSignature 列表。
    输出：
        normalized equipment_name → signature。
    使用示例：
        index = build_signature_index(signatures)
    """
    return {normalize_equipment_name(signature.equipment_name): signature for signature in signatures if signature.parse_status == "success"}


def build_attribute_exp_wiki_hints(exp_text: str, signature_index: Mapping[str, WikiAttributeSignature]) -> Tuple[str, int]:
    """
    给 attribute_exp 生成 Wiki 提示注释，不覆盖人工字段。

    输入：
        原始 attribute_exp 文本和 Wiki 签名索引。
    输出：
        (带 wiki_hint 的文本, 命中的卡片数)。
    使用示例：
        text, count = build_attribute_exp_wiki_hints(raw, index)
    """
    output_lines: List[str] = []
    current_card_key = ""
    hit_count = 0
    skip_old_hint = False
    for raw_line in exp_text.splitlines():
        line = raw_line.rstrip("\n")
        if re.match(r"^card_\d+\.equipment_name\s*:", line.strip()):
            prefix, name = line.split(":", 1)
            current_card_key = prefix.split(".", 1)[0]
            signature = signature_index.get(normalize_equipment_name(name))
            if signature is not None:
                hit_count += 1
                output_lines.append(f"# {current_card_key}.wiki_signature:{signature.attribute_signature()}")
                output_lines.append(f"# {current_card_key}.wiki_url:{signature.wiki_url}")
        if re.match(r"^# card_\d+\.wiki_(signature|url):", line.strip()):
            skip_old_hint = True
        else:
            skip_old_hint = False
        if not skip_old_hint:
            output_lines.append(line)
    return "\n".join(output_lines) + ("\n" if exp_text.endswith("\n") else ""), hit_count


def write_attribute_exp_hints(
    attribute_exp: Path,
    signatures: Sequence[WikiAttributeSignature],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Optional[Path]:
    """
    读取 attribute_exp 并写出 Wiki 提示版。

    输入：
        attribute_exp 路径和已抓取签名。
    输出：
        生成文件路径；如果原文件不存在则返回 None。
    使用示例：
        path = write_attribute_exp_hints(Path("attribute_exp.txt"), signatures)
    """
    if not attribute_exp.exists():
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_text = attribute_exp.read_text(encoding="utf-8-sig", errors="replace")
    hinted_text, hit_count = build_attribute_exp_wiki_hints(raw_text, build_signature_index(signatures))
    output_path = output_dir / "attribute_exp_wiki_hints.txt"
    header = (
        "# 该文件由 wiki_attribute_prefill.py 生成。\n"
        "# wiki_signature 只是机器提示，不会覆盖你的人工字段；正式标注仍以你填写的字段为准。\n"
        f"# wiki_hint_hit_cards:{hit_count}\n\n"
    )
    output_path.write_text(header + hinted_text, encoding="utf-8")
    return output_path


# ============================================================
# 🚪 第八部分：命令行入口
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        终端参数。
    输出：
        argparse.Namespace。
    使用示例：
        python wiki_attribute_prefill.py --sample
    """
    parser = argparse.ArgumentParser(description="从碧蓝航线 Wiki 抓取装备初始属性，用于 OCR 属性签名辅助。")
    parser.add_argument("--library-csv", type=Path, default=DEFAULT_LIBRARY_CSV, help="装备库 CSV，只读。")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Wiki HTML 缓存目录。")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="结果输出目录。")
    parser.add_argument("--attribute-exp", type=Path, default=DEFAULT_ATTRIBUTE_EXP, help="可选：给 attribute_exp 生成 wiki_hint 注释版。")
    parser.add_argument("--name", action="append", default=[], help="只抓指定装备名，可重复传入，例如 基础声呐#T3。")
    parser.add_argument("--name-file", type=Path, default=None, help="从文本文件读取装备名，一行一个。")
    parser.add_argument("--from-human-archive", action="store_true", help="只抓 v2 已人工确认过的装备，减少无关 Wiki 请求。")
    parser.add_argument("--human-archive-csv", type=Path, default=DEFAULT_HUMAN_ARCHIVE_CSV, help="v2 人工标注总档案 CSV。")
    parser.add_argument("--limit", type=int, default=0, help="限制抓取前 N 件；0 表示不限制。")
    parser.add_argument("--start", type=int, default=0, help="从过滤后的第 N 件开始抓取，0 表示从头开始；用于分批续跑。")
    parser.add_argument("--sample", action="store_true", help="只抓两个样例：基础声呐#T3、试作型四联装152mm主炮#T0。")
    parser.add_argument("--refresh", action="store_true", help="忽略已有缓存，重新联网抓取。")
    parser.add_argument("--cache-only", action="store_true", help="只读缓存，不联网。")
    parser.add_argument("--sleep", type=float, default=0.15, help="每次联网请求后的最小间隔秒数；启用 target-seconds 时作为保底睡眠。")
    parser.add_argument("--target-seconds", type=float, default=DEFAULT_TARGET_SECONDS, help="按本轮需要联网的页数自动配速，尽量在该秒数附近完成；0 表示关闭。")
    parser.add_argument("--http-error-cooldown", type=float, default=6.0, help="遇到 HTTP 错误后的额外冷却秒数，用于缓解 Wiki 567/429。")
    parser.add_argument("--stop-after-http-errors", type=int, default=3, help="连续 HTTP/网络错误达到 N 次就停止；0 表示不自动停止。")
    return parser.parse_args()


def collect_requested_names(args: argparse.Namespace) -> List[str]:
    """合并 --sample、--name 和 --name-file。"""
    names: List[str] = []
    if args.sample:
        names.extend(["基础声呐#T3", "试作型四联装152mm主炮#T0"])
    if args.from_human_archive:
        names.extend(load_names_from_human_archive(args.human_archive_csv))
    names.extend(args.name)
    if args.name_file is not None and args.name_file.exists():
        names.extend(
            line.strip()
            for line in args.name_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    return names


def main() -> int:
    """
    命令行入口。

    输入：
        终端参数。
    输出：
        进程返回码，0 表示成功。
    使用示例：
        python ocr_training_lab/equipment_attribute_scan/wiki_attribute_prefill.py --sample
    """
    args = parse_args()
    rows = load_equipment_library(args.library_csv)
    requested_names = collect_requested_names(args)
    selected_rows = filter_equipment_rows(rows, requested_names, 0)
    if args.start > 0:
        selected_rows = selected_rows[args.start :]
    if args.limit > 0:
        selected_rows = selected_rows[: args.limit]
    if not selected_rows:
        print("没有找到待抓取装备；请检查 --name 或 equipment_library.csv。")
        return 2

    signatures = crawl_equipment_attributes(
        selected_rows,
        cache_dir=args.cache_dir,
        refresh=args.refresh,
        cache_only=args.cache_only,
        sleep_seconds=max(0.0, args.sleep),
        target_duration_seconds=max(0.0, args.target_seconds),
        http_error_cooldown_seconds=max(0.0, args.http_error_cooldown),
        max_consecutive_http_errors=max(0, args.stop_after_http_errors),
    )
    paths = write_signatures(signatures, args.output_dir)
    hint_path = write_attribute_exp_hints(args.attribute_exp, signatures, args.output_dir)

    success_count = sum(1 for item in signatures if item.parse_status == "success")
    print(f"Wiki 属性抓取完成：total={len(signatures)} success={success_count} unresolved={len(signatures) - success_count}")
    print(f"CSV: {paths['csv']}")
    print(f"JSON: {paths['json']}")
    print(f"未解析: {paths['unresolved']}")
    if hint_path is not None:
        print(f"attribute_exp Wiki 提示版: {hint_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
