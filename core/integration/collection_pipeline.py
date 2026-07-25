#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║          🧭 自动化采集整合流水线 (collection_pipeline.py)     ║
║                                                              ║
║  【一句话解释】串联 ADB 截图、OCR 识别、预览缓存和确认写入。  ║
║  【类比理解】它像港区验收台，识别结果先摆上桌，确认后才入账。║
║  【数据流说明】采集模式 → ADB/OCR → CollectionPreview → CSV。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from core.automation.adb_task_api import get_adb_task_api
from core.calculation.user_data_manager import get_user_data_manager
from core.contracts import (
    EquipmentRecognitionRecord,
    RecognitionScene,
    ResourceRecognitionRecord,
    StructuredTaskResult,
    TaskExecutionContext,
)
from core.recognition.equipment_name_resolver import get_equipment_name_resolver
from core.recognition.ocr_task_api import get_ocr_task_api
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger


# ============================================================
# 🏗️ 第二部分：数据结构
# ============================================================

class CollectionPipelineResult(StructuredTaskResult):
    """
    自动化采集流水线执行结果。
    输入：
        success/status/message/detail/payload/warnings。
    输出：
        与 ADB/OCR/Bridge 一致的结构化结果。
    使用示例：
        result = pipeline.run_collection("quick")
    """


@dataclass(frozen=True)
class CollectionProfile:
    """
    采集模式配置。
    输入：
        key/title/collect_resources/collect_equipment 等配置字段。
    输出：
        控制整合流水线执行哪些步骤的不可变对象。
    使用示例：
        profile = CollectionProfile.from_config("quick", config)
    """

    key: str
    title: str
    description: str = ""
    collect_resources: bool = True
    collect_equipment: bool = True
    collect_research: bool = False
    allow_partial: bool = True
    navigation_sequences: Tuple[str, ...] = ()
    estimated_seconds: int = 30

    @classmethod
    def from_config(cls, key: str, data: Dict[str, Any]) -> "CollectionProfile":
        """从 JSON 字典构造采集模式，缺失字段使用保守默认值。"""
        flags = data.get("steps", {}) if isinstance(data.get("steps"), dict) else {}
        return cls(
            key=key,
            title=str(data.get("title") or key),
            description=str(data.get("description") or ""),
            collect_resources=bool(flags.get("resources", True)),
            collect_equipment=bool(flags.get("equipment", True)),
            collect_research=bool(flags.get("research", False)),
            allow_partial=bool(data.get("allow_partial", True)),
            navigation_sequences=tuple(str(item) for item in data.get("navigation_sequences", []) if str(item).strip()),
            estimated_seconds=int(data.get("estimated_seconds", 30) or 30),
        )


@dataclass(frozen=True)
class CollectionPreview:
    """
    等待用户确认的采集预览。
    输入：
        preview_id/profile_key/equipment_records/resource_status 等字段。
    输出：
        可展示在 GUI 中、但尚未写入每日 CSV 的识别结果。
    使用示例：
        preview.to_batch_records()
    """

    preview_id: str
    profile_key: str
    profile_title: str
    created_at: datetime = field(default_factory=datetime.now)
    screenshot_paths: Tuple[str, ...] = ()
    equipment_records: Tuple[EquipmentRecognitionRecord, ...] = ()
    resource_status: Optional[ResourceRecognitionRecord] = None
    warnings: Tuple[str, ...] = ()

    def to_batch_records(self) -> Dict[str, Dict[str, int]]:
        """转换为 UserDataManager.update_batch 可直接接收的记录字典。"""
        return {
            record.equipment_id: {
                "equipment_count": int(record.equipment_count),
                "fragment_count": int(record.fragment_count),
            }
            for record in self.equipment_records
        }

    def to_payload(self) -> Dict[str, Any]:
        """转换为 GUI 预览表和测试可读取的基础类型字典。"""
        return {
            "preview_id": self.preview_id,
            "profile_key": self.profile_key,
            "profile_title": self.profile_title,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "screenshot_paths": list(self.screenshot_paths),
            "equipment_records": [record.to_dict() for record in self.equipment_records],
            "resource_status": self.resource_status.to_dict() if self.resource_status else None,
            "warnings": list(self.warnings),
        }


