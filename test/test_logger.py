# print("hello world")


# test_logger.py
import os
import sys
import time

from pyexpat.errors import messages

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.utils.logger import get_logger, setup_logging, info, debug, warning, error, exception, critical


def test_basic_logging():
    """测试基础日志功能"""
    print("=== 测试基础日志功能 ===")

    # 方法1：使用setup_logging设置（推荐）
    logger = setup_logging()

    # 方法2：直接使用便捷函数
    info("这是一条INFO级别的日志")
    debug("这是一条DEBUG级别的日志（可能在控制台看不到）")
    warning("这是一条WARNING级别的日志")
    error("这是一条ERROR级别的日志")

    # 测试性能日志
    operation = "测试性能日志"
    start_time = time.time()
    time.sleep(0.1)  # 模拟耗时操作
    execution_time = time.time() - start_time
    logger.log_performance(operation, execution_time)


    print("基础日志测试完成，请查看logs目录下的日志文件")


def test_exception_logging():
    """测试异常日志"""
    print("\n=== 测试异常日志 ===")

    try:
        # 模拟一个异常
        result = 1 / 0
    except Exception as e:
        exception("发生除零异常")

    print("异常日志测试完成")


def test_custom_log_methods():
    """测试自定义日志方法"""
    print("\n=== 测试自定义日志方法 ===")

    logger = get_logger()

    # 测试自动化步骤日志
    logger.log_automation_step("登录游戏", "开始", "点击游戏图标")
    time.sleep(0.05)  # 模拟操作耗时
    logger.log_automation_step("登录游戏", "完成", "耗时0.05秒")

    logger.log_automation_step("跳转装备界面", "开始")
    time.sleep(0.03)
    logger.log_automation_step("跳转装备界面", "完成")

    # 测试装备操作日志（模拟）
    logger.log_equipment_operation("添加", "457mm三联装主炮MkA", 1, "科研装备添加成功")
    logger.log_equipment_operation("更新", "试作型三联装310mm主炮T0", 2, "稀有度更新为彩")
    logger.log_equipment_operation("删除", "四联装381mm主炮", 3)

    print("自定义日志方法测试完成")


def test_logger_singleton():
    """测试日志器单例模式"""
    print("\n=== 测试单例模式 ===")

    logger1 = setup_logging()
    logger2 = setup_logging()

    # 应该是同一个实例
    print(f"logger1 ID: {id(logger1)}")
    print(f"logger2 ID: {id(logger2)}")
    print(f"是否是单例: {logger1 is logger2}")

    info("单例模式测试日志")


def test_different_log_levels():
    """测试不同日志级别"""
    print("\n=== 测试不同日志级别 ===")

    # 测试各种日志级别
    debug("这是DEBUG信息 - 用于详细调试")
    info("这是INFO信息 - 用于一般信息")
    warning("这是WARNING信息 - 用于警告")
    error("这是ERROR信息 - 用于错误")

    # 测试关键错误
    try:
        # 模拟关键错误场景
        raise ValueError("这是一个模拟的关键错误")
    except Exception as e:
        critical(f"发生关键错误: {e}")

    print("不同日志级别测试完成")


def test_log_file_creation():
    """测试日志文件创建"""
    print("\n=== 测试日志文件创建 ===")

    # 确保日志目录存在
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        info(f"创建日志目录: {log_dir}")

    # 记录一些测试日志
    for i in range(5):
        info(f"测试日志条目 #{i + 1}")

    # 检查日志文件是否创建
    log_files = [f for f in os.listdir(log_dir) if f.endswith('.log')]
    print(f"创建的日志文件: {log_files}")

    # 显示日志文件路径
    main_log_path = os.path.join(log_dir, "AzurLaneResearchTracker.log")
    error_log_path = os.path.join(log_dir, "AzurLaneResearchTracker_error.log")

    print(f"主日志文件: {main_log_path} (存在: {os.path.exists(main_log_path)})")
    print(f"错误日志文件: {error_log_path} (存在: {os.path.exists(error_log_path)})")

    if os.path.exists(main_log_path):
        with open(main_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            print(f"主日志文件行数: {len(lines)}")

    if os.path.exists(error_log_path):
        with open(error_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            print(f"错误日志文件行数: {len(lines)}")

    print("日志文件创建测试完成")


def simulate_automation_workflow():
    """模拟一个完整的自动化工作流程"""
    print("\n=== 模拟自动化工作流程 ===")

    logger = get_logger()

    # 模拟自动化流程
    start_time,end_time = None,None
    start_time = time.time()
    logger.info("开始碧蓝航线装备统计自动化流程")

    # 步骤1: 启动模拟器
    logger.log_automation_step("启动模拟器", "开始")
    time.sleep(0.1)
    logger.log_automation_step("启动模拟器", "完成", "MuMu模拟器启动成功")

    # 步骤2: 登录游戏
    logger.log_automation_step("登录游戏", "开始", "点击游戏图标")
    time.sleep(0.2)
    logger.log_automation_step("登录游戏", "完成", "进入游戏主界面")

    # 步骤3: 导航到装备界面
    logger.log_automation_step("导航到装备界面", "开始", "寻找装备按钮")
    time.sleep(0.15)
    logger.log_automation_step("导航到装备界面", "完成", "成功进入装备仓库")

    # 步骤4: 截图和识别
    logger.log_automation_step("装备识别", "开始", "进行截图和图像识别")
    time.sleep(0.3)

    # 模拟识别到的装备
    simulated_equipment = [
        {"name": "457mm三联装主炮MkA", "count": 2, "fragments": 15},
        {"name": "试作型三联装310mm主炮T0", "count": 1, "fragments": 25},
    ]

    for eq in simulated_equipment:
        logger.log_equipment_operation(
            "识别",
            eq["name"],
            0,  # 使用0作为临时ID
            f"数量: {eq['count']}, 碎片: {eq['fragments']}"
        )

    logger.log_automation_step("装备识别", "完成", f"识别到 {len(simulated_equipment)} 种装备")

    # 步骤5: 计算欧非值
    logger.log_automation_step("欧非值计算", "开始", "使用公式计算")
    time.sleep(0.05)
    logger.log_automation_step("欧非值计算", "完成", "欧非值: 0.227")

    # 完成
    logger.info("自动化流程完成")
    end_time = time.time()
    execution_time = end_time - start_time
    print(f"start_time:{start_time},end_time:{end_time},execution_time:{execution_time}")
    # 记录总耗
    logger.log_automation_step("完整自动化流程", execution_time)  # 模拟总耗时

    print("自动化工作流程模拟完成")


if __name__ == "__main__":
    # 运行所有测试
    test_basic_logging()
    test_exception_logging()
    test_custom_log_methods()
    test_logger_singleton()
    test_different_log_levels()
    test_log_file_creation()
    simulate_automation_workflow()
    print("\n=== 所有测试完成 ===")
    print("请查看 Logs 目录下的日志文件，确认日志记录是否正确")