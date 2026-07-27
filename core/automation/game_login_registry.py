#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🚢 碧蓝航线客户端与服务器目录 (game_login_registry) ║
║                                                              ║
║  【一句话解释】维护可自动启动的碧蓝航线客户端包名和服务器列表。║
║  【类比理解】像一张港区航线图，先知道客户端在哪，再决定去哪个服。║
║  【数据流说明】UI选择 → 包名匹配 → ADB 启动游戏。             ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class AzurLaneClientProfile:
    """碧蓝航线客户端配置。"""

    key: str
    display_name: str
    package_name: str
    activity_name: str
    region: str
    server_group: str
    channel: str = ""

    def to_dict(self) -> Dict[str, str]:
        """转换为 payload 可直接使用的 dict。"""
        return {
            "key": self.key,
            "display_name": self.display_name,
            "package_name": self.package_name,
            "activity_name": self.activity_name,
            "region": self.region,
            "server_group": self.server_group,
            "channel": self.channel,
        }


_CLIENT_PROFILES: Tuple[AzurLaneClientProfile, ...] = (
    AzurLaneClientProfile("official_cn", "国服官服（B站）", "com.bilibili.azurlane", "com.manjuu.azurlane.MainActivity", "cn", "cn_android", "B站"),
    AzurLaneClientProfile("global_en", "国际服 EN", "com.YoStarEN.AzurLane", "com.manjuu.azurlane.PrePermissionActivity", "en", "en", "Yostar"),
    AzurLaneClientProfile("official_jp", "日服 JP", "com.YoStarJP.AzurLane", "com.manjuu.azurlane.PrePermissionActivity", "jp", "jp", "Yostar"),
    AzurLaneClientProfile("official_tw", "台服 TW", "com.hkmanjuu.azurlane.gp", "com.manjuu.azurlane.PrePermissionActivity", "tw", "tw", "Manjuu"),
    AzurLaneClientProfile("cn_huawei", "国服渠道服（华为）", "com.bilibili.blhx.huawei", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "华为"),
    AzurLaneClientProfile("cn_honor", "国服渠道服（荣耀）", "com.bilibili.blhx.honor", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "荣耀"),
    AzurLaneClientProfile("cn_xiaomi", "国服渠道服（小米）", "com.bilibili.blhx.mi", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "小米"),
    AzurLaneClientProfile("cn_tencent", "国服渠道服（应用宝）", "com.tencent.tmgp.bilibili.blhx", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "应用宝"),
    AzurLaneClientProfile("cn_baidu", "国服渠道服（百度）", "com.bilibili.blhx.baidu", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "百度"),
    AzurLaneClientProfile("cn_360", "国服渠道服（360）", "com.bilibili.blhx.qihoo", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "360"),
    AzurLaneClientProfile("cn_oppo", "国服渠道服（OPPO）", "com.bilibili.blhx.nearme.gamecenter", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "OPPO"),
    AzurLaneClientProfile("cn_vivo", "国服渠道服（vivo）", "com.bilibili.blhx.vivo", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "vivo"),
    AzurLaneClientProfile("cn_meizu", "国服渠道服（魅族）", "com.bilibili.blhx.mz", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "魅族"),
    AzurLaneClientProfile("cn_dangle", "国服渠道服（当乐）", "com.bilibili.blhx.dl", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "当乐"),
    AzurLaneClientProfile("cn_lenovo", "国服渠道服（联想）", "com.bilibili.blhx.lenovo", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "联想"),
    AzurLaneClientProfile("cn_uc", "国服渠道服（UC九游）", "com.bilibili.blhx.uc", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "UC九游"),
    AzurLaneClientProfile("cn_mzw", "国服渠道服（拇指玩）", "com.bilibili.blhx.mzw", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "拇指玩"),
    AzurLaneClientProfile("cn_yx15", "国服渠道服（一五游戏）", "com.yiwu.blhx.yx15", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "一五游戏"),
    AzurLaneClientProfile("cn_4399", "国服渠道服（4399）", "com.bilibili.blhx.m4399", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "4399"),
    AzurLaneClientProfile("cn_move", "国服渠道服（迁移）", "com.bilibili.blhx.bilibiliMove", "com.manjuu.azurlane.SplashActivity", "cn", "cn_channel", "迁移"),
    AzurLaneClientProfile("tw_mycard", "台服 TW（MyCard）", "com.hkmanjuu.azurlane.gp.mc", "com.manjuu.azurlane.PrePermissionActivity", "tw", "tw", "MyCard"),
)