# ============================================================
# 🧠 第三部分：整合流水线
# ============================================================

class AutomationCollectionPipeline:
    """
    ADB/OCR 自动化采集整合流水线。
    输入：
        无，生产环境使用全局 ADB/OCR/UserData/Runtime 管理器。
    输出：
        采集预览结果；只有 confirm_preview 会写入每日用户记录。
    使用示例：
        pipeline = get_automation_collection_pipeline()
        result = pipeline.run_collection("quick")
    """

    _instance: Optional["AutomationCollectionPipeline"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "AutomationCollectionPipeline":
        """单例模式：GUI 与桥接层共享同一份预览缓存。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化流水线，重复初始化时直接返回。"""
        if hasattr(self, "_initialized"):
            return
        self.logger = get_logger()
        self.config_loader = get_config_loader()
        self._adb_api: Optional[Any] = None
        self._ocr_api: Optional[Any] = None
        self._user_data_manager: Optional[Any] = None
        self._runtime_manager: Optional[Any] = None
        self._pending_previews: Dict[str, CollectionPreview] = {}
        self._initialized = True

    @property
    def adb_api(self) -> Any:
        """延迟获取 ADB API，避免 GUI 启动时提前触碰设备实现。"""
        if self._adb_api is None:
            self._adb_api = get_adb_task_api()
        return self._adb_api

    @property
    def ocr_api(self) -> Any:
        """延迟获取 OCR API，避免 GUI 启动时加载模型或可选依赖。"""
        if self._ocr_api is None:
            self._ocr_api = get_ocr_task_api()
        return self._ocr_api

    @property
    def user_data_manager(self) -> Any:
        """延迟获取用户数据管理器，只在确认写入时真正使用。"""
        if self._user_data_manager is None:
            self._user_data_manager = get_user_data_manager()
        return self._user_data_manager

    @property
    def runtime_manager(self) -> Any:
        """延迟获取运行期状态管理器，用于刷新港区资源。"""
        if self._runtime_manager is None:
            self._runtime_manager = get_runtime_state_manager()
        return self._runtime_manager

    def list_profiles(self) -> List[CollectionProfile]:
        """
        列出可用采集模式。
        输入：
            无。
        输出：
            List[CollectionProfile]，顺序来自 collection_profiles.json。
        使用示例：
            profiles = pipeline.list_profiles()
        """
        raw_config = self.config_loader.get_automation_config("collection_profiles")
        profiles_config = raw_config.get("profiles", {}) if isinstance(raw_config, dict) else {}
        order = raw_config.get("order", []) if isinstance(raw_config, dict) else []
        if not profiles_config:
            profiles_config = self._default_profiles()
            order = ["quick", "full", "custom"]
        ordered_keys = [str(key) for key in order if str(key) in profiles_config]
        ordered_keys.extend(key for key in profiles_config if key not in ordered_keys)
        return [
            CollectionProfile.from_config(key, profiles_config[key])
            for key in ordered_keys
            if isinstance(profiles_config[key], dict)
        ]

    def get_profile(self, profile_key: str) -> Optional[CollectionProfile]:
        """按 key 获取采集模式；不存在时返回 None。"""
        clean_key = str(profile_key or "").strip()
        for profile in self.list_profiles():
            if profile.key == clean_key:
                return profile
        return None

    def run_collection(
        self,
        profile_key: str = "quick",
        task_context: Optional[TaskExecutionContext] = None,
    ) -> CollectionPipelineResult:
        """
        执行采集并生成预览。
        输入：
            profile_key: quick/full/custom 等采集模式键。
            task_context: TaskManager 注入的进度和取消上下文。
        输出：
            CollectionPipelineResult；装备记录只进入预览缓存，不写入 CSV。
        使用示例：
            result = pipeline.run_collection("quick", task_context=context)
        """
        profile = self.get_profile(profile_key)
        if profile is None:
            return CollectionPipelineResult(False, "unavailable", "未找到采集模式配置。", f"profile={profile_key}")

        warnings: List[str] = []
        screenshots: List[str] = []
        equipment_records: List[EquipmentRecognitionRecord] = []
        resource_status: Optional[ResourceRecognitionRecord] = None

        self._report(task_context, 3, f"正在准备{profile.title}。", profile.description)
        self._raise_if_cancelled(task_context, f"{profile.title}已取消。")

        connection_result = self.adb_api.check_connection(task_context=task_context)
        if not bool(connection_result.success):
            return self._failed_from_step("ADB 连接检查失败。", connection_result, warnings)
        warnings.extend(self._warnings_from_result(connection_result))

        if profile.collect_resources:
            self._report(task_context, 22, "正在采集港区资源截图。", RecognitionScene.HARBOR.value)
            harbor_path = self._capture_scene(RecognitionScene.HARBOR, task_context, warnings, profile.allow_partial)
            if harbor_path:
                screenshots.append(harbor_path)
            self._report(task_context, 38, "正在识别港区资源。", harbor_path or "")
            resource_status = self._scan_resource_status(harbor_path, task_context, warnings, profile.allow_partial)
            if resource_status is not None:
                # 资源状态只更新运行期内存，不写每日装备记录，因此不需要确认。
                self.runtime_manager.update_player_from_ocr(resource_status.to_dict())

        if profile.collect_equipment:
            self._report(task_context, 56, "正在采集装备列表截图。", RecognitionScene.EQUIPMENT_LIST.value)
            equipment_path = self._capture_scene(RecognitionScene.EQUIPMENT_LIST, task_context, warnings, profile.allow_partial)
            if equipment_path:
                screenshots.append(equipment_path)
            self._report(task_context, 72, "正在识别装备数量与碎片。", equipment_path or "")
            equipment_records.extend(
                self._scan_equipment_records(equipment_path, task_context, warnings, profile.allow_partial)
            )

        self._raise_if_cancelled(task_context, f"{profile.title}已取消。")
        preview = CollectionPreview(
            preview_id=f"preview_{uuid4().hex[:12]}",
            profile_key=profile.key,
            profile_title=profile.title,
            screenshot_paths=tuple(screenshots),
            equipment_records=tuple(equipment_records),
            resource_status=resource_status,
            warnings=tuple(warnings),
        )
        self._pending_previews[preview.preview_id] = preview

        requires_confirmation = bool(equipment_records)
        payload = self._build_preview_payload(preview, requires_confirmation)
        if requires_confirmation:
            message = f"{profile.title}已生成 {len(equipment_records)} 条装备记录预览，请确认后写入。"
            status = "preview_ready"
        else:
            message = f"{profile.title}已完成，当前 OCR 未返回可确认的装备记录。"
            status = "preview_empty"
        self._report(task_context, 100, message, f"warnings={len(warnings)}")
        self.logger.info(message)
        return CollectionPipelineResult(True, status, message, f"预览ID={preview.preview_id}", payload, tuple(warnings))

    def confirm_preview(
        self,
        preview_id: str,
        target_date: Optional[str] = None,
        task_context: Optional[TaskExecutionContext] = None,
    ) -> CollectionPipelineResult:
        """
        用户确认后写入每日装备记录。
        输入：
            preview_id: run_collection 返回的预览 ID。
            target_date: 可选日期，默认写入今天。
            task_context: TaskManager 注入的进度和取消上下文。
        输出：
            CollectionPipelineResult，包含 UserDataManager.update_batch 结果。
        使用示例：
            result = pipeline.confirm_preview("preview_xxx")
        """
        self._raise_if_cancelled(task_context, "采集结果写入已取消。")
        preview = self._pending_previews.get(str(preview_id or "").strip())
        if preview is None:
            return CollectionPipelineResult(False, "missing", "未找到待确认的采集预览，可能已经写入或丢弃。", f"preview_id={preview_id}")
        if not preview.equipment_records:
            return CollectionPipelineResult(False, "empty", "该采集预览没有可写入的装备记录。", f"preview_id={preview_id}")

        self._report(task_context, 20, "正在写入今日装备记录。", preview.profile_title)
        write_result = self.user_data_manager.update_batch(preview.to_batch_records(), target_date)
        failed = int(write_result.get("failed", 0) or 0)
        success = failed == 0
        status = "success" if success else "partial"
        message = (
            f"已写入 {write_result.get('success', 0)} 条装备记录。"
            if success
            else f"采集记录部分写入：成功 {write_result.get('success', 0)} 条，失败 {failed} 条。"
        )
        payload = self._build_preview_payload(preview, False)
        payload["write_result"] = write_result
        self._pending_previews.pop(preview.preview_id, None)
        self.runtime_manager.set_task_state(TaskStateKind.IDLE, 100, message, "采集结果确认")
        self._report(task_context, 100, message, f"failed={failed}")
        self.logger.info(message)
        return CollectionPipelineResult(success, status, message, f"预览ID={preview.preview_id}", payload, preview.warnings)

    def discard_preview(self, preview_id: str) -> bool:
        """丢弃未确认的采集预览，不写入任何用户记录。"""
        return self._pending_previews.pop(str(preview_id or "").strip(), None) is not None

    def get_pending_preview(self, preview_id: str) -> Optional[CollectionPreview]:
        """读取一条待确认预览，供 GUI 或测试查看。"""
        return self._pending_previews.get(str(preview_id or "").strip())

    def reset_for_tests(
        self,
        adb_api: Optional[Any] = None,
        ocr_api: Optional[Any] = None,
        user_data_manager: Optional[Any] = None,
        runtime_manager: Optional[Any] = None,
    ) -> None:
        """重置可注入依赖和预览缓存，仅供开发测试使用。"""
        self._adb_api = adb_api
        self._ocr_api = ocr_api
        self._user_data_manager = user_data_manager
        self._runtime_manager = runtime_manager
        self._pending_previews.clear()

    def _capture_scene(
        self,
        scene: RecognitionScene,
        task_context: Optional[TaskExecutionContext],
        warnings: List[str],
        allow_partial: bool,
    ) -> Optional[str]:
        """调用 ADB 截图并提取截图路径，失败时按采集模式决定中断或告警。"""
        self._raise_if_cancelled(task_context, f"{scene.value} 截图已取消。")
        result = self._capture_screenshot_with_real_mode(scene, task_context)
        warnings.extend(self._warnings_from_result(result))
        if not bool(result.success):
            if allow_partial:
                warnings.append(f"{scene.value} 截图失败：{result.message}")
                return None
            raise RuntimeError(result.message)
        payload = self._payload_from_result(result)
        screenshot_path = payload.get("screenshot_path")
        return str(screenshot_path) if screenshot_path else None

    def _capture_screenshot_with_real_mode(
        self,
        scene: RecognitionScene,
        task_context: Optional[TaskExecutionContext],
    ) -> Any:
        """调用 ADB 截图；新 ADB API 支持 real_capture 时启用真实截图。"""
        capture = self.adb_api.capture_screenshot
        try:
            signature = inspect.signature(capture)
        except (TypeError, ValueError):
            return capture(scene=scene, task_context=task_context)
        if "real_capture" in signature.parameters:
            return capture(scene=scene, task_context=task_context, real_capture=True)
        return capture(scene=scene, task_context=task_context)

    def _scan_resource_status(
        self,
        screenshot_path: Optional[str],
        task_context: Optional[TaskExecutionContext],
        warnings: List[str],
        allow_partial: bool,
    ) -> Optional[ResourceRecognitionRecord]:
        """调用 OCR 资源识别并转换为 ResourceRecognitionRecord。"""
        self._raise_if_cancelled(task_context, "资源 OCR 已取消。")
        result = self.ocr_api.scan_resource_status(
            screenshot_path=screenshot_path,
            scene=RecognitionScene.HARBOR,
            task_context=task_context,
        )
        warnings.extend(self._warnings_from_result(result))
        if not bool(result.success):
            if allow_partial:
                warnings.append(f"资源 OCR 失败：{result.message}")
                return None
            raise RuntimeError(result.message)
        raw_resource = self._payload_from_result(result).get("resource_status")
        if not isinstance(raw_resource, dict):
            return None
        try:
            return ResourceRecognitionRecord(
                str(raw_resource.get("player_name", "等待识别")),
                int(raw_resource.get("oil", 0) or 0),
                int(raw_resource.get("coins", 0) or 0),
                int(raw_resource.get("gems", 0) or 0),
                float(raw_resource.get("confidence", 0.0) or 0.0),
            )
        except (TypeError, ValueError) as exc:
            warnings.append(f"资源 OCR 结果已跳过：{exc}")
            return None

    def _scan_equipment_records(
        self,
        screenshot_path: Optional[str],
        task_context: Optional[TaskExecutionContext],
        warnings: List[str],
        allow_partial: bool,
    ) -> List[EquipmentRecognitionRecord]:
        """调用 OCR 装备识别并转换为标准每日记录字段。"""
        self._raise_if_cancelled(task_context, "装备 OCR 已取消。")
        result = self.ocr_api.scan_equipment_counts(
            screenshot_path=screenshot_path,
            scene=RecognitionScene.EQUIPMENT_LIST,
            task_context=task_context,
        )
        warnings.extend(self._warnings_from_result(result))
        if not bool(result.success):
            if allow_partial:
                warnings.append(f"装备 OCR 失败：{result.message}")
                return []
            raise RuntimeError(result.message)
        payload = self._payload_from_result(result)
        raw_records = payload.get("equipment_records", [])
        if not raw_records:
            # 设计图识别链路以 final_equipment_name 为主输出；整合层在这里
            # 把名称解析成当前 equipment_library.csv 中的运行时 ID。
            raw_records = payload.get("cards", [])
        return self._equipment_records_from_payload(raw_records, warnings)

    @staticmethod
    def _equipment_records_from_payload(
        raw_records: Any,
        warnings: List[str],
    ) -> List[EquipmentRecognitionRecord]:
        """把 OCR payload 中的装备记录安全转换为契约对象。"""
        if not isinstance(raw_records, Iterable) or isinstance(raw_records, (str, bytes, dict)):
            return []
        records: List[EquipmentRecognitionRecord] = []
        for raw_record in raw_records:
            if not isinstance(raw_record, dict):
                warnings.append("已跳过非字典装备识别记录。")
                continue
            status = str(raw_record.get("final_status") or raw_record.get("status") or "").strip().lower()
            if status and status not in {"success", "ok", "ready"}:
                warnings.append(
                    f"装备识别记录已跳过：status={status}，仅允许成功或明确可写入结果。"
                )
                continue

            equipment_id = str(raw_record.get("equipment_id", "") or "").strip()
            if equipment_id.lower() in {"unknown", "none", "null"}:
                equipment_id = ""
            if not equipment_id:
                equipment_id = AutomationCollectionPipeline._resolve_equipment_id_from_name(raw_record, warnings)
            if not equipment_id:
                continue
            try:
                records.append(
                    EquipmentRecognitionRecord(
                        equipment_id,
                        int(raw_record.get("equipment_count", 0) or 0),
                        int(
                            raw_record.get("fragment_count", raw_record.get("owned_fragment_count", 0))
                            or 0
                        ),
                        float(raw_record.get("confidence", 0.0) or 0.0),
                    )
                )
            except (TypeError, ValueError) as exc:
                warnings.append(f"装备识别记录已跳过：{exc}")
        return records

    @staticmethod
    def _resolve_equipment_id_from_name(
        raw_record: Dict[str, Any],
        warnings: List[str],
    ) -> str:
        """从 OCR 主输出名称解析当前装备库 ID，失败时只记录告警并跳过。"""
        name_fields = (
            "final_equipment_name",
            "equipment_name",
            "name_resolve_equipment_name",
            "opencv_equipment_name",
            "nn_equipment_name",
        )
        raw_name = next(
            (
                str(raw_record.get(field, "") or "").strip()
                for field in name_fields
                if str(raw_record.get(field, "") or "").strip()
            ),
            "",
        )
        if not raw_name:
            warnings.append("装备识别记录缺少 equipment_id 和 equipment_name，已跳过。")
            return ""

        resolved = get_equipment_name_resolver().resolve(raw_name)
        if resolved.success and resolved.equipment_id:
            return resolved.equipment_id
        warnings.append(
            f"装备名称无法映射到当前 equipment_library.csv：{raw_name}（{resolved.status}）"
        )
        return ""

    @staticmethod
    def _payload_from_result(result: Any) -> Dict[str, Any]:
        """兼容 dataclass 结果和 dict 结果读取 payload。"""
        if isinstance(result, dict):
            payload = result.get("payload", {})
        else:
            payload = getattr(result, "payload", {})
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _warnings_from_result(result: Any) -> List[str]:
        """兼容 dataclass 结果和 dict 结果读取 warnings。"""
        if isinstance(result, dict):
            warnings = result.get("warnings", [])
        else:
            warnings = getattr(result, "warnings", [])
        return [str(item) for item in warnings or []]

    @staticmethod
    def _failed_from_step(
        message: str,
        result: Any,
        warnings: List[str],
    ) -> CollectionPipelineResult:
        """把底层步骤失败转换为统一流水线失败结果。"""
        detail = str(result.get("detail", "") if isinstance(result, dict) else getattr(result, "detail", ""))
        payload = AutomationCollectionPipeline._payload_from_result(result)
        return CollectionPipelineResult(False, "error", message, detail, payload, tuple(warnings))

    @staticmethod
    def _build_preview_payload(preview: CollectionPreview, requires_confirmation: bool) -> Dict[str, Any]:
        """构建 Bridge 和 GUI 可读取的预览 payload。"""
        payload = preview.to_payload()
        payload["preview"] = preview.to_payload()
        payload["requires_confirmation"] = requires_confirmation
        payload["write_result"] = None
        return payload

    @staticmethod
    def _report(
        task_context: Optional[TaskExecutionContext],
        progress: int,
        message: str,
        detail: str = "",
    ) -> None:
        """统一上报任务进度，兼容无 TaskManager 的单元测试。"""
        if task_context is not None:
            task_context.report_progress(progress, message, detail)

    @staticmethod
    def _raise_if_cancelled(task_context: Optional[TaskExecutionContext], message: str) -> None:
        """在安全点响应用户取消请求。"""
        if task_context is not None:
            task_context.raise_if_cancelled(message)

    @staticmethod
    def _default_profiles() -> Dict[str, Dict[str, Any]]:
        """配置文件缺失时使用的保守默认采集模式。"""
        return {
            "quick": {
                "title": "快速采集",
                "description": "采集港区资源与当前装备页。",
                "steps": {"resources": True, "equipment": True, "research": False},
                "allow_partial": True,
                "navigation_sequences": ["return_home", "capture_harbor", "open_equipment"],
                "estimated_seconds": 30,
            },
            "full": {
                "title": "完整采集",
                "description": "预留完整装备仓库与科研页遍历流程。",
                "steps": {"resources": True, "equipment": True, "research": True},
                "allow_partial": True,
                "navigation_sequences": ["return_home", "capture_harbor", "open_equipment", "open_research"],
                "estimated_seconds": 180,
            },
            "custom": {
                "title": "自定义采集",
                "description": "预留用户自选采集内容。",
                "steps": {"resources": True, "equipment": True, "research": False},
                "allow_partial": True,
                "navigation_sequences": [],
                "estimated_seconds": 60,
            },
        }


# ============================================================
# 🌐 第四部分：全局访问函数
# ============================================================

_automation_collection_pipeline: Optional[AutomationCollectionPipeline] = None


def get_automation_collection_pipeline() -> AutomationCollectionPipeline:
    """
    获取全局自动化采集整合流水线。
    输入：
        无。
    输出：
        AutomationCollectionPipeline: 全局共享流水线。
    使用示例：
        pipeline = get_automation_collection_pipeline()
    """
    global _automation_collection_pipeline
    if _automation_collection_pipeline is None:
        _automation_collection_pipeline = AutomationCollectionPipeline()
    return _automation_collection_pipeline
