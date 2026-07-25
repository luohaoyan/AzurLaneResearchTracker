#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 Wiki 装备属性签名抓取测试                            ║
║                                                              ║
║  【测试目标】确认 Wiki HTML 能解析为 OCR 可用的属性签名。      ║
║  【类比理解】先校验说明书索引，再交给识图模型查表。            ║
║  【数据流说明】mock HTML → wiki_attribute_prefill.py。         ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import importlib.util
import sys
from pathlib import Path
from typing import Any


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_attribute_scan" / "wiki_attribute_prefill.py"


def _load_lab_module() -> Any:
    """按文件路径加载实验脚本，避免把 ocr_training_lab 变成正式包。"""
    spec = importlib.util.spec_from_file_location("wiki_attribute_prefill_for_test", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sample_html() -> str:
    """构造 Wiki 装备页的最小 HTML，覆盖嵌套初始值和直接属性行。"""
    return """
    <html>
      <head><title>试作型四联装152mm主炮T0 - 碧蓝航线WIKI</title></head>
      <body>
        <h1>试作型四联装152mm主炮T0</h1>
        <ul>
          <li><table><tr><th>伤害</th><th></th></tr></table></li>
          <li><ul class="equip">
            <li><table><tr><th>初始</th><td>17×4</td></tr></table></li>
            <li><table><tr><th>强化+10(满)</th><td>30×4</td></tr></table></li>
          </ul></li>
          <li><table><tr><th>标准射速</th><th></th></tr></table></li>
          <li><ul class="equip">
            <li><table><tr><th>初始</th><td>3.43s/轮</td></tr></table></li>
          </ul></li>
        </ul>
        <table>
          <tr><th>炮击</th><td>65</td></tr>
          <tr><th>弹药</th><td>穿甲弹</td></tr>
          <tr><th>反潜</th><td>• 改良深弹投射器</td></tr>
        </table>
      </body>
    </html>
    """


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_equipment_name_to_wiki_slug_removes_tier_hash() -> None:
    """Wiki URL slug 应去掉装备库里的 #，保留 T 级别。"""
    lab = _load_lab_module()

    assert lab.equipment_name_to_wiki_slug("基础声呐#T3") == "基础声呐T3"
    assert lab.equipment_name_to_wiki_slug("试作型四联装152mm主炮#T0") == "试作型四联装152mm主炮T0"


def test_equipment_name_to_wiki_slug_candidates_include_manual_alias() -> None:
    """本地消歧名应补充 Wiki 实际页面名作为 fallback。"""
    lab = _load_lab_module()

    candidates = lab.equipment_name_to_wiki_slug_candidates("彗星(轰炸机)#T3")

    assert candidates[0] == "彗星(轰炸机)T3"
    assert "彗星T3" in candidates


def test_equipment_name_to_wiki_slug_candidates_keep_full_width_parentheses() -> None:
    """Wiki 页面名可能保留中文全角括号，候选不能只剩英文括号。"""
    lab = _load_lab_module()

    candidates = lab.equipment_name_to_wiki_slug_candidates("试作型F8F熊猫（浮筒型）#T0")

    assert candidates[0] == "试作型F8F熊猫（浮筒型）T0"
    assert "试作型F8F熊猫(浮筒型)T0" in candidates


def test_parse_wiki_page_extracts_initial_signature_and_filters_navigation() -> None:
    """解析 Wiki HTML 时，应提取初始值并过滤底部导航型列表。"""
    lab = _load_lab_module()
    equipment = lab.EquipmentLibraryRow("S5-002", "试作型四联装152mm主炮#T0", "5", "轻巡炮")

    signature = lab.parse_wiki_equipment_page(_sample_html(), equipment)

    assert signature.parse_status == "success"
    assert signature.damage_initial == "17x4"
    assert signature.fire_rate_initial == "3.43s/轮"
    assert signature.primary_stats()[0] == ("炮击", "65")
    assert signature.ammo_type == "穿甲弹"
    assert "改良深弹投射器" not in signature.attribute_signature()


def test_crawl_equipment_attributes_uses_injected_fetcher_without_network() -> None:
    """批量抓取应支持注入 fetcher，测试和离线环境不应联网。"""
    lab = _load_lab_module()
    equipment = lab.EquipmentLibraryRow("G0477", "基础声呐#T3", "3", "设备")

    def fake_fetcher(slug: str) -> Any:
        assert slug == "基础声呐T3"
        html = """
        <html><body>
          <h1>基础声呐T3</h1>
          <ul>
            <li><table><tr><th>反潜</th><th></th></tr></table></li>
            <li><ul><li><table><tr><th>初始</th><td>5</td></tr></table></li></ul></li>
            <li><table><tr><th>命中</th><th></th></tr></table></li>
            <li><ul><li><table><tr><th>初始</th><td>4</td></tr></table></li></ul></li>
          </ul>
          <table><tr><th>额外侦测范围</th><td>5</td></tr><tr><th>技能</th><td>基础声呐T3</td></tr></table>
        </body></html>
        """
        return lab.FetchResult(html=html, status="fetched", message="ok", url="https://example.invalid", cache_path=Path("cache.html"))

    signatures = lab.crawl_equipment_attributes([equipment], fetcher=fake_fetcher)

    assert len(signatures) == 1
    assert signatures[0].parse_status == "success"
    assert signatures[0].primary_stats()[:2] == [("命中", "4"), ("反潜", "5")]
    assert signatures[0].extra_detection_range == "5"
    assert "技能=基础声呐T3" in signatures[0].attribute_signature()


def test_build_attribute_exp_wiki_hints_does_not_fill_human_fields() -> None:
    """Wiki 提示只能作为注释出现，不能覆盖用户要填写的人工字段。"""
    lab = _load_lab_module()
    equipment = lab.EquipmentLibraryRow("S5-002", "试作型四联装152mm主炮#T0", "5", "轻巡炮")
    signature = lab.parse_wiki_equipment_page(_sample_html(), equipment)
    exp_text = "\n".join(
        [
            "[attr_001.png]",
            "card_01.equipment_name:试作型四联装152mm主炮#T0",
            "card_01.attr_damage:",
            "card_01.attr_fire_rate:",
            "",
        ]
    )

    hinted_text, hit_count = lab.build_attribute_exp_wiki_hints(exp_text, lab.build_signature_index([signature]))

    assert hit_count == 1
    assert "# card_01.wiki_signature:" in hinted_text
    assert "伤害=17x4" in hinted_text
    assert "card_01.attr_damage:" in hinted_text
    assert "card_01.attr_damage:17x4" not in hinted_text


def test_load_names_from_human_archive_deduplicates_human_labels(tmp_path: Path) -> None:
    """从人工档案读取装备名时，应去重并保持人工确认名称。"""
    lab = _load_lab_module()
    archive = tmp_path / "master_human_labels.csv"
    archive.write_text(
        "\n".join(
            [
                "filename,card_no,accepted_equipment_name",
                "a.png,1,基础声呐#T3",
                "a.png,2,基础声呐#T3",
                "b.png,1,试作型四联装152mm主炮#T0",
                "b.png,2,",
            ]
        ),
        encoding="utf-8-sig",
    )

    names = lab.load_names_from_human_archive(archive)

    assert names == ["基础声呐#T3", "试作型四联装152mm主炮#T0"]


def test_sleep_for_pacing_targets_total_duration() -> None:
    """配速器应根据已完成请求数和目标总时长计算动态睡眠。"""
    lab = _load_lab_module()
    slept: list[float] = []

    delay = lab.sleep_for_pacing(
        network_completed=1,
        network_total=10,
        started_at=100.0,
        target_duration_seconds=90.0,
        minimum_sleep_seconds=0.15,
        sleep_func=slept.append,
        monotonic_func=lambda: 103.0,
    )

    assert round(delay, 2) == 6.0
    assert slept == [6.0]


def test_count_planned_network_fetches_skips_existing_cache(tmp_path: Path) -> None:
    """已有缓存的装备不应计入 90 秒联网配速数量。"""
    lab = _load_lab_module()
    cached = lab.EquipmentLibraryRow("G0477", "基础声呐#T3", "3", "设备")
    missing = lab.EquipmentLibraryRow("S5-002", "试作型四联装152mm主炮#T0", "5", "轻巡炮")
    cached_path = lab.cache_path_for_slug("基础声呐T3", tmp_path)
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_text("<html></html>", encoding="utf-8")

    count = lab.count_planned_network_fetches([cached, missing], tmp_path, False, False, None)

    assert count == 1


def test_count_planned_network_fetches_accepts_alias_cache(tmp_path: Path) -> None:
    """别名页面已有缓存时，不应继续把该装备计入待联网数量。"""
    lab = _load_lab_module()
    equipment = lab.EquipmentLibraryRow("G0190", "彗星(轰炸机)#T3", "3", "轰炸机")
    cached_path = lab.cache_path_for_slug("彗星T3", tmp_path)
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_text("<html></html>", encoding="utf-8")

    count = lab.count_planned_network_fetches([equipment], tmp_path, False, False, None)

    assert count == 0


def test_crawl_equipment_attributes_uses_pacing_for_network_fetches() -> None:
    """批量抓取时，真实网络抓取应触发配速睡眠；缓存模式不应空等。"""
    lab = _load_lab_module()
    rows = [
        lab.EquipmentLibraryRow("G0477", "基础声呐#T3", "3", "设备"),
        lab.EquipmentLibraryRow("S5-002", "试作型四联装152mm主炮#T0", "5", "轻巡炮"),
    ]
    slept: list[float] = []
    now = iter([0.0, 0.0, 10.0])

    def fake_fetcher(slug: str) -> Any:
        return lab.FetchResult(html="", status="http_error", message="HTTP 567", url="https://example.invalid", cache_path=Path("x"))

    lab.crawl_equipment_attributes(
        rows,
        fetcher=fake_fetcher,
        target_duration_seconds=90.0,
        sleep_seconds=0.0,
        http_error_cooldown_seconds=0.0,
        max_consecutive_http_errors=0,
        sleep_func=slept.append,
        monotonic_func=lambda: next(now),
    )

    assert slept[0] == 45.0
