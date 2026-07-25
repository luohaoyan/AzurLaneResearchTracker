#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║             🧭 模拟器连接注册表 (simulator_registry.py)      ║
║                                                              ║
║  【一句话解释】集中维护安卓模拟器的 ADB 候选端口和路径资料。  ║
║  【类比理解】它像港区设备通讯录，ADB 控制器按通讯录逐个拨号。 ║
║  【数据流说明】配置 key/端口 → 候选 serial → 自动连接流程。   ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple


# ============================================================
# 🧱 第二部分：模拟器资料结构
# ============================================================

LOCAL_HOST = "127.0.0.1"


@dataclass(frozen=True)
class SimulatorPortRange:
    """
    模拟器常见 ADB 端口范围。
    输入：
        start/end/step: 端口扫描起止和步长。
    输出：
        可转换为 127.0.0.1:port 的候选 serial。
    使用示例：
        ports = SimulatorPortRange(5555, 5619, 2).ports()
    """

    start: int
    end: int
    step: int = 1

    def ports(self) -> Tuple[int, ...]:
        """返回范围内端口，自动限制到 TCP 合法端口。"""
        safe_step = max(1, int(self.step or 1))
        return tuple(port for port in range(self.start, self.end + 1, safe_step) if 0 < port < 65536)


@dataclass(frozen=True)
class SimulatorConnectionProfile:
    """
    单类模拟器的连接资料。
    输入：
        key/name/serials/ports/adb_paths。
    输出：
        供自动发现和 UI 展示复用的稳定元数据。
    使用示例：
        profile = get_simulator_profile("mumu")
    """

    key: str
    display_name: str
    aliases: Tuple[str, ...]
    default_serials: Tuple[str, ...] = ()
    port_ranges: Tuple[SimulatorPortRange, ...] = ()
    adb_paths: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()

    def candidate_serials(self, simulator_config: Dict[str, Any] | None = None) -> Tuple[str, ...]:
        """根据用户配置和内置资料生成去重后的 TCP serial 候选。"""
        config = simulator_config or {}
        adb_config = config.get("adb", {}) if isinstance(config, dict) else {}
        candidates: list[str] = []

        for key in ("serial", "device_serial"):
            normalized = normalize_serial(adb_config.get(key, ""))
            if normalized:
                candidates.append(normalized)

        configured_port = _safe_int(adb_config.get("port"))
        if configured_port:
            candidates.append(f"{LOCAL_HOST}:{configured_port}")

        configured_serials = adb_config.get("candidate_serials", ())
        if isinstance(configured_serials, Iterable) and not isinstance(configured_serials, (str, bytes)):
            candidates.extend(normalize_serial(item) for item in configured_serials)

        candidates.extend(self.default_serials)
        for port_range in self.port_ranges:
            candidates.extend(f"{LOCAL_HOST}:{port}" for port in port_range.ports())

        return tuple(dict.fromkeys(item for item in candidates if item))


# ============================================================
# 🗂️ 第三部分：内置连接资料
# ============================================================

SIMULATOR_PROFILES: Tuple[SimulatorConnectionProfile, ...] = (
    SimulatorConnectionProfile(
        key="mumu",
        display_name="MuMu 模拟器",
        aliases=("mumu", "nemu", "mumuplayer", "网易mumu"),
        default_serials=(f"{LOCAL_HOST}:7555",),
        port_ranges=(SimulatorPortRange(16384, 17408, 32),),
        adb_paths=(
            "D:/MuMuPlayer-12.0/shell/adb.exe",
            "C:/Program Files/Netease/MuMuPlayer-12.0/shell/adb.exe",
            "C:/Program Files/Netease/MuMuPlayerGlobal-12.0/shell/adb.exe",
        ),
        notes=("MuMu 12 多开通常使用 16384 起、步长 32 的本地端口。",),
    ),
    SimulatorConnectionProfile(
        key="leidian",
        display_name="雷电模拟器",
        aliases=("leidian", "ldplayer", "ld", "雷电"),
        default_serials=(f"{LOCAL_HOST}:5555",),
        port_ranges=(SimulatorPortRange(5555, 5619, 2),),
        adb_paths=(
            "C:/LDPlayer/LDPlayer9/adb.exe",
            "C:/LDPlayer/LDPlayer4.0/adb.exe",
            "F:/Program Files/LDPlayer9/adb.exe",
            "D:/LDPlayer/LDPlayer9/adb.exe",
            "D:/LDPlayer/LDPlayer4.0/adb.exe",
            "C:/Program Files/LDPlayer/LDPlayer9/adb.exe",
        ),
        notes=("雷电和部分 BlueStacks 传统实例都可能落在 5555 起的端口族。",),
    ),
    SimulatorConnectionProfile(
        key="bluestacks",
        display_name="BlueStacks 蓝叠",
        aliases=("bluestacks", "bst", "蓝叠"),
        default_serials=(f"{LOCAL_HOST}:5555",),
        port_ranges=(SimulatorPortRange(5555, 5619, 2),),
        adb_paths=(
            "C:/Program Files/BlueStacks_nxt/HD-Adb.exe",
            "C:/Program Files/BlueStacks/HD-Adb.exe",
            "C:/Program Files/BlueStacks_bgp64/HD-Adb.exe",
        ),
        notes=("Hyper-V 版本端口可能随实例变化，后续可读取 bluestacks.conf 精确补全。",),
    ),
    SimulatorConnectionProfile(
        key="nox",
        display_name="夜神模拟器",
        aliases=("nox", "noxplayer", "夜神"),
        default_serials=(f"{LOCAL_HOST}:62001",),
        port_ranges=(SimulatorPortRange(62001, 62025, 1),),
        adb_paths=(
            "C:/Program Files/Nox/bin/adb.exe",
            "C:/Program Files (x86)/Nox/bin/adb.exe",
            "D:/Program Files/Nox/bin/adb.exe",
        ),
        notes=("夜神常见 ADB 端口从 62001 起，多开时端口会递增。",),
    ),
    SimulatorConnectionProfile(
        key="memu",
        display_name="逍遥模拟器",
        aliases=("memu", "memuplay", "逍遥"),
        default_serials=(f"{LOCAL_HOST}:21503", f"{LOCAL_HOST}:21513", f"{LOCAL_HOST}:21523"),
        adb_paths=(
            "C:/Program Files/Microvirt/MEmu/adb.exe",
            "D:/Program Files/Microvirt/MEmu/adb.exe",
            "C:/Program Files (x86)/Microvirt/MEmu/adb.exe",
        ),
        notes=("逍遥多开常见端口为 21503/21513/21523 一组递增。",),
    ),
    SimulatorConnectionProfile(
        key="avd",
        display_name="Android Emulator",
        aliases=("avd", "android_emulator", "emulator"),
        default_serials=(),
        adb_paths=(),
        notes=("Android Emulator 通常已由 adb server 发现为 emulator-5554，不需要 adb connect。",),
    ),
    SimulatorConnectionProfile(
        key="wsa",
        display_name="Windows Subsystem for Android",
        aliases=("wsa", "windows_subsystem_for_android"),
        default_serials=(f"{LOCAL_HOST}:58526",),
        adb_paths=(),
        notes=("WSA 常见本地 ADB 端口为 58526，需先在 WSA 设置中开启开发人员模式。",),
    ),
)


