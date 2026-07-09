#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🎀 秘书舰资源包校验 (secretary_pack.py)          ║
║                                                              ║
║  【一句话解释】校验用户自制秘书舰资源包是否符合 GUI 读取格式。  ║
║  【类比理解】它像港区入渠检查单，图片和台词都合格才允许登记。  ║
║  【数据流说明】资源目录 → secretary.json → 校验结果 → UI。     ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class SecretaryPackValidationResult:
    """
    秘书舰资源包校验结果。
    输入：
        valid: 是否通过。
        message: 用户可见说明。
        errors: 错误列表。
    输出：
        不可变结果对象。
    使用示例：
        result = validate_secretary_pack(Path("resources/secretaries/template"))
    """

    valid: bool
    message: str
    errors: List[str]


class SecretaryPackValidator:
    """
    秘书舰资源包校验器。
    输入：
        资源包目录，目录内应包含 secretary.json 与头像图片。
    输出：
        校验结果，不直接修改用户文件。
    使用示例：
        result = SecretaryPackValidator().validate(pack_dir)
    """

    REQUIRED_LINE_GROUPS = ("idle", "target_changed", "completed", "history", "error")

    def validate(self, pack_dir: Path) -> SecretaryPackValidationResult:
        """
        校验秘书舰资源包目录。
        输入：
            pack_dir: 资源包目录。
        输出：
            SecretaryPackValidationResult: 校验结果。
        使用示例：
            result = validator.validate(Path("resources/secretaries/template"))
        """
        errors: List[str] = []
        if not pack_dir.exists() or not pack_dir.is_dir():
            return SecretaryPackValidationResult(False, "资源包目录不存在。", ["目录不存在"])

        json_path = pack_dir / "secretary.json"
        if not json_path.exists():
            return SecretaryPackValidationResult(False, "缺少 secretary.json。", ["缺少 secretary.json"])

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return SecretaryPackValidationResult(False, "secretary.json 格式错误。", [str(exc)])

        self._validate_required_text(data, "id", errors)
        self._validate_required_text(data, "name", errors)
        avatar = str(data.get("avatar", "")).strip()
        if not avatar:
            errors.append("avatar 不能为空")
        elif not (pack_dir / avatar).exists():
            errors.append(f"头像文件不存在: {avatar}")

        lines = data.get("lines")
        if not isinstance(lines, dict):
            errors.append("lines 必须是对象")
        else:
            self._validate_lines(lines, errors)

        if errors:
            return SecretaryPackValidationResult(False, "秘书舰资源包未通过校验。", errors)
        return SecretaryPackValidationResult(True, "秘书舰资源包格式正确。", [])

    @staticmethod
    def _validate_required_text(data: Dict[str, object], key: str, errors: List[str]) -> None:
        """校验必填文本字段。"""
        if not str(data.get(key, "")).strip():
            errors.append(f"{key} 不能为空")

    def _validate_lines(self, lines: Dict[str, object], errors: List[str]) -> None:
        """校验各场景台词列表。"""
        for group in self.REQUIRED_LINE_GROUPS:
            raw_lines = lines.get(group)
            if not isinstance(raw_lines, list):
                errors.append(f"lines.{group} 必须是数组")
                continue
            if not all(isinstance(item, str) and item.strip() for item in raw_lines):
                errors.append(f"lines.{group} 只能包含非空字符串")


# ============================================================
# 🌐 第三部分：全局函数
# ============================================================

def validate_secretary_pack(pack_dir: Path) -> SecretaryPackValidationResult:
    """
    便捷校验秘书舰资源包。
    输入：
        pack_dir: 资源包目录。
    输出：
        SecretaryPackValidationResult。
    使用示例：
        result = validate_secretary_pack(Path("resources/secretaries/template"))
    """
    return SecretaryPackValidator().validate(pack_dir)
