# 碧蓝航线科研装备统计器 — 开发文档

## 项目概况

| 属性 | 值 |
|------|-----|
| 项目名称 | 碧蓝航线科研装备统计器 (AzurLaneResearchTracker) |
| 当前版本 | v0.5.0 |
| 开发语言 | Python 3.12 |
| IDE | PyCharm 2024 |
| 测试框架 | pytest / unittest |
| 测试状态 | 800/804 项测试，99.5% 通过（376开发 + 390 QA） |

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
### v0.4.1 — 通用装备ID格式修复（已完成）★

完成日期：2026-07-09
类型：跨层Bug修复（v0.2.0数据层 → v0.3.0计算层 → v0.4.0 CLI层连锁修复）
测试：810项全部通过（249开发 + 561 QA，含24项GenID专项测试）

问题：EquipmentManager._generate_id() 通用装备分支生成纯数字ID（1,2,3...），
      与CSV实际数据（G0001,G0002）和文档声明（G{序号:04d}）不一致。

修复文件：
- core/data/equipment_manager.py — _generate_id() 通用分支改为解析G前缀最大序号+1
- test/test_data_layer.py — 断言 isdigit() → startswith("G")+isdigit()
- core/data/special_equipment_manager.py — 5处docstring示例ID更新
- test/test_calculation.py — 2处测试标签名更新
- core/cli/app.py — 排序键 isdigit() → startswith("G") 适配
- core/data/export_manager.py — 排序键同步适配

审查与测试：
- v0.2.0对话审查：69/69通过，零回归
- v0.3.0对话审查：175/175通过，docstring修复
- v0.4.0对话审查：258/258通过，排序键修复
- QA全量回归：810/810通过（含24项GenID专项）



### v0.5.0 — GUI界面 + 装备爬虫（已完成）★
完成日期：2026-07-10
分支：feature/v0.5.0-gui + feature/v0.5.0-crawler（并行开发）
测试：800/804（99.5%），全版本通过

**GUI 部分：**
  - ui/main_window.py：9页导航（港区总览/装备库/科研进度/历史趋势/自动化实验室/等待开发/小游戏/设置/关于）
  - ui/theme.py：多套阵营皮肤（铁血精修+东煌+预留白鹰/北联/重樱）
  - ui/widgets/log_drawer.py：日志抽屉（折叠/筛选/复制诊断/清空，含2px尾差容差）
  - ui/ui_config.py：UI配置管理（皮肤/表格密度/自定义背景）
  - ui/future_hooks.py：自动化安全桥接层
  - ui/automation_bridge.py：crawler/OCR 安全import接口
  - ui/secretary_pack.py：秘书舰资源包模板校验
  - 历史趋势图：matplotlib嵌入PySide6（金彩比+装备碎片双线）
  - 科研进度持久化：按期保存目标彩装数和开始时间

**Crawler 部分：**
  - crawler/equipment_crawler.py：装备图鉴页解析+抽样/全量+图片下载
  - crawler/research_crawler.py：研究室页面解析+科研装备识别
  - crawler/crawler_sync.py：stage→正式data同步+旧数据备份
  - crawler/crawler_integration.py：装备+科研结果整合到独立工作区

**配置文件新增：**
  - config/ui/appearance.json / research_progress.json / secretary_lines.json
  - config/crawler/equipment_crawler.json / research_crawler.json / crawler_sync.json / crawler_integration.json / research_image_bundle.json
  - resources/secretaries/template/（秘书舰资源包模板）

**已知问题：**
  - 日志抽屉动画高度偶发尾差（QPropertyAnimation容差，不影响功能）
  - OCR/crawler/模拟器自动化仍为接口占位，完整闭环依赖 v0.6.0
  - 爬虫需网络，受 wiki 页面结构稳定性影响

### v0.4.2 — 代码审查Bug修复（已完成）★

完成日期：2026-07-09
类型：全项目代码审查修复（3个轻微Bug + 3个附带问题）
测试：786项全部通过（252开发 + 534 QA，100%通过率）

发现来源：QA 全项目代码审查报告（qa_tests/reports/code_review_report.md）

修复内容：

BUG-REVIEW-001（归属v0.3.0）：特殊装备空ID校验不一致
  - 文件：core/data/special_equipment_manager.py（+6行）
  - delete_special("") 和 update_special("",{...}) 缺少空ID前置校验
  - 修复：统一添加空字符串校验 + 警告日志

BUG-REVIEW-002（归属v0.2.0）：_generate_id 缺少 phase 有效性守护
  - 文件：core/data/equipment_manager.py（+4行）
  - _generate_id(True, phase=0) 静默生成无效ID "S0-001"
  - 修复：添加 phase<=0 时 raise ValueError

BUG-REVIEW-003（归属v0.2.0）：add_research_phase_equipment 空列表边界
  - 文件：core/data/equipment_updater.py（+9行）
  - 空装备列表传入不存在期数时返回 success=True 但期数未创建
  - 修复：添加空列表前置守护，返回明确的失败信息

