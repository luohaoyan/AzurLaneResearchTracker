from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1200, 800
img = Image.new("RGB", (W, H), (30, 32, 45))
draw = ImageDraw.Draw(img)

title_font = None
font_s = None
font_m = None
font_l = None

font_paths = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\yahei.ttf",
    r"C:\Windows\Fonts\SIMHEI.TTF",
]
for fp in font_paths:
    if os.path.exists(fp):
        font_s = ImageFont.truetype(fp, 14)
        font_m = ImageFont.truetype(fp, 18)
        title_font = ImageFont.truetype(fp, 24)
        font_l = ImageFont.truetype(fp, 32)
        break

if title_font is None:
    font_s = font_m = title_font = font_l = ImageFont.load_default()

# Title Bar
draw.rectangle((0, 0, W, 48), fill=(22, 24, 36))
draw.text((20, 12), "\u78a7\u84dd\u822a\u7ebf\u79d1\u7814\u88c5\u5907\u7edf\u8ba1\u5668 v0.1.0", fill=(200, 210, 230), font=font_l if font_l else title_font)
for x, c in [(W-55, (255,90,90)), (W-35, (255,190,60)), (W-15, (80,200,80))]:
    draw.ellipse((x, 14, x+12, 26), fill=c)

# Left Sidebar
SX, SY = 0, 48
SW = 180
draw.rectangle((SX, SY, SW, H), fill=(35, 38, 52))
nav_items = ["\ud83d\udce6 \u88c5\u5907\u5e93", "\ud83d\udd2c \u79d1\u7814\u7ba1\u7406", "\ud83d\udcca \u6b27\u975e\u7edf\u8ba1", "\ud83e\udd16 \u81ea\u52a8\u5316", "\u2699\ufe0f \u8bbe\u7f6e"]
for i, item in enumerate(nav_items):
    y = SY + 16 + i * 52
    if i == 1:
        draw.rectangle((0, y-6, SW, y+28), fill=(60, 100, 200, 60))
    draw.text((20, y), item, fill=(180, 190, 210) if i != 1 else (100, 180, 255), font=font_m)

# Main Content Area
MX, MY = SW + 10, SY + 10

# Section 1: Research Phase Cards
draw.text((MX, MY), "\ud83d\udd2c \u79d1\u7814\u671f\u6570\u6982\u89c8", fill=(200, 210, 230), font=title_font)
phases = [
    ("\u79d1\u7814\u4e00\u671f (PR1)", "6\u4ef6\u88c5\u5907", "\u57fa\u51c6 100", (70, 120, 200)),
    ("\u79d1\u7814\u4e8c\u671f (PR2)", "8\u4ef6\u88c5\u5907", "\u57fa\u51c6 150", (80, 140, 180)),
    ("\u79d1\u7814\u4e09\u671f (PR3)", "5\u4ef6\u88c5\u5907", "\u57fa\u51c6 200", (100, 160, 160)),
    ("\u79d1\u7814\u56db\u671f (PR4)", "7\u4ef6\u88c5\u5907", "\u57fa\u51c6 250", (120, 140, 180)),
]
x0 = MX
for name, count, base, col in phases:
    cx, cy = x0, MY + 40
    cw, ch = 190, 80
    draw.rectangle((cx, cy, cx+cw, cy+ch), fill=col + (40,), outline=(80, 90, 120))
    draw.text((cx+12, cy+10), name, fill=(210, 220, 240), font=font_m)
    draw.text((cx+12, cy+34), count, fill=(150, 200, 150), font=font_s)
    draw.text((cx+12, cy+54), base, fill=(200, 180, 120), font=font_s)
    x0 = cx + cw + 12

# Section 2: Equipment Table
TY = MY + 140
draw.text((MX, TY), "\ud83d\udce6 \u5f53\u524d\u79d1\u7814\u88c5\u5907\u5217\u8868", fill=(200, 210, 230), font=title_font)
tx, ty = MX, TY + 35
tcol = (45, 48, 62)
draw.rectangle((tx, ty, tx + 780, ty + 28), fill=tcol)
headers = ["ID", "\u88c5\u5907\u540d\u79f0", "\u7a00\u6709\u5ea6", "\u7c7b\u578b", "\u62e5\u6709\u6570", "\u788e\u7247\u6570", "\u6b27\u975e\u503c"]
widths = [40, 220, 80, 100, 80, 80, 80]
cx = tx
for i, h in enumerate(headers):
    draw.rectangle((cx, ty, cx + widths[i], ty + 28), outline=(55, 58, 72))
    draw.text((cx + 8, ty + 5), h, fill=(150, 180, 220), font=font_s)
    cx += widths[i]

