# 碧蓝航线装备统计器 - 项目总结(0.0.0)
## 基础项目格式:
```
AzurLaneResearchTracker/
├── main.py                             # 程序主入口
├── launcher.py                         # 程序启动器（可选）
├── requirements.txt                    # 依赖包列表
├── README.md                          # 项目说明文档
├── .gitignore                         # Git忽略文件配置
├── config.json                        # 主配置文件
│
├── core/                              # 核心功能模块
│   ├── __init__.py
│   ├── automation/                    # 自动化相关模块
│   │   ├── __init__.py
│   │   ├── base_automator.py          # 自动化基类
│   │   ├── simulator_controller.py    # 模拟器控制器
│   │   ├── game_automator.py          # 游戏自动化
│   │   └── click_sequences/           # 点击序列定义
│   │       ├── __init__.py
│   │       ├── login_sequence.py      # 登录序列
│   │       ├── equipment_sequence.py  # 装备界面序列
│   │       └── research_sequence.py   # 科研界面序列
│   │
│   ├── recognition/                   # 识别相关模块
│   │   ├── __init__.py
│   │   ├── base_recognizer.py         # 识别基类
│   │   ├── image_recognizer.py        # 图像识别
│   │   ├── text_recognizer.py         # 文字识别（OCR）
│   │   ├── template_manager.py        # 模板管理
│   │   └── detectors/                 # 各种检测器
│   │       ├── __init__.py
│   │       ├── equipment_detector.py  # 装备检测
│   │       ├── fragment_detector.py   # 碎片检测
│   │       └── ui_detector.py         # UI元素检测
│   │
│   ├── data/                          # 数据管理模块
│   │   ├── __init__.py
│   │   ├── base_manager.py            # 数据管理基类
│   │   ├── equipment_manager.py       # 装备数据管理
│   │   ├── research_manager.py        # 科研数据管理
│   │   ├── luck_manager.py            # 欧非数据管理
│   │   └── export_manager.py          # 数据导出管理
│   │
│   ├── calculation/                   # 计算模块
│   │   ├── __init__.py
│   │   ├── base_calculator.py         # 计算基类
│   │   ├── fragment_calculator.py     # 碎片计算
│   │   ├── luck_calculator.py         # 欧非值计算
│   │   └── formula_manager.py         # 公式管理
│   │
│   └── utils/                         # 核心工具
│       ├── __init__.py
│       ├── config_loader.py           # 配置加载器
│       ├── logger.py                  # 日志工具
│       └── file_utils.py              # 文件工具
│
├── ui/                                # 用户界面模块
│   ├── __init__.py
│   ├── main_window.py                 # 主窗口
│   ├── equipment_library_ui.py        # 装备库管理
│   ├── research_manager_ui.py         # 科研管理
│   ├── data_display_ui.py             # 数据显示
│   ├── automation_control_ui.py       # 自动化控制面板
│   ├── settings_ui.py                 # 设置界面
│   └── widgets/                       # 自定义UI组件
│       ├── __init__.py
│       ├── equipment_card.py
│       ├── luck_chart.py
│       ├── automation_panel.py        # 自动化控制面板组件
│       └── config_editor.py           # 配置编辑器组件
│
├── data/                              # 数据存储目录
│   ├── __init__.py
│   ├── equipment_library.csv
│   ├── research_phases.csv
│   ├── research_equipment.csv
│   ├── luck_records.csv
│   ├── equipment_records/
│   │   └── __init__.py
│   ├── images/
│   │   └── __init__.py
│   └── exports/                       # 导出数据目录
│       └── __init__.py
│
├── config/                            # 配置文件目录
│   ├── __init__.py
│   ├── simulators/                    # 模拟器配置目录
│   │   ├── __init__.py
│   │   ├── mumu.json                  # MuMu模拟器配置
│   │   ├── leidian.json               # 雷电模拟器配置
│   │   ├── bluestacks.json            # 蓝叠模拟器配置
│   │   └── custom.json                # 自定义模拟器配置
│   │
│   ├── games/                         # 游戏配置目录
│   │   ├── __init__.py
│   │   ├── azur_lane.json             # 碧蓝航线配置
│   │   └── template_mapping.json      # 模板映射配置
│   │
│   ├── automation/                    # 自动化配置
│   │   ├── __init__.py
│   │   ├── sequences.json             # 点击序列配置
│   │   ├── timing.json                #  timing配置
│   │   └── retry_policy.json          # 重试策略配置
│   │
│   └── ui/                            # UI配置
│       ├── __init__.py
│       ├── themes.json                # 主题配置
│       └── layout.json                # 布局配置
│
├── resources/                         # 资源文件
│   ├── templates/                     # 图像识别模板
│   │   ├── azur_lane/                 # 碧蓝航线模板
│   │   │   ├── ui_elements/
│   │   │   ├── equipment/
│   │   │   └── fragments/
│   │   └── common/                    # 通用模板
│   │
│   ├── icons/                         # 程序图标
│   │   ├── app_icon.ico
│   │   ├── equipment.png
│   │   └── ...
│   │
│   └── fonts/                         # 字体文件
│       └── ...
│
├── plugins/                           # 插件目录（为未来扩展预留）
│   ├── __init__.py
│   ├── example_plugin.py
│   └── README.md
│
└── tests/                             # 测试目录
    ├── __init__.py
    ├── test_automation.py
    ├── test_recognition.py
    └── test_data.py
```


