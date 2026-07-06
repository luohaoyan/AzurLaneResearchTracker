# test_equipment_manager.py
"""
╔══════════════════════════════════════════════════════════════╗
║        🧪 装备管理器单元测试                                  ║
║                                                              ║
║   测试覆盖了装备管理器的全部功能：                             ║
║   ① 单例模式       → 确保全局只有一个装备管理器               ║
║   ② 获取所有装备   → get_all()                               ║
║   ③ 按ID查询       → get_by_id()                             ║
║   ④ 按稀有度查询   → get_by_rarity()                         ║
║   ⑤ 按类型查询     → get_by_type()                           ║
║   ⑥ 按期数查询     → get_by_phase()                          ║
║   ⑦ 增删改操作     → add / update / delete                   ║
║   ⑧ 统计信息       → get_statistics()                        ║
║   ⑨ 异常处理       → 无效稀有度等边界情况                     ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import sys

# ── 把项目根目录加到Python的搜索路径中 ──
# 这样我们才能 import core.data.equipment_manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data.equipment_manager import get_equipment_manager, EquipmentManager


def test_singleton():
    """
    测试1：单例模式
    
    验证：连续两次获取装备管理器，拿到的是同一个对象
    """
    print("\n===== 🧪 测试1：单例模式 =====")
    mgr1 = get_equipment_manager()
    mgr2 = get_equipment_manager()
    # is 判断两个变量是否指向同一个对象（比 == 更严格）
    assert mgr1 is mgr2, "❌ 单例模式失败：两个实例不是同一个对象"
    print("✅ 单例模式测试通过")


def test_get_all():
    """
    测试2：获取所有装备
    
    验证：装备库里有数据，并且能正确显示
    """
    print("\n===== 🧪 测试2：获取所有装备 =====")
    mgr = get_equipment_manager()
    all_eq = mgr.get_all()
    assert len(all_eq) > 0, "❌ 装备库不应为空"
    print(f"📋 装备总数: {len(all_eq)}")
    for eq in all_eq[:3]:
        print(f"    - {eq['name']} (ID:{eq['equipment_id']}, 稀有度:{eq['rarity']})")
    print("✅ 获取所有装备测试通过")


def test_get_by_id():
    """
    测试3：按ID查询装备
    
    验证：能找到存在的装备，不存在的返回None
    """
    print("\n===== 🧪 测试3：按ID查询 =====")
    mgr = get_equipment_manager()
    eq = mgr.get_by_id(1)
    assert eq is not None, "❌ 装备ID=1应该存在"
    assert eq['name'] == "试作型三联装406mm主炮Mk6", f"❌ 装备名称不匹配: {eq['name']}"
    print(f"🔍 查询结果: {eq['name']} (稀有度:{eq['rarity']})")

    # 查询不存在的ID → 应返回None
    eq_none = mgr.get_by_id(99999)
    assert eq_none is None, "❌ 不存在的ID应返回None"
    print("✅ 按ID查询测试通过")


def test_get_by_rarity():
    """
    测试4：按稀有度筛选
    
    验证：能正确筛选出海上传奇（彩虹）装备
    """
    print("\n===== 🧪 测试4：按稀有度查询 =====")
    mgr = get_equipment_manager()

    # 查海上传奇装备
    legendary = mgr.get_by_rarity("海上传奇")
    assert len(legendary) > 0, "❌ 应该有海上传奇装备"
    print(f"🌈 海上传奇装备数: {len(legendary)}")
    for eq in legendary:
        print(f"    - {eq['name']}")

    # 测试无效稀有度 → 应返回空列表
    invalid = mgr.get_by_rarity("传说")
    assert invalid == [], "❌ 无效稀有度应返回空列表"
    print("✅ 按稀有度查询测试通过")


def test_get_by_type():
    """测试5：按类型筛选"""
    print("\n===== 🧪 测试5：按类型查询 =====")
    mgr = get_equipment_manager()
    bb_guns = mgr.get_by_type("战列炮")
    assert len(bb_guns) > 0, "❌ 应该有战列炮"
    print(f"🎯 战列炮数量: {len(bb_guns)}")
    for eq in bb_guns:
        print(f"    - {eq['name']} (稀有度:{eq['rarity']})")
    print("✅ 按类型查询测试通过")


def test_get_by_phase():
    """测试6：按期数筛选"""
    print("\n===== 🧪 测试6：按期数查询 =====")
    mgr = get_equipment_manager()
    phase1 = mgr.get_by_phase(1)
    assert len(phase1) == 2, f"❌ 第一期应有2个装备，实际: {len(phase1)}"
    print(f"🔢 第一期装备:")
    for eq in phase1:
        print(f"    - {eq['name']}")
    print("✅ 按期数查询测试通过")


def test_crud_operations():
    """
    测试7：增删改操作（CRUD的完整流程）
    
    流程：添加 → 验证 → 更新 → 验证 → 删除 → 验证
    这模拟了用户使用装备管理器的完整生命周期
    """
    print("\n===== 🧪 测试7：CRUD操作 =====")
    mgr = get_equipment_manager()

    # ── ① 添加新装备 ──
    new_eq = {
        "name": "测试装备X",      # 测试用的临时装备
        "rarity": "精锐",          # 紫色品质
        "type": "设备",            # 设备类型
        "research_phase": 1,
        "owned_quantity": 3,
        "fragment_quantity": 10,
    }
    result = mgr.add_equipment(new_eq)
    assert result, "❌ 添加装备应该成功"
    print("➕ 添加装备: 成功")

    # ── ② 验证添加 ──
    all_eq = mgr.get_all()
    added = [e for e in all_eq if e['name'] == "测试装备X"]
    assert len(added) == 1, f"❌ 应找到1个测试装备X，实际: {len(added)}"
    test_id = added[0]['equipment_id']
    print(f"🔍 新装备ID: {test_id}")

    # ── ③ 更新装备 ──
    update_result = mgr.update_equipment(test_id, {"owned_quantity": 5, "fragment_quantity": 20})
    assert update_result, "❌ 更新装备应该成功"
    updated = mgr.get_by_id(test_id)
    assert updated['owned_quantity'] == 5, f"❌ 拥有数量应为5，实际: {updated['owned_quantity']}"
    assert updated['fragment_quantity'] == 20, f"❌ 碎片数量应为20，实际: {updated['fragment_quantity']}"
    print("✏️ 更新装备: 成功")

    # ── ④ 删除装备 ──
    delete_result = mgr.delete_equipment(test_id)
    assert delete_result, "❌ 删除装备应该成功"
    deleted = mgr.get_by_id(test_id)
    assert deleted is None, "❌ 删除后查询应返回None"
    print("🗑️ 删除装备: 成功")

    print("✅ CRUD操作测试通过")


def test_statistics():
    """测试8：统计信息"""
    print("\n===== 🧪 测试8：统计信息 =====")
    mgr = get_equipment_manager()
    stats = mgr.get_statistics()
    assert 'total' in stats, "❌ 统计应包含total"
    assert 'by_rarity' in stats, "❌ 统计应包含by_rarity"
    print(f"📊 总装备数: {stats['total']}")
    print(f"📊 各稀有度: {stats['by_rarity']}")
    print("✅ 统计信息测试通过")


def test_invalid_rarity():
    """
    测试9：异常处理 ── 测试无效稀有度被拒绝
    
    这就是"边界测试"：程序不仅要处理正常情况，
    还要能优雅地处理异常输入
    """
    print("\n===== 🧪 测试9：无效稀有度 =====")
    mgr = get_equipment_manager()
    result = mgr.add_equipment({
        "name": "无效装备",
        "rarity": "传说级",  # 这是不存在的稀有度！
        "type": "设备",
        "research_phase": 1,
    })
    assert not result, "❌ 无效稀有度应添加失败"
    print("✅ 无效稀有度拒绝: 通过")


# ==========================================================
# 🚀 主程序入口
# ==========================================================
if __name__ == "__main__":
    # 按顺序运行所有测试
    test_singleton()       # 1. 单例模式
    test_get_all()         # 2. 获取全部
    test_get_by_id()       # 3. 按ID查询
    test_get_by_rarity()   # 4. 按稀有度
    test_get_by_type()     # 5. 按类型
    test_get_by_phase()    # 6. 按期数
    test_crud_operations() # 7. 增删改
    test_statistics()      # 8. 统计
    test_invalid_rarity()  # 9. 异常处理

    print("\n🎉 === 装备管理器测试全部通过 ===")
