#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        设计图全量复核包生成脚本                              ║
║                                                              ║
║  【一句话解释】把一轮设计图识别结果整理成“看图+改CSV”的包。   ║
║  【类比理解】像把散落的作业卷子装订成一本批改册。              ║
║  【数据流说明】prelabel/final CSV + 原截图 → 裁剪图/总览图/CSV ║
╚══════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

# ============================================================
# 📦 第一部分：导入依赖
# ============================================================

import argparse
import ast
import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow 缺失时退化为只输出 CSV。
    Image = None
    ImageDraw = None
    ImageFont = None


# ============================================================
# ⚙️ 第二部分：路径与常量
# ============================================================

FONT_PATHS = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)

REVIEW_FIELDNAMES = [
    "review_index",
    "filename",
    "card_no",
    "current_equipment_name",
    "correct_equipment_name",
    "current_fragment_owned",
    "correct_fragment_owned",
    "current_fragment_required",
    "correct_fragment_required",
    "label_source",
    "needs_user_review",
    "machine_suggested_equipment_name",
    "icon_confidence",
    "name_ocr_text",
    "attribute_ocr_text",
    "review_reason",
    "card_crop_path",
    "annotated_source_path",
    "notes",
]


# ============================================================
# 🧱 第三部分：基础工具
# ============================================================

