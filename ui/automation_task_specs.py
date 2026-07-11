#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║              🧭 自动化任务规格表 (automation_task_specs.py)   ║
║                                                              ║
║  【一句话解释】集中定义 GUI 可启动的 crawler/ADB/OCR 长任务。 ║
║  【类比理解】它像港区任务公告板，按钮只按公告板派发任务。      ║
║  【数据流说明】任务 key → BackgroundTaskSpec → TaskManager。  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.state.runtime_state import TaskStateKind
from ui.task_manager import BackgroundTaskSpec


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class AutomationTaskDefinition:
    """
    GUI 自动化任务定义。
    输入：
        key: 稳定任务键。
        title: 任务清单展示标题。
        kind: 运行期任务类型。
        start_message: 启动时提示。
        bridge_method: AutomationBridge 上的无参方法名。
        feature_key: FutureHookRegistry 使用的功能键。
        button_text: GUI 按钮文案。
        summary: 卡片说明。
        cancel_supported: 是否支持取消预留。
    输出：
        可转换为 BackgroundTaskSpec 的定义对象。
    使用示例：
        spec = definition.to_background_spec()
    """

    key: str
    title: str
    kind: TaskStateKind
    start_message: str
    bridge_method: str
    feature_key: str
    button_text: str
    summary: str
    cancel_supported: bool = False

    def to_background_spec(self) -> BackgroundTaskSpec:
        """
        转换为 GUI 任务管理器使用的任务规格。
        输入：
            无。
        输出：
            BackgroundTaskSpec。
        使用示例：
            manager.start_task(definition.to_background_spec(), runner)
        """
        return BackgroundTaskSpec(
            self.key,
            self.title,
            self.kind,
            self.start_message,
            cancel_supported=self.cancel_supported,
        )


# ============================================================
# 🌐 第三部分：全局访问函数
# ============================================================

_TASK_DEFINITIONS: Dict[str, AutomationTaskDefinition] = {
    "crawler_update": AutomationTaskDefinition(
        key="crawler_update",
        title="资料爬取与更新",
        kind=TaskStateKind.EQUIPMENT_UPDATING,
        start_message="正在更新装备与科研基础资料。",
        bridge_method="run_crawler_update",
        feature_key="crawler_update",
        button_text="检查并更新资料",
        summary="调用爬虫同步入口，更新装备表、图片表和科研期数表。",
    ),
    "adb_connection_check": AutomationTaskDefinition(
        key="adb_connection_check",
        title="ADB 连接预检",
        kind=TaskStateKind.AUTO_TESTING,
        start_message="正在预检模拟器 ADB 配置。",
        bridge_method="run_adb_connection_check",
        feature_key="adb_connection_check",
        button_text="检测连接",
        summary="检查当前模拟器配置、ADB 路径和未来设备串号，不启动真实模拟器。",
    ),
    "adb_screenshot_capture": AutomationTaskDefinition(
        key="adb_screenshot_capture",
        title="ADB 截图预检",
        kind=TaskStateKind.SCREENSHOT_CAPTURING,
        start_message="正在预检截图采集目录。",
        bridge_method="run_adb_screenshot_capture",
        feature_key="adb_screenshot_capture",
        button_text="采集截图预检",
        summary="准备截图输出目录和命名规则，为后续 ADB 截图链路预留接口。",
        cancel_supported=True,
    ),
    "ocr_equipment_scan": AutomationTaskDefinition(
        key="ocr_equipment_scan",
        title="装备 OCR 预检",
        kind=TaskStateKind.OCR_PROCESSING,
        start_message="正在预检装备 OCR 识别结构。",
        bridge_method="run_ocr_equipment_scan",
        feature_key="ocr_equipment_scan",
        button_text="装备识别预检",
        summary="固定装备数量与碎片数量的识别结果字段，后续可直接写入数据层。",
        cancel_supported=True,
    ),
    "ocr_resource_scan": AutomationTaskDefinition(
        key="ocr_resource_scan",
        title="资源 OCR 预检",
        kind=TaskStateKind.OCR_PROCESSING,
        start_message="正在预检玩家资源 OCR 结构。",
        bridge_method="run_ocr_resource_scan",
        feature_key="ocr_resource_scan",
        button_text="资源识别预检",
        summary="固定玩家名称、石油、物资和钻石字段，后续可刷新港区实况。",
        cancel_supported=True,
    ),
    "environment_check": AutomationTaskDefinition(
        key="environment_check",
        title="自动化环境预检",
        kind=TaskStateKind.AUTO_TESTING,
        start_message="正在检查自动化与 OCR 基础环境。",
        bridge_method="run_automation_environment_check",
        feature_key="environment_check",
        button_text="检查环境",
        summary="检查配置、目录和可选依赖，为 v0.6.0 自动化闭环做准备。",
    ),
}


def get_automation_task_definition(key: str) -> Optional[AutomationTaskDefinition]:
    """
    按 key 获取自动化任务定义。
    输入：
        key: 任务键。
    输出：
        AutomationTaskDefinition 或 None。
    使用示例：
        definition = get_automation_task_definition("ocr_equipment_scan")
    """
    return _TASK_DEFINITIONS.get(key)


def get_automation_task_spec(key: str) -> BackgroundTaskSpec:
    """
    按 key 获取 BackgroundTaskSpec。
    输入：
        key: 任务键。
    输出：
        BackgroundTaskSpec；key 不存在时抛出 KeyError。
    使用示例：
        spec = get_automation_task_spec("environment_check")
    """
    definition = _TASK_DEFINITIONS[key]
    return definition.to_background_spec()


def list_automation_task_definitions(keys: Optional[List[str]] = None) -> List[AutomationTaskDefinition]:
    """
    获取自动化任务定义列表。
    输入：
        keys: 可选任务键顺序；为空时返回全部。
    输出：
        List[AutomationTaskDefinition]。
    使用示例：
        cards = list_automation_task_definitions(["adb_connection_check"])
    """
    if keys is None:
        return list(_TASK_DEFINITIONS.values())
    return [_TASK_DEFINITIONS[key] for key in keys]
