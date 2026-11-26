# -*- coding: utf-8 -*-
"""钢琴改动设计图 v3。"""
import math, os
from PIL import Image, ImageDraw, ImageFont

W, H = 1680, 1850
PAPER = (250, 246, 239); CARD = (255, 252, 246)
INK = (36, 28, 20); INK2 = (108, 94, 78); INK3 = (150, 136, 118)
BORDER = (201, 185, 159); RULE = (236, 228, 214)
RED = (192, 57, 43); GREEN = (46, 125, 79); BLUE = (44, 95, 138)
WOOD = (185, 138, 84); WOOD_D = (138, 97, 54); WOOD_L = (206, 168, 116)
KEYW = (247, 237, 218); KEYW_S = (214, 196, 168); KEYB = (44, 36, 30)
FLOOR = (70, 51, 31); REAR = (120, 88, 52); PEDAL = (150, 148, 145)

F = "C:/Windows/Fonts/msyh.ttc"; FB = "C:/Windows/Fonts/msyhbd.ttc"
img = Image.new("RGB", (W, H), PAPER); d = ImageDraw.Draw(img)
_fc = {}
def _font(sz, bold):
    k = (sz, bold)
    if k not in _fc: _fc[k] = ImageFont.truetype(FB if bold else F, sz)
    return _fc[k]
def text(x, y, s, sz=15, color=INK, bold=False, anchor="la"):
    d.text((x, y), s, font=_font(sz, bold), fill=color, anchor=anchor)
def tw(s, sz, bold=False):
    return d.textbbox((0, 0), s, font=_font(sz, bold))[2]
def rect(x1, y1, x2, y2, fill, outline=None, w=1):
    d.rectangle([x1, y1, x2, y2], fill=fill, outline=outline, width=w)
def panel(x1, y1, x2, y2, tag, title, sub=""):
    d.rectangle([x1, y1, x2, y2], fill=CARD, outline=BORDER, width=2)
    d.rectangle([x1, y1, x1 + 46, y1 + 31], fill=INK)
    text(x1 + 23, y1 + 16, tag, 18, PAPER, True, "mm")
    text(x1 + 58, y1 + 6, title, 20, INK, True)
    if sub: text(x1 + 58, y1 + 32, sub, 13, INK2)
def badge(cx, cy, n, color=RED, r=11):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    text(cx, cy, str(n), 13, PAPER, True, "mm")
def arrow(x1, y1, x2, y2, color=INK, w=2):
    d.line([x1, y1, x2, y2], fill=color, width=w)
    a = math.atan2(y2 - y1, x2 - x1); L, sp = 9, 0.42
    d.polygon([(x2, y2), (x2 - L*math.cos(a-sp), y2 - L*math.sin(a-sp)),
               (x2 - L*math.cos(a+sp), y2 - L*math.sin(a+sp))], fill=color)

PITCH = 2.3333          # (KEY_MAX_X - KEY_MIN_X) / WHITE_KEYS = 35 / 15
WS = []; _x = -9.5        # well spans -9.5..25.5 = 35 px, 15 × 2.3333
for i in range(15): WS.append((_x, _x + PITCH)); _x += PITCH
PAT = [0, 1, 3, 4, 5]; BLACKS = []
for octv in range(3):
    for q in PAT:
        i = octv * 7 + q
        if i >= 14: continue
        x0 = WS[i][0] + PITCH - 0.55
        BLACKS.append((x0, x0 + 1.1))

text(40, 18, "钢琴 · 琴键改造设计图", 30, INK, True)
text(40, 56, "单位：模型 px（1 px = 1/16 方块 = 6.25 cm，1 texel = 1 模型 px）　键区 x 6.5–41.5（35 宽）　白键 15 / 黑键 10（共 25 键）", 14, INK2)
d.line([40, 78, 1640, 78], fill=BORDER, width=2)

