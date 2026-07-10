#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              🕸️ 装备图鉴爬虫测试 (test_equipment_crawler.py)     ║
║                                                                  ║
║   【一句话解释】                                                 ║
║   验证爬虫能正确解析图鉴页、过滤特殊兵装、按稀有度抽样，         ║
║   并把阶段性产物写入独立工作区。                                 ║
║                                                                  ║
║   【类比理解】                                                   ║
║   这组测试像“出厂检验”。先检查原料是否识别正确，再检查         ║
║   成品文件有没有落在正确位置。                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import threading
from csv import DictReader
from dataclasses import replace
from pathlib import Path
from typing import Dict, List

import pytest
from bs4 import BeautifulSoup

from core.data.equipment_crawler import (
    CrawlerSettings,
    EquipmentCard,
    EquipmentCrawler,
    assign_crawl_ids,
    build_default_crawler_config,
    extract_equipment_cards,
    resolve_image_url,
    select_sample_cards,
)


# ============================================================
# 🧪 第一部分：测试数据
# ============================================================


def build_sample_html() -> str:
    """构造一个最小可用的装备图鉴 HTML 片段。"""
    return """
    <html>
      <body>
        <div class="divsort" data-param0="0" data-param1="驱逐炮" data-param2=",驱逐," data-param3="白色" data-param4="重樱">
          <a href="/blhx/white_a" title="白色装备A"><img src="https://example.com/white_a.jpg" srcset="https://example.com/white_a_90.jpg 1.5x, https://example.com/white_a_115.jpg 2x" /></a>
        </div>
        <div class="divsort" data-param0="0" data-param1="鱼雷机" data-param2=",航母," data-param3="蓝色" data-param4="白鹰">
          <a href="/blhx/blue_b" title="蓝色装备B"><img src="https://example.com/blue_b.jpg" srcset="https://example.com/blue_b_90.jpg 1.5x, https://example.com/blue_b_115.jpg 2x" /></a>
        </div>
        <div class="divsort" data-param0="0" data-param1="特殊兵装" data-param2=",特殊," data-param3="金色" data-param4="铁血">
          <a href="/blhx/special_x" title="特殊兵装X"><img src="https://example.com/special_x.jpg" srcset="https://example.com/special_x_90.jpg 1.5x, https://example.com/special_x_115.jpg 2x" /></a>
        </div>
        <div class="divsort" data-param0="0" data-param1="战列炮" data-param2=",战列," data-param3="金色" data-param4="东煌">
          <a href="/blhx/gold_c" title="金色装备C"><img src="https://example.com/gold_c.jpg" srcset="https://example.com/gold_c_90.jpg 1.5x, https://example.com/gold_c_115.jpg 2x" /></a>
        </div>
      </body>
    </html>
    """


