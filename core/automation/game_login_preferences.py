#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          📝 游戏登录偏好存档 (game_login_preferences)        ║
║                                                              ║
║  【一句话解释】保存用户选择的碧蓝航线客户端和服务器。          ║
║  【类比理解】像记住上次指挥官选择的港区入口。                  ║
║  【数据流说明】UI选择 → config/config.json → 游戏启动 API。  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.logger import get_logger
from core.utils.path_manager import PathManager


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

DEFAULT_GAME_LOGIN_CONFIG: Dict[str, Any] = {
    "game_login_preferences": {
        "client": "official_cn",
        "server": "auto",
        "last_package": "",
        "last_status": "",
        "last_launched_at": "",
    },
}


class GameLoginPreferences:
    """
    游戏登录偏好管理器。
    输入：
        path: 测试可注入临时 config.json。
    输出：
        load/save/save_selection/record_launch。
    使用示例：
        get_game_login_preferences().save_selection("official_cn", "auto")
    """

    def __init__(self, path: Optional[Path | str] = None) -> None:
        """初始化配置路径和日志器。"""
        self.path = Path(path) if path is not None else PathManager.get_config_dir() / "config.json"
        self.logger = get_logger()

    def load(self) -> Dict[str, Any]:
        """读取配置并补齐默认字段，损坏时返回默认配置。"""
        try:
            if not self.path.exists():
                return deepcopy(DEFAULT_GAME_LOGIN_CONFIG)
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
            if not isinstance(raw, dict):
                raise ValueError("用户配置必须是 JSON 对象。")
            return _merge_defaults(raw, DEFAULT_GAME_LOGIN_CONFIG)
        except Exception as exc:
            self.logger.warning(f"读取游戏登录配置失败，将使用默认值: {self.path} ({exc})")
            return deepcopy(DEFAULT_GAME_LOGIN_CONFIG)

    def save(self, data: Dict[str, Any]) -> bool:
        """用同目录临时文件原子保存配置，失败时返回 False。"""
        temp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            serialized = f"{json.dumps(data, ensure_ascii=False, indent=4)}\n"
            with temp_path.open("w", encoding="utf-8") as file:
                file.write(serialized)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.path)
            return True
        except Exception as exc:
            self.logger.warning(f"保存游戏登录配置失败，不影响游戏启动结果: {self.path} ({exc})")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            return False

    def get_selection(self) -> Dict[str, Any]:
        """返回当前客户端和服务器选择。"""
        data = self.load()
        selection = data.get("game_login_preferences", {})
        default_selection = DEFAULT_GAME_LOGIN_CONFIG["game_login_preferences"]
        return dict(selection) if isinstance(selection, dict) else deepcopy(default_selection)

    def save_selection(self, client_key: str, server_key: str = "auto") -> bool:
        """保存用户主动选择，不要求游戏已经启动成功。"""
        data = self.load()
        preferences = data.get("game_login_preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
        preferences.update(
            {
                "client": str(client_key or "official_cn").strip() or "official_cn",
                "server": str(server_key or "auto").strip() or "auto",
            }
        )
        data["game_login_preferences"] = preferences
        return self.save(data)

    def record_launch(self, *, client_key: str, server_key: str, package_name: str, status: str) -> bool:
        """记录最近一次启动结果，便于用户下次恢复选择和排查。"""
        data = self.load()
        preferences = data.get("game_login_preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
        preferences.update(
            {
                "client": str(client_key or "official_cn").strip() or "official_cn",
                "server": str(server_key or "auto").strip() or "auto",
                "last_package": str(package_name or "").strip(),
                "last_status": str(status or "unknown").strip() or "unknown",
                "last_launched_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        data["game_login_preferences"] = preferences
        return self.save(data)


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_game_login_preferences: Optional[GameLoginPreferences] = None


def get_game_login_preferences() -> GameLoginPreferences:
    """获取全局游戏登录偏好管理器。"""
    global _game_login_preferences
    if _game_login_preferences is None:
        _game_login_preferences = GameLoginPreferences()
    return _game_login_preferences


def _merge_defaults(raw: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并默认字段，避免旧版 config.json 缺字段。"""
    result = deepcopy(defaults)
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_defaults(value, result[key])
        else:
            result[key] = value
    return result