_SERVER_LISTS: Dict[str, Tuple[str, ...]] = {
    "cn_android": (
        "莱茵演习", "巴巴罗萨", "霸王行动", "冰山行动", "彩虹计划",
        "发电机计划", "瞭望台行动", "十字路口行动", "朱诺行动",
        "杜立特空袭", "地狱犬行动", "开罗宣言", "奥林匹克行动",
        "小王冠行动", "波茨坦公告", "白色方案", "瓦尔基里行动",
        "曼哈顿计划", "八月风暴", "秋季旅行", "水星行动", "莱茵河卫兵",
        "北极光计划", "长戟计划", "暴雨行动", "水仙行动", "冬月计划",
        "长弓计划", "裁决协议", "帷幕计划",
    ),
    "cn_ios": (
        "夏威夷", "珊瑚海", "中途岛", "铁底湾", "所罗门", "马里亚纳",
        "莱特湾", "硫磺岛", "冲绳岛", "阿留申群岛", "马耳他",
    ),
    "cn_channel": (
        "皇家巡游", "大西洋宪章", "十字军行动", "龙骑兵行动", "冥王星行动", "群岛计划",
    ),
    "en": ("Avrora", "Lexington", "Sandy", "Washington", "Amagi", "Little Enterprise"),
    "jp": (
        "ブレスト", "横須賀", "佐世保", "呉", "舞鶴",
        "ルルイエ", "サモア", "大湊", "トラック", "ラバウル",
        "鹿児島", "マドラス", "サンディエゴ", "竹敷", "キール",
        "若松", "オデッサ", "スイートバン",
    ),
    "tw": (),
}

_CLIENT_BY_KEY = {profile.key: profile for profile in _CLIENT_PROFILES}
_CLIENT_BY_PACKAGE = {profile.package_name: profile for profile in _CLIENT_PROFILES}


def list_azur_lane_client_profiles() -> List[AzurLaneClientProfile]:
    """返回所有已知碧蓝航线客户端。"""
    return list(_CLIENT_PROFILES)


def get_azur_lane_client_profile(key: str) -> Optional[AzurLaneClientProfile]:
    """按客户端 key 获取配置；unknown 返回 None。"""
    return _CLIENT_BY_KEY.get(str(key or "").strip())


def find_azur_lane_client_by_package(package_name: str) -> Optional[AzurLaneClientProfile]:
    """按 Android 包名反查客户端配置。"""
    return _CLIENT_BY_PACKAGE.get(str(package_name or "").strip())


def detect_installed_azur_lane_clients(package_names: Iterable[str]) -> List[AzurLaneClientProfile]:
    """从已安装包名列表中筛出碧蓝航线客户端。"""
    installed = {str(item).strip() for item in package_names if str(item).strip()}
    return [profile for profile in _CLIENT_PROFILES if profile.package_name in installed]


def select_azur_lane_client(package_names: Iterable[str], requested_key: str) -> Optional[AzurLaneClientProfile]:
    """根据用户选择和已安装包名选择客户端。"""
    installed = detect_installed_azur_lane_clients(package_names)
    requested = str(requested_key or "official_cn").strip() or "official_cn"
    if requested == "auto":
        official = get_azur_lane_client_profile("official_cn")
        if official in installed:
            return official
        return installed[0] if installed else None
    profile = get_azur_lane_client_profile(requested)
    if profile is None:
        profile = get_azur_lane_client_profile("official_cn")
    return profile if profile in installed else None


def list_azur_lane_servers(server_group: str) -> List[str]:
    """按服务器分组返回服务器名称。"""
    return list(_SERVER_LISTS.get(str(server_group or "").strip(), ()))


def get_azur_lane_server_display(server_key: str) -> str:
    """把服务器 key 转为用户可见文本。"""
    safe_key = str(server_key or "auto").strip() or "auto"
    return "自动进入当前/上次服务器" if safe_key == "auto" else safe_key