def find_project_root(start: Path) -> Path:
    """
    从脚本位置向上寻找项目根目录。

    输入：
        当前脚本路径。
    输出：
        包含 data/equipment_library.csv 的项目根目录。
    使用示例：
        root = find_project_root(Path(__file__))
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "data" / "equipment_library.csv").exists():
            return candidate
    raise RuntimeError("无法定位项目根目录：未找到 data/equipment_library.csv。")


def read_csv(path: Path) -> List[Dict[str, str]]:
    """
    读取 UTF-8-SIG CSV。

    输入：
        CSV 路径。
    输出：
        每行一个 dict。
    使用示例：
        rows = read_csv(Path("result.csv"))
    """
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """
    写出 UTF-8-SIG CSV，方便 Excel/WPS 直接打开。

    输入：
        输出路径、行数据、字段名。
    输出：
        CSV 文件。
    使用示例：
        write_csv(path, rows, REVIEW_FIELDNAMES)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """
    写出 UTF-8 JSON。

    输入：
        输出路径和 JSON 内容。
    输出：
        JSON 文件。
    使用示例：
        write_json(path, {"count": 118})
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_font(size: int) -> Any:
    """
    加载中文字体；失败时退回 Pillow 默认字体。

    输入：
        字号。
    输出：
        ImageFont 对象。
    使用示例：
        font = load_font(18)
    """
    if ImageFont is None:
        return None
    for path in FONT_PATHS:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def parse_bool(value: Any) -> bool:
    """
    把 CSV 里的 True/False 字符串转换成 bool。

    输入：
        任意 CSV 字段值。
    输出：
        bool。
    使用示例：
        ok = parse_bool(row["selected"])
    """
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_bbox(value: str) -> Tuple[int, int, int, int]:
    """
    解析 CSV 中的 bbox 字段。

    输入：
        形如 "[x, y, w, h]" 的字符串。
    输出：
        x, y, w, h。
    使用示例：
        x, y, w, h = parse_bbox(row["bbox"])
    """
    parsed = ast.literal_eval(str(value))
    if not isinstance(parsed, list) or len(parsed) != 4:
        raise ValueError(f"bbox 格式错误：{value}")
    x, y, width, height = [int(item) for item in parsed]
    return x, y, width, height


def safe_stem(filename: str) -> str:
    """
    生成适合文件名使用的短名称。

    输入：
        原始图片名。
    输出：
        不含扩展名的安全 stem。
    使用示例：
        stem = safe_stem("frag_x.png")
    """
    return Path(filename).stem.replace(" ", "_")


def build_lookup(rows: Iterable[Mapping[str, str]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    """
    按 filename + card_no 建立查询表。

    输入：
        CSV 行。
    输出：
        (filename, card_no) → row。
    使用示例：
        lookup = build_lookup(prelabel_rows)
    """
    lookup: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in rows:
        filename = str(row.get("filename", "") or "").strip()
        card_no = str(row.get("card_no", "") or "").strip()
        if filename and card_no:
            lookup[(filename, card_no)] = dict(row)
    return lookup


def parse_todo_exp_keys(exp_path: Optional[Path]) -> Set[Tuple[str, str]]:
    """
    从待复核 exp 文件中读取需要展示的 filename + card_no。

    输入：
        v2_review_todo_exp.txt；为空时表示不过滤。
    输出：
        {(filename, card_no)} 集合。
    使用示例：
        keys = parse_todo_exp_keys(Path("v2_review_todo_exp.txt"))
    """
    keys: Set[Tuple[str, str]] = set()
    if exp_path is None or not exp_path.exists():
        return keys

    current_filename = ""
    for raw_line in exp_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_filename = line[1:-1].strip()
            continue
        if not current_filename:
            continue
        match = re.match(r"^card_(\d+)\.accepted_equipment_name\s*:", line)
        if match is None:
            continue
        keys.add((current_filename, str(int(match.group(1)))))
    return keys


def find_annotated_source_path(annotated_dir: Path, filename: str, annotated_prefix: str) -> Path:
    """
    查找一张原截图对应的整页标注图。

    输入：
        annotated 目录、原始文件名、常见前缀。
    输出：
        最可能的 annotated 图片路径。
    使用示例：
        path = find_annotated_source_path(out / "annotated", "v2_x.png", "v2_after_reviewed_")
    """
    candidates = [
        annotated_dir / f"{annotated_prefix}{filename}",
        annotated_dir / filename,
        annotated_dir / f"new_account_{filename}",
        annotated_dir / f"v2_after_reviewed_{filename}",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    stem = safe_stem(filename)
    wildcard_hits = sorted(annotated_dir.glob(f"*{stem}*.png"))
    if wildcard_hits:
        return wildcard_hits[0].resolve()
    return (annotated_dir / f"{annotated_prefix}{filename}").resolve()


def ensure_safe_output_dir(output_dir: Path, project_root: Path) -> None:
    """
    确认输出目录位于项目实验目录内，再允许清理重建。

    输入：
        输出目录和项目根目录。
    输出：
        不安全时抛异常。
    使用示例：
        ensure_safe_output_dir(out, root)
    """
    resolved = output_dir.resolve()
    allowed_roots = [
        (project_root / "ocr_training_lab").resolve(),
        (project_root / "ocr_preview_lab").resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError(f"拒绝清理非实验目录输出路径: {resolved}")


# ============================================================
# 🎨 第四部分：图像输出
# ============================================================

def draw_text_block(draw: Any, origin: Tuple[int, int], lines: Sequence[str], font: Any, fill: str = "black") -> None:
    """
    在图片上逐行写文本。

    输入：
        draw、起点、文本行、字体、颜色。
    输出：
        原地绘制文字。
    使用示例：
        draw_text_block(draw, (10, 10), ["001", "name"], font)
    """
    x, y = origin
    line_height = max(18, int(getattr(font, "size", 16) * 1.35)) if font is not None else 20
    for line in lines:
        draw.text((x, y), str(line), fill=fill, font=font)
        y += line_height


def create_card_crop(
    source_image_path: Path,
    crop_output_path: Path,
    row: Mapping[str, str],
    prelabel_row: Mapping[str, str],
) -> bool:
    """
    裁剪单张装备卡，并在下方写上当前机器/复核标签。

    输入：
        原截图路径、输出路径、最终标签行、预识别行。
    输出：
        是否成功输出图片。
    使用示例：
        ok = create_card_crop(src, out, row, prelabel_row)
    """
    if Image is None or ImageDraw is None:
        return False
    if not source_image_path.exists():
        return False

    try:
        source = Image.open(source_image_path).convert("RGB")
        x, y, width, height = parse_bbox(str(prelabel_row.get("bbox", "")))
    except Exception:
        return False

    # 这里多留 6px 边距，避免边框文字或卡片边缘被裁掉。
    pad = 6
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(source.width, x + width + pad)
    bottom = min(source.height, y + height + pad)
    crop = source.crop((left, top, right, bottom))

    info_height = 124
    canvas = Image.new("RGB", (max(crop.width, 760), crop.height + info_height), "white")
    canvas.paste(crop, (0, 0))

    draw = ImageDraw.Draw(canvas)
    font = load_font(18)
    small_font = load_font(15)
    source_color = "red" if parse_bool(row.get("needs_user_review", "")) else "green"
    draw.rectangle((0, 0, crop.width - 1, crop.height - 1), outline=source_color, width=4)
    draw_text_block(
        draw,
        (8, crop.height + 8),
        [
            f"#{row.get('review_index', '')}  {row.get('filename', '')}  card_{row.get('card_no', '')}",
            f"当前装备名: {row.get('current_equipment_name', '')}",
            f"碎片: {row.get('current_fragment_owned', '')}/{row.get('current_fragment_required', '')}  来源: {row.get('label_source', '')}",
            f"机器候选: {row.get('machine_suggested_equipment_name', '')}  icon={row.get('icon_confidence', '')}",
        ],
        font,
    )
    if small_font is not None:
        draw.text(
            (8, crop.height + 98),
            f"name_ocr={row.get('name_ocr_text', '')}  attr_ocr={row.get('attribute_ocr_text', '')}",
            fill="black",
            font=small_font,
        )

    crop_output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(crop_output_path)
    return True


def create_contact_sheets(
    review_rows: Sequence[Mapping[str, str]],
    card_crop_dir: Path,
    output_dir: Path,
    cards_per_page: int = 12,
) -> int:
    """
    把所有单卡裁剪图拼成多页总览图。

    输入：
        复核行、单卡裁剪目录、总览图输出目录、每页数量。
    输出：
        生成的总览图页数。
    使用示例：
        pages = create_contact_sheets(rows, crop_dir, sheet_dir)
    """
    if Image is None or ImageDraw is None:
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    thumb_width = 520
    thumb_height = 250
    columns = 2
    rows_per_page = max(1, cards_per_page // columns)
    title_height = 52
    gap = 18
    page_width = columns * thumb_width + (columns + 1) * gap
    page_height = title_height + rows_per_page * thumb_height + (rows_per_page + 1) * gap
    title_font = load_font(24)
    small_font = load_font(16)

    page_count = 0
    for offset in range(0, len(review_rows), cards_per_page):
        page_rows = review_rows[offset : offset + cards_per_page]
        page_count += 1
        canvas = Image.new("RGB", (page_width, page_height), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (gap, 14),
            f"设计图全量复核总览 page {page_count} / {((len(review_rows) - 1) // cards_per_page) + 1}",
            fill="black",
            font=title_font,
        )

        for index, row in enumerate(page_rows):
            review_index = str(row.get("review_index", ""))
            crop_name = f"{int(review_index):03d}_{safe_stem(str(row.get('filename', '')))}_card{int(str(row.get('card_no', ''))):02d}.png"
            crop_path = card_crop_dir / crop_name
            if not crop_path.exists():
                continue
            thumb = Image.open(crop_path).convert("RGB")
            thumb.thumbnail((thumb_width, thumb_height))
            col = index % columns
            row_no = index // columns
            x = gap + col * (thumb_width + gap)
            y = title_height + gap + row_no * (thumb_height + gap)
            canvas.paste(thumb, (x, y))
            draw.rectangle((x, y, x + thumb_width - 1, y + thumb_height - 1), outline="#cccccc", width=1)
            draw.text((x + 8, y + thumb.height + 2), f"改 CSV 第 {review_index} 行；错了填 correct_*", fill="#333333", font=small_font)

        canvas.save(output_dir / f"page_{page_count:03d}.png")

    return page_count


# ============================================================
# 🚀 第五部分：主流程
# ============================================================

def build_review_rows(
    final_rows: Sequence[Mapping[str, str]],
    prelabel_lookup: Mapping[Tuple[str, str], Mapping[str, str]],
    input_dir: Path,
    annotated_dir: Path,
    card_crop_dir: Path,
    annotated_prefix: str = "new_account_",
) -> List[Dict[str, str]]:
    """
    生成用户复核 CSV 行，并输出单卡裁剪图。

    输入：
        final CSV、prelabel 查询表、原图目录、整页标注目录、单卡输出目录。
    输出：
        用户复核 CSV 行。
    使用示例：
        rows = build_review_rows(final_rows, lookup, input_dir, annotated_dir, crop_dir)
    """
    review_rows: List[Dict[str, str]] = []
    for index, final_row in enumerate(final_rows, start=1):
        filename = str(final_row.get("filename", "") or "").strip()
        card_no = str(final_row.get("card_no", "") or "").strip()
        prelabel_row = prelabel_lookup.get((filename, card_no), {})
        crop_name = f"{index:03d}_{safe_stem(filename)}_card{int(card_no):02d}.png"
        current_name = (
            str(final_row.get("final_equipment_name", "") or "").strip()
            or str(final_row.get("accepted_equipment_name", "") or "").strip()
            or str(final_row.get("suggested_equipment_name", "") or "").strip()
            or str(prelabel_row.get("suggested_equipment_name", "") or "").strip()
        )
        current_owned = (
            str(final_row.get("fragment_owned", "") or "").strip()
            or str(final_row.get("final_fragment_owned", "") or "").strip()
            or str(final_row.get("accepted_fragment_owned", "") or "").strip()
            or str(final_row.get("ocr_fragment_count", "") or "").strip()
            or str(prelabel_row.get("ocr_fragment_count", "") or "").strip()
        )
        current_required = (
            str(final_row.get("fragment_required", "") or "").strip()
            or str(final_row.get("final_fragment_required", "") or "").strip()
            or str(final_row.get("accepted_fragment_required", "") or "").strip()
            or str(final_row.get("ocr_required_count", "") or "").strip()
            or str(prelabel_row.get("ocr_required_count", "") or "").strip()
        )
        label_source = (
            str(final_row.get("final_label_source", "") or "").strip()
            or str(final_row.get("self_label_decision", "") or "").strip()
            or str(final_row.get("review_reason", "") or "").strip()
            or "machine_review_row"
        )
        needs_user_review = (
            str(final_row.get("needs_user_review", "") or "").strip()
            or str(final_row.get("needs_review", "") or "").strip()
        )
        machine_suggested = (
            str(final_row.get("machine_suggested_equipment_name", "") or "").strip()
            or str(final_row.get("suggested_equipment_name", "") or "").strip()
            or str(prelabel_row.get("suggested_equipment_name", "") or "").strip()
        )
        row = {
            "review_index": str(index),
            "filename": filename,
            "card_no": card_no,
            "current_equipment_name": current_name,
            # 用户只在认为当前结果错误时填写 correct_*；空白表示沿用 current_*。
            "correct_equipment_name": "",
            "current_fragment_owned": current_owned,
            "correct_fragment_owned": "",
            "current_fragment_required": current_required,
            "correct_fragment_required": "",
            "label_source": label_source,
            "needs_user_review": needs_user_review,
            "machine_suggested_equipment_name": machine_suggested,
            "icon_confidence": str(final_row.get("icon_confidence", prelabel_row.get("icon_confidence", "")) or "").strip(),
            "name_ocr_text": str(final_row.get("name_ocr_text", prelabel_row.get("name_ocr_text", "")) or "").strip(),
            "attribute_ocr_text": str(prelabel_row.get("attribute_ocr_text", "") or "").strip(),
            "review_reason": str(final_row.get("review_reason", prelabel_row.get("review_reason", "")) or "").strip(),
            "card_crop_path": str((card_crop_dir / crop_name).resolve()),
            "annotated_source_path": str(find_annotated_source_path(annotated_dir, filename, annotated_prefix)),
            "notes": "",
        }
        create_card_crop(input_dir / filename, card_crop_dir / crop_name, row, prelabel_row)
        review_rows.append(row)
    return review_rows


def write_readme(path: Path, review_csv: Path, sheet_dir: Path, crop_dir: Path, annotated_dir: Path) -> None:
    """
    写出中文使用说明。

    输入：
        README 路径和关键目录。
    输出：
        txt 说明文件。
    使用示例：
        write_readme(out / "README.txt", csv, sheets, crops, annotated)
    """
    text = f"""设计图全量复核包使用说明

