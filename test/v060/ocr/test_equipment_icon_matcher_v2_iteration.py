#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║      🧪 equipment_icon_matcher_v2 复核迭代测试               ║
║                                                              ║
║  【测试目标】确认历史人工标注能自动预填到新一轮待标注文件。   ║
║  【类比理解】像新错题本自动继承上一页已经写对的答案。          ║
║  【数据流说明】old exp + generated exp → todo exp。           ║
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
LAB_SCRIPT = PROJECT_ROOT / "ocr_training_lab" / "equipment_icon_matcher_v2" / "prepare_review_iteration.py"


def _load_lab_module() -> Any:
    """按文件路径加载 lab 脚本，避免把实验目录改成正式包。"""
    spec = importlib.util.spec_from_file_location("prepare_review_iteration_for_test", LAB_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# 🧪 第三部分：测试用例
# ============================================================

def test_parse_accepted_annotations_reads_only_non_empty_names(tmp_path: Path) -> None:
    """解析历史 exp 时，只应记录非空 accepted_equipment_name。"""
    lab = _load_lab_module()
    exp_path = tmp_path / "review.txt"
    exp_path.write_text(
        "\n".join(
            [
                "[v2_rare_scroll_1.png]",
                "card_01.accepted_equipment_name:维修工具#T2",
                "card_01.current_resolved_equipment_id:G0731",
                "card_02.accepted_equipment_name:",
                "card_02.current_resolved_equipment_id:G0001",
            ]
        ),
        encoding="utf-8",
    )

    annotations = lab.parse_accepted_annotations(exp_path)

    assert len(annotations) == 1
    assert annotations[("v2_rare_scroll_1.png", 1)].accepted_equipment_name == "维修工具#T2"


def test_build_prefilled_review_text_reuses_previous_names() -> None:
    """新一轮待标注文件应自动预填历史人工名称，减少重复劳动。"""
    lab = _load_lab_module()
    generated = "\n".join(
        [
            "[v2_rare_scroll_1.png]",
            "card_01.accepted_equipment_name:",
            "card_01.current_resolved_equipment_id:G0001",
            "card_02.accepted_equipment_name:",
            "",
        ]
    )
    previous = {
        ("v2_rare_scroll_1.png", 1): lab.AcceptedAnnotation(
            filename="v2_rare_scroll_1.png",
            card_no=1,
            accepted_equipment_name="维修工具#T2",
            source_path="old.txt",
        )
    }

    text, filled_count, blank_count = lab.build_prefilled_review_text(generated, previous)

    assert "card_01.accepted_equipment_name:维修工具#T2" in text
    assert "card_02.accepted_equipment_name:" in text
    assert filled_count == 1
    assert blank_count == 1


def test_build_prefilled_review_text_clears_machine_generated_names_without_history() -> None:
    """没有历史人工标注时，机器生成的 accepted 字段必须清空，避免误导人工复核。"""
    lab = _load_lab_module()
    generated = "\n".join(
        [
            "[v2_rare_scroll_1.png]",
            "card_01.accepted_equipment_name:机器猜测名称#T3",
            "card_01.current_resolved_equipment_id:G0001",
            "",
        ]
    )

    text, filled_count, blank_count = lab.build_prefilled_review_text(generated, {})

    assert "机器猜测名称#T3" not in text
    assert "card_01.accepted_equipment_name:" in text
    assert filled_count == 0
    assert blank_count == 1


def test_build_prefilled_review_text_rebuilds_current_machine_hints_once() -> None:
    """旧 exp 里的机器 Top3 应被清理，只保留本轮 JSON 重建的一组提示。"""
    lab = _load_lab_module()
    generated = "\n".join(
        [
            "[v2_rare_scroll_1.png]",
            "# card_01.suggested:G0001 旧建议 status=ambiguous",
            "# card_01.image_top3:旧图像候选",
            "# card_01.name_top3:旧名称候选",
            "# card_01.attribute_top3:旧属性候选",
            "card_01.accepted_equipment_name:",
            "",
        ]
    )
    previous = {
        ("v2_rare_scroll_1.png", 1): lab.AcceptedAnnotation(
            filename="v2_rare_scroll_1.png",
            card_no=1,
            accepted_equipment_name="维修工具#T2",
            source_path="archive.csv",
        )
    }
    hints = {
        ("v2_rare_scroll_1.png", 1): [
            "# card_01.image_top3:本轮图像候选",
            "# card_01.name_top3:本轮名称候选",
            "# card_01.attribute_top3:本轮属性候选",
        ]
    }

    text, filled_count, blank_count = lab.build_prefilled_review_text(generated, previous, hints)

    assert "旧图像候选" not in text
    assert "旧名称候选" not in text
    assert "旧属性候选" not in text
    assert text.count("# card_01.image_top3:本轮图像候选") == 1
    assert text.count("# card_01.name_top3:本轮名称候选") == 1
    assert text.count("# card_01.attribute_top3:本轮属性候选") == 1
    assert "# card_01.suggested:G0001 旧建议 status=ambiguous" in text
    assert "card_01.accepted_equipment_name:维修工具#T2" in text
    assert filled_count == 1
    assert blank_count == 0


def test_omit_prefilled_cards_from_review_text_keeps_only_unlabeled_cards() -> None:
    """开启只看未标注项时，历史答案不应再次出现在待标注正文。"""
    lab = _load_lab_module()
    review_text = "\n".join(
        [
            "# header",
            "",
            "[v2_rare_scroll_1.png]",
            "image_mode:viewport_full",
            "# card_01.image_top3:旧答案候选",
            "card_01.accepted_equipment_name:维修工具#T2",
            "card_01.current_resolved_equipment_id:G0476",
            "# card_02.image_top3:新卡候选",
            "card_02.accepted_equipment_name:",
            "card_02.current_resolved_equipment_id:",
            "",
            "[v2_rare_scroll_2.png]",
            "image_mode:viewport_full",
            "# card_03.image_top3:已标注候选",
            "card_03.accepted_equipment_name:液压弹射装置#T3",
            "card_03.current_resolved_equipment_id:G0001",
            "",
        ]
    )
    previous = {
        ("v2_rare_scroll_1.png", 1): lab.AcceptedAnnotation(
            filename="v2_rare_scroll_1.png",
            card_no=1,
            accepted_equipment_name="维修工具#T2",
            source_path="archive.csv",
        ),
        ("v2_rare_scroll_2.png", 3): lab.AcceptedAnnotation(
            filename="v2_rare_scroll_2.png",
            card_no=3,
            accepted_equipment_name="液压弹射装置#T3",
            source_path="archive.csv",
        ),
    }

    text, omitted_count = lab.omit_prefilled_cards_from_review_text(review_text, previous)

    assert "card_01." not in text
    assert "card_03." not in text
    assert "v2_rare_scroll_2.png" not in text
    assert "card_02.accepted_equipment_name:" in text
    assert "[v2_rare_scroll_1.png]" in text
    assert omitted_count == 2


def test_collect_previous_iterations_skips_test_img_iterations_by_default(tmp_path: Path) -> None:
    """默认不继承 test_img 迭代标注，避免测试集答案混入训练复核。"""
    lab = _load_lab_module()
    normal = tmp_path / "review_iterations" / "iter_normal" / "to_label" / "v2_review_todo_exp.txt"
    test_img = tmp_path / "review_iterations" / "iter_testimg_case" / "to_label" / "v2_review_todo_exp.txt"
    normal.parent.mkdir(parents=True)
    test_img.parent.mkdir(parents=True)
    normal.write_text("[normal.png]\ncard_01.accepted_equipment_name:维修工具#T3\n", encoding="utf-8")
    test_img.write_text("[test.png]\ncard_01.accepted_equipment_name:液压弹射装置#T3\n", encoding="utf-8")

    paths = lab.collect_previous_explicit_and_iterations([], tmp_path / "review_iterations")
    paths_with_test = lab.collect_previous_explicit_and_iterations(
        [],
        tmp_path / "review_iterations",
        include_test_iterations=True,
    )

    assert normal.resolve() in paths
    assert test_img.resolve() not in paths
    assert test_img.resolve() in paths_with_test