# ---------------- A 现状 ----------------
AX1, AY1, AX2, AY2 = 40, 88, 810, 470
panel(AX1, AY1, AX2, AY2, "A", "现在的 bbmodel：整个键盘是两块实心木头", "键缝是画上去的像素，不是几何")
S = 7.6
def FX(x): return 62 + (x + 14.0) * S
def FY(y): return 430 - y * S
rect(FX(-12.5), FY(29), FX(28.5), FY(0), WOOD)
rect(FX(-13.5), FY(32), FX(29.5), FY(29), WOOD_L)
rect(FX(-12.5), FY(19), FX(-9.5), FY(0), WOOD_D)
rect(FX(25.5), FY(19), FX(28.5), FY(0), WOOD_D)
rect(FX(-9.5), FY(19), FX(25.5), FY(16), WOOD_L)
rect(FX(-1.5), FY(28.4), FX(17.5), FY(19.4), (233, 227, 209), BORDER)
text((FX(-1.5)+FX(17.5))/2, (FY(28.4)+FY(19.4))/2, "谱架 不动", 12, INK2, anchor="mm")
rect(FX(-9.5), FY(16), FX(25.5), FY(12), WOOD)
rect(FX(-9.5), FY(16), FX(25.5), FY(12), None, RED, 3)
for (x0, x1) in WS:
    d.line([FX(x0 + 0.06), FY(15.9), FX(x0 + 0.06), FY(13.1)], fill=KEYW_S, width=1)
for (x0, x1) in BLACKS:
    rect(FX(x0), FY(15.9), FX(x1), FY(14.3), KEYB)
for px in (2.5, 9.5):
    rect(FX(px), FY(2), FX(px + 4), FY(1), PEDAL)
# badges on model
badge(FX(22.6), FY(14.55), 1, RED)
badge(FX(-8.6), FY(12.7), 2, RED)

text(AX1 + 20, AY2 - 40, "① 键面贴片 688d3c5a（34×3×6）→ 删", 13, RED, True)
text(AX1 + 20, AY2 - 18, "② 键床 47cce97a（y12–16 实心）→ 掏空，顶面 16→13.6　两步都由生成器做，美术不手改", 12.5, INK2)

# ---------------- B 改后 ----------------
BX1, BY1, BX2, BY2 = 850, 88, 1640, 470
panel(BX1, BY1, BX2, BY2, "B", "改后：槽留在模型里，键单独一份模型", "槽是静态件；25 个键是 standalone model")
def BX(x): return 876 + (x + 14.0) * S
def BY(y): return 430 - y * S
rect(BX(-12.5), BY(29), BX(28.5), BY(0), WOOD)
rect(BX(-13.5), BY(32), BX(29.5), BY(29), WOOD_L)
rect(BX(-12.5), BY(19), BX(-9.5), BY(0), WOOD_D)
rect(BX(25.5), BY(19), BX(28.5), BY(0), WOOD_D)
rect(BX(-9.5), BY(19), BX(25.5), BY(16), WOOD_L)
rect(BX(-1.5), BY(28.4), BX(17.5), BY(19.4), (233, 227, 209), BORDER)
text((BX(-1.5)+BX(17.5))/2, (BY(28.4)+BY(19.4))/2, "谱架 不动", 12, INK2, anchor="mm")
rect(BX(-10), BY(16), BX(26), BY(12), FLOOR)
rect(BX(-10), BY(13.6), BX(26), BY(12), (52, 37, 22))
rect(BX(-10), BY(16), BX(-9.5), BY(13.6), WOOD_D)
rect(BX(25.5), BY(16), BX(26), BY(13.6), WOOD_D)
rect(BX(-9.5), BY(16), BX(25.5), BY(15.3), REAR)
for (x0, x1) in BLACKS:
    rect(BX(x0), BY(15.65), BX(x1), BY(14.65), KEYB)
for (x0, x1) in WS:
    rect(BX(x0 + 0.06), BY(14.6), BX(x1 - 0.06), BY(14.05), KEYW)