你现在只需要看两个地方、改一个文件。

一、先看总览图
{sheet_dir}

打开 page_001.png、page_002.png ... 从前往后看。
每张小图左上角都有 review_index，例如 #001、#002。
如果你发现某张卡的装备名或碎片数量错了，就去下面这个 CSV 改对应 review_index 的那一行。

二、如果总览图看不清，看单卡裁剪图
{crop_dir}

文件名格式：
001_frag_xxx_card01.png
其中 001 对应 review_index，card01 对应截图里的第 1 张卡。

三、如果想看它在整张截图里的位置，看整页标注图
{annotated_dir}

这里是 19 张完整截图的标注结果，适合确认“这张卡到底在原图哪里”。

四、唯一需要你修改的文件
{review_csv}

修改方法：
1. 如果 current_equipment_name 是对的：这一行不用动。
2. 如果装备名错了：只填 correct_equipment_name。
3. 如果左侧拥有碎片数错了：只填 correct_fragment_owned。
4. 如果右侧需求碎片数错了：只填 correct_fragment_required。
5. notes 可以写备注；不确定就写“疑似xxx”。

不要改 current_* 字段，也不要改机器输出原始 CSV。
correct_* 留空的意思就是“沿用 current_*”。

五、关于被截掉半张的卡
这次进入全量复核包的是完整可用卡。
被截掉半张或信息不足的卡不会进入训练合并，避免把错误数据喂给模型。
如果你想看它们，只需要看整页标注图里的 skip/partial 标记。
"""
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。

    输入：
        命令行参数。
    输出：
        argparse.Namespace。
    使用示例：
        args = parse_args()
    """
    project_root = find_project_root(Path(__file__))
    workbench = project_root / "ocr_training_lab" / "equipment_icon_matcher_v2" / "active_workbench" / "01_fragment_page"
    default_run = workbench / "img_out" / "run_new_account_design_frag_20260722_0001"
    default_review = workbench / "review" / "self_label_new_account_design_frag_20260722_0001_clean"

    parser = argparse.ArgumentParser(description="生成设计图识别结果的全量人工复核包。")
    parser.add_argument("--input-dir", type=Path, default=workbench / "img_input")
    parser.add_argument("--run-dir", type=Path, default=default_run)
    parser.add_argument("--review-dir", type=Path, default=default_review)
    parser.add_argument("--output-dir", type=Path, default=default_review / "full_review_pack")
    parser.add_argument("--row-csv", type=Path, default=None, help="要展示的行 CSV；默认使用 review-dir/new_account_collection_final_cards.csv。")
    parser.add_argument("--prelabel-csv", type=Path, default=None, help="bbox/name/attribute 详情 CSV；默认使用 run-dir/v2_prelabel_results.csv。")
    parser.add_argument("--todo-exp", type=Path, default=None, help="只展示这个 todo exp 中出现的卡。")
    parser.add_argument("--annotated-prefix", default="new_account_", help="整页标注图的文件名前缀。")
    parser.add_argument("--selected-only", action="store_true", help="只保留 selected=true 的卡。")
    parser.add_argument("--full-only", action="store_true", help="只保留 visibility=full 的卡。")
    return parser.parse_args()


