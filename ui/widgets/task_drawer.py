#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                 🧾 悬浮任务清单抽屉 (task_drawer.py)         ║
║                                                              ║
║  【一句话解释】把后台任务清单做成右侧悬浮折叠栏。              ║
║  【类比理解】它像港区右侧任务板，平时贴边收起，需要时滑出查看。║
║  【数据流说明】GuiTaskManager → TaskDrawer → 用户查看/清理。  ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.task_manager import get_gui_task_manager


# ============================================================
# 🧩 第二部分：格式化辅助函数
# ============================================================

def format_task_status_label(status: str) -> str:
    """
    把内部任务状态转换为用户可读标签。
    输入：
        status: TaskSnapshot.status。
    输出：
        str: 用户可见状态文案。
    使用示例：
        label = format_task_status_label("running")
    """
    mapping = {
        "running": "⏳ 执行中",
        "success": "✅ 已执行",
        "error": "❌ 执行失败",
        "missing": "⚠️ 缺少模块",
        "unavailable": "⚠️ 不可用",
        "rejected": "⛔ 已拒绝",
    }
    return mapping.get(status, "ℹ️ 已记录")


def format_task_progress_bar(progress: int) -> str:
    """
    生成轻量文本进度条。
    输入：
        progress: 0-100 任务进度。
    输出：
        str: 10 格文本进度条。
    使用示例：
        text = format_task_progress_bar(50)
    """
    safe_progress = max(0, min(100, int(progress)))
    filled_count = round(safe_progress / 10)
    return f"[{'█' * filled_count}{'░' * (10 - filled_count)}]"


def build_task_summary_text(limit: int = 8) -> str:
    """
    生成诊断信息里的任务清单文本。
    输入：
        limit: 最多导出的任务数量。
    输出：
        str: 多行任务摘要。
    使用示例：
        text = build_task_summary_text()
    """
    snapshots = get_gui_task_manager().get_task_snapshots()
    if not snapshots:
        return "无"
    lines: List[str] = []
    for snapshot in snapshots[:limit]:
        status = format_task_status_label(str(snapshot.get("status", "")))
        title = str(snapshot.get("title", "未知任务"))
        progress = int(snapshot.get("progress", 0) or 0)
        message = str(snapshot.get("message", ""))
        lines.append(f"{status} {title} {progress}% {message}".strip())
    return "\n".join(lines)


# ============================================================
# 🏗️ 第三部分：核心组件
# ============================================================