d.rectangle([BX(-9.4), BY(16.1), BX(-6.4), BY(13.5)], outline=BLUE, width=2)
text(BX(-6.4) + 6, BY(16.0), "见 E 放大", 12, BLUE, True)
badge(BX(-8.4), BY(13.2), 3, GREEN)
badge(BX(22.6), BY(15.4), 4, BLUE)

text(BX1 + 20, BY2 - 40, "③ 槽底顶面 y13.6（深 2 档木色，槽腔 2.4 深）→ 俯视看得见空槽", 13, GREEN, True)
text(BX1 + 20, BY2 - 18, "④ 25 个独立 cube（白 15 + 黑 10）：美术在 bb 里画，导出 piano_keys.json；代码只切片与摆角度", 12.5, INK2)

# ---------------- C 俯视 ----------------
CX1, CY1, CX2, CY2 = 40, 486, 810, 790
panel(CX1, CY1, CX2, CY2, "C", "改后俯视：槽里必须是空的", "白键 2.3333 / 缝 0.06 每边（纹理画不出，只能靠几何）")
S2 = 17.0
def TX(x): return 108 + (x + 10.0) * S2
def TZ(z): return 722 - z * S2
rect(TX(-10), TZ(6), TX(26), TZ(0), (52, 37, 22))
rect(TX(-10), TZ(6), TX(26), TZ(5.7), REAR)
rect(TX(-10), TZ(6), TX(-9.5), TZ(0), WOOD_D)
rect(TX(25.5), TZ(6), TX(26), TZ(0), WOOD_D)
rect(TX(-9.5), TZ(0.05), TX(25.5), TZ(0), WOOD_L)
for (x0, x1) in WS:
    rect(TX(x0 + 0.06), TZ(5.7), TX(x1 - 0.06), TZ(0.05), KEYW)
for (x0, x1) in BLACKS:
    rect(TX(x0), TZ(5.6), TX(x1), TZ(1.9), KEYB)
text(CX1 + 22, CY1 + 62, "黑键 1.1 宽，槽 1.1 + 2×0.03　白键 z 0.05–5.7　黑键 z 1.9–5.6", 13, INK2)
text(CX1 + 22, CY1 + 84, "槽内宽必须 35（15 × 2.3333）：现模型贴片只有 34，右侧要补 1 px", 13, RED)
# leaders
rect(TX(26), TZ(6), TX(27.4), TZ(0), WOOD)          # 琴体外壳：填掉缘木右侧的纸色空白
d.line([TX(26), TZ(6), TX(26), TZ(0)], fill=INK, width=2)
text(TX(27.4) + 6, TZ(4.2), "外壳", 11, INK3)
text(TX(26) - 12, TZ(6.0) - 22, "右缘木 0.5", 12, INK2, anchor="ra")
text(TX(-9.5) + 4, TZ(6.0) - 22, "后壁 z5.7–6", 12, INK2)


yb = TZ(0) + 30
d.line([TX(WS[1][0]), yb, TX(WS[1][1]), yb], fill=BLUE, width=2)
for xx in (TX(WS[1][0]), TX(WS[1][1])): d.line([xx, yb - 5, xx, yb + 5], fill=BLUE, width=2)
text((TX(WS[1][0]) + TX(WS[1][1])) / 2, yb + 6, "2.3333", 12, BLUE, True, "ma")


# ---------------- D 剖面 ----------------
DX1, DY1, DX2, DY2 = 850, 486, 1640, 790
panel(DX1, DY1, DX2, DY2, "D", "剖面：抬起 vs 按下", "白 4.4°　黑 6.727°　键尖都下沉 0.4334")
S3 = 56.0
def PZ(z): return 878 + z * S3
def PY(y): return 754 - (y - 11.9) * S3
rect(PZ(0), PY(13.6), PZ(6.0), PY(11.9), (52, 37, 22))
rect(PZ(0), PY(16.4), PZ(0.05), PY(13.6), WOOD_L)
rect(PZ(5.7), PY(16.4), PZ(6.0), PY(13.6), REAR)
def quad(zz, yy, L, thick, ang):
    a = math.radians(ang); c, s = math.cos(a), math.sin(a); p = []
    for dz, dy in [(0, 0), (-L, 0), (-L, -thick), (0, -thick)]:
        p.append((PZ(zz + dz*c - dy*s), PY(yy + dz*s + dy*c)))
    return p
