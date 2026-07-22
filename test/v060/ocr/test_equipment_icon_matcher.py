#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 装备图标匹配器测试 (test_equipment_icon_matcher.py)  ║
║                                                              ║
║  【测试目标】验证 data/images 图鉴检索的安全边界和保守返回。 ║
║  【类比理解】像用几张合成小图模拟装备图鉴，检查认不准就不认。║
║  【数据流说明】synthetic icon → EquipmentIconMatcher → result.║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.recognition import equipment_icon_matcher as matcher_module
from core.recognition.equipment_icon_matcher import EquipmentIconMatcher


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

class FakeCv2:
    """只实现图标匹配测试需要的 OpenCV 最小接口。"""

    COLOR_BGR2GRAY = 6
    IMREAD_COLOR = 1

    def cvtColor(self, image: np.ndarray, code: int) -> np.ndarray:
        """把 BGR/RGB 彩色数组转成灰度数组。"""
        if len(image.shape) == 2:
            return image
        return image.mean(axis=2).astype(image.dtype)

    def resize(self, image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
        """用最近邻缩放合成图；足够覆盖单元测试，不依赖真实 cv2。"""
        width, height = size
        source_height, source_width = image.shape[:2]
        y_index = np.linspace(0, source_height - 1, height).astype(int)
        x_index = np.linspace(0, source_width - 1, width).astype(int)
        return image[y_index][:, x_index]

    def imread(self, path: str, flags: int = 1) -> Any:
        """测试不从磁盘读取真实图片，因此默认返回 None。"""
        return None


def _icon(seed: int = 0, invert: bool = False) -> np.ndarray:
    """生成带结构差异的 4x4 彩色装备图标。"""
    gray = np.array(
        [
            [0, 40, 80, 120],
            [160, 200, 240, 20],
            [60, 100, 140, 180],
            [220, 10, 50, 90],
        ],
        dtype=np.uint8,
    )
    gray = (gray + seed).astype(np.uint8)
    if invert:
        gray = 255 - gray
    return np.stack([gray, np.roll(gray, 1, axis=0), np.roll(gray, 1, axis=1)], axis=2)


def _matcher(reference_images: dict[str, np.ndarray], **config: Any) -> EquipmentIconMatcher:
    """构造注入图库的 matcher，避免读写正式 data/images。"""
    merged_config = {
        "threshold": 0.82,
        "ambiguous_margin": 0.025,
        "top_n": 3,
        "target_size": [4, 4],
        "min_icon_size": [2, 2],
    }
    merged_config.update(config)
    return EquipmentIconMatcher(
        config=merged_config,
        cv2_module=FakeCv2(),
        np_module=np,
        reference_images=reference_images,
    )


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_missing_cv2_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenCV 缺失时图标匹配应返回 unavailable，而不是 import 崩溃。"""
    monkeypatch.setattr(matcher_module, "_cv2", None)
    matcher = EquipmentIconMatcher(np_module=np, reference_images={"G0001": _icon()})

    result = matcher.match_icon(_icon())

    assert result.success is False
    assert result.status == "unavailable"
    assert "OpenCV" in result.message


def test_injected_gallery_exact_match_returns_equipment_id() -> None:
    """注入图库中存在清晰 top1 时，应返回对应 equipment_id 和候选列表。"""
    query = _icon(seed=3)
    matcher = _matcher({"G0001": query, "G0002": _icon(seed=17, invert=True)})

    result = matcher.match_icon(query)

    payload = result.to_dict()
    assert result.success is True
    assert result.status == "success"
    assert result.equipment_id == "G0001"
    assert result.confidence >= 0.99
    assert payload["candidates"][0]["equipment_id"] == "G0001"
    assert payload["icon_roi"] == [0, 0, 4, 4]


def test_low_score_returns_unknown_instead_of_wrong_id() -> None:
    """最高分低于阈值时应返回 unknown，避免把陌生装备硬认成图库项。"""
    matcher = _matcher({"G0001": np.zeros((4, 4, 3), dtype=np.uint8)})
    query = np.full((4, 4, 3), 255, dtype=np.uint8)

    result = matcher.match_icon(query)

    assert result.success is True
    assert result.status == "unknown"
    assert result.equipment_id == "unknown"
    assert result.confidence < 0.82


def test_close_top_candidates_return_ambiguous_unknown() -> None:
    """Top1/Top2 分数过近时返回 ambiguous，不把同分候选乱定为一个 ID。"""
    query = _icon(seed=5)
    matcher = _matcher({"G0001": query, "G0002": query.copy()})

    result = matcher.match_icon(query)

    assert result.success is True
    assert result.status == "ambiguous"
    assert result.equipment_id == "unknown"
    assert len(result.candidates) == 2
    assert result.candidates[0].confidence == pytest.approx(result.candidates[1].confidence)


def test_duplicate_samples_for_same_equipment_do_not_trigger_ambiguous() -> None:
    """同一 equipment_id 的多张 accepted 样本不应互相触发 ambiguous。"""
    query = _icon(seed=7)
    other = _icon(seed=21, invert=True)
    matcher = _matcher({"G0001": query, "G0002": other}, top_n=3)
    prepared_query = matcher._prepare_icon(query, None)[0]  # noqa: SLF001 - 测试 accepted 图库重复样本。
    prepared_other = matcher._prepare_icon(other, None)[0]  # noqa: SLF001 - 测试 accepted 图库重复样本。
    matcher._gallery = [  # noqa: SLF001 - 模拟 manifest 中一个装备有多个样本。
        {
            "equipment_id": "G0001",
            "image_path": "sample_a.png",
            "source_image": query,
            "prepared": prepared_query,
            "ratio_cache": {},
        },
        {
            "equipment_id": "G0001",
            "image_path": "sample_b.png",
            "source_image": query.copy(),
            "prepared": prepared_query,
            "ratio_cache": {},
        },
        {
            "equipment_id": "G0002",
            "image_path": "other.png",
            "source_image": other,
            "prepared": prepared_other,
            "ratio_cache": {},
        },
    ]
    matcher._gallery_loaded = True  # noqa: SLF001 - 避免测试图库被重新加载。

    result = matcher.match_icon(query)

    assert result.status == "success"
    assert result.equipment_id == "G0001"
    assert result.candidates[0].equipment_id == "G0001"
    assert result.candidates[1].equipment_id == "G0001"


def test_match_card_uses_equipment_icon_ratio() -> None:
    """装备卡识别应先裁出图标 ROI，再和图库比对。"""
    icon = _icon(seed=9)
    card = np.full((10, 10, 3), 255, dtype=np.uint8)
    card[1:7, 1:9] = FakeCv2().resize(icon, (8, 6))
    matcher = _matcher(
        {"G0001": FakeCv2().resize(icon, (8, 6))},
        target_size=[8, 6],
        icon_ratios={"equipment": [[0.10, 0.10, 0.80, 0.60]]},
    )

    result = matcher.match_card(card, card_type="equipment")

    assert result.status == "success"
    assert result.equipment_id == "G0001"
    assert result.icon_roi == (1, 1, 8, 6)


def test_empty_gallery_returns_no_gallery(tmp_path: Path) -> None:
    """图库 CSV 缺失或为空时应返回 no_gallery，不写正式数据。"""
    matcher = EquipmentIconMatcher(
        config={"target_size": [4, 4], "min_icon_size": [2, 2]},
        gallery_csv_path=tmp_path / "missing_equipment_images.csv",
        project_root=tmp_path,
        cv2_module=FakeCv2(),
        np_module=np,
    )

    result = matcher.match_icon(_icon())

    assert result.success is True
    assert result.status == "no_gallery"
    assert result.equipment_id == "unknown"
    assert any("不存在" in warning for warning in result.warnings)


def test_multiple_gallery_sources_are_loaded_and_deduplicated(tmp_path: Path) -> None:
    """正式图库与人工验收图库可以同时加载，重复映射只保留一份。"""
    primary = tmp_path / "primary.csv"
    reviewed = tmp_path / "reviewed.csv"
    primary.write_text(
        "equipment_id,image_path\nG0001,one.png\nG0001,one.png\n",
        encoding="utf-8",
    )
    reviewed.write_text(
        "equipment_id,image_path\nG0001,one.png\nG0001,reviewed.png\nG0002,two.png\n",
        encoding="utf-8",
    )
    matcher = EquipmentIconMatcher(
        config={"target_size": [4, 4], "min_icon_size": [2, 2]},
        gallery_csv_paths=[primary, reviewed],
        project_root=tmp_path,
        cv2_module=FakeCv2(),
        np_module=np,
    )

    rows = matcher._load_gallery_rows()  # noqa: SLF001 - 验证多来源导入边界。

    assert rows == (("G0001", "one.png"), ("G0001", "reviewed.png"), ("G0002", "two.png"))
    assert matcher.check_status()["gallery_sources_configured"] == 2


def test_too_small_icon_roi_is_rejected_as_error() -> None:
    """过小 ROI 通常意味着截图/卡片不完整，应给出明确错误。"""
    matcher = _matcher({"G0001": _icon()}, min_icon_size=[4, 4])

    result = matcher.match_icon(_icon(), icon_roi=(0, 0, 2, 2))

    assert result.success is False
    assert result.status == "error"
    assert "ROI 过小" in result.message


def test_partial_vertical_icon_can_match_top_reference_crop() -> None:
    """底部半截图标应能和图库同等上半部分比较，避免把遮挡区域算进去。"""
    icon = _icon(seed=11)
    query = icon[:2, :, :]
    matcher = _matcher({"G0001": icon, "G0002": _icon(seed=33, invert=True)})

    result = matcher.match_icon(query, reference_vertical_ratio=0.5)

    assert result.status == "success"
    assert result.equipment_id == "G0001"


def test_region_score_tolerates_corner_occlusion_without_wrong_id() -> None:
    """装备页角落遮挡时，分块评分应保留未遮挡主体区域的识别能力。"""
    icon = _icon(seed=13)
    occluded = icon.copy()
    occluded[2:, 2:, :] = 255
    matcher = _matcher(
        {"G0001": icon, "G0002": _icon(seed=70, invert=True)},
        threshold=0.78,
        structure_weight=0.15,
        color_weight=0.10,
        edge_weight=0.10,
        hash_weight=0.05,
        region_weight=0.60,
        region_grid=[2, 2],
        region_keep_ratio=0.75,
    )

    result = matcher.match_icon(occluded)

    assert result.status == "success"
    assert result.equipment_id == "G0001"
    assert result.candidates[0].score_detail["region"] > 0.80
