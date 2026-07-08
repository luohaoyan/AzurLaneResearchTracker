# 碧蓝航线科研装备统计器 — 开发文档

## 项目概况

| 属性 | 值 |
|------|-----|
| 项目名称 | 碧蓝航线科研装备统计器 (AzurLaneResearchTracker) |
| 当前版本 | v0.4.0 |
| 开发语言 | Python 3.12 |
| IDE | PyCharm 2024 |
| 测试框架 | pytest / unittest |
| 测试状态 | 462 项测试，全部通过（225开发 + 237 QA） |

---

## 版本历史

### v0.1.0 — 基础设施层（已完成）

完成模块：
- core/utils/logger.py — 日志系统，单例模式，RotatingFileHandler（10MB、5个备份），双文件输出（普通+错误）
- core/utils/path_manager.py — 路径管理器，基于Path(__file__)相对解析，提供get_project_root/get_config_dir/get_log_dir/get_data_dir
- core/utils/config_loader.py — JSON配置加载器，单例模式+缓存，支持主配置、模拟器配置、游戏配置的加载/保存/深度更新
- config/*.json — 主配置、MuMu/雷电模拟器配置、碧蓝航线游戏配置、自动化序列配置

### v0.2.0 — 数据层（已完成）★

完成模块：
- core/data/rarity_manager.py — 稀有度独立管理器，CSV存储（rarity_id/name/color_hex/sort_order），完整CRUD
- core/data/equipment_manager.py — 装备数据管理器，CSV存储+图片映射分离，ID编码/解析工具，延迟加载稀有度管理器
- core/data/research_manager.py — 科研期数管理器，跨管理器关联查询（查某期->所有装备详情+稀有度名称），延迟加载装备管理器
- core/data/equipment_updater.py — 批量添加整期科研装备（1行代码：1彩虹+5金色，自动生成ID+创建期数记录）

数据文件：
- data/rarities.csv — 5种稀有度（普通/稀有/精锐/超稀有/海上传奇）
- data/equipment_library.csv — 12件初始科研装备（S1-001~S6-002），4字段（equipment_id/name/rarity_id/type）
- data/research_phases.csv — 6期科研（PR1~PR6），3字段（phase_number/name/equipment_list）
- data/equipment_images.csv — 装备图片映射表，独立存储

测试：test/test_all.py（后更名为test_data_layer.py）— 69项测试全部通过

### v0.2.1 — 测试重命名（已完成）

- test/test_all.py -> test/test_data_layer.py（命名规范化）
- 无功能变更，69/69测试通过

### v0.3.0 — 计算层（已完成）★

完成日期：2026-07-08
分支：feature/v0.3.0-calculation
测试：195项全部通过（69数据层 + 126计算层）

新增模块：
- core/data/special_equipment_manager.py (263行) — 特殊装备管理器，管理BR.810和B-13等非科研金色装备，ID与装备库严格对应
- core/calculation/formula_manager.py (370行) — 公式管理器，管理8种装备类别等值映射+欧非值阈值+特殊装备列表，公式可配置化+持久化写回JSON
- core/calculation/user_data_manager.py (~260行) — 用户数据管理器，按日分文件CSV存储（data/user_records/YYYY-MM-DD.csv），支持日期范围查询和历史趋势
- core/calculation/fragment_calculator.py (390行) — 碎片等值计算器，int整数运算，自动根据稀有度和类别选择公式，支持单件/批量/按期/全量计算
- core/calculation/luck_calculator.py (~420行) — 欧非值计算器，Decimal精确3位小数，按期汇总彩虹/金色装备得分，支持单期/全期/期数范围均值/历史趋势

新增数据文件：
- data/special_equipment.csv — 特殊装备表（BR.810剑鱼、B-13驱逐炮）

修改文件：
- config/games/azur_lane.json — 新增fragment_equivalents(6个等值键)+luck_levels(5个阈值)+luck_formula
- data/equipment_library.csv — 新增BR.810(ID=1)和B-13(ID=2)，装备总数12->14
- test/test_data_layer.py — 计数适配(12->14件)

核心设计决策：
1. 8种装备类别映射：科研彩色(50)/科研金色(25)/特殊金色(25)/普通金色(15)/紫色(10)/蓝色(5)/白色(None)/普通彩色(None)
2. 精度策略：等值分int整数运算（避免浮点误差），欧非值Decimal保留3位小数
3. 特殊装备ID严格校验装备库中存在性
4. 公式修改后持久化写回JSON（set_equivalent/set_luck_level）
5. 用户数据按日分文件：修改只影响当天，历史不可篡改
6. 全部边界处理：除零->None+警告，inf趋势中自动跳过，NaN->None

### v0.4.0 — CLI入口+数据导出（已完成）★

完成日期：2026-07-08
分支：feature/v0.4.0-cli
测试：462项全部通过（225开发 + 237 QA，4个Bug全部修复并通过复测）

新增模块：
- core/cli/app.py — CLI主体逻辑（交互菜单+子命令+ASCII折线图）
- core/data/export_manager.py — 导出管理器（CSV+Excel，6种导出类型）
- test/test_cli_app.py — CLI测试
- test/test_export.py — 导出测试

架构变更：
- main.py瘦身为纯入口壳（仅sys.path注入+CLI转发）
- CLI逻辑从main.py拆分到core/cli/app.py
- 导出逻辑从CLI中独立为core/data/export_manager.py

CLI命令体系：
- python main.py -> 交互菜单
- python main.py status -> 状态查看（统计/欧非值/碎片/趋势）
- python main.py record -> 数据录入（交互/非交互单条/批量CSV/dry-run）
- python main.py export -> 数据导出（6种类型，CSV+Excel+一键全套报告）

关键增强：
- record支持--set非交互单条录入（为OCR/自动化预留接口）
- record支持--batch-file批量CSV录入
- record支持--dry-run仅校验不写入
- export --date参数统一YYYY-MM-DD校验
- export --output-dir优先于--output
- 导出层独立，GUI可绕过CLI直接调用ExportManager

QA测试：237项（边界/集成/回归），4个Bug全部修复并通过复测

---

## 核心设计决策

### 1. ID编码方案

| 装备类型 | ID格式 | 示例 |
|----------|--------|------|
| 科研装备 | S{期数}-{序号:03d} | S1-001, S7-003 |
| 通用装备 | 纯数字自增 | 1, 2 |

### 2. 稀有度独立管理

- 稀有度存在rarities.csv中，通过rarity_id关联
- 游戏更新稀有度等级时改CSV即可
- 装备管理器通过@property rarity_manager延迟加载

### 3. 图片映射分离

- equipment_images.csv独立存储{equipment_id -> image_path}
- 和装备数据解耦，图片地址可以空缺

### 4. 碎片等值自动计算

- 8种装备类别自动映射对应等值
- int整数运算避免浮点误差
- 公式从azur_lane.json读取，可配置+持久化

### 5. 欧非值计算

- 彩虹装备总分/金色装备总分
- Decimal精确3位小数
- 支持按期/全期/期数范围均值/历史趋势

### 6. 用户数据按日分文件

- data/user_records/YYYY-MM-DD.csv
- 修改只影响当天，历史不可篡改

### 7. CLI架构

- main.py纯入口壳（sys.path+转发）
- CLI逻辑在core/cli/app.py
- 导出层独立为core/data/export_manager.py
- GUI可绕过CLI直接调用ExportManager

---

## 数据表结构

### rarities.csv

| rarity_id | name | color_hex | sort_order |
|-----------|------|-----------|------------|
| 1 | 普通 | #FFFFFF | 1 |
| 2 | 稀有 | #4169E1 | 2 |
| 3 | 精锐 | #800080 | 3 |
| 4 | 超稀有 | #FFD700 | 4 |
| 5 | 海上传奇 | #FF69B4 | 5 |

### equipment_library.csv

| equipment_id | name | rarity_id | type |
|-------------|------|-----------|------|
| S1-001 | 试作型三联装406mm主炮Mk6 | 5 | 战列炮 |
| S1-002 | 试作型三联装152mm主炮Mk17 | 4 | 轻巡炮 |
| ... | ... | ... | ... |
| S6-002 | 试作型四联装356mm主炮Mk7 | 4 | 战列炮 |
| 1 | BR.810 剑鱼(810中队) | 4 | 鱼雷机 |
| 2 | 双联装130mm主炮B-2LMT3 | 4 | 驱逐炮 |

### research_phases.csv

| phase_number | name | equipment_list |
|-------------|------|----------------|
| 1 | 科研1期(PR1) | S1-001,S1-002 |
| 2 | 科研2期(PR2) | S2-001,S2-002 |
| ... | ... | ... |
| 6 | 科研6期(PR6) | S6-001,S6-002 |

### special_equipment.csv

| equipment_id | equipment_name | notes |
|-------------|----------------|-------|
| 1 | BR.810 剑鱼(810中队) | 25碎片合成的特殊金装备--英航剑鱼 |
| 2 | 双联装130mm主炮B-2LMT3 | 25碎片合成的特殊金装备--彩坷垃炮 |

---

## 项目架构

```
AzurLaneResearchTracker/
├── main.py                     # ✅ v0.4.0 入口壳（sys.path+CLI转发）
├── requirements.txt            # 依赖清单
├── AGENTS.md                   # Codex开发规范
│
├── core/
│   ├── utils/                  # ✅ v0.1.0 基础设施
│   │   ├── logger.py
│   │   ├── path_manager.py
│   │   └── config_loader.py
│   ├── data/                   # ✅ v0.2.0+v0.3.0+v0.4.0
│   │   ├── rarity_manager.py
│   │   ├── equipment_manager.py
│   │   ├── research_manager.py
│   │   ├── equipment_updater.py
│   │   ├── special_equipment_manager.py  # v0.3.0
│   │   └── export_manager.py            # v0.4.0
│   ├── calculation/            # ✅ v0.3.0
│   │   ├── formula_manager.py
│   │   ├── user_data_manager.py
│   │   ├── fragment_calculator.py
│   │   └── luck_calculator.py
│   ├── cli/                    # ✅ v0.4.0
│   │   └── app.py
│   ├── automation/             # 📋 v0.6.0
│   └── recognition/            # 📋 v0.6.0
│
├── ui/                         # 📋 v0.5.0 PySide6界面
├── config/                     # ✅ JSON配置
├── data/                       # ✅ 6个CSV+user_records/+exports/
├── test/                       # ✅ 225项开发测试
├── qa_tests/                   # ✅ 237项QA测试+报告
└── Logs/                       # 自动生成
```

---

## 开发路线图

| 版本 | 内容 | 状态 |
|------|------|------|
| v0.1.0 | 基础设施（日志+配置+路径管理） | ✅ 已完成 |
| v0.2.0 | 数据层（装备/科研/稀有度+4CSV+69测试） | ✅ 已完成 |
| v0.3.0 | 计算层（公式/碎片/欧非值/特殊装备+195测试） | ✅ 已完成 |
| v0.4.0 | CLI入口+数据导出（462测试） | ✅ 已完成 |
| v0.5.0 | PySide6 GUI界面 | 📋 下一步 |
| v0.6.0 | ADB自动化+PaddleOCR识别 | 📋 待开发 |
| v1.0.0 | 打包&发布 | 📋 待开发 |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 数据存储 | CSV（utf-8-sig编码） |
| 配置格式 | JSON |
| 图像处理 | OpenCV + Pillow |
| OCR | PaddleOCR 3.x |
| GUI | PySide6（LGPL许可） |
| 模拟器控制 | ADB（雷电LDPlayer优先） |
| CLI | argparse + prettytable |
| 导出 | CSV + openpyxl Excel |
| 测试 | pytest + unittest（462项） |
| 版本控制 | Git（main/develop + feature分支） |