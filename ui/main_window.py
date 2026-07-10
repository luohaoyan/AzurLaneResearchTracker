#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                 🖥️ GUI 主窗口骨架 (main_window.py)           ║
║                                                              ║
║  【一句话解释】创建 v0.5.0 PySide6 桌面界面的主窗口和页面框架。║
║  【类比理解】主窗口像港区指挥室，左侧切换区域，右侧处理任务。 ║
║  【数据流说明】导航点击 → QStackedWidget 切页 → 后续页面接入。║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QDate, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QMovie, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.calculation.trend_analyzer import get_trend_analyzer
from core.calculation.research_progress_analyzer import get_research_progress_analyzer
from core.calculation.luck_calculator import get_luck_calculator
from core.calculation.user_data_manager import get_user_data_manager
from core.data.equipment_manager import get_equipment_manager
from core.data.research_manager import get_research_manager
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager
from ui.automation_bridge import get_automation_bridge
from ui.future_hooks import FeatureHookRegistry, FutureFeatureSpec, get_feature_hook_registry
from ui.secretary_pack import validate_secretary_pack
from ui.theme import ThemeTokens, build_stylesheet, get_theme_skin, install_application_fonts, list_theme_skins
from ui.ui_config import get_ui_config_manager
from ui.widgets.log_drawer import LogDrawer

rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


# ============================================================
# 🧭 第二部分：模块工具函数
# ============================================================

def get_gui_version() -> str:
    """
    从主配置读取 GUI 展示版本号。
    输入：
        无。
    输出：
        str: 带 v 前缀的版本号；配置缺失时使用 v0.5.0 兜底。
    使用示例：
        version = get_gui_version()
    """
    config = get_config_loader().get_main_config()
    raw_version = str(config.get("app", {}).get("version", "0.5.0")).strip()
    if not raw_version:
        raw_version = "0.5.0"
    return raw_version if raw_version.startswith("v") else f"v{raw_version}"


