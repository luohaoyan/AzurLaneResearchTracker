#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🔌 GUI 未来功能接口 (future_hooks.py)            ║
║                                                              ║
║  【一句话解释】提前定义自动化、OCR、模拟出货等未来页面的挂接点。║
║  【类比理解】它像港区船坞的预留泊位，功能船做好后可直接停靠。  ║
║  【数据流说明】FutureFeatureSpec → FeatureHookRegistry → UI。 ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class FutureFeatureSpec:
    """
    未来 GUI 功能描述对象。
    输入：
        key: 稳定功能键，用于后续代码查找。
        title: 页面展示标题。
        summary: 面向用户的功能说明。
        status: 当前状态，供内部代码判断，不直接展示给普通用户。
        entry_point: 未来真实实现的 Python 入口，不直接展示给普通用户。
    输出：
        不可变功能描述，供主窗口和占位页使用。
    使用示例：
        spec = FutureFeatureSpec("luck_prediction", "欧非预测", "...", "planned", "core.xxx")
    """

    key: str
    title: str
    summary: str
    status: str
    entry_point: str


class FeatureHookRegistry:
    """
    GUI 未来功能注册表。
    输入：
        无，默认注册 v0.6.0 及后续可能出现的自动化功能。
    输出：
        可查询、可绑定回调的功能列表。
    使用示例：
        registry = FeatureHookRegistry()
        registry.get("luck_prediction")
    """

    def __init__(self) -> None:
        """初始化默认功能泊位。"""
        self._features: Dict[str, FutureFeatureSpec] = {}
        self._callbacks: Dict[str, Callable[[FutureFeatureSpec], None]] = {}
        for feature in self._default_features():
            self.register(feature)

    def register(self, feature: FutureFeatureSpec) -> None:
        """
        注册一个未来功能。
        输入：
            feature: 未来功能描述。
        输出：
            None。
        使用示例：
            registry.register(FutureFeatureSpec(...))
        """
        self._features[feature.key] = feature

    def bind(self, key: str, callback: Callable[[FutureFeatureSpec], None]) -> bool:
        """
        绑定未来功能点击后的回调。
        输入：
            key: 功能键。
            callback: 接收 FutureFeatureSpec 的回调函数。
        输出：
            bool: 绑定成功返回 True，功能不存在返回 False。
        使用示例：
            registry.bind("research_simulation", open_simulator_page)
        """
        feature = self.get(key)
        if feature is None:
            return False
        self._callbacks[key] = callback
        return True

    def emit(self, key: str) -> bool:
        """
        触发某个未来功能。
        输入：
            key: 功能键。
        输出：
            bool: 有回调并触发成功返回 True，否则返回 False。
        使用示例：
            registry.emit("automation_capture")
        """
        feature = self.get(key)
        callback = self._callbacks.get(key)
        if feature is None or callback is None:
            return False
        callback(feature)
        return True

    def get(self, key: str) -> Optional[FutureFeatureSpec]:
        """
        按 key 查询未来功能。
        输入：
            key: 功能键。
        输出：
            FutureFeatureSpec 或 None。
        使用示例：
            feature = registry.get("luck_prediction")
        """
        return self._features.get(key)

    def get_all(self) -> List[FutureFeatureSpec]:
        """
        获取全部未来功能。
        输入：
            无。
        输出：
            List[FutureFeatureSpec]。
        使用示例：
            for feature in registry.get_all(): ...
        """
        return list(self._features.values())

    @staticmethod
    def _default_features() -> List[FutureFeatureSpec]:
        """构建默认未来功能列表，集中预留后续开发入口。"""
        return [
            FutureFeatureSpec(
                key="automation_capture",
                title="模拟器自动采集",
                summary="连接模拟器、采集截图，并把识别结果送入装备数据流程。",
                status="planned",
                entry_point="core.automation",
            ),
            FutureFeatureSpec(
                key="ocr_recognition",
                title="装备数字识别",
                summary="识别装备数量、碎片数量和玩家资源，未来约每 5 分钟刷新一次运行期状态。",
                status="planned",
                entry_point="core.recognition",
            ),
            FutureFeatureSpec(
                key="research_simulation",
                title="科研出货模拟",
                summary="按配置模拟科研产出，生成彩装、金装和碎片收益的期望分布。",
                status="planned",
                entry_point="core.simulation.research_drop",
            ),
            FutureFeatureSpec(
                key="luck_prediction",
                title="欧非走势预测",
                summary="结合历史记录和模拟结果，预测后续欧非值可能落入的区间。",
                status="planned",
                entry_point="core.simulation.luck_prediction",
            ),
            FutureFeatureSpec(
                key="crawler_update",
                title="资料爬取与更新",
                summary="从项目支持的数据源更新装备、图片路径和科研基础资料；网页结构变化导致失败时，引导用户前往 GitHub 下载新版本。",
                status="planned",
                entry_point="core.data.crawler_update",
            ),
            FutureFeatureSpec(
                key="adb_connection_check",
                title="ADB 连接预检",
                summary="检查模拟器配置、ADB 路径和设备串号，为后续自动化控制建立安全前置条件。",
                status="planned",
                entry_point="core.automation.adb_task_api",
            ),
            FutureFeatureSpec(
                key="adb_screenshot_capture",
                title="ADB 截图预检",
                summary="预留截图采集目录与命名规则，后续接入模拟器截图链路时可直接复用。",
                status="planned",
                entry_point="core.automation.adb_task_api",
            ),
            FutureFeatureSpec(
                key="ocr_equipment_scan",
                title="装备 OCR 预检",
                summary="固定装备数量和碎片数量的字段契约，后续可直接接入识别结果。",
                status="planned",
                entry_point="core.recognition.ocr_task_api",
            ),
            FutureFeatureSpec(
                key="ocr_resource_scan",
                title="资源 OCR 预检",
                summary="固定玩家名称、石油、物资和钻石字段，后续可刷新港区实况与运行期状态。",
                status="planned",
                entry_point="core.recognition.ocr_task_api",
            ),
            FutureFeatureSpec(
                key="environment_check",
                title="自动化环境预检",
                summary="检查自动化与 OCR 基础依赖、目录和配置，减少后续接入时的环境差异。",
                status="planned",
                entry_point="core.automation.adb_task_api",
            ),
            FutureFeatureSpec(
                key="anime_motion_assets",
                title="港区动效资源",
                summary="接入待机、识别完成、保存成功等轻量动效，让反馈更有港区氛围。",
                status="planned",
                entry_point="resources/animations",
            ),
            FutureFeatureSpec(
                key="mini_games",
                title="等待小游戏",
                summary="在长时间截图拼接或装备更新时，预留轻量小游戏入口。",
                status="planned",
                entry_point="ui.mini_games",
            ),
        ]


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_registry: Optional[FeatureHookRegistry] = None


def get_feature_hook_registry() -> FeatureHookRegistry:
    """
    获取 GUI 未来功能注册表。
    输入：
        无。
    输出：
        FeatureHookRegistry: 全局共享注册表。
    使用示例：
        registry = get_feature_hook_registry()
    """
    global _registry
    if _registry is None:
        _registry = FeatureHookRegistry()
    return _registry