d.polygon(quad(5.7, 14.05, 5.65, 0.55, 0), fill=(236, 239, 246), outline=INK, width=2)
d.polygon(quad(5.6, 14.65, 3.7, 1.0, 0), fill=KEYB, outline=INK2)
d.polygon(quad(5.7, 14.05, 5.65, 0.55, 4.4), fill=None, outline=RED, width=3)
d.polygon(quad(5.6, 14.65, 3.7, 1.0, 6.727), fill=None, outline=RED, width=3)
d.line([PZ(1.2), PY(14.05), PZ(1.2), PY(14.05-0.4334)], fill=RED, width=2)
for yy in (14.05, 14.05-0.4334):
    d.line([PZ(1.2) - 6, PY(yy), PZ(1.2) + 6, PY(yy)], fill=RED, width=2)
text(PZ(1.2) + 10, PY(13.5), "0.4334", 12, RED, True)

# 轴 = 键的后下缘（内侧）：两条轮廓只在这一点重合
wbx, wby = PZ(5.7), PY(14.05)
bbx, bby = PZ(5.6), PY(14.65)
d.ellipse([wbx - 6, wby - 6, wbx + 6, wby + 6], fill=BLUE, outline=PAPER)
d.ellipse([bbx - 4, bby - 4, bbx + 4, bby + 4], fill=GREEN, outline=PAPER)


text(PZ(0.05) + 4, PY(13.6) + 14, "前唇", 12, PAPER)
text(PZ(6.0) + 6, PY(15.4), "后壁", 12, INK2)
text(PZ(0.15), PY(11.9) + 6, "槽底 y13.6", 12, INK2)

nx = PZ(6.6) + 26
text(nx, DY1 + 64, "实线 = 抬起", 13, INK)
text(nx, DY1 + 84, "红线 = 按下", 13, RED)
text(nx, DY1 + 112, "白键 轴(5.7) 转 4.4° → 尖下沉 0.4334", 13, INK2)
text(nx, DY1 + 132, "黑键 轴(5.6) 转 6.727° → 尖下沉 0.4334", 13, INK2)
text(nx, DY1 + 158, "槽余量 白0.02 / 黑0.67", 13, GREEN)
text(nx, DY1 + 178, "键尖行程相同 → 不穿槽底", 12, INK3)
text(nx, DY1 + 204, "踏板：绕后缘压 0.15", 13, INK2)
text(nx, DY1 + 230, "轴 = 键的后下缘（内侧）", 13, BLUE, True)
text(nx, DY1 + 250, "→ 前端下沉，后端不动", 12, INK2)

# ---------------- E 放大 ----------------
EX1, EY1, EX2, EY2 = 40, 806, 810, 1210
panel(EX1, EY1, EX2, EY2, "E", "键区放大 4×：一个键长什么样", "美术的活就是这一小块，重复 25 份")
S5 = 58.0
def EX(x): return 150 + (x + 9.3) * S5
def EY(y): return 1124 - (y - 12.0) * S5
xe = WS[1][1]
rect(EX(-9.3), EY(16.5), EX(xe + 0.3), EY(12.0), (52, 37, 22))
rect(EX(-9.3), EY(16.5), EX(-9.0), EY(13.6), WOOD_D)
rect(EX(-9.0), EY(16.5), EX(xe + 0.3), EY(15.3), REAR)
for (x0, x1) in [b for b in BLACKS if b[1] <= xe + 0.5]:
    rect(EX(x0), EY(15.65), EX(x1), EY(14.65), KEYB)
