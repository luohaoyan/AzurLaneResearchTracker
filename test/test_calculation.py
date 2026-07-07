# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              🧪 计算层单元测试 (test_calculation.py)              ║
║                                                                  ║
║   【测试覆盖】                                                    ║
║   ① SpecialEquipmentManager — 12 项                              ║
║   ② FormulaManager          — 15 项                              ║
║   ③ UserDataManager         — 8 项                               ║
║   ④ FragmentCalculator      — 11 项                              ║
║   ⑤ LuckCalculator          — 10 项                              ║
║   ─────────────────────────────────────                          ║
║   合计: 56 项测试                                                ║
╚══════════════════════════════════════════════════════════════════╝
"""
import os
import sys

# 将项目根目录加入 sys.path，确保可以导入项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 测试统计 ──
PASSED = 0
FAILED = 0


def check(desc: str, condition: bool):
    """统一的测试断言函数：打印 PASS/FAIL 并更新统计"""
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS PASS: {desc}")
    else:
        FAILED += 1
        print(f"  FAIL FAIL: {desc}")


def section(title: str):
    """打印分节标题"""
    bar = "=" * 60
    print(f"\n{bar}\n  {title}\n{bar}")


# ══════════════════════════════════════════════════════════════════
#  第一部分：SpecialEquipmentManager 测试
# ══════════════════════════════════════════════════════════════════
section("1. SpecialEquipmentManager")

from core.data.special_equipment_manager import get_special_equipment_manager

sem = get_special_equipment_manager()

# 测试1: 获取全部特殊装备
all_special = sem.get_all()
check("get_all() 返回列表", isinstance(all_special, list))
check("get_all() 包含 2 件特殊装备", len(all_special) >= 2)

# 测试2: is_special 判断
check("ID=1(BR.810) 是特殊装备", sem.is_special("1") is True)
check("ID=2(B-13) 是特殊装备", sem.is_special("2") is True)
check("S1-001 不是特殊装备", sem.is_special("S1-001") is False)
check("空字符串不是特殊装备", sem.is_special("") is False)

# 测试3: get_all_ids
ids = sem.get_all_ids()
check("get_all_ids 返回集合", isinstance(ids, set))
check("id 集合包含 1(BR.810)", "1" in ids)
check("id 集合包含 2(B-13)", "2" in ids)

# 测试4: get_by_id
br = sem.get_by_id("1")
check("get_by_id('BR.810') 不为 None", br is not None)
check("ID=1 名称包含'剑鱼'", br and "剑鱼" in br.get("equipment_name", ""))
check("get_by_id('不存在的') 返回 None", sem.get_by_id("不存在的") is None)

# 测试5: CRUD（增删改）— 先在装备库注册再测特殊装备
from core.data.equipment_manager import get_equipment_manager as _get_em
_em = _get_em()
_em.add_equipment({"name": "__TEST_SP_EQ__", "rarity_id": 4, "type": "test", "research_phase": 0})
_tmp = _em.get_by_name("__TEST_SP_EQ__")
_tid = _tmp["equipment_id"]

check("add_special 添加新装备", sem.add_special(_tid, "test_sp", "test") is True)
check("is_special 识别新添加的装备", sem.is_special(_tid) is True)
check("重复添加同名 ID 失败", sem.add_special(_tid, "test_sp2") is False)
check("空 ID 添加失败", sem.add_special("", "empty") is False)
check("update_special 更新成功", sem.update_special(_tid, {"notes": "updated"}) is True)
check("delete_special 删除成功", sem.delete_special(_tid) is True)
check("删除后 is_special 返回 False", sem.is_special(_tid) is False)

_em.delete_equipment(_tid)


# ══════════════════════════════════════════════════════════════════
#  第二部分：FormulaManager 测试
# ══════════════════════════════════════════════════════════════════
section("2. FormulaManager")

from core.calculation.formula_manager import get_formula_manager

fm = get_formula_manager()

# 测试6: 等值映射加载
equivs = fm.get_equivalents()
check("research_rainbow = 50", equivs.get("research_rainbow") == 50)
check("research_gold = 25", equivs.get("research_gold") == 25)
check("general_gold = 15", equivs.get("general_gold") == 15)
check("purple = 10", equivs.get("purple") == 10)
check("blue = 5", equivs.get("blue") == 5)

# 测试7: get_equivalent — 科研彩色
check("S1-001(科研彩) 等值=50", fm.get_equivalent("S1-001", 5) == 50)
check("S2-001(科研彩) 等值=50", fm.get_equivalent("S2-001", 5) == 50)

# 测试8: get_equivalent — 科研金色
check("S1-002(科研金) 等值=25", fm.get_equivalent("S1-002", 4) == 25)
check("S4-001(科研金) 等值=25", fm.get_equivalent("S4-001", 4) == 25)

# 测试9: get_equivalent — 特殊金色
check("ID=1/BR.810(特殊金) 等值=25", fm.get_equivalent("1", 4) == 25)
check("ID=2/B-13(特殊金) 等值=25", fm.get_equivalent("2", 4) == 25)

# 测试10: get_equivalent — 普通金色
check("普通金(假设ID=999) 等值=15", fm.get_equivalent("999", 4) == 15)

# 测试11: get_equivalent — 紫色
check("S5-001(紫) 等值=10", fm.get_equivalent("S5-001", 3) == 10)

# 测试12: get_equivalent — 其他稀有度
check("rarity_id=2(蓝) 等值=5", fm.get_equivalent("任意ID", 2) == 5)
check("rarity_id=1(白) 等值=None", fm.get_equivalent("任意ID", 1) is None)

# 测试13: get_equivalent — 普通彩色（无碎片公式）
check("普通彩(假设ID=888) 等值=None", fm.get_equivalent("888", 5) is None)

# 测试14: 装备类别判断
check("S1-001 类别=科研彩色", fm.get_equipment_category("S1-001", 5) == "科研彩色")
check("S1-002 类别=科研金色", fm.get_equipment_category("S1-002", 4) == "科研金色")
check("ID=1 类别=特殊金色", fm.get_equipment_category("1", 4) == "特殊金色")
check("稀有度3 类别=紫色", fm.get_equipment_category("任意", 3) == "紫色")
check("稀有度2 类别=蓝色", fm.get_equipment_category("任意", 2) == "蓝色")
check("普通彩 类别=普通彩色", fm.get_equipment_category("888", 5) == "普通彩色")
check("稀有度1 类别=普通白色", fm.get_equipment_category("任意", 1) == "普通白色")

# 测试15: 欧非值等级判定
check("luck 3.0 → 极欧", fm.get_luck_level_name(3.0) == "极欧")
check("luck 2.0 → 极欧", fm.get_luck_level_name(2.0) == "极欧")
check("luck 1.5 → 较欧", fm.get_luck_level_name(1.5) == "较欧")
check("luck 1.0 → 正常", fm.get_luck_level_name(1.0) == "正常")
check("luck 0.5 → 较非", fm.get_luck_level_name(0.5) == "较非")
check("luck 0.3 → 极非", fm.get_luck_level_name(0.3) == "极非")
check("luck 0.0 → 极非", fm.get_luck_level_name(0.0) == "极非")

# 测试16: 等值修改 & 恢复
check("set_equivalent 修改成功", fm.set_equivalent("purple", 99) is True)
check("修改后等值生效", fm.get_equivalent("S5-001", 3) == 99)
check("reset_to_defaults 恢复成功", fm.reset_to_defaults() is True)
check("恢复后等值=10", fm.get_equivalent("S5-001", 3) == 10)

# 测试17: luck_levels 获取
levels = fm.get_luck_levels()
check("get_luck_levels 返回列表", isinstance(levels, list))
check("luck_levels 包含 5 个等级", len(levels) == 5)
check("第一个等级阈值最高", levels[0]["threshold"] >= levels[-1]["threshold"])

# 测试18: 科研装备判断
check("S1-001 是科研装备", fm.is_research_equipment("S1-001") is True)
check("S6-002 是科研装备", fm.is_research_equipment("S6-002") is True)
check("ID=1(BR.810) 不是科研装备", fm.is_research_equipment("1") is False)


# ══════════════════════════════════════════════════════════════════
#  第三部分：UserDataManager 测试
# ══════════════════════════════════════════════════════════════════
section("3. UserDataManager")

from core.calculation.user_data_manager import get_user_data_manager

udm = get_user_data_manager()

# 测试19: 写入 & 读取
check("update_record 写入成功",
      udm.update_record("S1-001", 3, 45) is True)
check("update_record 写入第二件",
      udm.update_record("S1-002", 2, 20) is True)

# 测试20: 读取今日数据
today = udm.get_today_data()
check("今日数据包含 S1-001", "S1-001" in today)
check("S1-001 count=3", today["S1-001"]["equipment_count"] == 3)
check("S1-001 frag=45", today["S1-001"]["fragment_count"] == 45)
check("今日数据包含 S1-002", "S1-002" in today)

# 测试21: 批量写入
batch_result = udm.update_batch({
    "S2-001": {"equipment_count": 1, "fragment_count": 10},
    "S2-002": {"equipment_count": 0, "fragment_count": 25},
    "S3-001": {"equipment_count": 2, "fragment_count": 0},
})
check("批量写入 3 件全部成功", batch_result["success"] == 3 and batch_result["total"] == 3)

# 测试22: 历史数据
history = udm.get_history("S1-001")
check("get_history 返回列表", isinstance(history, list))
check("历史数据非空", len(history) > 0)

# 测试23: 日期列表
dates = udm.list_available_dates()
check("list_available_dates 返回列表", isinstance(dates, list))
check("日期列表非空", len(dates) > 0)

# 测试24: 删除
check("delete_record 删除成功",
      udm.delete_record("S3-001") is True)


# ══════════════════════════════════════════════════════════════════
#  第四部分：FragmentCalculator 测试
# ══════════════════════════════════════════════════════════════════
section("4. FragmentCalculator")

from core.calculation.fragment_calculator import get_fragment_calculator

fc = get_fragment_calculator()

# 测试25: calculate_single — 科研彩色
r1 = fc.calculate_single("S1-001", 2, 30)
check("S1-001 score = 130", r1["score"] == 130)
check("S1-001 category = 科研彩色", r1["category"] == "科研彩色")
check("S1-001 equivalent = 50", r1["equivalent"] == 50)

# 测试26: calculate_single — 科研金色
r2 = fc.calculate_single("S1-002", 1, 15)
check("S1-002 score = 40", r2["score"] == 40)
check("S1-002 category = 科研金色", r2["category"] == "科研金色")

# 测试27: calculate_single — 紫色
r3 = fc.calculate_single("S5-001", 1, 5)
check("S5-001 score = 15", r3["score"] == 15)
check("S5-001 equivalent = 10", r3["equivalent"] == 10)

# 测试28: calculate_single — 不存在的装备
r4 = fc.calculate_single("不存在的ID", 1, 1)
check("不存在装备 score = None", r4["score"] is None)
check("不存在装备有 error 字段", "error" in r4)

# 测试29: calculate_batch 批量计算
batch = fc.calculate_batch({
    "S1-001": {"equipment_count": 2, "fragment_count": 30},
    "S1-002": {"equipment_count": 1, "fragment_count": 15},
    "S2-001": {"equipment_count": 0, "fragment_count": 60},
})
check("batch 返回 3 条结果", len(batch) == 3)
check("batch 总分 = 130+40+60=230",
      sum(item.get("score", 0) or 0 for item in batch) == 230)

# 测试30: calculate_by_phase — 第1期（显式传入数据）
p1 = fc.calculate_by_phase(1, {
    "S1-001": {"equipment_count": 2, "fragment_count": 30},
    "S1-002": {"equipment_count": 1, "fragment_count": 15},
})
check("phase1 装备数=2", p1["equipment_count"] == 2)
check("phase1 total_score=170", p1["total_score"] == 170)

# 测试31: calculate_all_phases
all_phases = fc.calculate_all_phases({
    "S1-001": {"equipment_count": 2, "fragment_count": 30},
    "S1-002": {"equipment_count": 1, "fragment_count": 15},
})
check("all phases 期数=6", all_phases["total_phases"] == 6)
check("overall_total >= 170", all_phases["overall_total_score"] >= 170)

# 测试32: 不存在的期数
p999 = fc.calculate_by_phase(999, {})
check("不存在的期数返回 error", "error" in p999)


# ══════════════════════════════════════════════════════════════════
#  第五部分：LuckCalculator 测试
# ══════════════════════════════════════════════════════════════════
section("5. LuckCalculator")

from core.calculation.luck_calculator import get_luck_calculator

lc = get_luck_calculator()

# 测试33: calculate_phase_luck — 第1期（标准案例）
luck1 = lc.calculate_phase_luck(1, {
    "S1-001": {"equipment_count": 2, "fragment_count": 30},
    "S1-002": {"equipment_count": 1, "fragment_count": 15},
})
check("Phase1 luck = 3.25", luck1["luck_value"] == 3.25)
check("Phase1 level = 极欧", luck1["luck_level"] == "极欧")
check("Phase1 rainbow_total = 130", luck1["rainbow_total"] == 130)
check("Phase1 gold_total = 40", luck1["gold_total"] == 40)
check("Phase1 rainbow 装备数=1", len(luck1["rainbow_equipments"]) == 1)
check("Phase1 gold 装备数=1", len(luck1["gold_equipments"]) == 1)

# 测试34: calculate_phase_luck — 第5期（含紫色装备，不参与欧非值计算）
luck5 = lc.calculate_phase_luck(5, {
    "S5-001": {"equipment_count": 1, "fragment_count": 5},
    "S5-002": {"equipment_count": 0, "fragment_count": 30},
})
check("Phase5 金色装备数=1", len(luck5["gold_equipments"]) == 1)
check("Phase5 彩虹装备数=0", len(luck5["rainbow_equipments"]) == 0)
# S5-001 是紫色(rarity_id=3), S5-002 是金色(rarity_id=4)
# rainbow=0/30=0 → 极非，但有 warning
check("Phase5 有 warning（无彩虹）", len(luck5["warnings"]) > 0)

# 测试35: 金色总分为0的边界情况
luck_zero_gold = lc.calculate_phase_luck(1, {
    "S1-001": {"equipment_count": 2, "fragment_count": 30},
    "S1-002": {"equipment_count": 0, "fragment_count": 0},
})
check("金色为0时 luck=inf", luck_zero_gold["luck_value"] == float("inf"))

# 测试36: 全部为0的边界情况
luck_all_zero = lc.calculate_phase_luck(1, {
    "S1-001": {"equipment_count": 0, "fragment_count": 0},
    "S1-002": {"equipment_count": 0, "fragment_count": 0},
})
check("全为0时 luck=None", luck_all_zero["luck_value"] is None)
check("全为0时 level=未知", luck_all_zero["luck_level"] == "未知")

# 测试37: calculate_all_luck（只有第1期有数据）
all_luck = lc.calculate_all_luck({
    "S1-001": {"equipment_count": 2, "fragment_count": 30},
    "S1-002": {"equipment_count": 1, "fragment_count": 15},
})
check("all_luck phases=6", all_luck["total_phases"] == 6)
check("overall luck value 不为 None", all_luck["overall_luck_value"] is not None)

# 测试38: 欧非值等级判定（直接调用）
check("lc 3.25=极欧", lc.get_luck_level(3.25) == "极欧")
check("lc 1.5=较欧", lc.get_luck_level(1.5) == "较欧")
check("lc 1.0=正常", lc.get_luck_level(1.0) == "正常")
check("lc 0.5=较非", lc.get_luck_level(0.5) == "较非")
check("lc 0.3=极非", lc.get_luck_level(0.3) == "极非")


# ══════════════════════════════════════════════════════════════════
#  测试结果汇总
# ══════════════════════════════════════════════════════════════════
section("Results")

# 清理测试产生的用户数据
try:
    # 删除今天创建的测试数据
    import shutil
    from datetime import date
    from core.utils.path_manager import PathManager
    records_dir = PathManager.get_data_dir() / "user_records"
    today_file = records_dir / f"{date.today().isoformat()}.csv"
    if os.path.exists(str(today_file)):
        os.remove(str(today_file))
        print("  [CLEAN] 已清理测试用户数据")
except Exception as e:
    print(f"  WARN 清理测试数据失败: {e}")

total = PASSED + FAILED
print(f"\n  总计: {total}  通过: {PASSED}  失败: {FAILED}")
if FAILED == 0:
    print("  ALL TESTS PASSED! ALL TESTS PASSED!")
else:
    print(f"  WARN {FAILED} FAILURES!")
    sys.exit(1)
