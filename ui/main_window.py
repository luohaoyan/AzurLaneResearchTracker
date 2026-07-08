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
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QDate, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtGui import QAction, QColor, QMovie, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
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
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.data.equipment_manager import get_equipment_manager
from core.data.research_manager import get_research_manager
from core.calculation.trend_analyzer import get_trend_analyzer
from core.state.runtime_state import TaskStateKind, get_runtime_state_manager
from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager
from ui.future_hooks import FeatureHookRegistry, FutureFeatureSpec, get_feature_hook_registry
from ui.theme import ThemeTokens, build_stylesheet, install_application_fonts
from ui.widgets.log_drawer import LogDrawer


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
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 24, 28, 24)
        self.root.setSpacing(16)

        marker = QLabel("ALRT")
        marker.setObjectName("page_marker")
        title_label = QLabel(title)
        title_label.setObjectName("page_title")
        summary_label = QLabel(summary)
        summary_label.setObjectName("page_summary")
        summary_label.setWordWrap(True)

        self.root.addWidget(marker)
        self.root.addWidget(title_label)
        self.root.addWidget(summary_label)

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
        super().__init__("用户数据", "面向玩家展示装备与碎片记录。内部装备编号不会显示，也不会修改基础装备表。", parent)
        self.icon_size = 36
        self._build_filters()
        self._build_table()

    def _build_filters(self) -> None:
        """构建装备筛选控件。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        row = QHBoxLayout(panel)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("按装备名称搜索")
        self.rarity_combo = QComboBox()
        self.rarity_combo.addItems(["全部稀有度", "普通", "稀有", "精锐", "超稀有", "海上传奇"])
        self.type_combo = QComboBox()
        self.type_combo.addItems(["全部类型", "主炮", "鱼雷", "舰载机", "防空炮", "设备", "其他"])
        self.phase_combo = QComboBox()
        self.phase_combo.addItems(["全部科研期"] + self._phase_labels())

        row.addWidget(self.search_input, stretch=2)
        row.addWidget(self.rarity_combo)
        row.addWidget(self.type_combo)
        row.addWidget(self.phase_combo)
        self.root.addWidget(panel)

    def _build_table(self) -> None:
        """构建用户可见装备表格。"""
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["装备名称", "稀有度", "类型", "科研期", "拥有数量", "碎片数量"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.root.addWidget(self.table, stretch=1)
        self._load_preview_rows()

    def _load_preview_rows(self) -> None:
        """加载基础装备表作为只读预览，不显示 equipment_id。"""
        equipments = get_equipment_manager().get_equipment_with_image()[:20]
        self.table.setRowCount(len(equipments))
        for row, equipment in enumerate(equipments):
            phase = self._phase_from_public_data(str(equipment.get("equipment_id", "")))
            self.table.setCellWidget(row, 0, self._build_name_icon_cell(equipment))
            values = [equipment.get("rarity_name", "未知"), equipment.get("type", ""), phase, "待识别", "待识别"]
            for column, value in enumerate(values):
                self.table.setItem(row, column + 1, QTableWidgetItem(str(value)))

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
        if equipment_id.startswith("S") and "-" in equipment_id:
            return f"科研 {equipment_id.split('-', 1)[0][1:]} 期"
        return "通用"

    @staticmethod
    def _phase_labels() -> List[str]:
        """读取科研期列表并转换成用户可见标签。"""
        phases = get_research_manager().get_all()
        return [f"科研 {phase.get('phase_number')} 期" for phase in phases]


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
        phases = get_research_manager().get_all()
        latest_phase = max((int(phase.get("phase_number", 0)) for phase in phases), default=1)

        top = QHBoxLayout()
        self.phase_combo = QComboBox()
        for phase in phases:
            phase_number = int(phase.get("phase_number", 0))
            suffix = "（最新）" if phase_number == latest_phase else "（历史期）"
            self.phase_combo.addItem(f"科研 {phase_number} 期 {suffix}", phase_number)
        if self.phase_combo.count() == 0:
            self.phase_combo.addItem("科研数据待加载", 0)
        top.addWidget(QLabel("科研期数"))
        top.addWidget(self.phase_combo)
        top.addStretch(1)
        self.root.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.root.addLayout(grid, stretch=1)
        grid.addWidget(BasePage.build_card("装备数量进度", "后续接入 OCR 后展示每件装备拥有数量、碎片数量和合成进度。"), 0, 0)
        grid.addWidget(BasePage.build_card("欧非值评价", "当前暂无识别数据。未来会用图片和文字展示极欧、较欧、正常、较非、极非。"), 0, 1)
        grid.addWidget(BasePage.build_card("非最新期标注", "当选择历史科研期时，页面会提示这不是最新科研进度，避免误读。"), 1, 0)
        grid.addWidget(AnimatedMascotPanel(), 1, 1)


class TrendPage(BasePage):
    """
    历史趋势页面。
    输入：
        无。
    输出：
        QWidget，预留多指标折线图展示区域。
    使用示例：
        page = TrendPage()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建历史趋势页面。"""
        super().__init__("历史趋势", "选择时间区间和指标后，以折线图展示欧非值、装备数量和碎片总量变化。", parent)
        self.trend_analyzer = get_trend_analyzer()
        controls = QHBoxLayout()
        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.end_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self._apply_available_date_range()
        self.metric_specs = self.trend_analyzer.get_metric_specs()
        self.metric_combo = QComboBox()
        for spec in self.metric_specs:
            self.metric_combo.addItem(spec.title, spec.key)
        self.metric_combo.currentIndexChanged.connect(lambda _index=0: self.refresh_trend_preview())
        self.metric_checks: Dict[str, QCheckBox] = {}
        self.phase_combo = QComboBox()
        self.phase_combo.addItem("全部科研期", None)
        for phase in get_research_manager().get_all():
            phase_number = int(phase.get("phase_number", 0))
            self.phase_combo.addItem(f"科研 {phase_number} 期", phase_number)
        refresh_button = QPushButton("刷新趋势")
        refresh_button.clicked.connect(self.refresh_trend_preview)
        controls.addWidget(QLabel("开始"))
        controls.addWidget(self.start_date)
        controls.addWidget(QLabel("结束"))
        controls.addWidget(self.end_date)
        controls.addWidget(QLabel("科研期"))
        controls.addWidget(self.phase_combo)
        controls.addWidget(QLabel("指标"))
        controls.addWidget(self.metric_combo)
        controls.addWidget(refresh_button)
        controls.addStretch(1)
        self.root.addLayout(controls)

        metric_bar = QHBoxLayout()
        metric_bar.setSpacing(10)
        metric_bar.addWidget(QLabel("叠加曲线"))
        for spec in self.metric_specs:
            checkbox = QCheckBox(spec.title)
            checkbox.setChecked(spec.key in {"equipment_count", "fragment_count", "luck_value"})
            checkbox.stateChanged.connect(lambda _state=0: self.refresh_trend_preview())
            self.metric_checks[spec.key] = checkbox
            metric_bar.addWidget(checkbox)
        metric_bar.addStretch(1)
        self.root.addLayout(metric_bar)

        chart = QFrame()
        chart.setObjectName("chart_panel")
        chart_layout = QVBoxLayout(chart)
        chart_layout.setContentsMargins(18, 18, 18, 18)
        self.chart_title = QLabel("趋势折线图")
        self.chart_title.setObjectName("section_title")
        self.chart_status = QLabel("等待历史记录数据。")
        self.chart_status.setObjectName("panel_body")
        self.chart_status.setWordWrap(True)
        self.chart = QChart()
        self.chart.setBackgroundVisible(False)
        self.chart.legend().setVisible(True)
        self.chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumHeight(260)
        chart_layout.addWidget(self.chart_title)
        chart_layout.addWidget(self.chart_status)
        chart_layout.addWidget(self.chart_view)
        chart_layout.addStretch(1)
        self.root.addWidget(chart, stretch=1)

        self.trend_table = QTableWidget(0, 6)
        self.trend_table.setHorizontalHeaderLabels(["日期", "装备数量", "碎片总量", "等值分", "欧非值", "评价"])
        self.trend_table.verticalHeader().setVisible(False)
        self.trend_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.root.addWidget(self.trend_table, stretch=1)
        self.refresh_trend_preview()

    def refresh_trend_preview(self) -> None:
        """
        刷新历史趋势预览表和折线图。
        输入：
            无。
        输出：
            None。
        使用示例：
            page.refresh_trend_preview()
        """
        phase_number = self.phase_combo.currentData()
        rows = self.trend_analyzer.get_trend(
            self.start_date.date().toString("yyyy-MM-dd"),
            self.end_date.date().toString("yyyy-MM-dd"),
            int(phase_number) if phase_number is not None else None,
        )
        selected_metrics = self._get_selected_metric_keys()
        self._refresh_chart(rows, selected_metrics)
        self.trend_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("date", ""),
                row.get("equipment_count", 0),
                row.get("fragment_count", 0),
                row.get("equivalent_score", 0),
                self._format_luck_value(row.get("luck_value")),
                row.get("luck_level", "未知"),
            ]
            for column, value in enumerate(values):
                self.trend_table.setItem(row_index, column, QTableWidgetItem(str(value)))

    def _get_selected_metric_keys(self) -> List[str]:
        """
        获取当前勾选的趋势指标。
        输入：
            无。
        输出：
            List[str]: 至少包含一个指标键。
        使用示例：
            keys = page._get_selected_metric_keys()
        """
        selected = [key for key, checkbox in self.metric_checks.items() if checkbox.isChecked()]
        if selected:
            return selected
        current_key = self.metric_combo.currentData()
        return [str(current_key or "equipment_count")]

    def _refresh_chart(self, rows: List[Dict[str, object]], metric_keys: List[str]) -> None:
        """
        根据历史趋势数据刷新折线图。
        输入：
            rows: TrendAnalyzer 返回的按日期排列数据。
            metric_keys: 需要绘制的指标键。
        输出：
            None。
        使用示例：
            page._refresh_chart(rows, ["equipment_count", "luck_value"])
        """
        self.chart.removeAllSeries()
        if not rows:
            self.chart_status.setText("当前时间区间暂无历史记录；完成一次识别或录入后这里会自动出现趋势。")
            self._reset_chart_axes(1, 1, 0.0, 1.0, "记录序号", "数值")
            return

        specs = {spec.key: spec for spec in self.metric_specs}
        use_normalized_value = len(metric_keys) > 1
        y_values: List[float] = []
        for metric_key in metric_keys:
            spec = specs.get(metric_key)
            if spec is None:
                continue
            raw_values = [self._coerce_chart_value(row.get(metric_key)) for row in rows]
            visible_values = [value for value in raw_values if value is not None]
            if not visible_values:
                continue
            series = QLineSeries()
            series.setName(spec.title)
            series.setPen(QPen(QColor(spec.color), 2))
            min_value = min(visible_values)
            max_value = max(visible_values)
            for index, value in enumerate(raw_values, start=1):
                if value is None:
                    continue
                chart_value = self._normalize_chart_value(value, min_value, max_value) if use_normalized_value else value
                series.append(float(index), float(chart_value))
                y_values.append(float(chart_value))
            self.chart.addSeries(series)

        if not self.chart.series():
            self.chart_status.setText("当前指标暂时没有可绘制的数据，可以换一个指标或时间区间。")
            self._reset_chart_axes(1, max(1, len(rows)), 0.0, 1.0, "记录序号", "数值")
            return

        x_max = max(1, len(rows))
        y_min = min(y_values)
        y_max = max(y_values)
        if y_min == y_max:
            y_min -= 1.0
            y_max += 1.0
        y_padding = max((y_max - y_min) * 0.12, 1.0)
        self._reset_chart_axes(
            1,
            x_max,
            y_min - y_padding,
            y_max + y_padding,
            "记录序号",
            "归一化值" if use_normalized_value else "数值",
        )
        first_day = rows[0].get("date", "")
        last_day = rows[-1].get("date", "")
        mode = "多指标已按 0-100 归一化显示" if use_normalized_value else "单指标按原始数值显示"
        self.chart_status.setText(f"{first_day} 至 {last_day}，共 {len(rows)} 条记录；{mode}。")

    def _reset_chart_axes(
        self,
        x_min: int,
        x_max: int,
        y_min: float,
        y_max: float,
        x_title: str,
        y_title: str,
    ) -> None:
        """
        重建图表坐标轴，避免刷新后旧坐标轴残留。
        输入：
            x_min/x_max: 横轴范围。
            y_min/y_max: 纵轴范围。
            x_title/y_title: 坐标轴标题。
        输出：
            None。
        使用示例：
            page._reset_chart_axes(1, 3, 0.0, 100.0, "记录序号", "归一化值")
        """
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        axis_x = QValueAxis()
        axis_x.setTitleText(x_title)
        axis_x.setLabelFormat("%d")
        axis_x.setRange(float(x_min), float(max(x_min, x_max)))
        axis_x.setTickCount(max(2, min(8, x_max)))

        axis_y = QValueAxis()
        axis_y.setTitleText(y_title)
        axis_y.setLabelFormat("%.2f")
        axis_y.setRange(float(y_min), float(y_max))
        axis_y.setTickCount(5)

        self.chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        for series in self.chart.series():
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)

    @staticmethod
    def _normalize_chart_value(value: float, min_value: float, max_value: float) -> float:
        """把多指标数值压缩到 0-100，保证不同量纲可以叠加观察。"""
        if min_value == max_value:
            return 50.0
        return (value - min_value) / (max_value - min_value) * 100.0

    @staticmethod
    def _coerce_chart_value(value: object) -> Optional[float]:
        """把趋势值转换成图表可消费的浮点数；空值返回 None。"""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _apply_available_date_range(self) -> None:
        """按已有历史记录设置日期选择器默认值；没有记录时使用当天。"""
        date_range = self.trend_analyzer.get_available_date_range()
        today = QDate.currentDate()
        start = QDate.fromString(str(date_range.get("start") or today.toString("yyyy-MM-dd")), "yyyy-MM-dd")
        end = QDate.fromString(str(date_range.get("end") or today.toString("yyyy-MM-dd")), "yyyy-MM-dd")
        self.start_date.setDate(start if start.isValid() else today)
        self.end_date.setDate(end if end.isValid() else today)

    @staticmethod
    def _format_luck_value(value: object) -> str:
        """把欧非值转换为用户可读文本。"""
        if value is None:
            return "暂无"
        return f"{float(value):.3f}"


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
        self.registry = registry
        for feature in registry.get_all():
            self.root.addWidget(self._build_feature_row(feature))
        self.root.addStretch(1)

    def _build_feature_row(self, feature: FutureFeatureSpec) -> QFrame:
        """构建一个用户可见的未来功能行。"""
        row = QFrame()
        row.setObjectName("future_feature_row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_box = QVBoxLayout()
        title = QLabel(feature.title)
        title.setObjectName("panel_title")
        summary = QLabel(feature.summary)
        summary.setObjectName("panel_body")
        summary.setWordWrap(True)
        status = QLabel("已预留入口")
        status.setObjectName("future_status")
        text_box.addWidget(title)
        text_box.addWidget(summary)
        text_box.addWidget(status)

        button = QPushButton("查看入口")
        button.clicked.connect(lambda _checked=False, key=feature.key: self.featureRequested.emit(key))

        layout.addLayout(text_box, stretch=1)
        layout.addWidget(button)
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

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """创建设置页面。"""
        super().__init__("设置", "管理主题、资源刷新、导出和后续自动化相关设置。", parent)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.root.addLayout(grid, stretch=1)
        grid.addWidget(BasePage.build_card("界面主题", "后续支持港区深色、明亮主题和节日样式。"), 0, 0)
        grid.addWidget(BasePage.build_card("刷新频率", "玩家资源未来由 OCR 运行期更新，默认约 5 分钟一次。"), 0, 1)
        grid.addWidget(BasePage.build_card("导出设置", "后续可选择 CSV、Excel 和图片报告导出偏好。"), 1, 0)
        grid.addWidget(BasePage.build_card("打包启动", "未来发布为双击即可打开的 exe/快捷方式，并包含运行依赖。"), 1, 1)


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
        self.theme_tokens = theme_tokens or ThemeTokens()
        self.registry = registry or get_feature_hook_registry()
        self.runtime_manager = get_runtime_state_manager()
        self.gui_version = get_gui_version()
        self.navigation_items = self._build_navigation_items()
        self.pages: Dict[str, QWidget] = {}
        self.nav_collapsed = False
        self._nav_animation: Optional[QParallelAnimationGroup] = None
        self.nav_animation_duration_ms = 180

        current_app = QApplication.instance()
        if current_app is not None:
            install_application_fonts(current_app)

        self.setObjectName("main_window")
        self.setWindowTitle(self._build_window_title())
        self.resize(1280, 820)
        self.setMinimumSize(1040, 700)

        self._build_shell()
        self._build_menu_bar()
        self._build_status_bar()
        self.setStyleSheet(build_stylesheet(self.theme_tokens))
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

        self.nav_toggle_button = QPushButton("<<")
        self.nav_toggle_button.setObjectName("nav_toggle_button")
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

        layout.addWidget(self.nav_toggle_button)
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
            return SettingsPage()
        if item.key == "about":
            return AboutPage()
        return BasePage(item.title, item.summary)

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
        self.nav_toggle_button.setText(">>" if self.nav_collapsed else "<<")
        self._set_navigation_content_visible(True)
        for index, item in enumerate(self.navigation_items):
            list_item = self.navigation_list.item(index)
            list_item.setText(item.title)
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