rows = [
    ("1", "\u8bd5\u4f5c\u578b\u4e09\u8054\u88c5406mm\u4e3b\u70aeMk6", "\u8d85\u7a00\u6709", "\u4e3b\u70ae", "2", "45", "\u826f\u597d"),
    ("2", "\u8bd5\u4f5c\u578b\u4e09\u8054\u88c5152mm\u4e3b\u70ae", "\u8d85\u7a00\u6709", "\u4e3b\u70ae", "1", "30", "\u666e\u901a"),
    ("3", "\u53cc\u8054\u88c5114mm\u9ad8\u5e73\u4e24\u7528\u70ae", "\u7cbe\u9510", "\u526f\u70ae", "3", "60", "\u4f18\u79c0"),
    ("4", "\u8bd5\u4f5c\u578b\u56db\u8054\u88c5533mm\u9c7c\u96f7", "\u8d85\u7a00\u6709", "\u9c7c\u96f7", "0", "15", "\u8f83\u5dee"),
    ("5", "\u535a\u798f\u65afSTAAG40mm\u9ad8\u70ae", "\u7cbe\u9510", "\u9632\u7a7a", "2", "50", "\u826f\u597d"),
    ("6", "\u9ad8\u6027\u80fd\u8235\u673a", "\u7a00\u6709", "\u8bbe\u5907", "4", "80", "\u4f18\u79c0"),
]
for ri, (rid, rname, rrar, rtype, rown, rfrag, rluck) in enumerate(rows):
    ry = ty + 28 + ri * 26
    bg = (40, 43, 58) if ri % 2 == 0 else (38, 41, 55)
    draw.rectangle((tx, ry, tx + 780, ry + 26), fill=bg)
    cx = tx
    vals = [rid, rname, rrar, rtype, rown, rfrag, rluck]
    for j, v in enumerate(vals):
        draw.rectangle((cx, ry, cx + widths[j], ry + 26), outline=(50, 53, 68))
        fc = (230, 240, 250) if j < 3 else (200, 210, 230)
        if j == 6:
            if v == "\u4f18\u79c0": fc = (100, 220, 130)
            elif v == "\u826f\u597d": fc = (100, 180, 230)
            elif v == "\u666e\u901a": fc = (200, 200, 160)
            else: fc = (230, 140, 120)
        draw.text((cx + 8, ry + 5), v, fill=fc, font=font_s)
        cx += widths[j]

# Right Stats Panel
RX = MX + 800 - 30
RY = MY
RW = 220
draw.rectangle((RX, RY, RX+RW, RY+340), fill=(38, 41, 55), outline=(55, 58, 72))
draw.text((RX+10, RY+8), "\ud83d\udcca \u7edf\u8ba1\u6982\u89c8", fill=(200, 210, 230), font=font_m)
stats = [
    ("\u603b\u88c5\u5907\u6570", "27 \u4ef6"),
    ("\u603b\u79d1\u7814\u671f\u6570", "4 \u671f"),
    ("\u8d85\u7a00\u6709\u88c5\u5907", "12 \u4ef6"),
    ("\u5e73\u5747\u6b27\u975e\u503c", "62.5%"),
    ("\u788e\u7247\u6536\u96c6\u7387", "45%"),
    ("\u81ea\u52a8\u5316\u72b6\u6001", "\u8fd0\u884c\u4e2d \u2705"),
]
for si, (label, val) in enumerate(stats):
    sy = RY + 44 + si * 44
    draw.text((RX+12, sy), label, fill=(150, 170, 200), font=font_s)
    draw.text((RX+12, sy+18), val, fill=(220, 230, 250), font=font_m)

# Section 4: Progress bars
PY = TY + 28 + len(rows) * 26 + 15
draw.text((MX, PY), "\ud83d\udcc8 \u6536\u96c6\u8fdb\u5ea6", fill=(200, 210, 230), font=title_font)
bars = [
    ("\u79d1\u7814\u4e00\u671f", 0.75, (80, 160, 255)),
    ("\u79d1\u7814\u4e8c\u671f", 0.60, (100, 200, 140)),
    ("\u79d1\u7814\u4e09\u671f", 0.40, (220, 180, 80)),
    ("\u79d1\u7814\u56db\u671f", 0.30, (200, 120, 160)),
]
bx0 = MX
for bname, pct, bcol in bars:
    by = PY + 32
    bw = 170
    draw.text((bx0, by-18), f"{bname} {int(pct*100)}%", fill=(180, 200, 220), font=font_s)
    draw.rectangle((bx0, by, bx0+bw, by+14), fill=(45, 48, 62))
    draw.rectangle((bx0, by, bx0+int(bw*pct), by+14), fill=bcol)
    bx0 = bx0 + bw + 20

# Footer
draw.rectangle((0, H-30, W, H), fill=(22, 24, 36))
draw.text((20, H-24), "\u6570\u636e\u81ea\u52a8\u540c\u6b65 | \u6700\u540e\u66f4\u65b0: 2026-07-02 10:30 | \u78a7\u84dd\u822a\u7ebf\u79d1\u7814\u88c5\u5907\u7edf\u8ba1\u5668", fill=(120, 130, 150), font=font_s)

out_path = r"G:\ALLPeoject\PythonProject\AzurLaneResearchTracker\preview.png"
img.save(out_path)
print(f"Preview saved to: {out_path}")
print(f"Image size: {W}x{H}")
print("Done!")