# 碧蓝航线科研装备统计器 - 项目总结（0.1.0）25.12.01

## 🚀 项目概述

**项目名称**：碧蓝航线科研装备统计器
**当前版本**：v0.1.0
**核心目标**：自动统计碧蓝航线游戏中科研装备数量和欧非值，提供可视化数据分析
**项目类型**：桌面自动化应用 + 数据分析工具
**项目状态**：基础架构已搭建，正在开发核心模块

## 🏗️ 技术架构

### 项目结构

text

复制下载

```
AzurLaneResearchTracker/
├── main.py                    # 程序入口（待开发）
├── core/                      # 核心功能模块
│   ├── utils/                 # 工具模块
│   │   └── logger.py          # 日志系统 ✅已完成
│   ├── data/                  # 数据管理模块（待开发）
│   ├── automation/            # 自动化模块（待开发）
│   ├── recognition/           # 识别模块（待开发）
│   └── calculation/           # 计算模块（待开发）
├── ui/                        # 用户界面模块（待开发）
├── config/                    # 配置文件目录（待开发）
├── data/                      # 数据存储目录（待初始化）
├── logs/                      # 日志目录 ✅已可用
├── resources/                 # 资源文件目录（待创建）
└── tests/                     # 测试文件目录
```



### 核心技术栈

- **Python版本**：3.11.0
- **开发工具**：PyCharm 2025
- **目标平台**：Windows（雷电/MuMu模拟器）
- **打包方式**：计划使用PyInstaller打包为exe

### 关键依赖包及版本

txt

复制下载

```
opencv-python==4.8.1.78       # 图像识别（待添加）
pillow==10.0.1                # 图像处理（待添加）
pysimplegui==4.60.4           # UI界面（待添加）
pyautogui==0.9.54             # 自动化控制（待添加）
pandas==2.0.3                 # 数据处理（待添加）
matplotlib==3.7.2             # 数据可视化（待添加）
```



## 📝 当前开发状态

### ✅ 已完成功能

**1. 日志系统模块**

- 所在文件：`core/utils/logger.py`
- 核心类：`Logger`（单例模式）
- 功能：多级别日志记录、文件轮转、错误日志分离、自定义日志方法
- 状态：✅ 已完成并测试通过
- 输出：`Logs/AzurLaneResearchTracker_YYYYMMDD.log`

**2. 项目基础架构**

- 已建立完整的项目目录结构
- 已创建各模块的`__init__.py`文件

### 🚧 进行中的功能

**暂无** - 已完成基础模块，等待下一步开发

### 📋 待开发功能（TODO列表）

**第一阶段：核心基础模块**

1. **配置管理模块** (`core/utils/config_loader.py`)
   - JSON配置文件管理
   - 默认配置生成
   - 模拟器/游戏配置加载
2. **装备数据管理** (`core/data/equipment_manager.py`)
   - CSV格式装备库管理
   - 装备图片存储
   - 每日装备记录保存
