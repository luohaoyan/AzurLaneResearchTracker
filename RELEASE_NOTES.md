# AzurLaneResearchTracker — Release Notes

---

## v0.5.1（最新）— GUI+Crawler 最终整合

**测试：543/546（99.5%）**

### 爬虫同步安全加固
- _atomic_write_csv() 原子写入防半成品覆盖
- _collect_final_rows 旧行保留合并机制
- 爬虫同步测试 15/15 通过

### v0.4.0 维护补丁
- main.py CLI 入口恢复
- 排序键适配 G 前缀格式
- 导出缓存自动清理

### 已知非阻断问题（3 FAIL）
- Trend 1 FAIL：offscreen 渲染时序
- Fix Verify 2 FAIL：QTimer 测试时序

---

## v0.5.0 — PySide6 GUI + 装备爬虫

**测试：764/766（99.7%）**

### GUI 模块（9 页面）
- PySide6 主窗口骨架 + 9 页导航
- 用户数据表图标预留 + 内部字段隐藏
- 运行状态展示 + 日志抽屉（折叠/展开动画）
- 历史趋势 TrendAnalyzer + QtCharts 折线图
- 多指标趋势叠加
- GUI/CLI 版本号统一从 config.json 读取

### 装备爬虫模块
- 装备图鉴爬虫（按稀有度分层抽样）
- 科研期数爬虫
- 图片下载 + 稀有度目录分类
- 爬虫同步流程 + 原子写入
- 68 项爬虫专项测试

### 修复
- v0.4.1：通用装备 ID 统一为 G{序号:04d} 格式（810 测试）
- v0.4.2：3 轻微 Bug + 1 附带修复（785 测试）
- pytest ENV-001 默认临时目录修复

---

## v0.4.0 — CLI 入口 + 数据导出

**测试：462 项全部通过**

### 新增模块
- core/cli/app.py — CLI 主体（交互菜单 + 子命令 + ASCII 折线图）
- core/data/export_manager.py — CSV/Excel 导出（6 种类型）
- test/test_cli_app.py、test/test_export.py

### 架构变更
- main.py 瘦身为入口壳（仅 sys.path + CLI 转发）
- 导出层独立，GUI 可绕过 CLI 直接调用
- CLI 支持交互菜单 + 子命令两种模式
- record 支持非交互单条/批量录入

---

## v0.3.0 — 计算层完成

**测试：195 项全部通过**

### 新增模块
- core/data/special_equipment_manager.py — 特殊装备管理器
- core/calculation/formula_manager.py — 公式管理器（可配置+持久化）
- core/calculation/user_data_manager.py — 用户数据管理器（按日分文件）
- core/calculation/fragment_calculator.py — 碎片等值计算器（8 种装备类别）
- core/calculation/luck_calculator.py — 欧非值计算器（按期汇总+范围均值）

### 核心特性
- 8 种装备类别碎片等值自动计算（int 整数运算）
- 欧非值按期汇总 + 期数范围均值（Decimal 3 位小数）
- 公式可配置 + 持久化写回 JSON
- 用户数据按日分文件 + 日期范围查询

---

## v0.2.1 — Bug 修复

**测试：305 项全部通过**

- BUG-001：parse_research_id() 新增 .strip() 防御空格的 CSV/OCR 输入
- BUG-002：add_research_phase_equipment() 返回字段统一命名

---

## v0.2.0 — 数据层完成

**测试：69 项全部通过**

### 新增模块
- core/data/rarity_manager.py — 稀有度管理器（单例 + CSV）
- core/data/equipment_manager.py — 装备管理器（S{期数}-{序号:03d}）
- core/data/research_manager.py — 科研期数管理器
- core/data/equipment_updater.py — 批量装备添加工具

### 数据文件
- data/rarities.csv（5 种稀有度）
- data/equipment_library.csv（12 件初始装备，S1-001 至 S6-002）
- data/research_phases.csv（6 期科研，PR1 至 PR6）
- data/equipment_images.csv（装备图片映射）

---

## v0.1.0 — 基础设施（随 v0.2.0 首发）

- core/utils/logger.py — 日志系统
- core/utils/path_manager.py — 路径管理器
- core/utils/config_loader.py — 配置加载器

---

> 内部标签：v0.5.0-p1、v0.5.0-p1-trend-version、v0.5.0-crawler-baseline-20260709 为开发里程碑，可不创建公开 Release。
