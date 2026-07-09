#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🧪 秘书舰资源包测试 (test_secretary_pack.py)    ║
║                                                              ║
║  【测试目标】确认 P2 秘书舰模板和资源包校验逻辑可用。          ║
║  【类比理解】像入港检查，图片、JSON 和台词格式都要过关。       ║
║  【数据流说明】resources/secretaries → validator → result。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
from pathlib import Path

from core.utils.path_manager import PathManager
from ui.secretary_pack import validate_secretary_pack


# ============================================================
# 🧪 第二部分：测试用例
# ============================================================

def test_secretary_template_pack_is_valid() -> None:
    """内置模板资源包应通过格式校验，便于用户复制制作。"""
    template_dir = PathManager.get_project_root() / "resources" / "secretaries" / "template"
    result = validate_secretary_pack(template_dir)

    assert result.valid is True
    assert result.errors == []
    assert (template_dir / "secretary.json").exists()
    assert (template_dir / "avatar.png").exists()
    assert (template_dir / "README.md").exists()


def test_secretary_pack_rejects_missing_avatar(tmp_path: Path) -> None:
    """缺少头像文件的资源包应给出明确错误。"""
    pack_dir = tmp_path / "bad_pack"
    pack_dir.mkdir()
    (pack_dir / "secretary.json").write_text(
        json.dumps(
            {
                "id": "bad",
                "name": "坏模板",
                "avatar": "avatar.png",
                "lines": {
                    "idle": ["待机"],
                    "target_changed": ["目标"],
                    "completed": ["完成"],
                    "history": ["历史"],
                    "error": ["错误"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = validate_secretary_pack(pack_dir)

    assert result.valid is False
    assert any("头像文件不存在" in error for error in result.errors)
