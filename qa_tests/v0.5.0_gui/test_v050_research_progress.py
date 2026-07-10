#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA: v0.5.0 科研进度页专项测试"""
import sys, os, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from core.calculation.research_progress_analyzer import (
    ResearchProgressAnalyzer,
    get_research_progress_analyzer,
)
from core.calculation.user_data_manager import get_user_data_manager
from ui.ui_config import UiConfigManager, get_ui_config_manager
from ui.main_window import MainWindow

pass_cnt = 0; fail_cnt = 0
def ck(desc, cond):
    global pass_cnt, fail_cnt
    if cond: pass_cnt += 1; print(f"  OK: {desc}")
    else: fail_cnt += 1; print(f"  FAIL: {desc}")
def sec(t):
    print(f"\n{'='*60}\n  [QA ResearchProgress] {t}\n{'='*60}")

# ============================================================
sec("1. ResearchProgressAnalyzer singleton")
# ============================================================
rpa1 = get_research_progress_analyzer()
rpa2 = get_research_progress_analyzer()
ck("get_research_progress_analyzer() returns non-None", rpa1 is not None)
ck("get_research_progress_analyzer() is singleton", rpa1 is rpa2)

# ============================================================
sec("2. get_latest_phase_number")
# ============================================================
latest = rpa1.get_latest_phase_number()
ck("get_latest_phase_number() returns int", isinstance(latest, int))
ck("get_latest_phase_number() >= 1", latest >= 1)

# ============================================================
sec("3. get_phase_progress basic")
# ============================================================
result = rpa1.get_phase_progress(phase_number=latest)
ck("get_phase_progress returns dict", isinstance(result, dict))
required_fields = [
    "phase_number", "phase_name", "latest_phase", "is_latest",
    "equipment_total", "completed_count", "overall_progress",
    "average_equipment_progress", "rainbow_target_count",
    "rainbow_target_fragments", "rainbow_total", "gold_total",
    "gold_rainbow_ratio", "total_score", "luck_value", "luck_level",
    "equipment_rows", "message",
]
for field in required_fields:
    ck(f"  含字段 {field}", field in result)

# ============================================================
sec("4. get_phase_progress defaults to latest")
# ============================================================
result_default = rpa1.get_phase_progress()
ck("默认期数 = latest", result_default["phase_number"] == latest)
ck("is_latest = True (默认)", result_default["is_latest"] is True)

# ============================================================
sec("5. rainbow_target_count boundary")
# ============================================================
r0 = rpa1.get_phase_progress(rainbow_target_count=0)
ck("target=0 clamped to 1", r0["rainbow_target_count"] == 1)

r_neg = rpa1.get_phase_progress(rainbow_target_count=-5)
ck("target=-5 clamped to 1", r_neg["rainbow_target_count"] == 1)

r_max = rpa1.get_phase_progress(rainbow_target_count=50)
ck("target=50 clamped to 20", r_max["rainbow_target_count"] == 20)

r20 = rpa1.get_phase_progress(rainbow_target_count=20)
ck("target=20 accepted", r20["rainbow_target_count"] == 20)

# ============================================================
sec("6. _calculate_gold_rainbow_ratio edge cases")
# ============================================================
ratio1 = ResearchProgressAnalyzer._calculate_gold_rainbow_ratio(0, 0)
ck("both 0 -> None", ratio1 is None)
ratio2 = ResearchProgressAnalyzer._calculate_gold_rainbow_ratio(100, 0)
ck("rainbow=0 -> None", ratio2 is None)
ratio3 = ResearchProgressAnalyzer._calculate_gold_rainbow_ratio(0, 100)
ck("gold=0 rainbow=100 -> 0.0", ratio3 == 0.0)

# ============================================================
sec("7. _normalize_luck_value edge cases")
# ============================================================
import math
nf = ResearchProgressAnalyzer._normalize_luck_value
ck("None -> None", nf(None) is None)
ck("3.0 -> 3.0", nf(3.0) == 3.0)
ck("inf -> None", nf(float("inf")) is None)
ck("-inf -> None", nf(float("-inf")) is None)
ck("'3.5' -> 3.5", nf("3.5") == 3.5)
ck("'abc' -> None", nf("abc") is None)

# ============================================================
sec("8. _calculate_target_progress edge cases")
# ============================================================
tp = ResearchProgressAnalyzer._calculate_target_progress
ck("target=0 -> 0.0", tp(100, 0) == 0.0)
ck("target=-5 -> 0.0", tp(100, -5) == 0.0)
ck("0/50 -> 0.0", tp(0, 50) == 0.0)
ck("25/50 -> 50.0", tp(25, 50) == 50.0)
ck("100/50 -> 100.0 (capped)", tp(100, 50) == 100.0)

# ============================================================
sec("9. _calculate_item_progress edge cases")
# ============================================================
ip = ResearchProgressAnalyzer._calculate_item_progress
ck("already built (count>0) -> 100", ip(1, 0, 50) == 100)
ck("equivalent None -> 0", ip(0, 50, None) == 0)
ck("equiv 0 -> 0", ip(0, 50, 0) == 0)
ck("25/50 -> 50", ip(0, 25, 50) == 50)

