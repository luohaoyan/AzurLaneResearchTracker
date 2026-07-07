# 碧蓝航线科研装备统计器

自动统计碧蓝航线科研装备数量和欧非值的桌面工具。

## 功能特点

- 安卓模拟器自动化操作（雷电 / MuMu）
- OpenCV 图像识别 + PaddleOCR 数字识别
- 装备库管理（增删改查 / 批量导入 / 图片映射）
- 科研期数管理（跨管理器关联查询）
- 碎片等值自动计算（8 种装备类别，int 整数运算）
- 欧非值计算（按期汇总 + 期数范围均值，Decimal 精确 3 位小数）
- 用户数据按日管理 + 历史趋势查询
- 特殊装备独立管理
- 公式可配置化（等值映射 + 欧非阈值，修改后持久化）
- PySide6 数据可视化（表格 / 折线图 / 柱状图）

## 技术栈

Python 3.12 ｜ CSV 数据存储 ｜ JSON 配置 ｜ OpenCV + Pillow 图像处理
PaddleOCR 文字识别 ｜ PySide6 GUI ｜ ADB 模拟器控制 ｜ pytest 测试

## 当前版本：v0.3.0

已完成基础设施层、数据层和计算层，195 项单元测试全部通过。
下一步：v0.4.0 CLI 入口 + 数据导出。

## 项目架构

```
AzurLaneResearchTracker/
├── main.py                     # 程序入口
├── requirements.txt            # 依赖清单
├── AGENTS.md                   # Codex 开发规范
│
├── core/
│   ├── utils/                  # ✅ 日志 / 路径 / 配置
│   ├── data/                   # ✅ 装备 / 科研 / 稀有度 / 特殊装备
│   ├── calculation/            # ✅ 公式 / 用户数据 / 碎片 / 欧非值
│   ├── automation/             # 📋 ADB 模拟器控制
│   └── recognition/            # 📋 OpenCV + PaddleOCR
│
├── ui/                         # 📋 PySide6 界面
├── data/                       # 6 个 CSV + user_records/
├── config/                     # JSON 配置文件
├── test/                       # 195 项测试
└── Logs/                       # 运行日志
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python test/test_data_layer.py
python test/test_calculation.py
```