for (x0, x1) in [w for w in WS if w[1] <= xe + 0.5]:
    rect(EX(x0 + 0.06), EY(14.6), EX(x1 - 0.06), EY(14.05), KEYW)
    d.line([EX(x0 + 0.06), EY(14.05), EX(x1 - 0.06), EY(14.05)], fill=KEYW_S, width=2)
def hline(y, x1, x2, label, color=INK2, dy=-16):
    d.line([x1, y, x2, y], fill=color, width=1)
    text((x1 + x2) / 2, y + dy, label, 12, color, anchor="mm")
hline(EY(14.6), EX(WS[0][0]) + 6, EX(WS[0][1]) - 6, "白键厚 0.55", INK2, -14)
hline(EY(14.05), EX(WS[1][0]) + 6, EX(WS[1][1]) - 6, "键面 = 美术的纹理", INK3, 14)
d.line([EX(-9.3) - 10, EY(15.65), EX(-9.3) - 10, EY(13.6)], fill=GREEN, width=2)
text(EX(-9.3) - 16, (EY(15.65) + EY(13.6)) / 2, "槽腔", 12, GREEN, True, "rm")
text(EX(-9.3) - 16, (EY(15.65) + EY(13.6)) / 2 + 16, "2.4 深", 12, GREEN, True, "rm")
text(EX(-9.3) + 4, EY(12.0) - 24, "槽底 y13.6（深 2 档木色）", 12, GREEN, True)
bk = BLACKS[0]
text((EX(bk[0]) + EX(bk[1])) / 2, EY(16.0), "1.1×1.0", 11, PAPER, True, "ma")
text(EX1 + 20, EY2 - 52, "每个键是独立 cube，原点在自己后下缘；白键长（z 0.05–5.7），黑键短（z 1.9–5.6）", 12.5, INK2)
text(EX1 + 20, EY2 - 30, "缝 0.06 / 边必须留：1 texel = 6.25 cm，画不出 0.06 px 的线", 12.5, INK2)

# ---------------- F 数值 ----------------
FX1, FY1, FX2, FY2 = 850, 806, 1640, 1210
panel(FX1, FY1, FX2, FY2, "F", "坐标契约", "全部单位 = 模型 px（1 px = 6.25 cm）")
rows = [("键区 x", "6.5 – 41.5（35 宽）"), ("白键", "15 个，宽 2.3333，缝 0.06 / 边"),
        ("黑键", "10 个，宽 1.1，槽 1.1 + 2×0.03"), ("白键 y", "14.05 – 14.6（0.55 厚）"),
        ("黑键 y", "14.65 – 15.65（1.0 厚）"), ("白键 z", "0.05 – 5.7"), ("黑键 z", "1.9 – 5.6"),
        ("槽底顶面", "y 13.6　槽腔 13.6–16（2.4 深）"), ("白键轴", "(x, 14.05, 5.7)　转 4.4°（尖下压）"),
        ("黑键轴", "(x, 14.65, 5.6)　转 6.727°（尖下压）"), ("键尖行程", "0.4334（白黑一致）"),
        ("踏板", "绕后缘压 0.15，连杆 0.4×0.4")]
ty = FY1 + 66
for k, v in rows:
    text(FX1 + 26, ty, k, 13.5, INK, True); text(FX1 + 140, ty, v, 13.5, INK2)
    ty += 25; d.line([FX1 + 26, ty - 7, FX2 - 26, ty - 7], fill=RULE, width=1)

# ---------------- G 分工 ----------------
GX1, GY1, GX2, GY2 = 40, 1226, 1640, 1530
panel(GX1, GY1, GX2, GY2, "G", "三个模型文件 + 谁做哪一步", "")
def box(x, y, w, title, color, lines):
    h = 34 + 22 * len(lines) + 10
    rect(x, y, x + w, y + h, (255, 253, 248), color, 2)
    d.rectangle([x, y, x + w, y + 30], fill=color)
    text(x + 12, y + 6, title, 14, PAPER, True)
    yy = y + 38
    for ln in lines: text(x + 12, yy, ln, 13, INK2); yy += 22
    return y + h
