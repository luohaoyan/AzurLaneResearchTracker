# test_research_manager.py
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 科研管理器单元测试                                  ║
║                                                              ║
║   测试覆盖了科研管理器的全部功能：                             ║
║   ① 单例模式           → 全局唯一实例                         ║
║   ② 获取所有期数       → get_all()                           ║
║   ③ 按期数查询         → get_by_phase()                      ║
║   ④ 关联装备查询       → get_phase_equipment()  🔗核心功能    ║
║   ⑤ 增删改操作         → add / update / delete               ║
║   ⑥ 统计信息           → get_statistics()                    ║
║   ⑦ 重复添加拒绝       → 边界测试                             ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import sys

# ── 加项目路径到Python搜索路径 ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.research_manager import get_research_manager, ResearchManager
from core.data.equipment_manager import get_equipment_manager


def test_singleton():
    """测试1：单例模式"""
    print("\n===== 🧪 测试1：单例模式 =====")
    mgr1 = get_research_manager()
    mgr2 = get_research_manager()
    assert mgr1 is mgr2, "❌ 单例模式失败：两个实例不是同一个对象"
    print("✅ 单例模式测试通过")


def test_get_all():
    """测试2：获取所有科研期数"""
    print("\n===== 🧪 测试2：获取所有科研期数 =====")
    mgr = get_research_manager()
    all_phases = mgr.get_all()
    assert len(all_phases) > 0, "❌ 科研期数不应为空"
    print(f"📋 科研期数总数: {len(all_phases)}")
    for phase in all_phases[:3]:
        print(f"    - {phase['name']} (第{phase['phase_number']}期, 基准值:{phase['luck_benchmark']})")
    print("✅ 获取所有期数测试通过")


def test_get_by_phase():
    """测试3：按期数编号查询"""
    print("\n===== 🧪 测试3：按期数编号查询 =====")
    mgr = get_research_manager()
    phase = mgr.get_by_phase(1)
    assert phase is not None, "❌ 第1期应该存在"
    assert phase['name'] == "科研一期(PR1)", f"❌ 名称不匹配: {phase['name']}"
    print(f"🔍 查询结果: {phase['name']}, 装备列表: {phase['equipment_list']}")

    # 查询不存在的期数
    phase_none = mgr.get_by_phase(999)
    assert phase_none is None, "❌ 不存在的期数应返回None"
    print("✅ 按期数查询测试通过")


def test_phase_equipment():
    """
    测试4：科研期数关联装备查询 🔗
    
    这是科研管理器的核心功能！
    测试流程：
    ① 查第1期科研 → 拿到装备ID列表 "1,2"
    ② 科研管理器拿着这些ID去找装备管理器
    ③ 返回完整的装备信息列表
    """
    print("\n===== 🧪 测试4：科研期数关联装备查询 =====")
    mgr = get_research_manager()

    # 第1期应有2个装备
    equipment_list = mgr.get_phase_equipment(1)
    assert len(equipment_list) == 2, f"❌ 第1期应有2个装备，实际: {len(equipment_list)}"
    print(f"🔗 第1期装备:")
    for eq in equipment_list:
        print(f"    - {eq['name']} (ID:{eq['equipment_id']}, 稀有度:{eq['rarity']})")

    # 测试装备数量统计
    count = mgr.get_phase_equipment_count(1)
    assert count == 2, f"❌ 第1期装备数应为2，实际: {count}"
    print(f"🔢 第1期装备数量: {count}")
    print("✅ 关联装备查询测试通过")


def test_crud_operations():
    """
    测试5：增删改操作
    
    完整测试添加→验证→更新→验证→关联查询→删除→验证
    """
    print("\n===== 🧪 测试5：CRUD操作 =====")
    mgr = get_research_manager()

    # ── ① 添加新期数 ──
    new_phase = {
        "name": "测试科研期",
        "equipment_list": "1,3",  # 引用第1号和第3号装备
        "luck_benchmark": 100.0,
    }
    result = mgr.add_phase(new_phase)
    assert result, "❌ 添加科研期数应该成功"
    print("➕ 添加科研期数: 成功")

    # ── ② 验证添加 ──
    all_phases = mgr.get_all()
    added = [p for p in all_phases if p['name'] == "测试科研期"]
    assert len(added) == 1, f"❌ 应找到1个测试科研期，实际: {len(added)}"
    test_phase_num = added[0]['phase_number']
    print(f"🔍 新科研期数编号: {test_phase_num}")

    # ── ③ 更新 ──
    update_result = mgr.update_phase(test_phase_num, {
        "name": "测试科研期(已更新)",
        "luck_benchmark": 200.0,
    })
    assert update_result, "❌ 更新科研期数应该成功"
    updated = mgr.get_by_phase(test_phase_num)
    assert updated['name'] == "测试科研期(已更新)", f"❌ 名称不匹配: {updated['name']}"
    assert updated['luck_benchmark'] == 200.0, f"❌ 基准值不匹配: {updated['luck_benchmark']}"
    print("✏️ 更新科研期数: 成功")

    # ── ④ 验证关联查询仍然正确 ──
    equipment_list = mgr.get_phase_equipment(test_phase_num)
    assert len(equipment_list) == 2, f"❌ 关联装备数应为2，实际: {len(equipment_list)}"
    print(f"🔗 关联装备查询: {len(equipment_list)}个装备")

    # ── ⑤ 删除 ──
    delete_result = mgr.delete_phase(test_phase_num)
    assert delete_result, "❌ 删除科研期数应该成功"
    deleted = mgr.get_by_phase(test_phase_num)
    assert deleted is None, "❌ 删除后查询应返回None"
    print("🗑️ 删除科研期数: 成功")

    print("✅ CRUD操作测试通过")


def test_statistics():
    """测试6：统计信息"""
    print("\n===== 🧪 测试6：统计信息 =====")
    mgr = get_research_manager()
    stats = mgr.get_statistics()
    assert 'total_phases' in stats, "❌ 统计应包含total_phases"
    assert 'total_equipment' in stats, "❌ 统计应包含total_equipment"
    print(f"📊 总科研期数: {stats['total_phases']}")
    print(f"📊 关联装备总数: {stats['total_equipment']}")
    print("✅ 统计信息测试通过")


def test_duplicate_phase():
    """
    测试7：重复添加拒绝
    
    验证：试图添加已存在的期数编号会被拒绝
    这是数据完整性的保证
    """
    print("\n===== 🧪 测试7：重复添加拒绝 =====")
    mgr = get_research_manager()
    result = mgr.add_phase({
        "phase_number": 1,  # 第1期已经存在了！
        "name": "重复期数",
        "equipment_list": "",
        "luck_benchmark": 0.0,
    })
    assert not result, "❌ 重复期数编号应添加失败"
    print("✅ 重复添加拒绝: 通过")


if __name__ == "__main__":
    test_singleton()
    test_get_all()
    test_get_by_phase()
    test_phase_equipment()
    test_crud_operations()
    test_statistics()
    test_duplicate_phase()

    print("\n🎉 === 科研管理器测试全部通过 ===")