3. **科研数据管理** (`core/data/research_manager.py`)
   - 科研期数定义
   - 科研装备关联
   - 欧非值记录

**第二阶段：计算模块**
\4. **碎片计算器** (`core/calculation/fragment_calculator.py`)

- 科研装备碎片公式计算
- 普通装备碎片公式计算

1. **欧非值计算器** (`core/calculation/luck_calculator.py`)
   - 科研欧非值计算
   - 公式可配置化

**第三阶段：UI界面模块**
\6. **主窗口界面** (`ui/main_window.py`)

- 程序主界面
- 功能导航面板

1. **装备库管理界面** (`ui/equipment_library_ui.py`)
   - 装备添加/删除/修改
   - 图片导入功能
2. **科研管理界面** (`ui/research_manager_ui.py`)
   - 科研期数定义
   - 欧非值可视化图表

**第四阶段：自动化与识别模块**
\9. **模拟器控制器** (`core/automation/simulator_controller.py`)

- 模拟器连接控制
- 点击/滑动操作

1. **图像识别器** (`core/recognition/image_recognizer.py`)
   - 装备识别
   - 碎片数量识别
   - 模板匹配

**第五阶段：打包与分发**
\11. **程序打包**
\- PyInstaller配置文件
\- 一键打包脚本
\- 安装程序制作

## ⚠️ 已知问题与解决方案

| 问题描述           | 解决方案                                | 状态     |
| :----------------- | :-------------------------------------- | :------- |
| 日志模块递归错误   | 移除`__getattr__`委托，显式定义所有方法 | ✅ 已解决 |
| 日志文件位置不统一 | 修改为项目根目录下的`Logs`文件夹        | ✅ 已解决 |
| 后续模块依赖关系   | 按阶段顺序开发，避免循环依赖            | 🚧 进行中 |

## 🔧 关键代码片段

### 核心逻辑：日志系统初始化

python

复制下载

```
# 位置：core/utils/logger.py
class Logger:
    """日志管理类 - 安全版本，避免递归"""
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, name="AzurLaneResearchTracker", log_dir="../Logs", level=logging.DEBUG):
        if hasattr(self, '_initialized'):
            return
        
        self.name = name
        self.log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), log_dir))
        self.level = level
        os.makedirs(self.log_dir, exist_ok=True)
        self.start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._setup_logger()
        self._initialized = True
```



### 核心逻辑：单例模式便捷函数

python

复制下载

```
# 位置：core/utils/logger.py
def get_logger(name="AzurLaneResearchTracker"):
    """获取全局日志器实例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(name=name)
    return _logger_instance

def setup_logging(name="AzurLaneResearchTracker", log_dir="../Logs", level=logging.DEBUG):
    """设置全局日志配置"""
    global _logger_instance
    _logger_instance = Logger(name=name, log_dir=log_dir, level=level)
    return _logger_instance
```



## 🧪 运行与测试

### 安装依赖（当前）

bash

复制下载

```
# 当前所需依赖较少，后续会增加
pip install opencv-python pillow pysimplegui pyautogui pandas matplotlib
```



### 运行测试

bash

复制下载

```
# 测试日志模块
python test_logger.py
```



### 运行程序（待开发）

bash

复制下载

```
# 主程序入口（待实现）
python main.py
```



## 📊 数据流说明

text

复制下载

```
模拟器操作 → 图像识别 → 装备数据 → 碎片计算 → 欧非值计算 → UI展示
    ↓           ↓           ↓           ↓           ↓         ↓
日志记录    配置管理    数据存储    公式配置    数据记录    用户交互
```



## 🔄 开发建议顺序

1. **配置管理模块** - 建立程序配置基础
2. **数据管理模块** - 建立数据存储基础
3. **计算模块** - 实现核心算法
4. **UI界面模块** - 提供用户交互
5. **自动化与识别模块** - 实现自动化功能
6. **打包分发** - 制作可执行文件

## 📞 快速开始新对话

**复制此总结到新对话，然后说明：**
"我已完成了碧蓝航线统计器的日志模块，现在需要开发配置管理模块，请帮我设计config_loader.py，要求使用JSON存储配置，支持模拟器配置、游戏配置和程序设置，并集成日志功能。"