# ============================================================
sec("10. _empty_result structure")
# ============================================================
empty = ResearchProgressAnalyzer._empty_result(1, 6, "test msg")
ck("phase_number = 1", empty["phase_number"] == 1)
ck("is_latest = False", empty["is_latest"] is False)
ck("message = test msg", empty["message"] == "test msg")
ck("overall_progress = 0.0", empty["overall_progress"] == 0.0)
ck("equipment_rows empty", empty["equipment_rows"] == [])

empty_latest = ResearchProgressAnalyzer._empty_result(6, 6, "")
ck("phase=6 latest=6 -> is_latest=True", empty_latest["is_latest"] is True)

# ============================================================
sec("11. Invalid phase handling")
# ============================================================
r_invalid = rpa1.get_phase_progress(phase_number=999)
ck("phase=999 has message", len(r_invalid.get("message", "")) > 0)
ck("phase=999 equipment_total=0", r_invalid["equipment_total"] == 0)
ck("phase=999 luck_level=未知", r_invalid["luck_level"] == "未知")

r_zero = rpa1.get_phase_progress(phase_number=0)
ck("phase=0 回退到最新期 (Python falsy)", r_zero["phase_number"] == latest); ck("phase=0 equipment_total>0", r_zero.get("equipment_total", 0) > 0)

# ============================================================
sec("12. Historical phase progress")
# ============================================================
r1 = rpa1.get_phase_progress(phase_number=1)
ck("phase=1 returns dict", isinstance(r1, dict))
ck("phase=1 is_latest=False (if latest>1)", r1["is_latest"] is (1 == latest))

# ============================================================
sec("13. UiConfigManager singleton")
# ============================================================
ucm1 = get_ui_config_manager()
ucm2 = get_ui_config_manager()
ck("get_ui_config_manager() returns non-None", ucm1 is not None)
ck("get_ui_config_manager() is singleton", ucm1 is ucm2)

# ============================================================
sec("14. get_research_progress_config structure")
# ============================================================
config = ucm1.get_research_progress_config()
ck("config is dict", isinstance(config, dict))
for key in ["phase_start_dates", "official_start_dates", "duration_messages",
            "secretary", "target_dialogs", "fallback_start_date"]:
    ck(f"  config has {key}", key in config)

# ============================================================
sec("15. Secretary config integrity")
# ============================================================
secretary = config["secretary"]
ck("secretary has name", isinstance(secretary.get("name"), str) and len(secretary["name"]) > 0)
ck("secretary has image_path", "image_path" in secretary)
ck("secretary has placeholder_text", "placeholder_text" in secretary)
ck("secretary has dialog_duration_ms", isinstance(secretary.get("dialog_duration_ms"), (int, float)))

# ============================================================
sec("16. Target dialogs structure")
# ============================================================
dialogs = config["target_dialogs"]
ck("target_dialogs is dict", isinstance(dialogs, dict))
scenarios = ["completed", "history", "history_completed", "target_1", "target_2_4", "target_5_7", "target_8_plus"]
for s in scenarios:
    ck(f"  target_dialogs has '{s}'", s in dialogs)
    ck(f"  '{s}' has text", isinstance(dialogs[s], str) and len(dialogs[s]) > 0)

# ============================================================
sec("17. Duration messages structure")
# ============================================================
dms = config["duration_messages"]
ck("duration_messages is list", isinstance(dms, list))
ck("duration_messages non-empty", len(dms) > 0)
for dm in dms:
    ck("  entry has min_day", "min_day" in dm)
    ck("  entry has text (duration)", "text" in dm)

# ============================================================
sec("18. save_phase_start_date persistence")
# ============================================================
original_dates = dict(config.get("phase_start_dates", {}))
ucm1.save_phase_start_date(1, "2024-01-15")
config2 = ucm1.get_research_progress_config()
ck("save then read: phase 1 = 2024-01-15", config2["phase_start_dates"].get("1") == "2024-01-15")
# Restore
ucm1.save_phase_start_date(1, original_dates.get("1", "2026-01-01"))

# ============================================================
sec("19. _merge_dicts deep merge")
# ============================================================
merged = UiConfigManager._merge_dicts(
    {"a": 1, "b": {"c": 2, "d": 3}},
    {"b": {"c": 99}},
)
ck("shallow key preserved", merged["a"] == 1)
ck("nested key overridden", merged["b"]["c"] == 99)
ck("nested key preserved", merged["b"]["d"] == 3)

# ============================================================
sec("20. GUI research progress page (refactored)")
win = MainWindow()
ck("MainWindow created", win is not None)
ck("research_progress page exists", "research_progress" in win.pages)
page = win.pages["research_progress"]
ck("page accessible", hasattr(page, "phase_combo"))
try:
    win.switch_to_page("research_progress")
    ck("switch_to_page no crash", True)
except:
    ck("switch_to_page no crash", False)
try:
    win.close()
    ck("MainWindow.close() succeeded", True)
except:
    pass
sec("RESULTS")
total = pass_cnt + fail_cnt
print(f"\n  Total: {total}  Pass: {pass_cnt}  Fail: {fail_cnt}")
if fail_cnt == 0:
    print("  ALL RESEARCH PROGRESS QA TESTS PASSED!")
else:
    print(f"  {fail_cnt} TEST(S) FAILED!")
print()
sys.exit(0 if fail_cnt == 0 else 1)











