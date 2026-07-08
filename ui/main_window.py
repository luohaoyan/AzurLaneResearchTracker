#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║             🖥️ GUI 主窗口骨架 (main_window.py)                  ║
║                                                                  ║
║   【一句话解释】创建 v0.5.0 PySide6 桌面界面的主窗口和导航框架。║
║   【类比理解】主窗口像港区指挥室，左侧选部门，右侧处理任务。    ║
║   【数据流说明】导航点击 → QStackedWidget 切页 → 未来页面接入。║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QMovie
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from core.utils.config_loader import get_config_loader
from core.utils.logger import get_logger
from core.utils.path_manager import PathManager
from ui.future_hooks import FeatureHookRegistry, FutureFeatureSpec, get_feature_hook_registry
from ui.theme import ThemeTokens, build_stylesheet, install_application_fonts


# ============================================================
# 🏗️ 第二部分：核心类
# ============================================================

@dataclass(frozen=True)
class NavigationItem:
    """
    左侧导航项定义。

    输入：
        key: 页面稳定键。
        title: 导航展示文本。
        summary: 页面简介。

    输出：
        不可变导航对象。

    使用示例：
        NavigationItem("dashboard", "港区总览", "查看今日状态")
    """

    key: str
    title: str
    summary: str


class AnimatedMascotPanel(QFrame):
    """
    二次元风格动效预留面板。

    输入：
        animation_path: 可选 GIF 路径；不存在时展示静态待机文案。

    输出：
        QWidget，可嵌入任何页面。

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

        self.title_label = QLabel(self.tr("秘书舰待机"))
        self.title_label.setObjectName("panel_title")
        self.motion_label = QLabel(self.tr("动画槽位已就绪"))
        self.motion_label.setObjectName("panel_body")
        self.motion_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.motion_label.setMinimumHeight(92)
        self.motion_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.hint_label = QLabel(self.tr("后续可接入 GIF / APNG / 序列帧，用于待机、保存成功、识别完成等反馈。"))
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
            self.motion_label.setText(self.tr("待机动画未配置"))
            return False

        movie = QMovie(str(path))
        if not movie.isValid():
            self.motion_label.setText(self.tr("动画资源无法播放"))
            return False

        self._movie = movie
        self.motion_label.setMovie(movie)
        movie.start()
        return True


class PlaceholderPage(QWidget):
    """
    P1 阶段通用占位页。

    输入：
        item: 导航项。
        panels: 页面要展示的重点能力列表。

    输出：
        QWidget，占位展示后续页面将承载的能力。

    使用示例：
        page = PlaceholderPage(item, ["筛选装备", "排序表格"])
    """

    def __init__(
        self,
        item: NavigationItem,
        panels: Sequence[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        """创建页面头部、内容面板和动效预留区。"""
        super().__init__(parent)
        self.setObjectName("page_shell")
        self.item = item

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        marker = QLabel(f"ALRT / {item.key}")
        marker.setObjectName("page_marker")
        title = QLabel(item.title)
        title.setObjectName("page_title")
        summary = QLabel(item.summary)
        summary.setObjectName("page_summary")
        summary.setWordWrap(True)

        root.addWidget(marker)
        root.addWidget(title)
        root.addWidget(summary)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        root.addLayout(content_row, stretch=1)

        panel_grid = QGridLayout()
        panel_grid.setSpacing(12)
        panel_grid.setContentsMargins(0, 0, 0, 0)
        panel_holder = QWidget()
        panel_holder.setLayout(panel_grid)

        for index, text in enumerate(panels):
            panel_grid.addWidget(self._build_panel(index + 1, text), index // 2, index % 2)

        content_row.addWidget(panel_holder, stretch=3)
        content_row.addWidget(AnimatedMascotPanel(), stretch=1)
        root.addStretch(1)

    def _build_panel(self, number: int, body: str) -> QFrame:
        """构建一个能力占位面板。"""
        panel = QFrame()
        panel.setObjectName("content_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel(f"{number:02d}")
        title.setObjectName("page_marker")
        label = QLabel(body)
        label.setObjectName("panel_body")
        label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(label)
        layout.addStretch(1)
        return panel


class FutureDockPage(QWidget):
    """
    未来功能泊位页。

    输入：
        registry: 未来功能注册表。

    输出：
        QWidget，展示自动化、OCR、模拟出货和欧非预测等预留接口。

    使用示例：
        page = FutureDockPage(get_feature_hook_registry())
    """

    featureRequested = Signal(str)

    def __init__(self, registry: FeatureHookRegistry, parent: Optional[QWidget] = None) -> None:
        """创建未来功能列表，并把按钮点击转换为 featureRequested 信号。"""
        super().__init__(parent)
        self.setObjectName("page_shell")
        self.registry = registry

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        marker = QLabel("ALRT / future-dock")
        marker.setObjectName("page_marker")
        title = QLabel(self.tr("自动化实验室"))
        title.setObjectName("page_title")
        summary = QLabel(self.tr("这里预留 ADB、OCR、科研出货模拟和欧非预测等功能入口。"))
        summary.setObjectName("page_summary")
        summary.setWordWrap(True)

        root.addWidget(marker)
        root.addWidget(title)
        root.addWidget(summary)

        for feature in registry.get_all():
            root.addWidget(self._build_feature_row(feature))
        root.addStretch(1)

    def _build_feature_row(self, feature: FutureFeatureSpec) -> QFrame:
        """构建一个未来功能行。"""
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
        status = QLabel(f"{feature.status} · {feature.entry_point}")
        status.setObjectName("future_status")
        text_box.addWidget(title)
        text_box.addWidget(summary)
        text_box.addWidget(status)

        button = QPushButton(self.tr("预留接口"))
        button.setProperty("feature_key", feature.key)
        button.clicked.connect(lambda _checked=False, key=feature.key: self.featureRequested.emit(key))

        layout.addLayout(text_box, stretch=1)
        layout.addWidget(button)
        return row


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
        """初始化主窗口、导航栏、页面栈、菜单和状态栏。"""
        super().__init__(parent)
        self.logger = get_logger()
        self.theme_tokens = theme_tokens or ThemeTokens()
        self.registry = registry or get_feature_hook_registry()
        self.navigation_items = self._build_navigation_items()
        self.pages: Dict[str, QWidget] = {}

        current_app = QApplication.instance()
        if current_app is not None:
            install_application_fonts(current_app)

        self.setObjectName("main_window")
        self.setWindowTitle(self._build_window_title())
        self.resize(1280, 800)
        self.setMinimumSize(1040, 680)

        self._build_shell()
        self._build_menu_bar()
        self._build_status_bar()
        self.setStyleSheet(build_stylesheet(self.theme_tokens))
        self.logger.info("GUI 主窗口骨架初始化完成")

    def _build_window_title(self) -> str:
        """从配置读取窗口标题。"""
        config = get_config_loader().get_main_config()
        app_config = config.get("app", {})
        name = app_config.get("name", "碧蓝航线科研装备统计器")
        version = app_config.get("version", "0.5.0")
        return f"{name} v{version}"

    def _build_shell(self) -> None:
        """构建左侧导航和右侧页面栈。"""
        central = QWidget()
        central.setObjectName("central_shell")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav_panel = self._build_navigation_panel()
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("page_stack")

        for item in self.navigation_items:
            page = self._build_page(item)
            self.pages[item.key] = page
            self.page_stack.addWidget(page)

        root.addWidget(nav_panel)
        root.addWidget(self.page_stack, stretch=1)
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

        title = QLabel(self.tr("港区研究室"))
        title.setObjectName("app_title")
        subtitle = QLabel(self.tr("科研装备统计器"))
        subtitle.setObjectName("app_subtitle")

        self.navigation_list = QListWidget()
        self.navigation_list.setObjectName("navigation_list")
        self.navigation_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation_list.currentRowChanged.connect(self.on_navigation_changed)

        for item in self.navigation_items:
            list_item = QListWidgetItem(item.title)
            list_item.setData(Qt.ItemDataRole.UserRole, item.key)
            list_item.setToolTip(item.summary)
            self.navigation_list.addItem(list_item)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.navigation_list, stretch=1)
        return panel

    def _build_page(self, item: NavigationItem) -> QWidget:
        """按导航项创建页面。"""
        if item.key == "automation_lab":
            page = FutureDockPage(self.registry)
            page.featureRequested.connect(self.on_future_feature_requested)
            return page

        panels = self._page_panels().get(item.key, [item.summary])
        return PlaceholderPage(item, panels)

    def _build_menu_bar(self) -> None:
        """创建菜单栏和快捷键。"""
        file_menu = self.menuBar().addMenu(self.tr("文件"))
        export_action = QAction(self.tr("导出数据"), self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.on_export_action_triggered)
        quit_action = QAction(self.tr("退出"), self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        help_menu: QMenu = self.menuBar().addMenu(self.tr("帮助"))
        about_action = QAction(self.tr("关于"), self)
        about_action.triggered.connect(self.on_about_action_triggered)
        help_menu.addAction(about_action)

    def _build_status_bar(self) -> None:
        """创建状态栏。"""
        status = QStatusBar()
        status.showMessage(self.tr("港区系统待命 · P1 GUI 骨架已加载"))
        self.setStatusBar(status)

    @staticmethod
    def _build_navigation_items() -> List[NavigationItem]:
        """构建固定导航顺序。"""
        return [
            NavigationItem("dashboard", "港区总览", "查看装备库、科研进度和今日录入的整体状态。"),
            NavigationItem("equipment_library", "装备库", "浏览装备、稀有度、类型和图片映射。"),
            NavigationItem("research_manager", "科研管理", "按 PR 期数查看关联装备，为后续 PR7+ 扩展留位。"),
            NavigationItem("data_entry", "数据录入", "手动记录装备数量和碎片数量，后续可接入 OCR 自动填充。"),
            NavigationItem("fragment_progress", "碎片进度", "查看等值分、进度条和按期汇总。"),
            NavigationItem("luck_display", "欧非值", "展示彩虹/金色分和欧非等级。"),
            NavigationItem("trend_display", "历史趋势", "按日期查看欧非值变化。"),
            NavigationItem("automation_lab", "自动化实验室", "预留 ADB、OCR、模拟出货与预测接口。"),
            NavigationItem("settings", "设置", "管理主题、公式、备份和关于信息。"),
        ]

    @staticmethod
    def _page_panels() -> Dict[str, List[str]]:
        """提供 P1 占位页能力说明。"""
        return {
            "dashboard": [
                "今日状态摘要：装备总数、科研期数、今日录入数量。",
                "港区提示语：后续按数据状态切换轻量二次元反馈文案。",
                "动效槽位：加载秘书舰待机 GIF 或保存成功动画。",
                "快捷入口：跳转到数据录入、欧非值和导出功能。",
            ],
            "equipment_library": [
                "表格模型预留：ID、名称、稀有度、类型、图片路径。",
                "筛选接口预留：稀有度、类型、科研期数和关键词。",
                "图片预览预留：未来展示装备立绘或装备图标。",
                "颜色映射预留：按稀有度显示金色、彩色等视觉标记。",
            ],
            "research_manager": [
                "期数列表预留：PR1 到 PR6，后续支持 PR7+。",
                "装备关联预留：点击期数后显示该期装备。",
                "统计预留：每期彩虹/金色/紫色装备数量。",
                "扩展预留：未来新增科研期可从这里维护。",
            ],
            "data_entry": [
                "表单预留：日期、装备、拥有数量、碎片数量。",
                "保存反馈预留：保存成功时触发轻量动效和状态栏提示。",
                "OCR 接入预留：自动识别结果可填入同一套表单。",
                "批量录入预留：CSV 或识别结果批量提交。",
            ],
            "fragment_progress": [
                "等值分表格预留：装备数、碎片数、等值分。",
                "进度条预留：按装备合成目标显示收集进度。",
                "按期筛选预留：全部 / PR1 / PR2 / ...。",
                "公式追踪预留：显示等值公式来源。",
            ],
            "luck_display": [
                "综合卡片预留：整体欧非值和等级。",
                "分期卡片预留：每期彩虹分、金色分、欧非值。",
                "图表预留：柱状图和折线图将使用 QtCharts。",
                "预测接口预留：接入未来欧非走势预测结果。",
            ],
            "trend_display": [
                "日期范围预留：按历史记录筛选趋势。",
                "折线图预留：展示单期或全期欧非值变化。",
                "悬浮提示预留：日期、欧非值、等级和分数组成。",
                "导出预留：将趋势数据导出为 CSV/Excel。",
            ],
            "settings": [
                "主题设置预留：港区深色、亮色、节日主题。",
                "公式设置预留：碎片等值和欧非阈值可编辑。",
                "动画资源预留：配置秘书舰待机 GIF 和反馈动效。",
                "自动化设置预留：模拟器、ADB 路径和识别参数。",
            ],
        }

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
        item = self.navigation_list.item(row)
        if item:
            self.statusBar().showMessage(f"已切换到 {item.text()}")

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
            self.statusBar().showMessage(self.tr("未找到功能入口"))
            return
        emitted = self.registry.emit(key)
        if emitted:
            self.statusBar().showMessage(f"已触发 {feature.title}")
            return
        self.statusBar().showMessage(f"{feature.title} 已预留，等待后续模块接入")

    def on_export_action_triggered(self) -> None:
        """响应导出菜单动作，P1 阶段先保留入口。"""
        self.statusBar().showMessage(self.tr("导出入口已预留，后续接入 ExportManager 对话框"))

    def on_about_action_triggered(self) -> None:
        """显示关于窗口。"""
        QMessageBox.about(
            self,
            self.tr("关于"),
            self.tr("碧蓝航线科研装备统计器\nv0.5.0 GUI 骨架\n港区控制台主题已就绪。"),
        )


# ============================================================
# 🌐 第三部分：全局运行函数
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
