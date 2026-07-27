#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🗃️ 模拟器用户偏好与连接记录 (simulator_preferences) ║
║                                                              ║
║  【一句话解释】保存用户选择的模拟器、端口和最近连接记录。      ║
║  【数据流说明】UI选择 → config/config.json → ADB连接历史。  ║
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

DEFAULT_USER_CONFIG: Dict[str, Any] = {
    "simulator_preferences": {
        "selection": "auto",
        "serial": "",
        "port": "",
        "auto_select": True,
        "history": [],
        "last_connection": {},
    },
}


class SimulatorPreferences:
    """模拟器用户偏好与连接历史管理器。"""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        """创建管理器；测试可以传入临时 JSON 路径。"""
        self.path = Path(path) if path is not None else PathManager.get_config_dir() / "config.json"
        self.logger = get_logger()

    def load(self) -> Dict[str, Any]:
        """读取用户 JSON；损坏或缺失时返回默认结构，不抛出异常。"""
        try:
            if not self.path.exists():
                return deepcopy(DEFAULT_USER_CONFIG)
            with self.path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
            if not isinstance(raw, dict):
                raise ValueError("用户配置必须是 JSON 对象。")
            return self._merge_defaults(raw)
        except Exception as exc:
            self.logger.warning(f"读取模拟器用户配置失败，将使用默认值: {self.path} ({exc})")
            return deepcopy(DEFAULT_USER_CONFIG)

    def save(self, data: Dict[str, Any]) -> bool:
        """使用同目录临时文件原子保存，失败时记录日志并返回 False。"""
        temp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(data, ensure_ascii=False, indent=4)
            with temp_path.open("w", encoding="utf-8") as file:
                file.write(serialized)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.path)
            return True
        except Exception as exc:
            self.logger.warning(f"保存模拟器用户配置失败，不影响 ADB 连接结果: {self.path} ({exc})")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            return False

    def get_selection(self) -> Dict[str, Any]:
        """返回最近一次用户选择。"""
        data = self.load()
        selection = data.get("simulator_preferences", {})
        default_selection = DEFAULT_USER_CONFIG["simulator_preferences"]
        return dict(selection) if isinstance(selection, dict) else deepcopy(default_selection)

    def save_selection(
        self,
        simulator_key: str,
        *,
        serial: str = "",
        port: str | int = "",
        auto_select: bool = False,
    ) -> bool:
        """保存用户选择，不要求连接必须成功。"""
        data = self.load()
        preferences = data.get("simulator_preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
        preferences.update(
            {
                "selection": str(simulator_key or "auto").strip() or "auto",
                "serial": str(serial or "").strip(),
                "port": str(port or "").strip(),
                "auto_select": bool(auto_select),
            }
        )
        data["simulator_preferences"] = preferences
        return self.save(data)

    def record_connection(
        self,
        *,
        simulator_key: str,
        simulator_name: str,
        serial: str = "",
        port: str | int = "",
        status: str,
        success: bool,
        auto_selected: bool = False,
        message: str = "",
    ) -> bool:
        """
        记录一次连接尝试。

        连接记录只用于用户侧恢复偏好和排查环境，不参与业务数据计算。
        """
        data = self.load()
        now = datetime.now().isoformat(timespec="seconds")
        safe_key = str(simulator_key or "auto").strip() or "auto"
        safe_serial = str(serial or "").strip()
        safe_port = str(port or "").strip()
        preferences = data.get("simulator_preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
        history = preferences.get("history", [])
        if not isinstance(history, list):
            history = []

        match: Optional[Dict[str, Any]] = None
        for item in history:
            if (
                isinstance(item, dict)
                and str(item.get("simulator_key", "")) == safe_key
                and str(item.get("serial", "")) == safe_serial
                and str(item.get("port", "")) == safe_port
            ):
                match = item
                break

        if match is None:
            match = {
                "simulator_key": safe_key,
                "simulator_name": str(simulator_name or safe_key),
                "serial": safe_serial,
                "port": safe_port,
                "connection_count": 0,
            }
            history.insert(0, match)

        match.update(
            {
                "simulator_name": str(simulator_name or safe_key),
                "last_status": str(status or "unknown"),
                "last_success": bool(success),
                "last_attempt_at": now,
                "auto_selected": bool(auto_selected),
                "last_message": str(message or ""),
            }
        )
        if success:
            match["connection_count"] = int(match.get("connection_count", 0) or 0) + 1
            match["last_connected_at"] = now

        preferences["history"] = history[:20]
        preferences["last_connection"] = dict(match)
        data["simulator_preferences"] = preferences
        return self.save(data)

    @staticmethod
    def _merge_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
        """递归合并默认字段，避免旧版 config.json 缺字段。"""
        return _merge_defaults(raw, DEFAULT_USER_CONFIG)


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_simulator_preferences: Optional[SimulatorPreferences] = None


def get_simulator_preferences() -> SimulatorPreferences:
    """获取全局模拟器偏好管理器。"""
    global _simulator_preferences
    if _simulator_preferences is None:
        _simulator_preferences = SimulatorPreferences()
    return _simulator_preferences


def _merge_defaults(raw: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并默认字段，避免旧版 user.json 缺字段。"""
    result = deepcopy(defaults)
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_defaults(value, result[key])
        else:
            result[key] = value
    return result