# ============================================================
# 🌐 第四部分：全局访问函数
# ============================================================

def normalize_serial(value: object) -> str:
    """
    宽容归一化用户输入的 ADB serial。
    输入：
        value: 用户配置或 UI 粘贴的串号。
    输出：
        str: 规范化 serial；无法识别时返回清理后的原值。
    使用示例：
        normalize_serial("7555") == "127.0.0.1:7555"
    """
    serial = str(value or "").strip().replace(" ", "")
    if not serial:
        return ""
    serial = serial.replace("。", ".").replace("，", ".").replace(",", ".").replace("：", ":")
    serial = serial.replace("127.0.0.1.", "127.0.0.1:")
    serial = serial.replace("12127.0.0.1", "127.0.0.1")
    serial = serial.replace("auto127.0.0.1", "127.0.0.1").replace("autoemulator", "emulator")

    simulator_match = re.search(r"(127\.\d+\.\d+\.\d+:\d+)", serial)
    if "模拟" in serial and simulator_match:
        return simulator_match.group(1)

    if serial.isdigit():
        port = _safe_int(serial)
        if port:
            return f"{LOCAL_HOST}:{port}"

    return serial


def get_simulator_profile(key_or_alias: str) -> SimulatorConnectionProfile | None:
    """按 key 或 alias 查找模拟器连接资料。"""
    normalized = str(key_or_alias or "").strip().lower()
    if not normalized:
        return None
    for profile in SIMULATOR_PROFILES:
        if normalized == profile.key or normalized in profile.aliases:
            return profile
    return None


def list_simulator_profiles() -> Tuple[SimulatorConnectionProfile, ...]:
    """返回全部内置模拟器资料，供环境检查和 UI 展示使用。"""
    return SIMULATOR_PROFILES


def build_auto_connect_candidates(
    simulator_key: str,
    simulator_config: Dict[str, Any] | None = None,
    *,
    include_all_profiles: bool = False,
) -> Tuple[str, ...]:
    """
    生成自动连接候选 serial。
    输入：
        simulator_key: 当前配置的模拟器 key。
        simulator_config: 当前模拟器 JSON 配置。
        include_all_profiles: 是否追加其他模拟器候选，供兜底扫描使用。
    输出：
        Tuple[str, ...]: 去重后的候选 serial。
    使用示例：
        candidates = build_auto_connect_candidates("mumu", config)
    """
    profile = get_simulator_profile(simulator_key)
    candidates: list[str] = []
    primary_candidates: Tuple[str, ...] = ()
    if profile is not None:
        primary_candidates = profile.candidate_serials(simulator_config)
        candidates.extend(primary_candidates[:4])
    elif simulator_config:
        fallback = SimulatorConnectionProfile(str(simulator_key or "generic"), str(simulator_key or "通用 ADB"), ())
        primary_candidates = fallback.candidate_serials(simulator_config)
        candidates.extend(primary_candidates)

    if include_all_profiles:
        for item in SIMULATOR_PROFILES:
            if profile is not None and item.key == profile.key:
                continue
            candidates.extend(item.default_serials)

    candidates.extend(primary_candidates)

    if include_all_profiles:
        for item in SIMULATOR_PROFILES:
            if profile is not None and item.key == profile.key:
                continue
            candidates.extend(item.candidate_serials({}))

    return tuple(dict.fromkeys(item for item in candidates if item))


def collect_common_adb_paths(configured_paths: Iterable[object] | None = None) -> Tuple[str, ...]:
    """合并配置路径和内置模拟器 ADB 常见路径。"""
    paths: list[str] = []
    if configured_paths is not None and not isinstance(configured_paths, (str, bytes)):
        paths.extend(str(item) for item in configured_paths if str(item or "").strip())
    for profile in SIMULATOR_PROFILES:
        paths.extend(profile.adb_paths)
    return tuple(dict.fromkeys(paths))


def _safe_int(value: object) -> int:
    """安全转换端口数字，非法值返回 0。"""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return port if 0 < port < 65536 else 0