def polish_data_table(table: QTableWidget, row_height: int = 44) -> None:
    """
    统一整理 GUI 数据表的可读性和交互行为。
    输入：
        table: 需要整理的 QTableWidget。
        row_height: 默认行高。
    输出：
        None。
    使用示例：
        polish_data_table(self.table, 52)
    """
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setCornerButtonEnabled(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.verticalHeader().setMinimumSectionSize(row_height)


def get_visible_research_phases(min_phase_number: int = 2) -> List[Dict[str, Any]]:
    """
    从科研期数据表读取用户可选择的科研期。
    输入：
        min_phase_number: 最小科研期；默认从 PR2 开始，避开没有彩装的一期科研。
    输出：
        List[dict]: 过滤后的科研期数据，来源于 data/research_phases.csv。
    使用示例：
        phases = get_visible_research_phases()
    """
    visible: List[Dict[str, Any]] = []
    for phase in get_research_manager().get_all():
        try:
            phase_number = int(phase.get("phase_number", 0))
        except (TypeError, ValueError):
            continue
        if phase_number < min_phase_number:
            continue
        visible.append(phase)
    return visible


# ============================================================
# 🏗️ 第三部分：核心类
# ============================================================

@dataclass(frozen=True)
class NavigationItem:
    """
    左侧导航项定义。
    输入：
        key: 页面稳定键。
        title: 导航展示文本。
        icon: 折叠导航时展示的短标记。
        summary: 页面简介。
    输出：
        不可变导航对象。
    使用示例：
        NavigationItem("dashboard", "港区实况", "港", "查看状态")
    """

    key: str
    title: str
    icon: str
    summary: str


class AnimatedMascotPanel(QFrame):
    """
    二次元风格动效预留面板。
    输入：
        animation_path: 可选 GIF 路径；不存在时展示静态待机文案。
    输出：
        QWidget，可嵌入任意页面。
    使用示例：
        panel = AnimatedMascotPanel("resources/animations/secretary_idle.gif")
    """

    def __init__(self, animation_path: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        """创建动效面板，并尝试加载 GIF。"""
        super().__init__(parent)
        self.setObjectName("mascot_panel")
        self._movie: Optional[QMovie] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.title_label = QLabel("秘书舰待机")
        self.title_label.setObjectName("panel_title")
        self.motion_label = QLabel("✨")
        self.motion_label.setObjectName("panel_body")
        self.motion_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.motion_label.setMinimumHeight(112)
        self.motion_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.hint_label = QLabel("后续可接入待机、识别完成、保存成功等轻量 GIF 动画。")
        self.hint_label.setObjectName("panel_body")
        self.hint_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.motion_label)
        layout.addWidget(self.hint_label)

        if animation_path:
            self.load_animation(animation_path)

    def load_animation(self, animation_path: str) -> bool:
        """
        加载 GIF 动画资源。
        输入：
            animation_path: 相对项目根目录或绝对路径。
        输出：
            bool: 成功加载可播放动画返回 True，否则返回 False。
        使用示例：
            panel.load_animation("resources/animations/secretary_idle.gif")
        """
        path = Path(animation_path)
        if not path.is_absolute():
            path = PathManager.get_project_root() / path
        if not path.exists():
            self.motion_label.setText("待机动画未配置")
            return False

        movie = QMovie(str(path))
        if not movie.isValid():
            self.motion_label.setText("动画资源无法播放")
            return False

        self._movie = movie
        self.motion_label.setMovie(movie)
        movie.start()
        return True


class ElasticScrollArea(QScrollArea):
    """
    带边界回弹反馈的滚动容器。
    输入：
        parent: 可选父控件。
    输出：
        QScrollArea，内容超出视口时支持滚轮滚动，到顶/到底时给出轻量动画。
    使用示例：
        scroll_area = ElasticScrollArea()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建等待开发页使用的柔和滚动区域。"""
        super().__init__(parent)
        self.setObjectName("elastic_scroll_area")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._edge_animation: Optional[QPropertyAnimation] = None

    def content_overflows(self) -> bool:
        """
        判断内容是否超过当前视口。
        输入：
            无。
        输出：
            bool: 垂直滚动条存在有效滚动范围时返回 True。
        使用示例：
            if scroll_area.content_overflows(): ...
        """
        scroll_bar = self.verticalScrollBar()
        return scroll_bar.maximum() > scroll_bar.minimum()

    def play_edge_bounce(self, edge: str) -> bool:
        """
        播放顶部或底部的轻量回弹动画。
        输入：
            edge: top 或 bottom。
        输出：
            bool: 成功触发动画返回 True，内容不溢出时返回 False。
        使用示例：
            scroll_area.play_edge_bounce("top")
        """
        if not self.content_overflows():
            return False

        scroll_bar = self.verticalScrollBar()
        minimum = scroll_bar.minimum()
        maximum = scroll_bar.maximum()
        distance = min(18, max(1, maximum - minimum))
        if edge == "top":
            start_value = minimum
            middle_value = min(minimum + distance, maximum)
            end_value = minimum
        elif edge == "bottom":
            start_value = maximum
            middle_value = max(maximum - distance, minimum)
            end_value = maximum
        else:
            return False

        if self._edge_animation is not None:
            self._edge_animation.stop()

        scroll_bar.setValue(start_value)
        animation = QPropertyAnimation(scroll_bar, b"value", self)
        animation.setDuration(190)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(start_value)
        animation.setKeyValueAt(0.45, middle_value)
        animation.setEndValue(end_value)
        animation.finished.connect(lambda: self._clear_edge_animation(animation))
        self._edge_animation = animation
        animation.start()
        return True

    def wheelEvent(self, event: QWheelEvent) -> None:
        """滚轮滚动内容，并在边界处给用户一个柔和反馈。"""
        if not self.content_overflows():
            event.ignore()
            return

        scroll_bar = self.verticalScrollBar()
        delta_y = event.angleDelta().y()
        if delta_y > 0 and scroll_bar.value() <= scroll_bar.minimum():
            self.play_edge_bounce("top")
            event.accept()
            return
        if delta_y < 0 and scroll_bar.value() >= scroll_bar.maximum():
            self.play_edge_bounce("bottom")
            event.accept()
            return

        super().wheelEvent(event)

    def _clear_edge_animation(self, animation: QPropertyAnimation) -> None:
        """动画结束后释放当前动画引用，避免重复滚动时状态残留。"""
        if self._edge_animation is animation:
            self._edge_animation = None


class MatplotlibTrendPanel(QFrame):
    """
    matplotlib 趋势图面板。
    输入：
        title: 图表标题。
        subtitle: 图表说明。
    输出：
        带工具栏、折线图和悬停提示的 QWidget。
    使用示例：
        panel = MatplotlibTrendPanel("金彩比趋势", "按日期展示")
    """

    def __init__(self, title: str, subtitle: str, parent: Optional[QWidget] = None) -> None:
        """创建趋势图面板。"""
        super().__init__(parent)
        self.setObjectName("chart_panel")
        self.theme_tokens = ThemeTokens()
        self._line_metadata: Dict[Any, List[Dict[str, object]]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("section_title")
        self.status_label = QLabel(subtitle)
        self.status_label.setObjectName("panel_body")
        self.status_label.setWordWrap(True)
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.figure = Figure(figsize=(7.2, 3.0), dpi=100, tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setObjectName("matplotlib_trend_canvas")
        self.axes = self.figure.add_subplot(111)
        self.annotation = self.axes.annotate(
            "",
            xy=(0, 0),
            xytext=(14, 18),
            textcoords="offset points",
            bbox={"boxstyle": "round,pad=0.35", "fc": "#102337", "ec": "#58D7FF", "alpha": 0.94},
            arrowprops={"arrowstyle": "->", "color": "#58D7FF"},
        )
        self.annotation.set_visible(False)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

        layout.addLayout(header)
        layout.addWidget(self.status_label)
        layout.addWidget(self.canvas, stretch=1)
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.apply_theme_tokens(self.theme_tokens)

    def apply_theme_tokens(self, tokens: ThemeTokens) -> None:
        """
        按 GUI 皮肤刷新 matplotlib 图表颜色。
        输入：
            tokens: 当前皮肤令牌。
        输出：
            None。
        使用示例：
            panel.apply_theme_tokens(tokens)
        """
        self.theme_tokens = tokens
        self.figure.patch.set_facecolor(tokens.surface)
        self.axes.set_facecolor(tokens.table_row)
        self.axes.tick_params(colors=tokens.text_muted)
        self.axes.xaxis.label.set_color(tokens.text_muted)
        self.axes.yaxis.label.set_color(tokens.text_muted)
        self.axes.title.set_color(tokens.text)
        for spine in self.axes.spines.values():
            spine.set_color(tokens.line)
        self.annotation.get_bbox_patch().set_facecolor(tokens.surface_soft)
        self.annotation.get_bbox_patch().set_edgecolor(tokens.azure)
        self.annotation.arrow_patch.set_color(tokens.azure)
        self.annotation.set_color(tokens.text)
        self.canvas.setStyleSheet(f"background: {tokens.surface};")
        self.canvas.draw_idle()

    def plot_series(
        self,
        series_map: Dict[str, List[Dict[str, object]]],
        y_label: str,
        empty_message: str,
        colors: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        绘制多条时间序列。
        输入：
            series_map: {"折线名": [{"date": "...", "value": 1.0, "detail": "..."}]}。
            y_label: Y 轴标题。
            empty_message: 无数据时展示的文案。
            colors: 可选折线颜色。
        输出：
            None。
        使用示例：
            panel.plot_series({"PR6": points}, "金彩比", "暂无数据")
        """
        self.axes.clear()
        self._line_metadata.clear()
        visible_count = 0
        color_map = colors or {}
        for index, (name, points) in enumerate(series_map.items()):
            visible_points = [point for point in points if point.get("value") is not None]
            if not visible_points:
                continue
            x_values = list(range(1, len(visible_points) + 1))
            y_values = [float(point.get("value", 0.0)) for point in visible_points]
            line_color = color_map.get(name) or self._fallback_line_color(index)
            line, = self.axes.plot(
                x_values,
                y_values,
                marker="o",
                linewidth=2.2,
                markersize=5.5,
                label=name,
                color=line_color,
            )
            self._line_metadata[line] = visible_points
            self.axes.set_xticks(x_values)
            self.axes.set_xticklabels([str(point.get("date", ""))[5:] for point in visible_points], rotation=0)
            visible_count += 1

        if visible_count == 0:
            self.axes.text(
                0.5,
                0.5,
                empty_message,
                ha="center",
                va="center",
                transform=self.axes.transAxes,
                color=self.theme_tokens.text_muted,
            )
            self.status_label.setText(empty_message)
        else:
            self.axes.legend(loc="upper left", frameon=False)
            for text in self.axes.get_legend().get_texts():
                text.set_color(self.theme_tokens.text)
            self.status_label.setText(f"已绘制 {visible_count} 条折线；可悬停点位查看日期和数值。")

        self.axes.set_ylabel(y_label)
        self.axes.grid(True, color=self.theme_tokens.table_grid, linewidth=0.8, alpha=0.72)
        self.apply_theme_tokens(self.theme_tokens)

    def _fallback_line_color(self, index: int) -> str:
        """返回稳定的默认折线颜色。"""
        palette = [
            self.theme_tokens.azure,
            self.theme_tokens.sakura,
            self.theme_tokens.gold,
            self.theme_tokens.success,
            self.theme_tokens.danger,
            "#B8F09A",
            "#9AA7FF",
        ]
        return palette[index % len(palette)]

    def _on_motion(self, event: object) -> None:
        """鼠标悬停点位时显示日期和数值。"""
        if getattr(event, "inaxes", None) != self.axes:
            if self.annotation.get_visible():
                self.annotation.set_visible(False)
                self.canvas.draw_idle()
            return
        for line, points in self._line_metadata.items():
            contains, info = line.contains(event)
            if not contains:
                continue
            point_index = int(info.get("ind", [0])[0])
            if point_index >= len(points):
                continue
            point = points[point_index]
            value = point.get("value")
            detail = str(point.get("detail") or "")
            text = f"{line.get_label()}\n{point.get('date', '')}: {float(value):.3f}"
            if detail:
                text = f"{text}\n{detail}"
            x_data = line.get_xdata()[point_index]
            y_data = line.get_ydata()[point_index]
            self.annotation.xy = (x_data, y_data)
            self.annotation.set_text(text)
            self.annotation.set_visible(True)
            self.canvas.draw_idle()
            return
        if self.annotation.get_visible():
            self.annotation.set_visible(False)
            self.canvas.draw_idle()


class BasePage(QWidget):
    """
    GUI 业务页面基类。
    输入：
        title: 页面标题。
        summary: 页面说明。
    输出：
        带统一页头和内容布局的 QWidget。
    使用示例：
        page = BasePage("港区实况", "查看状态")
    """

    def __init__(self, title: str, summary: str, parent: Optional[QWidget] = None) -> None:
        """创建统一页面外壳。"""
        super().__init__(parent)
        self.setObjectName("page_shell")
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.page_scroll_area = ElasticScrollArea(self)
        self.page_scroll_area.setObjectName("page_scroll_area")
        self.page_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.page_scroll_content = QWidget()
        self.page_scroll_content.setObjectName("page_scroll_content")
        self.root = QVBoxLayout(self.page_scroll_content)
        self.root.setContentsMargins(28, 24, 28, 24)
        self.root.setSpacing(16)
        self.page_scroll_area.setWidget(self.page_scroll_content)
        outer_layout.addWidget(self.page_scroll_area)

        self.page_marker_label = QLabel("ALRT")
        self.page_marker_label.setObjectName("page_marker")
        self.page_title_label = QLabel(title)
        self.page_title_label.setObjectName("page_title")
        self.page_summary_label = QLabel(summary)
        self.page_summary_label.setObjectName("page_summary")
        self.page_summary_label.setWordWrap(True)

        self.root.addWidget(self.page_marker_label)
        self.root.addWidget(self.page_title_label)
        self.root.addWidget(self.page_summary_label)

    def set_header_compact(self) -> None:
        """
        压缩页面头部留白。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.set_header_compact()
        """
        self.root.setContentsMargins(28, 16, 28, 18)
        self.root.setSpacing(8)
        self.page_title_label.setStyleSheet("font-size: 24px;")
        self.page_summary_label.setStyleSheet("margin-bottom: 2px;")

    @staticmethod
    def build_card(title: str, body: str, caption: str = "") -> QFrame:
        """
        构建通用信息卡片。
        输入：
            title: 卡片标题。
            body: 主要内容。
            caption: 可选辅助说明。
        输出：
            QFrame: 可放入布局的卡片。
        使用示例：
            card = BasePage.build_card("装备更新", "待命中")
        """
        card = QFrame()
        card.setObjectName("content_panel")
        card.setMinimumHeight(96)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("panel_title")
        body_label = QLabel(body)
        body_label.setObjectName("panel_body")
        body_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(body_label)
        if caption:
            caption_label = QLabel(caption)
            caption_label.setObjectName("card_caption")
            caption_label.setWordWrap(True)
            layout.addWidget(caption_label)
        layout.addStretch(1)
        return card


class DashboardPage(BasePage):
    """
    港区实况页面。
    输入：
        runtime_manager: 运行期状态管理器。
    输出：
        QWidget，展示玩家资源、项目运行状态、快捷入口和提示语。
    使用示例：
        page = DashboardPage(get_runtime_state_manager())
    """

    quickActionRequested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建港区实况页并启动轻量刷新定时器。"""
        super().__init__("港区实况", "展示玩家资源、当前任务、快捷入口和港区提示。资源信息来自未来 OCR，仅在本次运行内显示。", parent)
        self.runtime_manager = get_runtime_state_manager()
        self.stat_labels: Dict[str, QLabel] = {}

        content = QHBoxLayout()
        content.setSpacing(16)
        self.root.addLayout(content, stretch=1)

        left = QVBoxLayout()
        left.setSpacing(14)
        right = QVBoxLayout()
        right.setSpacing(14)
        content.addLayout(left, stretch=3)
        content.addLayout(right, stretch=2)

        self._build_player_grid(left)
        self._build_task_panel(left)
        self._build_quick_actions(left)
        self._build_prompt_panel(right)
        right.addWidget(AnimatedMascotPanel(), stretch=1)
        right.addWidget(BasePage.build_card("海报 / GIF 展示位", "后续可放置游戏相关海报、待机动效或识别完成反馈。"), stretch=1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(self.refresh_state)
        self.refresh_timer.start()
        self.refresh_state()

    def _build_player_grid(self, parent_layout: QVBoxLayout) -> None:
        """构建玩家资源卡片区。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setSpacing(12)

        for index, (key, label) in enumerate([
            ("player_name", "玩家名称"),
            ("oil", "石油"),
            ("coins", "物资"),
            ("gems", "钻石"),
        ]):
            card = QFrame()
            card.setObjectName("stat_card")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 12, 14, 12)
            value_label = QLabel("等待识别")
            value_label.setObjectName("stat_value")
            caption_label = QLabel(label)
            caption_label.setObjectName("stat_label")
            layout.addWidget(value_label)
            layout.addWidget(caption_label)
            self.stat_labels[key] = value_label
            grid.addWidget(card, index // 2, index % 2)

        parent_layout.addWidget(panel)

    def _build_task_panel(self, parent_layout: QVBoxLayout) -> None:
        """构建项目运行状态区。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.task_title = QLabel("当前状态：空闲")
        self.task_title.setObjectName("panel_title")
        self.task_message = QLabel("港区系统待命中，请选择操作。")
        self.task_message.setObjectName("panel_body")
        self.task_message.setWordWrap(True)
        self.task_progress = QProgressBar()
        self.task_progress.setRange(0, 100)
        self.task_progress.setValue(0)

        layout.addWidget(self.task_title)
        layout.addWidget(self.task_message)
        layout.addWidget(self.task_progress)
        parent_layout.addWidget(panel)

    def _build_quick_actions(self, parent_layout: QVBoxLayout) -> None:
        """构建快捷入口区。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("快捷切换")
        title.setObjectName("panel_title")
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        for key, label in [
            ("user_data", "用户数据"),
            ("research_progress", "科研进度"),
            ("trend", "历史趋势"),
            ("automation_lab", "自动化实验室"),
            ("settings", "设置"),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, page_key=key: self.quickActionRequested.emit(page_key))
            button_row.addWidget(button)
        layout.addWidget(title)
        layout.addLayout(button_row)
        parent_layout.addWidget(panel)

    def _build_prompt_panel(self, parent_layout: QVBoxLayout) -> None:
        """构建港区提示语区。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel("今日提示")
        title.setObjectName("panel_title")
        prompt = QLabel("指挥官，装备清点还没开始。等 OCR 接入后，我会定时把港区资源更新到这里。")
        prompt.setObjectName("prompt_text")
        prompt.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(prompt)
        parent_layout.addWidget(panel)

    def refresh_state(self) -> None:
        """
        刷新运行期状态展示。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.refresh_state()
        """
        state = self.runtime_manager.get_full_state()
        player = state["player"]
        task = state["task"]
        self.stat_labels["player_name"].setText(str(player.get("player_name") or "等待识别"))
        for key in ("oil", "coins", "gems"):
            value = player.get(key)
            self.stat_labels[key].setText("等待识别" if value is None else f"{int(value):,}")
        self.task_title.setText(f"当前状态：{task.get('kind_name', '未知')}")
        self.task_message.setText(str(task.get("user_message", "")))
        self.task_progress.setValue(int(task.get("progress", 0)))


class UserDataPage(BasePage):
    """
    用户数据页面。
    输入：
        无。
    输出：
        QWidget，展示装备与碎片数据的表格筛选骨架。
    使用示例：
        page = UserDataPage()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建用户装备数据表格与筛选栏。"""
        super().__init__("用户数据", "展示玩家当前装备与碎片数据；基础装备库清单可从本页单独打开。", parent)
        self.icon_size = 36
        self.equipment_manager = get_equipment_manager()
        self.all_equipment_rows: List[Dict[str, object]] = self.equipment_manager.get_equipment_with_image()
        self._build_views()

    def _build_views(self) -> None:
        """构建用户数据主视图和基础装备库子视图。"""
        self.view_stack = QStackedWidget()
        self.view_stack.setObjectName("user_data_view_stack")

        self.player_data_view = QWidget()
        player_layout = QVBoxLayout(self.player_data_view)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(12)
        self._build_filters(player_layout)
        self._build_table(player_layout)

        self.library_view = QWidget()
        library_layout = QVBoxLayout(self.library_view)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(12)
        self._build_library_view(library_layout)

        self.view_stack.addWidget(self.player_data_view)
        self.view_stack.addWidget(self.library_view)
        self.root.addWidget(self.view_stack, stretch=1)
        self.refresh_equipment_table()
        self.refresh_library_table()

    def _build_filters(self, parent_layout: QVBoxLayout) -> None:
        """构建装备筛选控件。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        row = QHBoxLayout(panel)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("按装备名称搜索")
        self.rarity_combo = QComboBox()
        self.rarity_combo.addItem("全部稀有度", None)
        for rarity in self.equipment_manager.rarity_manager.get_all():
            self.rarity_combo.addItem(str(rarity.get("name", "未知")), int(rarity.get("rarity_id", 0)))
        self.phase_combo = QComboBox()
        self.phase_combo.addItem("全部科研期", None)
        for phase in get_research_manager().get_all():
            phase_number = int(phase.get("phase_number", 0))
            self.phase_combo.addItem(f"科研 {phase_number} 期", phase_number)
        self.phase_combo.addItem("通用", 0)
        self.search_input.textChanged.connect(lambda _text="": self.refresh_equipment_table())
        self.rarity_combo.currentIndexChanged.connect(lambda _index=0: self.refresh_equipment_table())
        self.phase_combo.currentIndexChanged.connect(lambda _index=0: self.refresh_equipment_table())
        self.open_library_button = QPushButton("查看装备库表")
        self.open_library_button.setObjectName("open_equipment_library_button")
        self.open_library_button.setToolTip("打开基础装备清单，只展示名称、稀有度和科研期。")
        self.open_library_button.clicked.connect(self._show_library_view)

        row.addWidget(self.search_input, stretch=2)
        row.addWidget(self.rarity_combo)
        row.addWidget(self.phase_combo)
        row.addStretch(1)
        row.addWidget(self.open_library_button)
        parent_layout.addWidget(panel)

    def _build_table(self, parent_layout: QVBoxLayout) -> None:
        """构建用户可见装备表格。"""
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["装备名称", "稀有度", "科研期", "装备数", "碎片数"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        polish_data_table(self.table, 52)
        parent_layout.addWidget(self.table, stretch=1)

    def _build_library_view(self, parent_layout: QVBoxLayout) -> None:
        """构建基础装备库表子页面。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        row = QHBoxLayout(panel)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(10)

        title_box = QVBoxLayout()
        title = QLabel("装备库表")
        title.setObjectName("panel_title")
        hint = QLabel("展示基础装备清单，仅保留玩家需要查看的名称、稀有度和科研期。")
        hint.setObjectName("card_caption")
        hint.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(hint)

        self.back_to_player_data_button = QPushButton("返回用户数据")
        self.back_to_player_data_button.setObjectName("back_to_player_data_button")
        self.back_to_player_data_button.clicked.connect(self._show_player_data_view)

        row.addLayout(title_box, stretch=1)
        row.addWidget(self.back_to_player_data_button)
        parent_layout.addWidget(panel)

        filter_panel = QFrame()
        filter_panel.setObjectName("content_panel")
        filter_row = QHBoxLayout(filter_panel)
        filter_row.setContentsMargins(16, 12, 16, 12)
        filter_row.setSpacing(10)

        self.library_search_input = QLineEdit()
        self.library_search_input.setObjectName("equipment_library_search")
        self.library_search_input.setPlaceholderText("按装备名称搜索")
        self.library_rarity_combo = QComboBox()
        self.library_rarity_combo.setObjectName("equipment_library_rarity_filter")
        self.library_rarity_combo.addItem("全部稀有度", None)
        for rarity in self.equipment_manager.rarity_manager.get_all():
            self.library_rarity_combo.addItem(str(rarity.get("name", "未知")), int(rarity.get("rarity_id", 0)))
        self.library_phase_combo = QComboBox()
        self.library_phase_combo.setObjectName("equipment_library_phase_filter")
        self.library_phase_combo.addItem("全部科研期", None)
        for phase in get_research_manager().get_all():
            phase_number = int(phase.get("phase_number", 0))
            self.library_phase_combo.addItem(f"科研 {phase_number} 期", phase_number)
        self.library_phase_combo.addItem("通用", 0)

        self.library_search_input.textChanged.connect(lambda _text="": self.refresh_library_table())
        self.library_rarity_combo.currentIndexChanged.connect(lambda _index=0: self.refresh_library_table())
        self.library_phase_combo.currentIndexChanged.connect(lambda _index=0: self.refresh_library_table())

        filter_row.addWidget(QLabel("名称"))
        filter_row.addWidget(self.library_search_input, stretch=2)
        filter_row.addWidget(QLabel("稀有度"))
        filter_row.addWidget(self.library_rarity_combo)
        filter_row.addWidget(QLabel("科研期"))
        filter_row.addWidget(self.library_phase_combo)
        filter_row.addStretch(1)
        parent_layout.addWidget(filter_panel)

        self.library_table = QTableWidget(0, 3)
        self.library_table.setObjectName("equipment_library_table")
        self.library_table.setHorizontalHeaderLabels(["装备名称", "稀有度", "科研期"])
        self.library_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 3):
            self.library_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        polish_data_table(self.library_table, 52)
        parent_layout.addWidget(self.library_table, stretch=1)

    def refresh_equipment_table(self) -> None:
        """
        按当前筛选条件刷新玩家装备数据展示。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.refresh_equipment_table()
        """
        equipments = self._filtered_equipment_rows()
        self.table.setRowCount(len(equipments))
        for row, equipment in enumerate(equipments):
            phase = self._phase_from_public_data(str(equipment.get("equipment_id", "")))
            self.table.setCellWidget(row, 0, self._build_name_icon_cell(equipment))
            values = [
                equipment.get("rarity_name", "未知"),
                phase,
                self._display_count(equipment, "owned_quantity"),
                self._display_count(equipment, "fragment_quantity"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column + 1, item)

    def refresh_library_table(self) -> None:
        """刷新基础装备库表，只展示公开列。"""
        equipments = self._filtered_library_rows()
        self.library_table.setRowCount(len(equipments))
        for row, equipment in enumerate(equipments):
            phase = self._phase_from_public_data(str(equipment.get("equipment_id", "")))
            self.library_table.setCellWidget(row, 0, self._build_name_icon_cell(equipment))
            for column, value in enumerate([equipment.get("rarity_name", "未知"), phase], start=1):
                self.library_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _show_library_view(self) -> None:
        """切换到基础装备库表视图。"""
        self.refresh_library_table()
        self.view_stack.setCurrentWidget(self.library_view)

    def _show_player_data_view(self) -> None:
        """切回玩家当前装备数据视图。"""
        self.view_stack.setCurrentWidget(self.player_data_view)

    @staticmethod
    def _display_count(equipment: Dict[str, object], key: str) -> int:
        """把装备数量字段转换成用户可读整数，缺失或异常时显示 0。"""
        try:
            return int(equipment.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _filtered_equipment_rows(self) -> List[Dict[str, object]]:
        """
        返回符合名称、稀有度和科研期筛选的装备行。
        输入：
            无。
        输出：
            List[dict]: 不包含内部字段展示逻辑的装备数据。
        使用示例：
            rows = page._filtered_equipment_rows()
        """
        return self._filter_equipment_rows(
            self.search_input.text().strip(),
            self.rarity_combo.currentData(),
            self.phase_combo.currentData(),
        )

    def _filtered_library_rows(self) -> List[Dict[str, object]]:
        """返回符合装备库子页筛选条件的公开装备行。"""
        return self._filter_equipment_rows(
            self.library_search_input.text().strip(),
            self.library_rarity_combo.currentData(),
            self.library_phase_combo.currentData(),
        )

    def _filter_equipment_rows(
        self,
        keyword: str,
        rarity_id: Optional[int],
        phase_filter: Optional[int],
    ) -> List[Dict[str, object]]:
        """按名称、稀有度和科研期过滤装备列表。"""
        normalized_keyword = keyword.lower()
        rows: List[Dict[str, object]] = []
        for equipment in self.all_equipment_rows:
            name = str(equipment.get("name", ""))
            equipment_id = str(equipment.get("equipment_id", ""))
            parsed_phase = self._phase_number_from_id(equipment_id)
            if normalized_keyword and normalized_keyword not in name.lower():
                continue
            if rarity_id is not None and int(equipment.get("rarity_id", 0)) != int(rarity_id):
                continue
            if phase_filter is not None:
                if int(phase_filter) == 0 and parsed_phase is not None:
                    continue
                if int(phase_filter) > 0 and parsed_phase != int(phase_filter):
                    continue
            rows.append(equipment)
        return rows

    def _build_name_icon_cell(self, equipment: Dict[str, object]) -> QWidget:
        """
        构建装备名称 + 小图标单元格。
        输入：
            equipment: 装备数据，包含 name 与 image_path。
        输出：
            QWidget: 固定尺寸图标不会撑大表格行高。
        使用示例：
            self.table.setCellWidget(row, 0, self._build_name_icon_cell(equipment))
        """
        cell = QWidget()
        cell.setObjectName("equipment_name_icon_cell")
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        name_label = QLabel(str(equipment.get("name", "")))
        name_label.setObjectName("equipment_name_label")
        name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        name_label.setWordWrap(False)

        icon_label = QLabel()
        icon_label.setObjectName("equipment_icon_label")
        icon_label.setFixedSize(self.icon_size, self.icon_size)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(self._load_equipment_icon(str(equipment.get("image_path") or "")))

        layout.addWidget(name_label, stretch=1)
        layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return cell

    def _load_equipment_icon(self, image_path: str) -> QPixmap:
        """
        加载并缩放装备图标；缺失时返回透明空白图标。
        输入：
            image_path: equipment_images.csv 中记录的相对路径或绝对路径。
        输出：
            QPixmap: 固定最大尺寸的小图标。
        使用示例：
            pixmap = self._load_equipment_icon("resources/equipment/S1-001.png")
        """
        blank = QPixmap(self.icon_size, self.icon_size)
        blank.fill(Qt.GlobalColor.transparent)
        resolved_path = self._resolve_equipment_image_path(image_path)
        if resolved_path is None:
            return blank

        pixmap = QPixmap(str(resolved_path))
        if pixmap.isNull():
            return blank
        return pixmap.scaled(
            self.icon_size,
            self.icon_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    @staticmethod
    def _resolve_equipment_image_path(image_path: str) -> Optional[Path]:
        """
        解析装备图片路径。
        输入：
            image_path: CSV 中的图片路径。
        输出：
            Optional[Path]: 存在则返回绝对路径，否则返回 None。
        使用示例：
            path = UserDataPage._resolve_equipment_image_path("img/a.png")
        """
        clean_path = image_path.strip()
        if not clean_path:
            return None
        path = Path(clean_path)
        candidates = [path] if path.is_absolute() else [
            PathManager.get_project_root() / path,
            PathManager.get_data_dir() / path,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _phase_from_public_data(equipment_id: str) -> str:
        """从内部 ID 推断科研期，只展示给用户可理解的期数名称。"""
        phase_number = UserDataPage._phase_number_from_id(equipment_id)
        return f"科研 {phase_number} 期" if phase_number is not None else "通用"

    @staticmethod
    def _phase_number_from_id(equipment_id: str) -> Optional[int]:
        """从装备 ID 解析科研期数；通用装备返回 None。"""
        if equipment_id.startswith("S") and "-" in equipment_id:
            try:
                return int(equipment_id.split("-", 1)[0][1:])
            except ValueError:
                return None
        return None


class ResearchProgressPage(BasePage):
    """
    科研进度页面。
    输入：
        无。
    输出：
        QWidget，展示科研期选择、当前进度占位和欧非值图文评价。
    使用示例：
        page = ResearchProgressPage()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建科研进度页面。"""
        super().__init__("科研进度", "默认展示最新科研期，也可以切换历史期数；非最新期会明确标注。", parent)
        self.set_header_compact()
        self.progress_analyzer = get_research_progress_analyzer()
        self.ui_config_manager = get_ui_config_manager()
        self.ui_config = self.ui_config_manager.get_research_progress_config()
        self.secretary_lines_config = self.ui_config_manager.get_secretary_lines_config()
        self._secretary_line_cursor = 0
        self._last_target_comment = ""
        self._last_target_context = "target_changed"
        self._syncing_start_date = False
        self._syncing_target = False
        self._secretary_dialog_timer = QTimer(self)
        self._secretary_dialog_timer.setSingleShot(True)
        self._secretary_dialog_timer.timeout.connect(self._reset_secretary_dialog)
        phases = get_visible_research_phases()
        latest_phase = self.progress_analyzer.get_latest_phase_number()
        visible_phase_numbers = [int(phase.get("phase_number", 0)) for phase in phases]
        selected_phase = latest_phase if latest_phase in visible_phase_numbers else (visible_phase_numbers[-1] if visible_phase_numbers else 0)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.phase_combo = QComboBox()
        self.phase_combo.setFixedWidth(180)
        for phase in phases:
            phase_number = int(phase.get("phase_number", 0))
            suffix = "（最新）" if phase_number == latest_phase else "（历史期）"
            self.phase_combo.addItem(f"科研 {phase_number} 期 {suffix}", phase_number)
        if self.phase_combo.count() == 0:
            self.phase_combo.addItem("科研数据待加载", 0)
        latest_index = self.phase_combo.findData(selected_phase)
        if latest_index >= 0:
            self.phase_combo.setCurrentIndex(latest_index)
        self.phase_combo.currentIndexChanged.connect(lambda _index=0: self._on_phase_changed())
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("research_notice")
        self.notice_label.setWordWrap(True)
        top.addWidget(QLabel("科研期数"))
        top.addWidget(self.phase_combo)
        top.addWidget(self.notice_label, stretch=1)
        top.addStretch(1)
        self.root.addLayout(top)

        summary_grid = QGridLayout()
        summary_grid.setSpacing(12)
        self.root.addLayout(summary_grid)

        self.target_combo = QComboBox()
        self.target_combo.setObjectName("target_combo")
        self.target_combo.setFixedWidth(92)
        for target_count in range(1, 21):
            self.target_combo.addItem(f"{target_count} 件", target_count)
        self.target_combo.setCurrentIndex(1)
        self.target_combo.currentIndexChanged.connect(lambda _index=0: self._on_target_changed())
        self.completed_value_label = QLabel("完成装备 0 / 0")
        self.completed_value_label.setObjectName("card_caption")
        self.completed_value_label.setFixedWidth(112)
        self.secretary_avatar_label = QLabel(str(self._secretary_config().get("placeholder_text", "秘书舰")))
        self.secretary_avatar_label.setObjectName("secretary_avatar")
        self.secretary_avatar_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self.secretary_avatar_label.setFixedSize(76, 112)
        self._load_secretary_avatar()
        self.secretary_dialog_frame = QFrame()
        self.secretary_dialog_frame.setObjectName("secretary_dialog")
        self.secretary_dialog_frame.setProperty("quiet", True)
        self.secretary_dialog_frame.setMinimumHeight(112)
        self.secretary_dialog_frame.setFixedWidth(300)
        self.secretary_dialog_frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        dialog_layout = QVBoxLayout(self.secretary_dialog_frame)
        dialog_layout.setContentsMargins(16, 12, 16, 12)
        self.target_comment_label = QLabel("")
        self.target_comment_label.setObjectName("secretary_dialog_text")
        self.target_comment_label.setWordWrap(True)
        dialog_layout.addWidget(self.target_comment_label, stretch=1)
        self._reset_secretary_dialog()

        self.start_date_edit = QDateEdit()
        self.start_date_edit.setObjectName("research_start_date")
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setMaximumDate(QDate.currentDate())
        self.start_date_edit.setFixedWidth(132)
        self.start_date_edit.dateChanged.connect(lambda _date=QDate(): self._on_start_date_changed())
        self.reset_start_date_button = QPushButton("复位")
        self.reset_start_date_button.setObjectName("reset_start_date_button")
        self.reset_start_date_button.setFixedWidth(56)
        self.reset_start_date_button.clicked.connect(self._reset_start_date_to_official)
        self.research_day_value_label = QLabel("第 1 天")
        self.research_day_value_label.setObjectName("research_day_value")
        self.research_day_caption_label = QLabel("")
        self.research_day_caption_label.setObjectName("card_caption")
        self.research_day_caption_label.setWordWrap(True)
        self.duration_message_label = QLabel("")
        self.duration_message_label.setObjectName("card_caption")
        self.duration_message_label.setWordWrap(True)

        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setOrientation(Qt.Orientation.Vertical)
        self.overall_progress_bar.setRange(0, 10000)
        self.overall_progress_bar.setFormat("0.00%")
        self.overall_progress_bar.setTextVisible(False)
        self.overall_progress_bar.setFixedWidth(46)
        self.overall_progress_bar.setMinimumHeight(220)
        self.overall_percent_label = QLabel("0.00%")
        self.overall_percent_label.setObjectName("research_day_value")
        self.overall_percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_detail_label = QLabel("彩装碎片 0 / 0")
        self.progress_detail_label.setObjectName("card_caption")

        self.score_value_label = QLabel("暂无")
        self.ratio_detail_label = QLabel("金 0 / 彩 0")
        self.ratio_detail_label.setObjectName("card_caption")
        self.luck_value_label = QLabel("暂无")
        self.luck_value_label.setObjectName("luck_badge")
        self.luck_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_cards = {
            "target": self._build_target_card(),
            "duration": self._build_duration_card(),
            "progress": self._build_progress_card(),
            "ratio_luck": self._build_ratio_luck_card(),
        }
        summary_grid.addWidget(self.summary_cards["duration"], 0, 0)
        summary_grid.addWidget(self.summary_cards["target"], 0, 1)
        summary_grid.setColumnStretch(0, 2)
        summary_grid.setColumnStretch(1, 3)

        self.progress_table = QTableWidget(0, 5)
        self.progress_table.setHorizontalHeaderLabels(["位置", "装备", "稀有度", "当前图纸", "整装"])
        self.progress_table.setMinimumHeight(156)
        self.progress_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.progress_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.progress_table.setColumnWidth(0, 88)
        for column in (2, 3, 4):
            self.progress_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.progress_table.setColumnWidth(column, 90)
        polish_data_table(self.progress_table, 38)
        self.root.addWidget(self._build_research_detail_area(), stretch=1)
        self._sync_target_from_config()
        self._sync_start_date_from_config()
        self.refresh_progress()

    def apply_theme_tokens(self, tokens: ThemeTokens) -> None:
        """
        接收主窗口皮肤令牌并刷新局部手写样式。
        输入：
            tokens: 当前主窗口皮肤令牌。
        输出：
            None。
        使用示例：
            page.apply_theme_tokens(window.theme_tokens)
        """
        self.theme_tokens = tokens
        self._apply_progress_bar_style(float(self.overall_progress_bar.value()) / 100.0)
        self._apply_luck_badge_style(self.luck_value_label.text())

    @staticmethod
    def _build_summary_card(title: str, value_widget: QWidget, caption: str) -> QFrame:
        """构建科研进度汇总卡片。"""
        card = QFrame()
        card.setObjectName("content_panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("panel_title")
        caption_label = QLabel(caption)
        caption_label.setObjectName("card_caption")
        caption_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_widget)
        layout.addWidget(caption_label)
        return card

    def refresh_progress(self) -> None:
        """
        刷新当前科研期进度展示。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.refresh_progress()
        """
        phase_number = self.phase_combo.currentData()
        progress = self.progress_analyzer.get_phase_progress(
            int(phase_number or 0),
            rainbow_target_count=int(self.target_combo.currentData() or 2),
        )
        self._update_notice(progress)
        self._update_summary(progress)
        self._update_research_day()
        self._update_table(progress.get("equipment_rows", []))

    def _on_phase_changed(self) -> None:
        """科研期切换时同步目标数量、开始日期并刷新展示。"""
        self._sync_target_from_config()
        self._sync_start_date_from_config()
        self.refresh_progress()

    def _on_target_changed(self) -> None:
        """目标彩装切换时刷新进度并弹出秘书舰对话。"""
        if self._syncing_target:
            return
        phase_number = self._selected_phase_number()
        if phase_number > 0:
            self.ui_config_manager.save_phase_target_count(
                phase_number,
                int(self.target_combo.currentData() or 2),
            )
            self.ui_config = self.ui_config_manager.get_research_progress_config()
        self.refresh_progress()
        self._show_secretary_dialog(self._secretary_dialog_text(self._last_target_context))

    def _on_start_date_changed(self) -> None:
        """用户修改科研开始日期时保存到 UI 配置并刷新天数。"""
        if self._syncing_start_date:
            return
        phase_number = self._selected_phase_number()
        if phase_number <= 0:
            return
        selected_date = self.start_date_edit.date()
        today = QDate.currentDate()
        if selected_date > today:
            self._syncing_start_date = True
            self.start_date_edit.setDate(today)
            self._syncing_start_date = False
            self.notice_label.setText("时间选择有误：科研开始时间不能晚于今天，已自动切回今天。")
            selected_date = today
        self.ui_config_manager.save_phase_start_date(
            phase_number,
            selected_date.toString("yyyy-MM-dd"),
        )
        self.ui_config = self.ui_config_manager.get_research_progress_config()
        self._update_research_day()

    def _selected_phase_number(self) -> int:
        """返回当前科研期数，异常时返回 0。"""
        return int(self.phase_combo.currentData() or 0)

    def _sync_target_from_config(self) -> None:
        """按当前科研期从 JSON 配置同步目标彩装数量。"""
        phase_number = self._selected_phase_number()
        if phase_number <= 0:
            return
        setting = self.ui_config_manager.get_phase_setting(phase_number)
        target_count = max(1, min(20, int(setting.get("target", 2))))
        index = self.target_combo.findData(target_count)
        if index < 0:
            return
        self._syncing_target = True
        self.target_combo.setCurrentIndex(index)
        self._syncing_target = False

    def _sync_start_date_from_config(self) -> None:
        """按当前科研期从 JSON 配置同步开始日期。"""
        phase_number = self._selected_phase_number()
        phase_setting = self.ui_config_manager.get_phase_setting(phase_number) if phase_number > 0 else {}
        phase_dates = self.ui_config.get("phase_start_dates", {})
        official_dates = self.ui_config.get("official_start_dates", {})
        date_text = str(
            phase_setting.get("start_date")
            or phase_dates.get(str(phase_number))
            or official_dates.get(str(phase_number))
            or self.ui_config.get("official_fallback_start_date")
            or self.ui_config.get("fallback_start_date")
            or QDate.currentDate().toString("yyyy-MM-dd")
        )
        date = QDate.fromString(date_text, "yyyy-MM-dd")
        today = QDate.currentDate()
        self.start_date_edit.setMaximumDate(today)
        if not date.isValid() or date > today:
            date = today
        self._syncing_start_date = True
        self.start_date_edit.setDate(date)
        self._syncing_start_date = False
        self._update_reset_button_tooltip()
        self._update_research_day()

    def _official_start_date(self, phase_number: int) -> QDate:
        """从 UI 配置读取某一期科研官方开始时间。"""
        official_dates = self.ui_config.get("official_start_dates", {})
        date_text = str(
            official_dates.get(str(phase_number))
            or self.ui_config.get("official_fallback_start_date")
            or self.ui_config.get("fallback_start_date")
            or QDate.currentDate().toString("yyyy-MM-dd")
        )
        date = QDate.fromString(date_text, "yyyy-MM-dd")
        today = QDate.currentDate()
        if not date.isValid() or date > today:
            return today
        return date

    def _reset_start_date_to_official(self) -> None:
        """把当前科研开始日期复位到配置中的官方开始时间。"""
        phase_number = self._selected_phase_number()
        if phase_number <= 0:
            return
        date = self._official_start_date(phase_number)
        self._syncing_start_date = True
        self.start_date_edit.setDate(date)
        self._syncing_start_date = False
        self.ui_config_manager.save_phase_start_date(phase_number, date.toString("yyyy-MM-dd"))
        self.ui_config = self.ui_config_manager.get_research_progress_config()
        self.notice_label.setText(f"已复位到 {phase_number} 期科研官方开始时间。")
        self._update_research_day()

    def _update_reset_button_tooltip(self) -> None:
        """刷新官方开始时间复位按钮悬停说明。"""
        phase_number = self._selected_phase_number()
        official_date = self._official_start_date(phase_number).toString("yyyy-MM-dd")
        self.reset_start_date_button.setToolTip(
            f"把时间复位到第 {phase_number} 期科研官方开始时间：{official_date}"
        )

    def _update_research_day(self) -> None:
        """刷新科研已进行天数和阶段标语。"""
        phase_number = self._selected_phase_number()
        day_count = self._calculate_research_day(self.start_date_edit.date(), QDate.currentDate())
        self.research_day_value_label.setText(f"第 {day_count} 天")
        self.research_day_caption_label.setText(f"现在是 {phase_number} 期科研的第 {day_count} 天")
        self.duration_message_label.setText(self._duration_message(day_count))

    @staticmethod
    def _calculate_research_day(start_date: QDate, today: QDate) -> int:
        """按开始当天为第 1 天计算科研进行天数。"""
        if not start_date.isValid() or not today.isValid():
            return 1
        return max(1, start_date.daysTo(today) + 1)

    def _duration_message(self, day_count: int) -> str:
        """根据 JSON 配置返回科研天数阶段标语。"""
        for item in self.ui_config.get("duration_messages", []):
            min_day = int(item.get("min_day", 1))
            max_day = item.get("max_day")
            if day_count < min_day:
                continue
            if max_day is not None and day_count > int(max_day):
                continue
            return str(item.get("text", "科研进度记录中。"))
        return "科研进度记录中。"

    def _update_notice(self, progress: Dict[str, object]) -> None:
        """根据当前期数状态刷新提示语。"""
        message = str(progress.get("message") or "")
        if message:
            self.notice_label.setText(message)
            self.notice_label.setVisible(True)
            return
        if progress.get("is_latest"):
            self.notice_label.setText("当前展示最新科研期进度。")
        else:
            self.notice_label.setText("当前展示历史科研期，并非最新科研进度。")
        self.notice_label.setVisible(True)

    def _update_summary(self, progress: Dict[str, object]) -> None:
        """刷新汇总卡片内容。"""
        overall = float(progress.get("overall_progress", 0.0))
        self.overall_progress_bar.setValue(int(round(overall * 100)))
        self.overall_progress_bar.setFormat(f"{overall:.2f}%")
        self.overall_percent_label.setText(f"{overall:.2f}%")
        self._apply_progress_bar_style(overall)
        self.progress_detail_label.setText(
            f"彩装碎片 {progress.get('rainbow_total', 0)} / {progress.get('rainbow_target_fragments', 0)}"
        )
        self.completed_value_label.setText(
            f"完成装备 {progress.get('completed_count', 0)} / {progress.get('equipment_total', 0)}"
        )
        target_count = int(progress.get("rainbow_target_count", self.target_combo.currentData() or 2))
        is_latest = bool(progress.get("is_latest"))
        self._last_target_context = self._target_dialog_key(target_count, overall, is_latest)
        self._last_target_comment = self._target_comment(target_count, overall, is_latest)
        ratio = progress.get("gold_rainbow_ratio")
        ratio_text = "暂无" if ratio is None else f"{float(ratio):.3f}"
        self.score_value_label.setText(ratio_text)
        self.ratio_detail_label.setText(
            f"金 {progress.get('gold_total', 0)} / 彩 {progress.get('rainbow_total', 0)}"
        )
        luck_value = progress.get("luck_value")
        luck_text = "暂无" if luck_value is None else f"{float(luck_value):.3f}"
        luck_level = str(progress.get("luck_level", "未知"))
        self.luck_value_label.setText(f"{luck_level} · {luck_text}")
        self._apply_luck_badge_style(luck_level)

    def _update_table(self, rows: List[Dict[str, object]]) -> None:
        """刷新当期科研装备数量表，固定以 1 彩 + 5 金的顺序展示 6 个装备位。"""
        slot_rows = self._build_research_equipment_slots(rows)
        self.progress_table.setRowCount(len(slot_rows))
        for row_index, row in enumerate(slot_rows):
            values = [
                row.get("slot_name", ""),
                row.get("equipment_name", ""),
                row.get("rarity_name", ""),
                row.get("fragment_count", "—"),
                row.get("equipment_count", "—"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in {0, 2, 3, 4}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.progress_table.setItem(row_index, column, item)

    def _build_research_equipment_slots(self, rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
        """
        构建科研装备固定展示槽位。
        输入：
            rows: 科研进度分析器返回的真实装备行。
        输出：
            List[dict]: 固定 6 行，顺序为 1 彩装位 + 5 金装位。
        使用示例：
            slots = page._build_research_equipment_slots(rows)
        """
        rows_by_rarity = {
            5: self._sorted_research_rows_by_rarity(rows, 5),
            4: self._sorted_research_rows_by_rarity(rows, 4),
        }
        slot_specs = [("彩装位", 5, "海上传奇")]
        slot_specs.extend((f"金装位 {index}", 4, "超稀有") for index in range(1, 6))

        slots: List[Dict[str, object]] = []
        used_index_by_rarity = {5: 0, 4: 0}
        for slot_name, rarity_id, rarity_name in slot_specs:
            rarity_rows = rows_by_rarity.get(rarity_id, [])
            row_index = used_index_by_rarity.get(rarity_id, 0)
            if row_index < len(rarity_rows):
                row = dict(rarity_rows[row_index])
                used_index_by_rarity[rarity_id] = row_index + 1
                row["slot_name"] = slot_name
                slots.append(row)
                continue
            slots.append({
                "slot_name": slot_name,
                "equipment_name": "待资料同步",
                "rarity_name": rarity_name,
                "fragment_count": "—",
                "equipment_count": "—",
            })
        return slots

    @staticmethod
    def _sorted_research_rows_by_rarity(rows: List[Dict[str, object]], rarity_id: int) -> List[Dict[str, object]]:
        """按稀有度取出科研装备行，并用名称稳定排序。"""
        filtered = [
            row for row in rows
            if int(row.get("rarity_id") or 0) == rarity_id
        ]
        return sorted(filtered, key=lambda row: str(row.get("equipment_name", "")))

    @staticmethod
    def _target_dialog_key(target_count: int, progress: float, is_latest: bool = True) -> str:
        """根据目标数量和期数状态选择对话配置键。"""
        if not is_latest:
            return "history_completed" if progress >= 100 else "history"
        if progress >= 100:
            return "completed"
        if target_count <= 1:
            return "target_1"
        if 2 <= target_count <= 4:
            return "target_2_4"
        if 5 <= target_count <= 7:
            return "target_5_7"
        return "target_8_plus"

    def _target_comment(self, target_count: int, progress: float, is_latest: bool = True) -> str:
        """根据用户选择的目标彩装数量生成二次元风格提示。"""
        dialogs = self.ui_config.get("target_dialogs", {})
        key = self._target_dialog_key(target_count, progress, is_latest)
        fallback = self._fallback_target_dialog(key)
        return str(dialogs.get(key) or fallback)

    @staticmethod
    def _fallback_target_dialog(key: str) -> str:
        """当 JSON 文案缺失时返回稳定兜底文案。"""
        fallbacks = {
            "history": "补旧期属于港区档案整理任务，过期科研可不代表欧非程度哦，按自己的节奏推进就好。",
            "history_completed": "旧期目标已经补完啦，档案室盖章通过；不过过期科研可不代表欧非程度哦。",
            "completed": "目标已经突破啦，科研室建议立刻换个更闪亮的新目标。",
            "target_1": "秘书舰歪头：只锁定一件吗？稳是很稳，但港区烟花还没点燃呢。",
            "target_2_4": "标准指挥官路线，后勤妖精点头通过，肝度刚刚好。",
            "target_5_7": "勇者级科研计划启动，今晚科研室的灯大概要常亮了。",
            "target_8_plus": "指挥官，理智值还在线吗？这么多彩装连科研终端都开始冒蓝光了。",
        }
        return fallbacks.get(key, "科研目标已更新。")

    def _secretary_config(self) -> Dict[str, object]:
        """返回秘书舰占位配置。"""
        base_config = self.ui_config.get("secretary", {})
        if not isinstance(base_config, dict):
            base_config = {}
        profile = self._secretary_profile()
        merged = dict(base_config)
        if profile:
            merged.update({
                "name": profile.get("name", merged.get("name", "默认秘书舰")),
                "image_path": profile.get("avatar_path") or profile.get("image_path") or merged.get("image_path", ""),
                "placeholder_text": profile.get("placeholder_text", merged.get("placeholder_text", "秘书舰")),
            })
        return merged

    def _secretary_profile(self) -> Dict[str, object]:
        """
        返回当前选中的秘书舰台词配置。
        输入：
            无。
        输出：
            dict: 当前秘书舰配置，缺失时返回默认配置。
        使用示例：
            profile = self._secretary_profile()
        """
        secretaries = self.secretary_lines_config.get("secretaries", {})
        if not isinstance(secretaries, dict):
            return {}
        active_key = str(self.secretary_lines_config.get("active_secretary", "default"))
        profile = secretaries.get(active_key) or secretaries.get("default") or {}
        return profile if isinstance(profile, dict) else {}

    def _secretary_lines(self, context: str) -> List[str]:
        """
        按上下文读取秘书舰台词列表。
        输入：
            context: 台词场景，如 target_changed/history/completed。
        输出：
            List[str]: 可展示的台词列表。
        使用示例：
            lines = self._secretary_lines("target_changed")
        """
        profile = self._secretary_profile()
        lines_map = profile.get("lines", {})
        if not isinstance(lines_map, dict):
            return []
        candidates: List[str] = []
        for key in [context, "target_changed", "idle"]:
            raw_lines = lines_map.get(key, [])
            if isinstance(raw_lines, list):
                candidates = [str(line) for line in raw_lines if str(line).strip()]
            if candidates:
                return candidates
        return []

    def _secretary_dialog_text(self, context: str) -> str:
        """
        生成秘书舰本次弹出的台词。
        输入：
            context: 当前目标评价场景。
        输出：
            str: 优先来自台词 JSON，缺失时回退到目标评价。
        使用示例：
            text = self._secretary_dialog_text("target_2_4")
        """
        lines = self._secretary_lines(context)
        if lines:
            text = lines[self._secretary_line_cursor % len(lines)]
            self._secretary_line_cursor += 1
            return text
        return self._last_target_comment

    def _load_secretary_avatar(self) -> None:
        """加载秘书舰图片占位；未配置图片时显示固定占位格。"""
        image_path = str(self._secretary_config().get("image_path", "")).strip()
        if image_path:
            path = Path(image_path)
            if not path.is_absolute():
                path = PathManager.get_project_root() / path
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.secretary_avatar_label.setPixmap(
                    pixmap.scaled(
                        72,
                        108,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.secretary_avatar_label.setText("")
                return
        self.secretary_avatar_label.setText(str(self._secretary_config().get("placeholder_text", "秘书舰")))

    def _show_secretary_dialog(self, text: str) -> None:
        """显示秘书舰目标对话，并在配置的时间后恢复占位文案。"""
        if not text:
            self._quiet_secretary_dialog()
            return
        if self._secretary_dialog_timer.isActive():
            self._secretary_dialog_timer.stop()
        self._set_secretary_dialog_quiet(False)
        self.target_comment_label.setText(text)
        self._secretary_dialog_timer.start(self._secretary_dialog_duration_ms())

    def _secretary_dialog_duration_ms(self) -> int:
        """
        返回秘书舰对话展示时间。
        输入：
            无。
        输出：
            int: 毫秒；目标切换对话至少保留 3600ms，避免快速选择时刚弹出就被旧计时器清掉。
        使用示例：
            duration = self._secretary_dialog_duration_ms()
        """
        candidates = [
            self.secretary_lines_config.get("dialog_duration_ms"),
            self._secretary_config().get("dialog_duration_ms"),
            3600,
        ]
        parsed: List[int] = []
        for value in candidates:
            try:
                parsed.append(int(value))
            except (TypeError, ValueError):
                continue
        return max(3600, *(duration for duration in parsed if duration > 0))

    def _reset_secretary_dialog(self) -> None:
        """恢复秘书舰静默状态，保持头像和气泡位置不跳动。"""
        self._quiet_secretary_dialog()

    def _quiet_secretary_dialog(self) -> None:
        """
        让秘书舰气泡进入静默状态。
        输入：
            无。
        输出：
            None。
        使用示例：
            self._quiet_secretary_dialog()
        """
        if self._secretary_dialog_timer.isActive():
            self._secretary_dialog_timer.stop()
        self.target_comment_label.setText("")
        self._set_secretary_dialog_quiet(True)

    def _set_secretary_dialog_quiet(self, quiet: bool) -> None:
        """
        设置秘书舰对话框静默属性，并刷新 QSS。
        输入：
            quiet: True 表示透明静默。
        输出：
            None。
        使用示例：
            self._set_secretary_dialog_quiet(True)
        """
        self.secretary_dialog_frame.setProperty("quiet", quiet)
        self.secretary_dialog_frame.style().unpolish(self.secretary_dialog_frame)
        self.secretary_dialog_frame.style().polish(self.secretary_dialog_frame)
        self.secretary_dialog_frame.update()

    def _apply_progress_bar_style(self, progress: float) -> None:
        """根据目标进度给进度条换色。"""
        tokens = getattr(self, "theme_tokens", ThemeTokens())
        if progress >= 100:
            color = tokens.success
        elif progress >= 70:
            color = tokens.azure
        elif progress >= 40:
            color = tokens.gold
        else:
            color = tokens.danger
        self.overall_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {tokens.surface};
                color: {tokens.text};
                border: 1px solid {tokens.line};
                border-radius: 8px;
                text-align: center;
                min-width: 34px;
                min-height: 220px;
            }}
            QProgressBar::chunk {{
                background: {color};
                border-radius: 7px;
            }}
        """)

    def _apply_luck_badge_style(self, luck_level: str) -> None:
        """按欧非评价设置标签颜色。"""
        styles = {
            "极非": ("#6F7C89", "#F3F7FA", "#8C9AA8"),
            "较非": ("#8FA4B8", "#07131F", "#B7C7D8"),
            "正常": ("#F2F7FA", "#07131F", "#FFFFFF"),
            "较欧": ("#FFD36A", "#07131F", "#FFE49B"),
            "极欧": ("#FF8EC7", "#07131F", "#58D7FF"),
            "未知": ("#214E72", "#A5BDCB", "#2C607D"),
        }
        background, text, border = styles.get(luck_level, styles["未知"])
        self.luck_value_label.setStyleSheet(f"""
            QLabel#luck_badge {{
                background: {background};
                color: {text};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 700;
            }}
        """)

    @staticmethod
    def theme_surface() -> str:
        """返回科研进度页局部进度条背景色。"""
        return "#102337"

    def _build_progress_card(self) -> QFrame:
        """构建用户目标导向的总体进度卡片。"""
        card = QFrame()
        card.setObjectName("content_panel")
        card.setFixedWidth(172)
        card.setMinimumHeight(320)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_label = QLabel("总体进度")
        title_label.setObjectName("panel_title")
        caption_label = QLabel("按彩装碎片 / 目标计算")
        caption_label.setObjectName("card_caption")
        caption_label.setWordWrap(True)

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.addStretch(1)
        bar_row.addWidget(self.overall_progress_bar)
        bar_row.addStretch(1)

        layout.addWidget(title_label)
        layout.addWidget(self.overall_percent_label)
        layout.addLayout(bar_row, stretch=1)
        layout.addWidget(self.progress_detail_label)
        layout.addWidget(caption_label)
        return card

    def _build_research_detail_area(self) -> QWidget:
        """构建科研进度页下方的竖向进度 + 金彩比 + 当期装备数量区域。"""
        area = QWidget()
        area.setObjectName("research_detail_area")
        area.setMinimumHeight(320)
        layout = QHBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        right_layout.addWidget(self.summary_cards["ratio_luck"])
        right_layout.addWidget(self.progress_table, stretch=1)

        layout.addWidget(self.summary_cards["progress"])
        layout.addWidget(right_panel, stretch=1)
        return area

    def _build_target_card(self) -> QFrame:
        """构建彩色科研装备目标选择卡片。"""
        card = QFrame()
        card.setObjectName("content_panel")
        card.setMinimumHeight(144)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        title_label = QLabel("目标彩装")
        title_label.setObjectName("panel_title")
        title_label.setFixedWidth(72)

        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(8)
        control_row = QHBoxLayout()
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)
        control_row.addWidget(title_label)
        control_row.addWidget(self.target_combo)
        left_column.addLayout(control_row)
        left_column.addWidget(self.completed_value_label)
        left_column.addStretch(1)

        secretary_row = QHBoxLayout()
        secretary_row.setSpacing(12)
        secretary_row.setContentsMargins(0, 0, 0, 0)
        secretary_row.addWidget(self.secretary_avatar_label, alignment=Qt.AlignmentFlag.AlignBottom)
        secretary_row.addWidget(self.secretary_dialog_frame, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(left_column)
        layout.addStretch(1)
        layout.addLayout(secretary_row)
        return card

    def _build_duration_card(self) -> QFrame:
        """构建科研已进行天数卡片。"""
        card = QFrame()
        card.setObjectName("content_panel")
        card.setMinimumHeight(144)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_label = QLabel("科研天数")
        title_label.setObjectName("panel_title")
        date_label = QLabel("开始")
        date_label.setObjectName("card_caption")
        header.addWidget(title_label)
        header.addStretch(1)
        header.addWidget(date_label)
        header.addWidget(self.start_date_edit)
        header.addWidget(self.reset_start_date_button)

        layout.addLayout(header)
        layout.addWidget(self.research_day_value_label)
        layout.addWidget(self.research_day_caption_label)
        layout.addWidget(self.duration_message_label)
        layout.addStretch(1)
        return card

    def _build_ratio_luck_card(self) -> QFrame:
        """构建金彩比与欧非评价平分展示卡片。"""
        card = QFrame()
        card.setObjectName("content_panel")
        card.setMinimumHeight(148)
        card.setMaximumHeight(172)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(18)

        ratio_title = QLabel("金彩装备比")
        ratio_title.setObjectName("panel_title")
        ratio_caption = QLabel("当期科研中：金色等效碎片总量 / 彩色等效碎片总量。")
        ratio_caption.setObjectName("card_caption")
        ratio_caption.setWordWrap(True)
        self.score_value_label.setObjectName("panel_title")

        luck_title = QLabel("欧非评价")
        luck_title.setObjectName("panel_title")
        luck_caption = QLabel("标签颜色按评价等级变化，方便一眼判断当前运势。")
        luck_caption.setObjectName("card_caption")
        luck_caption.setWordWrap(True)

        ratio_column = QVBoxLayout()
        ratio_column.setSpacing(6)
        ratio_column.addWidget(ratio_title)
        ratio_column.addWidget(self.score_value_label)
        ratio_column.addWidget(self.ratio_detail_label)
        ratio_column.addWidget(ratio_caption)

        luck_column = QVBoxLayout()
        luck_column.setSpacing(6)
        luck_column.addWidget(luck_title)
        luck_column.addWidget(self.luck_value_label)
        luck_column.addWidget(luck_caption)
        luck_column.addStretch(1)

        layout.addLayout(ratio_column, stretch=1)
        layout.addLayout(luck_column, stretch=1)
        return card


class TrendPage(BasePage):
    """
    历史趋势页面。
    输入：
        无。
    输出：
        QWidget，展示科研期金彩比趋势与指定装备碎片趋势。
    使用示例：
        page = TrendPage()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建历史趋势页面。"""
        super().__init__("历史趋势", "观察各科研期金彩比变化，并查询指定装备的碎片数量趋势。", parent)
        self.theme_tokens = ThemeTokens()
        self.trend_analyzer = get_trend_analyzer()
        self.user_data_manager = get_user_data_manager()
        self.luck_calculator = get_luck_calculator()
        self.equipment_manager = get_equipment_manager()
        self.research_manager = get_research_manager()
        self._equipment_search_results: List[Dict[str, object]] = []
        self._selected_equipment_lines: Dict[str, str] = {}

        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.end_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self._apply_available_date_range()
        self.start_date.dateChanged.connect(lambda _date=None: self.refresh_trend_preview())
        self.end_date.dateChanged.connect(lambda _date=None: self.refresh_trend_preview())

        self.chart_palette_combo = QComboBox()
        self.chart_palette_combo.setObjectName("chart_palette_combo")
        self.chart_palette_combo.addItem("默认线色", "default")
        self.chart_palette_combo.addItem("柔和线色", "soft")
        self.chart_palette_combo.addItem("高对比线色", "contrast")
        self.chart_palette_combo.currentIndexChanged.connect(lambda _index=0: self.refresh_trend_preview())

        common_panel = QFrame()
        common_panel.setObjectName("content_panel")
        common_controls = QHBoxLayout(common_panel)
        common_controls.setContentsMargins(16, 12, 16, 12)
        common_controls.setSpacing(10)
        self._build_common_trend_controls(common_controls)
        common_controls.addStretch(1)
        self.root.addWidget(common_panel)

        self.trend_tabs = QTabWidget()
        self.trend_tabs.setObjectName("trend_mode_tabs")
        self.trend_tabs.addTab(self._build_phase_trend_tab(), "科研金彩比")
        self.trend_tabs.addTab(self._build_equipment_trend_tab(), "装备碎片趋势")
        self.trend_tabs.currentChanged.connect(lambda _index=0: self._on_trend_tab_changed())
        self.trend_tabs.setMinimumHeight(150)
        self.trend_tabs.setMaximumHeight(190)
        self.trend_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.root.addWidget(self.trend_tabs)

        self.trend_panel = MatplotlibTrendPanel(
            "历史趋势图",
            "选择上方功能标签后，这里只展示当前功能对应的一张折线图。",
        )
        self.trend_panel.setObjectName("single_trend_panel")
        self.root.addWidget(self.trend_panel, stretch=4)

        self.search_equipment_options()
        self.apply_theme_tokens(self.theme_tokens)
        self._sync_trend_tab_height()
        self.refresh_trend_preview()

    def _build_common_trend_controls(self, parent_layout: QHBoxLayout) -> None:
        """构建两个趋势功能共用的日期、线色和刷新控件。"""
        self.import_history_button = QPushButton("导入/刷新历史数据")
        self.import_history_button.setObjectName("import_history_button")
        self.import_history_button.setToolTip("用户手动添加历史记录后，点击这里重新读取并刷新当前趋势图。")
        self.import_history_button.clicked.connect(self.reload_history_data)
        refresh_button = QPushButton("刷新趋势")
        refresh_button.clicked.connect(self.refresh_trend_preview)
        parent_layout.addWidget(QLabel("开始日期"))
        parent_layout.addWidget(self.start_date)
        parent_layout.addWidget(QLabel("结束日期"))
        parent_layout.addWidget(self.end_date)
        parent_layout.addWidget(QLabel("折线配色"))
        parent_layout.addWidget(self.chart_palette_combo)
        parent_layout.addWidget(self.import_history_button)
        parent_layout.addWidget(refresh_button)

    def _build_phase_trend_tab(self) -> QWidget:
        """构建科研金彩比趋势的控制标签页。"""
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        intro = QLabel("功能说明：从 PR2 开始，按日期展示不同科研期的金彩装备比（金色等效碎片总量 / 彩色等效碎片总量），可同时选择多个科研期。")
        intro.setObjectName("card_caption")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        phase_panel = QFrame()
        phase_panel.setObjectName("content_panel")
        phase_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        phase_layout = QVBoxLayout(phase_panel)
        phase_layout.setContentsMargins(14, 10, 14, 10)
        phase_layout.setSpacing(6)
        phase_header = QHBoxLayout()
        self.phase_drawer_button = QPushButton("选择科研期")
        self.phase_drawer_button.setObjectName("phase_drawer_button")
        self.phase_drawer_button.setToolTip("展开或收起科研期选择表。")
        self.phase_drawer_button.clicked.connect(self._toggle_phase_drawer)
        self.phase_selection_summary_label = QLabel("")
        self.phase_selection_summary_label.setObjectName("card_caption")
        phase_header.addWidget(self.phase_drawer_button)
        phase_header.addWidget(self.phase_selection_summary_label, stretch=1)
        phase_layout.addLayout(phase_header)

        self.phase_drawer_table = QTableWidget(0, 2)
        self.phase_drawer_table.setObjectName("phase_drawer_table")
        self.phase_drawer_table.setHorizontalHeaderLabels(["选择", "科研期"])
        self.phase_drawer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.phase_drawer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.phase_drawer_table.setMinimumHeight(0)
        self.phase_drawer_table.setMaximumHeight(190)
        polish_data_table(self.phase_drawer_table, 34)
        self.phase_drawer_table.setVisible(False)
        self.phase_checks: Dict[int, QCheckBox] = {}
        for row, phase in enumerate(get_visible_research_phases()):
            phase_number = int(phase.get("phase_number", 0))
            checkbox = QCheckBox(f"PR{phase_number}")
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(lambda _state=0: self._on_phase_selection_changed())
            self.phase_checks[phase_number] = checkbox
            self.phase_drawer_table.insertRow(row)
            self.phase_drawer_table.setCellWidget(row, 0, checkbox)
            self.phase_drawer_table.setItem(row, 1, QTableWidgetItem(str(phase.get("name") or f"科研{phase_number}期(PR{phase_number})")))
        phase_layout.addWidget(self.phase_drawer_table)
        layout.addWidget(phase_panel)
        self._refresh_phase_selection_summary()
        return page

    def _build_equipment_trend_tab(self) -> QWidget:
        """构建单件装备碎片趋势的控制标签页。"""
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        intro = QLabel("功能说明：先输入装备名称进行查询，再把结果添加到右侧列表；列表中的多件装备会同时绘制碎片趋势线。")
        intro.setObjectName("card_caption")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        search_panel = QFrame()
        search_panel.setObjectName("content_panel")
        search_panel.setMinimumHeight(112)
        search_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        search_grid = QGridLayout(search_panel)
        search_grid.setContentsMargins(14, 12, 14, 12)
        search_grid.setHorizontalSpacing(10)
        search_grid.setVerticalSpacing(8)

        self.equipment_search_input = QLineEdit()
        self.equipment_search_input.setObjectName("trend_equipment_search")
        self.equipment_search_input.setPlaceholderText("输入装备名称，支持模糊或精确查询")
        self.equipment_search_input.setMinimumWidth(180)
        self.equipment_search_button = QPushButton("查询装备")
        self.equipment_search_button.clicked.connect(self.search_equipment_options)
        self.equipment_select_combo = QComboBox()
        self.equipment_select_combo.setObjectName("trend_equipment_select")
        self.equipment_select_combo.setMinimumWidth(260)
        self.add_equipment_line_button = QPushButton("添加折线")
        self.add_equipment_line_button.clicked.connect(self._add_selected_equipment_line)
        search_grid.addWidget(QLabel("装备名称"), 0, 0)
        search_grid.addWidget(self.equipment_search_input, 0, 1)
        search_grid.addWidget(self.equipment_search_button, 0, 2)
        search_grid.addWidget(QLabel("查询结果"), 1, 0)
        search_grid.addWidget(self.equipment_select_combo, 1, 1)
        search_grid.addWidget(self.add_equipment_line_button, 1, 2)
        search_grid.setColumnStretch(1, 1)

        selected_panel = QFrame()
        selected_panel.setObjectName("content_panel")
        selected_panel.setMinimumWidth(320)
        selected_panel.setMinimumHeight(136)
        selected_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        selected_layout = QVBoxLayout(selected_panel)
        selected_layout.setContentsMargins(14, 10, 14, 10)
        selected_layout.setSpacing(6)
        selected_title = QLabel("已选择划线装备")
        selected_title.setObjectName("panel_title")
        selected_hint = QLabel("右侧列表中的装备会一起绘制折线。")
        selected_hint.setObjectName("card_caption")
        selected_hint.setWordWrap(True)
        self.selected_equipment_list = QListWidget()
        self.selected_equipment_list.setObjectName("selected_equipment_line_list")
        self.selected_equipment_list.setMinimumHeight(78)
        button_row = QHBoxLayout()
        self.remove_equipment_line_button = QPushButton("移除")
        self.remove_equipment_line_button.clicked.connect(self._remove_selected_equipment_line)
        self.clear_equipment_lines_button = QPushButton("清空")
        self.clear_equipment_lines_button.clicked.connect(self._clear_selected_equipment_lines)
        button_row.addWidget(self.remove_equipment_line_button)
        button_row.addWidget(self.clear_equipment_lines_button)
        selected_layout.addWidget(selected_title)
        selected_layout.addWidget(selected_hint)
        selected_layout.addWidget(self.selected_equipment_list, stretch=1)
        selected_layout.addLayout(button_row)

        content_row.addWidget(search_panel, stretch=1)
        content_row.addWidget(selected_panel)
        layout.addLayout(content_row)
        return page

    def _on_trend_tab_changed(self) -> None:
        """
        趋势功能切换时同步控制区高度并刷新图表。
        输入：
            无。
        输出：
            None。
        使用示例：
            self._on_trend_tab_changed()
        """
        self._sync_trend_tab_height()
        self.refresh_trend_preview()

    def _sync_trend_tab_height(self) -> None:
        """
        按当前趋势功能调节上方控制区高度。
        输入：
            无。
        输出：
            None。
        使用示例：
            self._sync_trend_tab_height()
        """
        if self.trend_tabs.currentIndex() == 1:
            self.trend_tabs.setMinimumHeight(220)
            self.trend_tabs.setMaximumHeight(260)
            return
        expanded = getattr(self, "phase_drawer_table", None) is not None and not self.phase_drawer_table.isHidden()
        self.trend_tabs.setMinimumHeight(150)
        self.trend_tabs.setMaximumHeight(320 if expanded else 190)

    def _toggle_phase_drawer(self) -> None:
        """
        展开或收起科研期抽屉表。
        输入：
            无。
        输出：
            None。
        使用示例：
            self._toggle_phase_drawer()
        """
        expanded = not self.phase_drawer_table.isVisible()
        self.phase_drawer_table.setVisible(expanded)
        self.phase_drawer_button.setText("收起科研期" if expanded else "选择科研期")
        self._sync_trend_tab_height()
        self._refresh_phase_selection_summary()

    def _on_phase_selection_changed(self) -> None:
        """
        科研期勾选变化时刷新摘要和金彩比图。
        输入：
            无。
        输出：
            None。
        使用示例：
            checkbox.stateChanged.connect(lambda: self._on_phase_selection_changed())
        """
        self._refresh_phase_selection_summary()
        if hasattr(self, "trend_panel"):
            self.refresh_trend_preview()

    def _refresh_phase_selection_summary(self) -> None:
        """
        刷新科研期抽屉旁边的已选摘要。
        输入：
            无。
        输出：
            None。
        使用示例：
            self._refresh_phase_selection_summary()
        """
        if not self.phase_checks:
            self.phase_selection_summary_label.setText("暂无可选科研期")
            return
        checked = [phase for phase, checkbox in self.phase_checks.items() if checkbox.isChecked()]
        if not checked:
            self.phase_selection_summary_label.setText("未勾选时默认绘制全部可选科研期")
            return
        display = "、".join(f"PR{phase}" for phase in checked)
        self.phase_selection_summary_label.setText(f"已选择：{display}")

    def apply_theme_tokens(self, tokens: ThemeTokens) -> None:
        """
        接收主窗口皮肤令牌并刷新 matplotlib 图表样式。
        输入：
            tokens: 当前主窗口皮肤令牌。
        输出：
            None。
        使用示例：
            page.apply_theme_tokens(window.theme_tokens)
        """
        self.theme_tokens = tokens
        self.trend_panel.apply_theme_tokens(tokens)

    def refresh_trend_preview(self) -> None:
        """
        按当前功能标签刷新单张历史趋势折线图。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.refresh_trend_preview()
        """
        if self.trend_tabs.currentIndex() == 0:
            self.refresh_phase_ratio_chart()
            return
        self.refresh_equipment_fragment_chart()

    def refresh_phase_ratio_chart(self) -> None:
        """刷新各科研期金彩比折线图。"""
        series_map = self._build_phase_ratio_series_map()
        self.trend_panel.title_label.setText("科研期金彩比趋势")
        self.trend_panel.plot_series(
            series_map,
            "金彩比",
            "当前时间区间暂无可绘制的科研金彩比记录。",
            self._phase_color_map(series_map.keys()),
        )

    def refresh_equipment_fragment_chart(self) -> None:
        """刷新已选择装备的碎片数量折线图。"""
        if not self._selected_equipment_lines:
            self.trend_panel.title_label.setText("装备碎片数量趋势")
            self.trend_panel.plot_series(
                {},
                "碎片数量",
                "请先查询装备，并把需要划线的装备添加到右侧列表。",
            )
            return
        series_map = {
            equipment_name: self._build_equipment_fragment_series(equipment_id, equipment_name)
            for equipment_id, equipment_name in self._selected_equipment_lines.items()
        }
        self.trend_panel.title_label.setText("装备碎片数量趋势")
        self.trend_panel.plot_series(
            series_map,
            "碎片数量",
            "当前时间区间内没有已选择装备的碎片历史记录。",
            self._phase_color_map(series_map.keys()),
        )

    def reload_history_data(self) -> None:
        """
        重新读取历史数据并刷新当前趋势图。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.reload_history_data()
        """
        self.user_data_manager = get_user_data_manager()
        self.trend_analyzer = get_trend_analyzer()
        self._apply_available_date_range()
        self.refresh_trend_preview()
        self.trend_panel.status_label.setText("已重新读取历史记录，并刷新当前趋势图。")

    def search_equipment_options(self) -> None:
        """
        按输入名称搜索装备，并把结果放入选择框。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.search_equipment_options()
        """
        keyword = self.equipment_search_input.text().strip()
        rows = self._search_equipment_rows(keyword)
        self._equipment_search_results = rows
        self.equipment_select_combo.blockSignals(True)
        self.equipment_select_combo.clear()
        if not rows:
            self.equipment_select_combo.addItem("未找到装备", None)
        else:
            for equipment in rows[:30]:
                self.equipment_select_combo.addItem(str(equipment.get("name", "")), str(equipment.get("equipment_id", "")))
        self.equipment_select_combo.blockSignals(False)
        self.refresh_equipment_fragment_chart()

    def _add_selected_equipment_line(self) -> None:
        """把查询结果中的当前装备加入右侧划线列表。"""
        equipment_id = self.equipment_select_combo.currentData()
        if not equipment_id:
            return
        self._selected_equipment_lines[str(equipment_id)] = self.equipment_select_combo.currentText()
        self._refresh_selected_equipment_list()
        self.refresh_equipment_fragment_chart()

    def _remove_selected_equipment_line(self) -> None:
        """从右侧划线列表移除当前选中的装备。"""
        current_item = self.selected_equipment_list.currentItem()
        if current_item is None:
            return
        equipment_id = current_item.data(Qt.ItemDataRole.UserRole)
        self._selected_equipment_lines.pop(str(equipment_id), None)
        self._refresh_selected_equipment_list()
        self.refresh_equipment_fragment_chart()

    def _clear_selected_equipment_lines(self) -> None:
        """清空所有已选择的装备折线。"""
        self._selected_equipment_lines.clear()
        self._refresh_selected_equipment_list()
        self.refresh_equipment_fragment_chart()

    def _refresh_selected_equipment_list(self) -> None:
        """刷新右侧已选择划线装备列表。"""
        self.selected_equipment_list.clear()
        for equipment_id, equipment_name in self._selected_equipment_lines.items():
            item = QListWidgetItem(equipment_name)
            item.setData(Qt.ItemDataRole.UserRole, equipment_id)
            self.selected_equipment_list.addItem(item)

    def _search_equipment_rows(self, keyword: str) -> List[Dict[str, object]]:
        """
        搜索装备名称，精确匹配优先，模糊匹配补充。
        输入：
            keyword: 用户输入的装备名称片段。
        输出：
            List[dict]: 最多用于选择框展示的装备行。
        使用示例：
            rows = page._search_equipment_rows("406")
        """
        equipments = self.equipment_manager.get_equipment_with_image()
        if not keyword:
            return equipments[:10]
        normalized = keyword.lower()
        exact = [equipment for equipment in equipments if str(equipment.get("name", "")).lower() == normalized]
        fuzzy = [
            equipment for equipment in equipments
            if normalized in str(equipment.get("name", "")).lower()
            and equipment not in exact
        ]
        return exact + fuzzy

    def _selected_phase_numbers(self) -> List[int]:
        """返回当前勾选的科研期；未勾选时回退为全部期数。"""
        selected = [phase for phase, checkbox in self.phase_checks.items() if checkbox.isChecked()]
        return selected or list(self.phase_checks)

    def _build_phase_ratio_series_map(self) -> Dict[str, List[Dict[str, object]]]:
        """
        构建各科研期金彩比序列。
        输入：
            无。
        输出：
            Dict[str, List[dict]]: {"PR6": [{"date": "...", "value": ...}]}。
        使用示例：
            series = page._build_phase_ratio_series_map()
        """
        start = self.start_date.date().toString("yyyy-MM-dd")
        end = self.end_date.date().toString("yyyy-MM-dd")
        series_map: Dict[str, List[Dict[str, object]]] = {}
        for phase_number in self._selected_phase_numbers():
            points: List[Dict[str, object]] = []
            for date_str in self._available_dates_in_range(start, end):
                day_data = self.user_data_manager.get_data_by_date(date_str)
                result = self.luck_calculator.calculate_phase_luck(phase_number, day_data)
                rainbow_total = int(result.get("rainbow_total", 0) or 0)
                gold_total = int(result.get("gold_total", 0) or 0)
                ratio = None if rainbow_total <= 0 else round(gold_total / rainbow_total, 3)
                points.append({
                    "date": date_str,
                    "value": ratio,
                    "detail": f"金 {gold_total} / 彩 {rainbow_total}",
                })
            series_map[f"PR{phase_number}"] = points
        return series_map

    def _build_equipment_fragment_series(self, equipment_id: str, equipment_name: str) -> List[Dict[str, object]]:
        """构建单件装备碎片数量历史序列。"""
        start = self.start_date.date().toString("yyyy-MM-dd")
        end = self.end_date.date().toString("yyyy-MM-dd")
        points: List[Dict[str, object]] = []
        for row in self.user_data_manager.get_history(equipment_id):
            date_str = str(row.get("date", ""))
            if date_str < start or date_str > end:
                continue
            points.append({
                "date": date_str,
                "value": int(row.get("fragment_count", 0)),
                "detail": f"{equipment_name} 成品 {int(row.get('equipment_count', 0))}",
            })
        return points

    def _phase_color_map(self, names: Any) -> Dict[str, str]:
        """按当前线色方案生成科研期折线颜色。"""
        palette = str(self.chart_palette_combo.currentData() or "default")
        palettes = {
            "soft": ["#7FAFD2", "#D9B872", "#91C9A4", "#D69BC8", "#AFC4FF", "#E6AFAF"],
            "contrast": ["#1E88E5", "#F9A825", "#00A86B", "#D81B60", "#6A4CFF", "#E53935"],
            "default": [
                self.theme_tokens.azure,
                self.theme_tokens.sakura,
                self.theme_tokens.gold,
                self.theme_tokens.success,
                self.theme_tokens.danger,
                "#B8F09A",
            ],
        }
        selected_palette = palettes.get(palette, palettes["default"])
        return {name: selected_palette[index % len(selected_palette)] for index, name in enumerate(names)}

    def _available_dates_in_range(self, start: str, end: str) -> List[str]:
        """返回当前日期范围内的历史记录日期。"""
        return [
            date_str for date_str in self.user_data_manager.list_available_dates()
            if start <= date_str <= end
        ]

    def _apply_available_date_range(self) -> None:
        """按已有历史记录设置日期选择器默认值；没有记录时使用当天。"""
        date_range = self.trend_analyzer.get_available_date_range()
        today = QDate.currentDate()
        start = QDate.fromString(str(date_range.get("start") or today.toString("yyyy-MM-dd")), "yyyy-MM-dd")
        end = QDate.fromString(str(date_range.get("end") or today.toString("yyyy-MM-dd")), "yyyy-MM-dd")
        self.start_date.setDate(start if start.isValid() else today)
        self.end_date.setDate(end if end.isValid() else today)


class AutomationLabPage(BasePage):
    """
    自动化实验室页面。
    输入：
        registry: 未来功能注册表。
    输出：
        QWidget，展示模拟器连接、截图、OCR 和基础测试入口。
    使用示例：
        page = AutomationLabPage(registry)
    """

    featureRequested = Signal(str)

    def __init__(self, registry: FeatureHookRegistry, parent: Optional[QWidget] = None) -> None:
        """创建自动化实验室页面。"""
        super().__init__("自动化实验室", "检查模拟器连接、截图采集、OCR 识别和关键环境，帮助判断程序是否能正常运行。", parent)
        self.registry = registry
        self.automation_bridge = get_automation_bridge()
        grid = QGridLayout()
        grid.setSpacing(12)
        self.root.addLayout(grid, stretch=1)
        for index, (title, body) in enumerate([
            ("模拟器连接", "后续用于检测 ADB、设备在线状态和游戏窗口。"),
            ("登录截图", "后续用于采集当前画面，确认截图链路可用。"),
            ("OCR 识别测试", "后续用于识别玩家资源、装备数量和碎片数量。"),
            ("基础环境测试", "后续用于检查依赖、配置和导出目录。"),
        ]):
            grid.addWidget(BasePage.build_card(title, body), index // 2, index % 2)

        self.crawler_status_label = QLabel("待命：资料爬取模块将在 v0.6.0 合并后接入真实执行。")
        self.crawler_status_label.setObjectName("panel_body")
        self.crawler_status_label.setWordWrap(True)
        self.root.addWidget(self._build_crawler_update_panel())
        self.secretary_pack_status_label = QLabel("模板已预留：用户可按 README 制作秘书舰资源包。")
        self.secretary_pack_status_label.setObjectName("panel_body")
        self.secretary_pack_status_label.setWordWrap(True)
        self.root.addWidget(self._build_secretary_pack_panel())

        feature_panel = QFrame()
        feature_panel.setObjectName("content_panel")
        feature_layout = QVBoxLayout(feature_panel)
        feature_layout.setContentsMargins(16, 14, 16, 14)
        feature_layout.addWidget(QLabel("预留实验入口"))
        for feature in registry.get_all():
            if feature.key in {"automation_capture", "ocr_recognition"}:
                button = QPushButton(feature.title)
                button.clicked.connect(lambda _checked=False, key=feature.key: self.featureRequested.emit(key))
                feature_layout.addWidget(button)
        self.root.addWidget(feature_panel)

    def _build_crawler_update_panel(self) -> QFrame:
        """
        构建资料爬取与更新入口。
        输入：
            无。
        输出：
            QFrame: 自动化实验室中的 crawler 预留面板。
        使用示例：
            panel = self._build_crawler_update_panel()
        """
        panel = QFrame()
        panel.setObjectName("content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("资料爬取与更新")
        title.setObjectName("panel_title")
        self.crawler_update_button = QPushButton("检查并更新资料")
        self.crawler_update_button.setToolTip("后续会调用爬虫模块，更新装备、图片路径和科研基础资料。")
        self.crawler_update_button.clicked.connect(self._on_crawler_update_clicked)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.crawler_update_button)

        self.crawler_notice_label = QLabel("如果网页结构调整导致更新失败，请前往项目 GitHub 页面下载新版本；运行日志会保留错误信息，便于开发者修复。")
        self.crawler_notice_label.setObjectName("card_caption")
        self.crawler_notice_label.setWordWrap(True)

        layout.addLayout(title_row)
        layout.addWidget(self.crawler_status_label)
        layout.addWidget(self.crawler_notice_label)
        return panel

    def _on_crawler_update_clicked(self) -> None:
        """触发资料爬取安全桥接入口，并给出友好状态。"""
        result = self.automation_bridge.run_crawler_update()
        self.crawler_status_label.setText(result.message)
        self.featureRequested.emit("crawler_update")

    def _build_secretary_pack_panel(self) -> QFrame:
        """
        构建秘书舰资源包导入占位入口。
        输入：
            无。
        输出：
            QFrame: 自动化实验室中的秘书舰资源包面板。
        使用示例：
            panel = self._build_secretary_pack_panel()
        """
        panel = QFrame()
        panel.setObjectName("content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("秘书舰资源包")
        title.setObjectName("panel_title")
        self.secretary_pack_button = QPushButton("检查模板格式")
        self.secretary_pack_button.setToolTip("校验 resources/secretaries/template 是否符合秘书舰资源包要求。")
        self.secretary_pack_button.clicked.connect(self._on_secretary_pack_clicked)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.secretary_pack_button)

        notice = QLabel("P2 阶段先提供模板和校验占位；后续会支持选择用户打包的秘书舰资源包并导入。")
        notice.setObjectName("card_caption")
        notice.setWordWrap(True)

        layout.addLayout(title_row)
        layout.addWidget(self.secretary_pack_status_label)
        layout.addWidget(notice)
        return panel

    def _on_secretary_pack_clicked(self) -> None:
        """校验秘书舰模板资源包，并把结果展示到 UI。"""
        template_dir = PathManager.get_project_root() / "resources" / "secretaries" / "template"
        result = validate_secretary_pack(template_dir)
        if result.valid:
            self.secretary_pack_status_label.setText("秘书舰模板格式正确，可以作为用户自制资源包参考。")
            return
        self.secretary_pack_status_label.setText(f"{result.message} {'；'.join(result.errors)}")


class FutureDockPage(BasePage):
    """
    等待开发页面。
    输入：
        registry: 未来功能注册表。
    输出：
        QWidget，展示用户可理解的未来开发方向，不暴露内部字段。
    使用示例：
        page = FutureDockPage(get_feature_hook_registry())
    """

    featureRequested = Signal(str)

    def __init__(self, registry: FeatureHookRegistry, parent: Optional[QWidget] = None) -> None:
        """创建等待开发页面。"""
        super().__init__("等待开发", "这里展示后续可能加入的功能方向，当前只作为入口预留。", parent)
        self.set_header_compact()
        self.registry = registry
        self.future_scroll_area = ElasticScrollArea()
        self.future_scroll_area.setObjectName("future_scroll_area")
        self.future_scroll_content = QWidget()
        self.future_scroll_content.setObjectName("future_scroll_content")
        self.future_scroll_layout = QVBoxLayout(self.future_scroll_content)
        self.future_scroll_layout.setContentsMargins(0, 4, 10, 6)
        self.future_scroll_layout.setSpacing(16)

        for feature in registry.get_all():
            self.future_scroll_layout.addWidget(self._build_feature_row(feature))
        self.future_scroll_layout.addStretch(1)
        self.future_scroll_area.setWidget(self.future_scroll_content)
        self.root.addWidget(self.future_scroll_area, stretch=1)

    def _build_feature_row(self, feature: FutureFeatureSpec) -> QFrame:
        """构建一个用户可见的未来功能行。"""
        row = QFrame()
        row.setObjectName("future_feature_row")
        row.setMinimumHeight(104)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(18)

        text_box = QVBoxLayout()
        text_box.setSpacing(5)
        title = QLabel(feature.title)
        title.setObjectName("panel_title")
        title.setMinimumHeight(24)
        summary = QLabel(feature.summary)
        summary.setObjectName("panel_body")
        summary.setWordWrap(True)
        summary.setMinimumHeight(30)
        summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        status = QLabel("已预留入口")
        status.setObjectName("future_status")
        status.setMinimumHeight(18)
        text_box.addWidget(title)
        text_box.addWidget(summary)
        text_box.addWidget(status)

        button = QPushButton("查看入口")
        button.setMinimumWidth(96)
        button.clicked.connect(lambda _checked=False, key=feature.key: self.featureRequested.emit(key))

        layout.addLayout(text_box, stretch=1)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter)
        return row


class MiniGamePage(BasePage):
    """
    小游戏页面。
    输入：
        无。
    输出：
        QWidget，暂时展示占位符，后续接入等待小游戏。
    使用示例：
        page = MiniGamePage()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建小游戏占位页面。"""
        super().__init__("小游戏", "长时间装备更新或截图拼接时可打开这里，当前阶段先预留入口。", parent)
        self.root.addWidget(BasePage.build_card("开发中", "后续会接入轻量小游戏，不影响识别与统计任务运行。"), stretch=1)


class SettingsPage(BasePage):
    """
    设置页面。
    输入：
        无。
    输出：
        QWidget，预留普通用户设置入口。
    使用示例：
        page = SettingsPage()
    """

    skinChangeRequested = Signal(str)

    def __init__(self, active_skin: str = "harbor_night", parent: Optional[QWidget] = None) -> None:
        """创建设置页面。"""
        super().__init__("设置", "管理主题、资源刷新、导出和后续自动化相关设置。", parent)
        self.active_skin = active_skin
        self.skin_combo = QComboBox()
        self.skin_combo.setObjectName("skin_combo")
        self.skin_preview_cards: Dict[str, QFrame] = {}
        self.skin_preview_expanded = False
        self.skin_preview_limit = 3
        self.root.addWidget(self._build_skin_panel())
        self.skin_combo.currentIndexChanged.connect(self._on_skin_combo_changed)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.root.addLayout(grid, stretch=1)
        grid.addWidget(BasePage.build_card("显示细节", "表格、日志和导航栏会跟随皮肤使用更柔和的低眩光样式。"), 0, 0)
        grid.addWidget(BasePage.build_card("刷新频率", "玩家资源未来由 OCR 运行期更新，默认约 5 分钟一次。"), 0, 1)
        grid.addWidget(BasePage.build_card("自定义背景", "已预留背景图片路径、透明度和模糊配置，后续接入文件选择。"), 1, 0)
        grid.addWidget(BasePage.build_card("秘书舰资源包", "用户可按模板准备图片和台词，后续从自动化实验室导入。"), 1, 1)
        grid.addWidget(BasePage.build_card("导出设置", "后续可选择 CSV、Excel 和图片报告导出偏好。"), 2, 0)
        grid.addWidget(BasePage.build_card("打包启动", "未来发布为双击即可打开的 exe/快捷方式，并包含运行依赖。"), 2, 1)

    def _build_skin_panel(self) -> QFrame:
        """
        构建皮肤选择和预览区域。
        输入：
            无。
        输出：
            QFrame: 设置页顶部的皮肤面板。
        使用示例：
            panel = self._build_skin_panel()
        """
        panel = QFrame()
        panel.setObjectName("content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel("界面皮肤")
        title.setObjectName("panel_title")
        hint = QLabel("选择后会立即应用，并写入 GUI 外观配置。")
        hint.setObjectName("card_caption")
        hint.setWordWrap(True)
        title_row.addWidget(title)
        title_row.addWidget(hint, stretch=1)
        title_row.addWidget(self.skin_combo)
        layout.addLayout(title_row)

        preview_grid = QGridLayout()
        preview_grid.setSpacing(10)
        self.skin_preview_grid = preview_grid
        self.skin_preview_row = preview_grid
        preview_columns = self.skin_preview_limit + 1
        for index, skin in enumerate(list_theme_skins()):
            self.skin_combo.addItem(skin.name, skin.key)
            card = self._build_skin_preview_card(skin.key)
            self.skin_preview_cards[skin.key] = card
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.mousePressEvent = lambda _event, key=skin.key: self._select_skin_key(key)
            preview_grid.addWidget(card, index // preview_columns, index % preview_columns)
        self.skin_preview_expand_button = QPushButton("＋")
        self.skin_preview_expand_button.setObjectName("skin_preview_expand_button")
        self.skin_preview_expand_button.setToolTip("展开或收起其余阵营皮肤预览卡。")
        self.skin_preview_expand_button.setFixedWidth(56)
        self.skin_preview_expand_button.setMinimumHeight(104)
        self.skin_preview_expand_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.skin_preview_expand_button.clicked.connect(self._toggle_skin_preview_expand)
        preview_grid.addWidget(self.skin_preview_expand_button, 0, self.skin_preview_limit)
        layout.addLayout(preview_grid)

        index = self.skin_combo.findData(self.active_skin)
        self.skin_combo.setCurrentIndex(index if index >= 0 else 0)
        self._refresh_skin_preview_state()
        self._refresh_skin_preview_visibility()
        return panel

    def _build_skin_preview_card(self, skin_key: str) -> QFrame:
        """
        构建单个皮肤预览卡。
        输入：
            skin_key: 皮肤 key。
        输出：
            QFrame: 皮肤预览卡。
        使用示例：
            card = self._build_skin_preview_card("harbor_night")
        """
        skin = get_theme_skin(skin_key)
        card = QFrame()
        card.setObjectName("skin_preview_card")
        card.setMinimumWidth(165)
        card.setMinimumHeight(112)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel(skin.name)
        title.setObjectName("panel_title")
        desc = QLabel(skin.description)
        desc.setObjectName("panel_body")
        desc.setWordWrap(True)
        desc.setMinimumHeight(38)
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(5)
        for color in skin.preview_colors:
            swatch = QLabel()
            swatch.setObjectName("skin_swatch")
            swatch.setFixedSize(28, 18)
            swatch.setStyleSheet(f"background: {color}; border: 1px solid rgba(255,255,255,0.34); border-radius: 5px;")
            swatch_row.addWidget(swatch)
        swatch_row.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addLayout(swatch_row)
        return card

    def _on_skin_combo_changed(self) -> None:
        """皮肤下拉切换时通知主窗口应用新皮肤。"""
        skin_key = str(self.skin_combo.currentData() or "harbor_night")
        self.active_skin = skin_key
        self._refresh_skin_preview_state()
        self.skinChangeRequested.emit(skin_key)

    def _select_skin_key(self, skin_key: str) -> None:
        """
        点击皮肤预览卡时同步切换下拉框。
        输入：
            skin_key: 皮肤 key。
        输出：
            None。
        使用示例：
            self._select_skin_key("sakura_mist")
        """
        index = self.skin_combo.findData(skin_key)
        if index >= 0:
            self.skin_combo.setCurrentIndex(index)

    def _toggle_skin_preview_expand(self) -> None:
        """展开或收起额外皮肤预览卡。"""
        self.skin_preview_expanded = not self.skin_preview_expanded
        self._refresh_skin_preview_visibility()

    def _refresh_skin_preview_visibility(self) -> None:
        """默认只展示少量皮肤卡，展开后显示全部。"""
        keys = list(self.skin_preview_cards)
        if len(keys) <= self.skin_preview_limit:
            self.skin_preview_expand_button.setVisible(False)
            visible_keys = set(keys)
        elif self.skin_preview_expanded:
            self.skin_preview_expand_button.setText("－")
            self.skin_preview_expand_button.setVisible(True)
            visible_keys = set(keys)
        else:
            self.skin_preview_expand_button.setText("＋")
            self.skin_preview_expand_button.setVisible(True)
            visible = keys[:self.skin_preview_limit]
            if self.active_skin in keys and self.active_skin not in visible:
                visible[-1] = self.active_skin
            visible_keys = set(visible)
        visible_order = [key for key in keys if key in visible_keys]
        for skin_key, card in self.skin_preview_cards.items():
            card.setVisible(skin_key in visible_keys)
        preview_columns = self.skin_preview_limit + 1
        for index, skin_key in enumerate(visible_order):
            self.skin_preview_grid.addWidget(
                self.skin_preview_cards[skin_key],
                index // preview_columns,
                index % preview_columns,
            )
        if self.skin_preview_expand_button.isVisible():
            button_index = len(visible_order)
            self.skin_preview_grid.addWidget(
                self.skin_preview_expand_button,
                button_index // preview_columns,
                button_index % preview_columns,
            )

    def _refresh_skin_preview_state(self) -> None:
        """刷新皮肤预览卡的选中边框。"""
        for skin_key, card in self.skin_preview_cards.items():
            skin = get_theme_skin(skin_key)
            border = skin.tokens.sakura if skin_key == self.active_skin else skin.tokens.line
            card.setStyleSheet(
                f"QFrame#skin_preview_card {{"
                f"background: {skin.tokens.surface};"
                f"border: 1px solid {border};"
                f"border-radius: {skin.tokens.radius}px;"
                f"}}"
                f"QFrame#skin_preview_card QLabel#panel_title {{"
                f"color: {skin.tokens.text};"
                f"}}"
                f"QFrame#skin_preview_card QLabel#panel_body {{"
                f"color: {skin.tokens.text_muted};"
                f"}}"
            )
        self._refresh_skin_preview_visibility()


class AboutPage(BasePage):
    """
    关于页面。
    输入：
        无。
    输出：
        QWidget，展示项目版本和说明。
    使用示例：
        page = AboutPage()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建关于页面。"""
        super().__init__("关于", "碧蓝航线科研装备统计器用于统计科研装备、碎片进度与欧非值。", parent)
        self.root.addWidget(BasePage.build_card("当前阶段", "v0.5.0 GUI 界面开发：页面骨架、运行状态、日志抽屉和未来功能接口。"), stretch=1)


class MainWindow(QMainWindow):
    """
    v0.5.0 GUI 主窗口。
    输入：
        theme_tokens: 可选主题令牌。
        registry: 可选未来功能注册表。
    输出：
        QMainWindow，可由 QApplication 展示。
    使用示例：
        window = MainWindow()
        window.show()
    """

    def __init__(
        self,
        theme_tokens: Optional[ThemeTokens] = None,
        registry: Optional[FeatureHookRegistry] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """初始化主窗口、导航栏、页面栈、日志抽屉、菜单和状态栏。"""
        super().__init__(parent)
        self.logger = get_logger()
        self.ui_config_manager = get_ui_config_manager()
        self.active_skin = str(self.ui_config_manager.get_appearance_config().get("active_skin", "harbor_night"))
        self.theme_tokens = theme_tokens or get_theme_skin(self.active_skin).tokens
        self.registry = registry or get_feature_hook_registry()
        self.runtime_manager = get_runtime_state_manager()
        self.gui_version = get_gui_version()
        self.navigation_items = self._build_navigation_items()
        self.pages: Dict[str, QWidget] = {}
        self.nav_collapsed = False
        self._nav_animation: Optional[QParallelAnimationGroup] = None
        self.nav_animation_duration_ms = 180
        self._iron_pulse_on = False
        self._iron_blood_timer = QTimer(self)
        self._iron_blood_timer.setInterval(1200)
        self._iron_blood_timer.timeout.connect(self._toggle_iron_blood_pulse)

        current_app = QApplication.instance()
        if current_app is not None:
            install_application_fonts(current_app)

        self.setObjectName("main_window")
        self.setWindowTitle(self._build_window_title())
        self.resize(1280, 820)
        self.setMinimumSize(900, 620)

        self._build_shell()
        self._build_menu_bar()
        self._build_status_bar()
        self.setStyleSheet(build_stylesheet(self.theme_tokens))
        self._apply_page_theme_tokens()
        self._configure_skin_motion()
        self.runtime_manager.set_task_state(TaskStateKind.IDLE, 0)
        self.logger.info("GUI 主窗口骨架初始化完成")

    def _build_window_title(self) -> str:
        """从配置读取窗口标题。"""
        config = get_config_loader().get_main_config()
        app_config = config.get("app", {})
        name = app_config.get("name", "碧蓝航线科研装备统计器")
        return f"{name} {self.gui_version}"

    def _build_shell(self) -> None:
        """构建左侧导航、右侧页面栈和底部日志抽屉。"""
        central = QWidget()
        central.setObjectName("central_shell")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.navigation_panel = self._build_navigation_panel()
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("page_stack")

        for item in self.navigation_items:
            page = self._build_page(item)
            self.pages[item.key] = page
            self.page_stack.addWidget(page)

        body.addWidget(self.navigation_panel)
        body.addWidget(self.page_stack, stretch=1)
        root.addLayout(body, stretch=1)

        self.log_drawer = LogDrawer()
        self.log_drawer.install_logging_handler()
        root.addWidget(self.log_drawer)

        self.setCentralWidget(central)
        self.navigation_list.setCurrentRow(0)

    def _build_navigation_panel(self) -> QWidget:
        """构建左侧导航栏。"""
        panel = QWidget()
        panel.setObjectName("navigation_panel")
        panel.setFixedWidth(self.theme_tokens.nav_width)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(12)

        self.nav_toggle_button = QPushButton("<")
        self.nav_toggle_button.setObjectName("nav_toggle_button")
        self.nav_toggle_button.setFixedSize(32, 32)
        self.nav_toggle_button.clicked.connect(self.toggle_navigation)

        self.app_title = QLabel("港区控制台")
        self.app_title.setObjectName("app_title")
        self.app_subtitle = QLabel("科研装备统计器")
        self.app_subtitle.setObjectName("app_subtitle")

        self.navigation_list = QListWidget()
        self.navigation_list.setObjectName("navigation_list")
        self.navigation_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation_list.currentRowChanged.connect(self.on_navigation_changed)

        for item in self.navigation_items:
            list_item = QListWidgetItem(item.title)
            list_item.setData(Qt.ItemDataRole.UserRole, item.key)
            list_item.setToolTip(item.summary)
            self.navigation_list.addItem(list_item)

        layout.addWidget(self.nav_toggle_button, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.app_title)
        layout.addWidget(self.app_subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.navigation_list, stretch=1)
        return panel

    def _build_page(self, item: NavigationItem) -> QWidget:
        """按导航项创建页面。"""
        if item.key == "dashboard":
            page = DashboardPage()
            page.quickActionRequested.connect(self.switch_to_page)
            return page
        if item.key == "user_data":
            return UserDataPage()
        if item.key == "research_progress":
            return ResearchProgressPage()
        if item.key == "trend":
            return TrendPage()
        if item.key == "automation_lab":
            page = AutomationLabPage(self.registry)
            page.featureRequested.connect(self.on_future_feature_requested)
            return page
        if item.key == "future":
            page = FutureDockPage(self.registry)
            page.featureRequested.connect(self.on_future_feature_requested)
            return page
        if item.key == "mini_game":
            return MiniGamePage()
        if item.key == "settings":
            page = SettingsPage(self.active_skin)
            page.skinChangeRequested.connect(self.apply_theme_skin)
            return page
        if item.key == "about":
            return AboutPage()
        return BasePage(item.title, item.summary)

    def apply_theme_skin(self, skin_key: str) -> None:
        """
        应用并保存 GUI 皮肤。
        输入：
            skin_key: 皮肤注册表中的稳定键名。
        输出：
            None。
        使用示例：
            window.apply_theme_skin("sakura_mist")
        """
        skin = get_theme_skin(skin_key)
        self.active_skin = skin.key
        self.theme_tokens = skin.tokens
        self.setStyleSheet(build_stylesheet(self.theme_tokens))
        self._apply_page_theme_tokens()
        self._configure_skin_motion()
        self.ui_config_manager.save_active_skin(skin.key)
        width = self.theme_tokens.nav_collapsed_width if self.nav_collapsed else self.theme_tokens.nav_width
        self.navigation_panel.setFixedWidth(width)
        self.statusBar().showMessage(f"已切换界面皮肤：{skin.name}")

    def _configure_skin_motion(self) -> None:
        """
        按当前皮肤启停轻量动效。
        输入：
            无。
        输出：
            None。
        使用示例：
            self._configure_skin_motion()
        """
        if self.active_skin == "iron_blood":
            if not self._iron_blood_timer.isActive():
                self._iron_blood_timer.start()
        else:
            self._iron_blood_timer.stop()
            self._set_iron_blood_pulse(False)

    def _toggle_iron_blood_pulse(self) -> None:
        """铁血皮肤状态栏呼吸线动画。"""
        self._set_iron_blood_pulse(not self._iron_pulse_on)

    def _set_iron_blood_pulse(self, enabled: bool) -> None:
        """设置铁血呼吸线动态属性并刷新状态栏样式。"""
        self._iron_pulse_on = enabled
        status_bar = self.statusBar()
        if status_bar is None:
            return
        status_bar.setProperty("ironPulse", enabled)
        status_bar.style().unpolish(status_bar)
        status_bar.style().polish(status_bar)
        status_bar.update()

    def _apply_page_theme_tokens(self) -> None:
        """
        把主窗口皮肤同步给使用手写 Qt 样式的页面。
        输入：
            无。
        输出：
            None。
        使用示例：
            self._apply_page_theme_tokens()
        """
        for page in self.pages.values():
            apply_method = getattr(page, "apply_theme_tokens", None)
            if callable(apply_method):
                apply_method(self.theme_tokens)

    def _build_menu_bar(self) -> None:
        """创建菜单栏和快捷键。"""
        file_menu = self.menuBar().addMenu("文件")
        export_action = QAction("导出数据", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.on_export_action_triggered)
        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("视图")
        toggle_nav_action = QAction("折叠/展开导航", self)
        toggle_nav_action.setShortcut("Ctrl+B")
        toggle_nav_action.triggered.connect(self.toggle_navigation)
        toggle_log_action = QAction("打开运行日志", self)
        toggle_log_action.setShortcut("Ctrl+L")
        toggle_log_action.triggered.connect(self.log_drawer.toggle)
        view_menu.addAction(toggle_nav_action)
        view_menu.addAction(toggle_log_action)

        help_menu: QMenu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(lambda: self.switch_to_page("about"))
        help_menu.addAction(about_action)

    def _build_status_bar(self) -> None:
        """创建状态栏。"""
        status = QStatusBar()
        status.showMessage("港区系统待命，P1 GUI 页面骨架已加载")
        self.setStatusBar(status)

    @staticmethod
    def _build_navigation_items() -> List[NavigationItem]:
        """构建固定导航顺序。"""
        return [
            NavigationItem("dashboard", "港区实况", "港", "查看玩家资源、运行状态和快捷入口。"),
            NavigationItem("user_data", "用户数据", "数", "查看玩家装备与碎片记录。"),
            NavigationItem("research_progress", "科研进度", "研", "按科研期查看装备进度和欧非值。"),
            NavigationItem("trend", "历史趋势", "趋", "查看欧非值、装备数和碎片数变化。"),
            NavigationItem("automation_lab", "自动化实验室", "自", "检测模拟器、截图、OCR 与基础环境。"),
            NavigationItem("future", "等待开发", "待", "展示后续可能加入的功能。"),
            NavigationItem("mini_game", "小游戏", "游", "预留等待时可用的小游戏入口。"),
            NavigationItem("settings", "设置", "设", "管理主题、刷新和导出设置。"),
            NavigationItem("about", "关于", "关", "查看项目说明和当前阶段。"),
        ]

    def toggle_navigation(self) -> None:
        """
        折叠或展开左侧导航栏。
        输入：
            无。
        输出：
            None。
        使用示例：
            window.toggle_navigation()
        """
        self.nav_collapsed = not self.nav_collapsed
        target_width = self.theme_tokens.nav_collapsed_width if self.nav_collapsed else self.theme_tokens.nav_width
        self.nav_toggle_button.setText(">" if self.nav_collapsed else "<")
        if self.nav_collapsed:
            self._set_navigation_content_visible(False)
            for index in range(len(self.navigation_items)):
                self.navigation_list.item(index).setText("")
        self._animate_navigation_width(target_width)

    def _animate_navigation_width(self, target_width: int) -> None:
        """
        使用宽度动画展开或收起左侧导航栏。
        输入：
            target_width: 动画结束后的导航栏宽度。
        输出：
            None。
        使用示例：
            window._animate_navigation_width(76)
        """
        if self._nav_animation is not None:
            self._nav_animation.stop()

        start_width = self.navigation_panel.width()
        group = QParallelAnimationGroup(self)
        for property_name in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self.navigation_panel, property_name, group)
            animation.setDuration(self.nav_animation_duration_ms)
            animation.setStartValue(start_width)
            animation.setEndValue(target_width)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            group.addAnimation(animation)
        group.finished.connect(self._finish_navigation_animation)
        self._nav_animation = group
        group.start()

    def _finish_navigation_animation(self) -> None:
        """导航栏动画结束后固定宽度并恢复展开内容。"""
        width = self.theme_tokens.nav_collapsed_width if self.nav_collapsed else self.theme_tokens.nav_width
        self.navigation_panel.setFixedWidth(width)
        self._set_navigation_content_visible(not self.nav_collapsed)
        for index, item in enumerate(self.navigation_items):
            list_item = self.navigation_list.item(index)
            list_item.setText("" if self.nav_collapsed else item.title)

    def _set_navigation_content_visible(self, visible: bool) -> None:
        """统一控制导航栏内部内容显隐，避免折叠后残留单字导航。"""
        self.app_title.setVisible(visible)
        self.app_subtitle.setVisible(visible)
        self.navigation_list.setVisible(visible)

    def switch_to_page(self, key: str) -> None:
        """
        按页面 key 切换导航。
        输入：
            key: NavigationItem.key。
        输出：
            None。
        使用示例：
            window.switch_to_page("trend")
        """
        for index, item in enumerate(self.navigation_items):
            if item.key == key:
                self.navigation_list.setCurrentRow(index)
                return
        self.statusBar().showMessage("未找到对应页面")

    def on_navigation_changed(self, row: int) -> None:
        """
        响应导航切换。
        输入：
            row: QListWidget 当前行。
        输出：
            None。
        使用示例：
            navigation_list.setCurrentRow(1)
        """
        if row < 0:
            return
        self.page_stack.setCurrentIndex(row)
        item = self.navigation_items[row]
        self.statusBar().showMessage(f"已切换到 {item.title}")

    def on_future_feature_requested(self, key: str) -> None:
        """
        响应未来功能入口点击。
        输入：
            key: FutureFeatureSpec.key。
        输出：
            None。
        使用示例：
            page.featureRequested.emit("luck_prediction")
        """
        feature = self.registry.get(key)
        if feature is None:
            self.statusBar().showMessage("未找到功能入口")
            return
        emitted = self.registry.emit(key)
        if emitted:
            self.statusBar().showMessage(f"已触发 {feature.title}")
            return
        self.statusBar().showMessage(f"{feature.title} 已预留，等待后续模块接入")

    def on_export_action_triggered(self) -> None:
        """响应导出菜单动作，P1 阶段先保留入口。"""
        self.runtime_manager.set_task_state(TaskStateKind.EXPORTING, 0, "导出入口已预留，后续接入数据报告。")
        self.statusBar().showMessage("导出入口已预留，后续接入数据报告")

    def on_about_action_triggered(self) -> None:
        """显示关于窗口。"""
        QMessageBox.about(
            self,
            "关于",
            f"碧蓝航线科研装备统计器\n{self.gui_version} GUI 界面开发\n港区控制台主题已就绪。",
        )


# ============================================================
# 🌐 第四部分：全局运行函数
# ============================================================

def run_gui(argv: Optional[Sequence[str]] = None) -> int:
    """
    启动 PySide6 GUI。
    输入：
        argv: 可选命令行参数；不传则使用 sys.argv。
    输出：
        int: QApplication 退出码。
    使用示例：
        python -m ui.main_window
    """
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(list(argv) if argv is not None else sys.argv)
    window = MainWindow()
    window.show()
    if owns_app:
        return int(app.exec())
    return 0


if __name__ == "__main__":
    raise SystemExit(run_gui())