PRE-001（归属v0.5.0）：日志抽屉动画高度断言偶发失败
  - 文件：test/test_log_drawer.py
  - QPropertyAnimation 结束时高度可能差 7px（253 vs 260）
  - 修复：断言改为范围检查或增大 qWait

PRE-002（归属v0.3.0）：test_calculation.py 清理逻辑可能误删真实数据
  - 文件：test/test_calculation.py
  - 动态生成的 _tid 在特定执行顺序下可能等于真实装备ID
  - 修复：清理前添加名称前缀判断（__T 开头）

验收：QA 全量回归 786 项测试（100%通过率），6 项问题全部验证通过

### v0.5.0 — GUI界面 + Wiki装备爬虫（已完成）★

完成日期：2026-07-10
分支：feature/v0.5.0-gui + feature/v0.5.0-crawler（并行开发，双Worktree）
测试：800/804（99.5%），全版本通过

GUI 部分（9页面 + 6套皮肤 + matplotlib趋势图）：
  - ui/main_window.py：9页导航（港区实况/用户数据/科研进度/历史趋势/自动化实验室/等待开发/小游戏/设置/关于）
  - ui/theme.py：6套阵营皮肤（铁血精修+东煌+白鹰+北联+重樱+默认）+ 可折叠导航
  - ui/widgets/log_drawer.py：日志抽屉（折叠/筛选/复制诊断/清空）
  - 用户数据页：装备主表（icon+稀有度+科研期+装备数+碎片数）+ 装备库子页面（名称/稀有度/科研期筛选 + 右键添加趋势）
  - 科研进度页：按期保存目标彩装数+开始时间+官方日期配置（PR1-PR9）+ 金彩比+欧非评价+秘书舰对话
  - 历史趋势页：matplotlib折线图（金彩比/装备碎片双模式）+ 悬停提示+装备搜索
  - 自动化实验室：Crawler安全桥接（QThread+Worker+Signal，不阻塞主界面）
  - 皮肤系统：config/ui/appearance.json + research_progress.json + secretary_lines.json
  - 多线程：爬虫更新使用QThread后台执行，BusyOverlay提示

Crawler 部分（装备爬虫 + 科研爬虫 + 同步器）：
  - crawler/equipment_crawler.py：Wiki图鉴页解析→全量/抽样→图片下载→stage输出
  - crawler/research_crawler.py：研究室页面解析→通用S0+各期Sx装备识别→stage输出
  - crawler/crawler_sync.py：stage→正式data同步（备份+原子写入+旧行保留）
  - crawler/crawler_integration.py：装备+科研结果整合
  - 正式数据：equipment_library.csv(757行) / images(754) / phases(9期) / special(2)

已知非阻断问题（9项）：
  - Trend offscreen渲染时序 / QTimer测试时序 / phase动态计数 / 配置文件锁




---

## 核心设计决策

### 1. ID编码方案

| 装备类型 | ID格式 | 示例 |
|----------|--------|------|
| 科研装备 | S{期数}-{序号:03d} | S1-001, S7-003 |
| 通用装备 | G{序号:04d} | G0001, G0002 |

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
| G0001 | BR.810 剑鱼(810中队) | 4 | 鱼雷机 |
| G0002 | 双联装130mm主炮B-2LMT3 | 4 | 驱逐炮 |

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
| G0001 | BR.810 剑鱼(810中队) | 25碎片合成的特殊金装备--英航剑鱼 |
| G0002 | 双联装130mm主炮B-2LMT3 | 25碎片合成的特殊金装备--彩坷垃炮 |

---

## 项目架构

```
AzurLaneResearchTracker/
├── main.py                     # ✅ v0.4.0 入口壳（sys.path+CLI转发）
├── requirements.txt            # 依赖清单
├── AGENTS.md                   # Codex开发规范
│
├── crawler/                    # ✅ v0.5.0 Wiki爬虫
│   ├── equipment_crawler.py
│   ├── research_crawler.py
│   ├── crawler_sync.py
│   └── crawler_integration.py
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
├── ui/                         # ✅ v0.5.0 PySide6界面
├── config/                     # ✅ JSON配置
├── data/                       # ✅ 6个CSV+user_records/+exports/
├── test/                       # ✅ 249项开发测试
├── qa_tests/                   # ✅ 561项QA测试+报告
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
| v0.4.1 | 通用装备ID格式修复（G前缀统一，810测试） | ✅ 已完成 |
| v0.4.2 | 代码审查Bug修复（3轻微Bug+3附带，786测试） | ✅ 已完成 |
| v0.5.0 | PySide6 GUI + Wiki装备爬虫（543测试，99.5%） | ✅ 已完成 |

| v0.5.0 | GUI界面 + Wiki装备爬虫 | ✅ 已完成 |
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
| 测试 | pytest + unittest（766项） |
| 版本控制 | Git（main/develop + feature分支） |