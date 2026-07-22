#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║    🧪 装备图标 v2 Accepted 图库测试                          ║
║                                                              ║
║  【测试目标】验证 accepted 图标图库只收干净、完整、已确认样本。║
║  【类比理解】像检查剪贴本，只允许贴进已经确认身份的完整头像。 ║
║  【数据流说明】rarity_bucket JSON → accepted gallery manifest.║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np


# ============================================================
# 🧰 第二部分：测试辅助
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "build_accepted_icon_gallery.py"


def _load_lab_module() -> Any:
    """按文件路径加载 v2 gallery 脚本，避免把 ocr_training_lab 改成正式包。"""
    spec = importlib.util.spec_from_file_location("build_accepted_icon_gallery", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result_fixture(tmp_path: Path) -> list[dict[str, Any]]:
    """构造一份最小 rarity_bucket 结果，覆盖 accepted/partial/未选中三种情况。"""
    screenshot = tmp_path / "shot.png"
    screenshot.write_bytes(b"fake image bytes")
    return [
        {
            "filename": "shot.png",
            "screenshot_path": str(screenshot),
            "annotation": {
                "fields": {
                    "filter_rarity": "rare",
                    "filter_rarity_id": 2,
                }
            },
            "cards": [
                {
                    "card_no": 1,
                    "icon_selected": True,
                    "visibility": "full",
                    "icon_match_roi": [1, 2, 4, 5],
                    "accepted_equipment_id": "G0001",
                    "accepted_fragment_owned": 8,
                    "accepted_fragment_required": 5,
                    "icon_status": "ambiguous",
                    "icon_confidence": 0.7,
                },
                {
                    "card_no": 2,
                    "icon_selected": True,
                    "visibility": "partial_bottom",
                    "icon_match_roi": [2, 2, 4, 5],
                    "accepted_equipment_id": "G0002",
                },
                {
                    "card_no": 3,
                    "icon_selected": False,
                    "visibility": "full",
                    "icon_match_roi": [3, 2, 4, 5],
                    "accepted_equipment_id": "G0003",
                },
                {
                    "card_no": 4,
                    "icon_selected": True,
                    "visibility": "full",
                    "icon_match_roi": [4, 2, 4, 5],
                    "accepted_equipment_id": "",
                },
            ],
        }
    ]


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_iter_accepted_cards_keeps_only_full_icon_selected_samples(tmp_path: Path) -> None:
    """默认只允许完整、已选中、已 accepted 的图标进入图库。"""
    lab = _load_lab_module()
    results = _result_fixture(tmp_path)

    rows = list(lab.iter_accepted_cards(results))

    assert len(rows) == 1
    assert rows[0][1]["accepted_equipment_id"] == "G0001"


def test_build_gallery_writes_manifest_without_partial_samples(tmp_path: Path, monkeypatch: Any) -> None:
    """构建图库时应写出 manifest，并跳过半截或未选中的 accepted 行。"""
    lab = _load_lab_module()
    source_results = tmp_path / "rarity_bucket_results.json"
    source_results.write_text(json.dumps(_result_fixture(tmp_path), ensure_ascii=False), encoding="utf-8")
    output_dir = tmp_path / "accepted_icon_gallery"
    written_paths: list[Path] = []

    def fake_read_image(_path: Path) -> np.ndarray:
        """返回足够容纳测试 ROI 的合成截图。"""
        return np.zeros((20, 20, 3), dtype=np.uint8)

    def fake_write_image(path: Path, image: np.ndarray) -> None:
        """写出临时测试文件，避免依赖真实 OpenCV 编码。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        written_paths.append(path)
        assert image.shape[:2] == (5, 4)

    monkeypatch.setattr(lab, "read_image", fake_read_image)
    monkeypatch.setattr(lab, "write_image", fake_write_image)

    manifest = lab.build_gallery(source_results, output_dir)

    assert len(manifest) == 1
    assert manifest[0]["equipment_id"] == "G0001"
    assert "equipment_name" in manifest[0]
    assert written_paths and written_paths[0].name.startswith("accepted_G0001")

    with (output_dir / lab.MANIFEST_CSV_NAME).open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["equipment_id"] == "G0001"
    assert "equipment_name" in rows[0]
    assert rows[0]["rarity"] == "rare"