def main() -> int:
    """
    生成 full_review_pack。

    输入：
        默认读取当前 active_workbench 的最新新号设计图结果。
    输出：
        full_review_pack 文件夹。
    使用示例：
        python build_fragment_full_review_pack.py
    """
    args = parse_args()
    input_dir = args.input_dir.resolve()
    run_dir = args.run_dir.resolve()
    review_dir = args.review_dir.resolve()
    output_dir = args.output_dir.resolve()
    project_root = find_project_root(Path(__file__))
    final_csv = (args.row_csv or (review_dir / "new_account_collection_final_cards.csv")).resolve()
    prelabel_csv = (args.prelabel_csv or (run_dir / "v2_prelabel_results.csv")).resolve()
    annotated_dir = run_dir / "annotated"
    card_crop_dir = output_dir / "card_crops_all"
    sheet_dir = output_dir / "full_contact_sheets"

    ensure_safe_output_dir(output_dir, project_root)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    final_rows = read_csv(final_csv)
    if bool(args.selected_only):
        final_rows = [row for row in final_rows if parse_bool(row.get("selected"))]
    if bool(args.full_only):
        final_rows = [row for row in final_rows if str(row.get("visibility", "") or "").strip().lower() == "full"]
    todo_keys = parse_todo_exp_keys(args.todo_exp.resolve() if args.todo_exp is not None else None)
    if todo_keys:
        final_rows = [
            row for row in final_rows
            if (str(row.get("filename", "") or "").strip(), str(row.get("card_no", "") or "").strip()) in todo_keys
        ]
    prelabel_rows = read_csv(prelabel_csv)
    prelabel_lookup = build_lookup(prelabel_rows)
    review_rows = build_review_rows(
        final_rows,
        prelabel_lookup,
        input_dir,
        annotated_dir,
        card_crop_dir,
        annotated_prefix=str(args.annotated_prefix or ""),
    )
    review_csv = output_dir / "review_all_cards_for_user.csv"
    write_csv(review_csv, review_rows, REVIEW_FIELDNAMES)
    page_count = create_contact_sheets(review_rows, card_crop_dir, sheet_dir, cards_per_page=12)
    write_readme(output_dir / "README_FULL_REVIEW_HOW_TO_EDIT.txt", review_csv, sheet_dir, card_crop_dir, annotated_dir)
    write_json(
        output_dir / "full_review_summary.json",
        {
            "review_rows": len(review_rows),
            "contact_sheet_pages": page_count,
            "review_csv": str(review_csv),
            "card_crop_dir": str(card_crop_dir),
            "full_annotated_source_dir": str(annotated_dir),
        },
    )
    print(f"已生成全量复核包: {output_dir}")
    print(f"复核 CSV: {review_csv}")
    print(f"总览图目录: {sheet_dir}")
    print(f"单卡裁剪目录: {card_crop_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