class TaskDrawer(QWidget):
    """
    右侧悬浮任务清单抽屉。
    输入：
        parent: 通常为主窗口 central widget。
    输出：
        悬浮覆盖式 QWidget，不参与主布局宽度计算。
    使用示例：
        drawer = TaskDrawer(central)
        drawer.fit_to_parent()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化右侧任务抽屉，默认贴边收起。"""
        super().__init__(parent)
        self.setObjectName("task_drawer")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.collapsed_width = 48
        self.collapsed_height = 56
        self.collapsed_top_offset = 12
        self.expanded_width = 380
        self.animation_duration_ms = 180
        self._expanded = False
        self._animation: Optional[QPropertyAnimation] = None
        self.task_manager = get_gui_task_manager()

        self._build_ui()
        self._set_content_visible(False)
        self.task_manager.taskChanged.connect(self.refresh_task_list)
        self.task_list.itemSelectionChanged.connect(self._update_task_actions)
        self.refresh_task_list()

    def _build_ui(self) -> None:
        """构建抽屉界面。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.panel = QFrame()
        self.panel.setObjectName("task_drawer_panel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(8, 12, 8, 12)
        panel_layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.title_label = QLabel("任务清单")
        self.title_label.setObjectName("task_drawer_title")
        self.toggle_button = QPushButton("<")
        self.toggle_button.setObjectName("task_drawer_toggle_button")
        self.toggle_button.setToolTip("展开或收起任务清单")
        self.toggle_button.setFixedSize(32, 32)
        self.toggle_button.clicked.connect(self.toggle)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.toggle_button, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.task_list = QListWidget()
        self.task_list.setObjectName("task_list")
        self.task_list.setToolTip("显示当前和最近的后台长任务。")

        self.cancel_task_button = QPushButton("取消任务")
        self.cancel_task_button.setToolTip("预留给 OCR 等可安全重启任务；当前长任务不支持强制中断。")
        self.cancel_task_button.clicked.connect(self._request_cancel_task)
        self.delete_task_button = QPushButton("删除选中")
        self.delete_task_button.setToolTip("删除已执行完毕的任务记录。")
        self.delete_task_button.clicked.connect(self._delete_selected_task)
        self.clear_finished_button = QPushButton("清理已完成")
        self.clear_finished_button.setToolTip("一键清理所有已完成或已失败的任务。")
        self.clear_finished_button.clicked.connect(self._clear_finished_tasks)

        panel_layout.addLayout(header)
        panel_layout.addWidget(self.task_list, stretch=1)
        panel_layout.addWidget(self.cancel_task_button)
        panel_layout.addWidget(self.delete_task_button)
        panel_layout.addWidget(self.clear_finished_button)
        root.addWidget(self.panel)

    def toggle(self) -> None:
        """展开或收起任务抽屉。"""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        """
        设置任务抽屉展开状态。
        输入：
            expanded: True 展开，False 收起。
            animate: 是否播放宽度动画。
        输出：
            None。
        使用示例：
            drawer.set_expanded(True)
        """
        self._expanded = expanded
        self.toggle_button.setText(">" if expanded else "<")
        if expanded:
            self._set_content_visible(True)

        target_width = self.expanded_width if expanded else self.collapsed_width
        if not animate:
            self._set_overlay_width(target_width)
            self._finish_drawer_animation(expanded)
            return

        if self._animation is not None:
            self._animation.stop()
        self._animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._animation.setDuration(self.animation_duration_ms)
        self._animation.setStartValue(self.width() or self.collapsed_width)
        self._animation.setEndValue(target_width)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.valueChanged.connect(lambda value: self._set_overlay_width(int(value)))
        self._animation.finished.connect(lambda: self._finish_drawer_animation(expanded))
        self._animation.start()
        QTimer.singleShot(
            self.animation_duration_ms + 40,
            lambda: self._finish_drawer_animation(expanded),
        )

    def fit_to_parent(self) -> None:
        """
        按父组件尺寸重新贴附到右侧。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.fit_to_parent()
        """
        target_width = self.expanded_width if self._expanded else self.collapsed_width
        self._set_overlay_width(target_width)
        self.raise_()

    def refresh_task_list(self) -> None:
        """
        刷新任务列表。
        输入：
            无。
        输出：
            None。
        使用示例：
            drawer.refresh_task_list()
        """
        snapshots = self.task_manager.get_task_snapshots()
        self.task_list.clear()
        if not snapshots:
            self.task_list.addItem("暂无后台任务")
            self.cancel_task_button.setEnabled(False)
            self.delete_task_button.setEnabled(False)
            self.clear_finished_button.setEnabled(False)
            return

        active_cancellable = False
        finished_count = 0
        for snapshot in snapshots[:12]:
            status = format_task_status_label(str(snapshot.get("status", "")))
            progress = int(snapshot.get("progress", 0) or 0)
            title = str(snapshot.get("title", "未知任务"))
            message = str(snapshot.get("message", ""))
            text = f"{status} {title} · {progress}% {format_task_progress_bar(progress)}"
            if message:
                text = f"{text}\n{message}"
            item = QListWidgetItem(text)
            item.setToolTip(str(snapshot.get("detail", "")) or message)
            item.setData(Qt.ItemDataRole.UserRole, str(snapshot.get("task_id", "")))
            item.setData(Qt.ItemDataRole.UserRole + 1, str(snapshot.get("status", "")))
            self.task_list.addItem(item)
            active_cancellable = active_cancellable or (
                snapshot.get("status") == "running"
                and bool(snapshot.get("cancel_supported"))
            )
            if snapshot.get("status") != "running":
                finished_count += 1

        self.cancel_task_button.setEnabled(active_cancellable)
        self.clear_finished_button.setEnabled(finished_count > 0)
        self._update_task_actions()

    def _set_overlay_width(self, width: int) -> None:
        """固定右边缘位置，展开时全高覆盖，收起时仅保留小按钮。"""
        parent = self.parentWidget()
        if parent is None:
            self.setFixedSize(width, self.collapsed_height if not self._expanded else self.height())
            return
        safe_width = max(self.collapsed_width, min(self.expanded_width, int(width)))
        self.setMinimumWidth(safe_width)
        self.setMaximumWidth(safe_width)
        if self._expanded:
            self.setMinimumHeight(parent.height())
            self.setMaximumHeight(parent.height())
            self.setGeometry(parent.width() - safe_width, 0, safe_width, parent.height())
        else:
            safe_height = min(self.collapsed_height, parent.height())
            safe_top = min(self.collapsed_top_offset, max(0, parent.height() - safe_height))
            self.setMinimumHeight(safe_height)
            self.setMaximumHeight(safe_height)
            self.setGeometry(parent.width() - safe_width, safe_top, safe_width, safe_height)
        self.raise_()

    def _finish_drawer_animation(self, expanded: bool) -> None:
        """动画结束后固定宽度，并在收起时隐藏内容。"""
        if self._expanded != expanded:
            return
        target_width = self.expanded_width if expanded else self.collapsed_width
        self._set_overlay_width(target_width)
        self._set_content_visible(expanded)

    def _set_content_visible(self, visible: bool) -> None:
        """折叠时隐藏任务内容，仅保留固定位置的切换按钮。"""
        for widget in (
            self.title_label,
            self.task_list,
            self.cancel_task_button,
            self.delete_task_button,
            self.clear_finished_button,
        ):
            widget.setVisible(visible)

    def _request_cancel_task(self) -> None:
        """请求取消当前可取消任务。"""
        self.task_manager.request_cancel()

    def _update_task_actions(self) -> None:
        """根据当前选择启用或禁用任务操作按钮。"""
        current_item = self.task_list.currentItem()
        if current_item is None:
            self.delete_task_button.setEnabled(False)
            return
        task_id = str(current_item.data(Qt.ItemDataRole.UserRole) or "")
        status = str(current_item.data(Qt.ItemDataRole.UserRole + 1) or "")
        self.delete_task_button.setEnabled(bool(task_id) and status != "running")

    def _delete_selected_task(self) -> None:
        """删除当前选中的已完成任务记录。"""
        current_item = self.task_list.currentItem()
        if current_item is None:
            return
        task_id = str(current_item.data(Qt.ItemDataRole.UserRole) or "")
        status = str(current_item.data(Qt.ItemDataRole.UserRole + 1) or "")
        if not task_id or status == "running":
            return
        if self.task_manager.remove_task(task_id):
            self.refresh_task_list()

    def _clear_finished_tasks(self) -> None:
        """一键清理所有已结束的任务记录。"""
        if self.task_manager.clear_finished_tasks() > 0:
            self.refresh_task_list()