def build_fallback_name_html() -> str:
    """鏋勯€犱竴涓彧鑳芥崟鑾峰埌鏂囨湰鍚嶇О鐨勮澶囬〉鐗囨銆?"""
    return """
    <html>
      <body>
        <div class="divsort" data-param0="0" data-param1="战列炮" data-param2=",战巡,战列" data-param3="彩色" data-param4="白鹰">
          <a href="/blhx/problem"><img src="https://example.com/problem.jpg" /></a>
          <a href="/blhx/problem"><span class="AF">试作型三联装419mm主炮MK.IT0 }</span></a>
        </div>
      </body>
    </html>
    """


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """读取阶段性 CSV，便于检查输出内容。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(DictReader(handle))


class FakeEquipmentManager:
    """给装备爬虫测试用的最小装备库。"""

    def get_all(self) -> List[Dict[str, str]]:
        return [
            {"equipment_id": "G0001", "name": "BR.810"},
            {"equipment_id": "G0002", "name": "B-13"},
        ]

    def _generate_id(self, is_research: bool, phase: int = 0) -> str:
        """只给测试用的最小实现。"""
        return "G0003"


# ============================================================
# 🔍 第二部分：解析与抽样测试
# ============================================================


def test_resolve_image_url_prefers_highest_srcset_candidate() -> None:
    """当图片提供多个分辨率时，应该优先取最高质量版本。"""
    soup = BeautifulSoup(
        '<img src="https://example.com/fallback.jpg" srcset="https://example.com/low.jpg 1x, https://example.com/high.jpg 2x" />',
        "html.parser",
    )
    image = soup.find("img")

    assert image is not None
    assert resolve_image_url(image, "https://wiki.biligame.com/blhx/%E8%A3%85%E5%A4%87%E5%9B%BE%E9%89%B4") == "https://example.com/high.jpg"


def test_extract_equipment_cards_filters_special_equipment_and_maps_rarity() -> None:
    """图鉴页里应正确过滤特殊兵装，并映射稀有度与图片链接。"""
    settings = CrawlerSettings.from_mapping(build_default_crawler_config())
    cards = extract_equipment_cards(build_sample_html(), settings)

    assert len(cards) == 3
    assert [card.name for card in cards] == ["白色装备A", "蓝色装备B", "金色装备C"]
    assert [card.rarity_name for card in cards] == ["白色", "蓝色", "金色"]
    assert [card.rarity_id for card in cards] == [1, 2, 4]
    assert all(card.crawl_id == "" for card in cards)
    assert all(card.source_url.startswith("https://wiki.biligame.com/blhx/") for card in cards)
    assert cards[0].image_url == "https://example.com/white_a_115.jpg"


def test_extract_equipment_cards_cleans_fallback_text_names() -> None:
    """褰撴爣棰樼己澶辨椂锛屽簲浠庢枃鏈閫夊悕绉帮紝涓嶈鎶婂彸鑺辨嫹绛夋潅瀛楃甯﹀叆銆?"""
    settings = CrawlerSettings.from_mapping(build_default_crawler_config())
    cards = extract_equipment_cards(build_fallback_name_html(), settings)

    assert len(cards) == 1
    assert cards[0].name == "试作型三联装419mm主炮MK.IT0"
    assert "}" not in cards[0].name


def test_select_sample_cards_respects_per_rarity_limit() -> None:
    """抽样结果应该按稀有度限制数量，而不是把全部条目都带出来。"""
    settings = CrawlerSettings.from_mapping(build_default_crawler_config())
    cards = extract_equipment_cards(build_sample_html(), settings)
    selected = select_sample_cards(cards, settings, {"白色": 1, "蓝色": 1, "金色": 1})

    assert [card.name for card in selected] == ["白色装备A", "蓝色装备B", "金色装备C"]
    assert selected[0].rarity_folder == "common"
    assert selected[1].rarity_folder == "rare"
    assert selected[2].rarity_folder == "super_rare"


def test_assign_crawl_ids_uses_ascii_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """临时 ID 应该稳定、纯 ASCII，便于后续导入和路径处理。"""
    monkeypatch.setattr("core.data.equipment_crawler.get_equipment_manager", lambda: FakeEquipmentManager())
    settings = CrawlerSettings.from_mapping(build_default_crawler_config())
    cards = extract_equipment_cards(build_sample_html(), settings)[:2]
    assigned = assign_crawl_ids(cards)

    assert [card.crawl_id for card in assigned] == ["G0003", "G0004"]


# ============================================================
# 🏗️ 第三部分：落盘流程测试
# ============================================================


def test_crawl_sample_writes_isolated_stage_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """一次小批量抓取应该落到独立工作区，而不是正式 data/。"""
    settings = CrawlerSettings.from_mapping(build_default_crawler_config())
    crawler = EquipmentCrawler(config_data=build_default_crawler_config(), workspace_root=tmp_path)

    monkeypatch.setattr(crawler, "fetch_page_html", lambda: build_sample_html())
    monkeypatch.setattr("core.data.equipment_crawler.get_equipment_manager", lambda: FakeEquipmentManager())

    def fake_download_image(image_url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-image-bytes")
        return destination

    monkeypatch.setattr(crawler, "_download_image_task", fake_download_image)
    monkeypatch.setattr("core.data.equipment_crawler.time.sleep", lambda *_args, **_kwargs: None)

    result = crawler.crawl_sample(sample_size_override={"白色": 1, "蓝色": 1, "金色": 1, "紫色": 0, "彩色": 0}, workspace_name="20260709_001200")

    assert result.selected_count == 3
    assert result.workspace_dir == tmp_path / "20260709_001200"
    assert result.raw_html_path.exists()
    assert result.library_csv_path.exists()
    assert result.images_csv_path.exists()
    assert result.manifest_json_path.exists()
    assert (result.workspace_dir / "images" / "common").exists()
    assert (result.workspace_dir / "images" / "rare").exists()
    assert (result.workspace_dir / "images" / "super_rare").exists()
    assert all("特殊兵装" not in row["name"] for row in read_csv_rows(result.library_csv_path))

    library_rows = read_csv_rows(result.library_csv_path)
    image_rows = read_csv_rows(result.images_csv_path)
    assert [row["equipment_id"] for row in library_rows] == ["G0003", "G0004", "G0005"]
    assert [row["equipment_id"] for row in image_rows] == ["G0003", "G0004", "G0005"]
    assert all(Path(row["image_path"]).exists() for row in image_rows)
    assert set(library_rows[0].keys()) == {"equipment_id", "name", "rarity_id", "type"}
    assert set(image_rows[0].keys()) == {"equipment_id", "image_path"}
    assert not Path(image_rows[0]["image_path"]).is_absolute()
    assert image_rows[0]["image_path"].replace("\\", "/").endswith("/images/common/G0003.jpg")


def test_download_images_runs_in_parallel_and_preserves_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """并行下载应当真正并发执行，同时返回顺序要和输入顺序一致。"""
    crawler = EquipmentCrawler(config_data=build_default_crawler_config(), workspace_root=tmp_path)
    crawler.settings = replace(
        crawler.settings,
        image_download_workers=2,
        image_download_delay_seconds=0.0,
    )

    barrier = threading.Barrier(2)
    download_plan = []
    for index in range(2):
        card = EquipmentCard(
            crawl_id=f"CW000{index + 1}",
            name=f"测试装备{index + 1}",
            rarity_name="铁壳",
            rarity_id=1,
            rarity_folder="common",
            equipment_type="主炮",
            source_url=f"https://example.com/{index + 1}",
            image_url=f"https://example.com/{index + 1}.jpg",
            page_order=index + 1,
        )
        destination = tmp_path / f"image_{index + 1}.jpg"
        download_plan.append((card, destination))

    def fake_download_image(image_url: str, destination: Path) -> Path:
        barrier.wait(timeout=5)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(image_url.encode("utf-8"))
        return destination

    monkeypatch.setattr(crawler, "_download_image_task", fake_download_image)

    image_paths = crawler._download_images(download_plan)

    assert image_paths == [item[1] for item in download_plan]
    assert all(path.exists() for path in image_paths)


def test_manifest_keeps_only_compact_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """manifest 应该只保留后续导入和排查需要的字段，避免保存过程性信息。"""
    crawler = EquipmentCrawler(config_data=build_default_crawler_config(), workspace_root=tmp_path)
    monkeypatch.setattr(crawler, "fetch_page_html", lambda: build_sample_html())

    def fake_download_image(image_url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-image-bytes")
        return destination

    monkeypatch.setattr(crawler, "_download_image_task", fake_download_image)
    monkeypatch.setattr("core.data.equipment_crawler.time.sleep", lambda *_args, **_kwargs: None)

    result = crawler.crawl_sample(sample_size_override={key: 1 for key in crawler.settings.sample_size_per_rarity.keys()}, workspace_name="20260709_001500")
    manifest = result.to_manifest()

    assert "config" not in manifest
    assert "selected_cards" not in manifest
    assert "image_paths" not in manifest
    assert "raw_html_path" not in manifest
    assert "manifest_json_path" not in manifest
    assert manifest["selected_count"] == 3
    assert manifest["counts_by_rarity"]
    assert manifest["warnings"] == []