y0 = GY1 + 58
box(GX1 + 26, y0, 500, "piano.json（方块模型 · blockstate 烘焙）", GREEN,
    ["槽壳：地板 y12–13.6、左右缘木、后壁、前唇", "壳体 / 琴盖 / 谱架 / 踏板", "不含任何一个琴键"])
box(GX1 + 26, y0 + 132, 500, "piano_keys.json（standalone 模型）", BLUE,
    ["整排 25 个独立 cube：白 15 + 黑 10", "每个 cube 原点在自己的转动轴", "piano_keys.png：1 个键 32×32"])
box(GX1 + 596, y0, 460, "美术做", RED,
    ["1. 删键面贴片、掏空键床 —— 我来做", "2. 画 25 个键 + 键小图", "3. 踏板连杆、端木配色"])
box(GX1 + 596, y0 + 116, 460, "代码做", INK,
    ["1. standalone 注册（ModelEvent.RegisterStandalone）", "2. BER 取模型 → 按 x 切 25 组 → 每键一 pose", "3. 按键状态同步 + 音符映射"])
box(GX1 + 1100, y0, 500, "为什么不能塞进一个方块模型", BLUE,
    ["blockstate 是整块的：一个键换角度就要整块换模型", "25 键 × 2 态 = 2^25 组合，和弦要同时按多键", "→ 组合不可枚举，只能走 standalone"])
text(GX2 - 26, GY2 - 26, "下一步：先做 1 个白键原型 → 游戏内截图确认观感 → 再全量 25", 13, GREEN, True, "ra")



# ---------------- H 键盘映射 ----------------
HX1, HY1, HX2, HY2 = 40, 1546, 1640, 1824
panel(HX1, HY1, HX2, HY2, "H", "为什么是 25 键：每个音在键盘上都有位置",
      "PianoKeyboard.java:14-32 的 KEY_CODES / WHITE_LABELS / BLACK_LABELS 就是这张图")
KW2, KH2 = 46, 58
X0 = 476
WHITE_LABELS = ["Z", "X", "C", "V", "B", "N", "M", "Q", "W", "E", "R", "T", "Y", "U", "I"]
BLACKS2 = [(0, "S"), (1, "D"), (3, "G"), (4, "H"), (5, "J"), (7, "2"), (8, "3"), (10, "5"), (11, "6"), (12, "7")]
WY, BY = 1668, 1622
for wi, lb in enumerate(WHITE_LABELS):
    x = X0 + wi * KW2
    rect(x, WY, x + KW2 - 2, WY + KH2, KEYW, INK2, 2)
    text(x + (KW2 - 2) / 2, WY + KH2 - 16, lb, 15, INK, True, "mm")
for wi, lb in BLACKS2:
    x = X0 + wi * KW2 + KW2 - 2 - 19
    rect(x, BY, x + 38, BY + 62, KEYB, None)
    text(x + 19, BY + 52, lb, 14, PAPER, True, "mm")
text(HX1 + 40, HY1 + 52, "白键 15：Z X C V B N M ／ Q W E R T Y U I　　黑键 10：S D G H J ／ 2 3 5 6 7", 14, INK)
text(HX1 + 40, HY2 - 44, "25 个音 = C3 – C5（两个八度 + 收尾 C），一个音对一个物理键，和弦三个指头同时下去就行。", 14, INK2)
text(HX1 + 40, HY2 - 22, "再加 6 白 5 黑就没有舒适键位了：剩下的 A F K L ; 正好是白键之间的空档，也就是黑键的位置。", 14, RED)

out = os.path.join("build", "piano_brief", "piano_change_sheet.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
img.save(out); print(out, img.size)
