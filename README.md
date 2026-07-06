
# 碧蓝航线科研装备统计器

自动统计碧蓝航线科研装备数量和欧非值的桌面工具。

## 功能特点

- 安卓模拟器自动化操作（雷电 / MuMu）
- OpenCV 图像识别 + PaddleOCR 数字识别
- 装备库管理（增删改查 / 批量导入 / 稀有度体系）
- 科研期数管理（跨管理器关联查询）
- 碎片数量统计 & 欧非值计算
- PySide6 数据可视化（表格 / 折线图 / 柱状图）

## 技术栈

Python 3.12 ｜ CSV 数据存储 ｜ JSON 配置 ｜ OpenCV + Pillow 图像处理
PaddleOCR 文字识别 ｜ PySide6 GUI ｜ ADB 模拟器控制 ｜ pytest 测试

## 当前版本：v0.2.0

已完成基础设施层（日志 / 配置 / 路径管理）和数据层（装备管理 / 科研管理 / 稀有度管理 / 批量更新工具），69 项单元测试全部通过。

## 项目架构

```
AzurLaneResearchTracker/
├── main.py                     # 程序入口
├── requirements.txt            # 依赖清单
├── AGENTS.md                   # Codex 开发规范
│
├── core/
│   ├── utils/                  # ✅ 日志 / 路径 / 配置
│   ├── data/                   # ✅ 装备 / 科研 / 稀有度 / 批量更新
│   ├── calculation/            # 📋 碎片 & 欧非值计算
│   ├── automation/             # 📋 ADB 模拟器控制
│   └── recognition/            # 📋 OpenCV + PaddleOCR
│
├── ui/                         # 📋 PySide6 界面
├── data/                       # 4 个 CSV 数据文件
├── config/                     # JSON 配置文件
├── test/                       # 单元测试
└── Logs/                       # 运行日志
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python test/test_all.py
```
