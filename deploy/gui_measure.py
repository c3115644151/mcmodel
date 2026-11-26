#!/usr/bin/env python3
"""GUI 图标显示测量器 — 解析计算模型 in 物品栏 16x16 格的确切显示。

【参数语义 —— 与 16x16 图标格像素空间映射】(实测校准, 2026-08-23):
  scale: 有效显示宽度 = span × scale 单位; 16单位满格×0.625 = 10单位 = 格62.5%。
         "放大 n%" = scale × (1+n/100) — 线性等效视觉大小。
  translation[0] (tx): 屏幕右移像素, 正=右移, 1px = 图标格 1/16。
  translation[1] (ty): 屏幕上移像素, 正=上移, 1px = 图标格 1/16。
         (实测验证: 晾衣架 ty=-2 低, -2.5 更低(-0.5=下移0.5px), +1.09 高)
  rotation: [30, 225, 0] 是项目 bb 朝南模型的正确等轴测; [30,45,0] 仅用于朝北模型。

【已知偏差】:
  文本 box 居中(包围盒) ≠ 视觉居中(模型形状重心); ty 建议仅供起点, 微调 ±3px。
  可见增益下限: scale 调整 ±10% 屏幕几乎不可见, 建议 ±20% 起 (用户实测)。

原理 (同碰撞箱体素化思路, 但正交投影数学):
1. 取模型各元素的 8 角点 (含负坐标/旋转需先应用)
2. 应用 GUI 变换 (rotation [30,225,0] + scale + translation)
3. 等轴测正交投影: 屏幕 X = (worldX - worldZ) / sqrt2,
   screenY = -(worldY - (worldX + worldZ)/sqrt6) (MC 屏幕 y 向下, 故取反)
4. 计算投影后 16x16 图标格内的真实可见边界 → 输出误差
   最优 scale = 让投影最大边恰好贴格内 (留 12% 边距)

用法: python gui_measure.py <model.json> [--scale s] [--ty t]
      无 --scale/--ty 时输出【最优解析值】, 供工具自动应用。
"""
import json
import math
import sys


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def rot_x(p, angle_deg, origin):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
    ny = y * c - z * s
    nz = y * s + z * c
    return (x + origin[0], ny + origin[1], nz + origin[2])


def rot_y(p, angle_deg, origin):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
    nx = x * c + z * s
    nz = -x * s + z * c
    return (nx + origin[0], y + origin[1], nz + origin[2])


def apply_rotation(p, rot, element_origin=None):
    """支持两种格式: {"axis","angle","origin"} (导出JSON) 或 [x,y,z] 欧拉数组 (bbmodel 内嵌)。
    element_origin: bbmodel 数组格式的 origin 在元素字段上 (e.origin)。"""
    if isinstance(rot, list) and len(rot) >= 3:
        # bbmodel 数组: [rx, ry, rz] 欧拉角, origin 从元素取, 缺省 [8,8,8]
        origin = element_origin or [8.0, 8.0, 8.0]
        if all(abs(a) < 1e-9 for a in rot):
            return p
        # BB 顺序: x → y → z
        for axis, ang in zip(('x', 'y', 'z'), rot):
            if abs(ang) < 1e-9:
                continue
            if axis == 'x':
                p = rot_x(p, ang, origin)
            elif axis == 'y':
                p = rot_y(p, ang, origin)
            else:
                a = math.radians(ang)
                c, s = math.cos(a), math.sin(a)
                x, y, z = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
                p = (x * c - y * s + origin[0], x * s + y * c + origin[1], z + origin[2])
        return p
    a = rot.get('angle', 0)
    axis = rot.get('axis', 'x')
    origin = rot.get('origin', [8, 8, 8])
    if a == 0:
        return p
    if axis == 'x':
        return rot_x(p, a, origin)
    if axis == 'y':
        return rot_y(p, a, origin)
    # z
    ar = math.radians(a)
    c, s = math.cos(ar), math.sin(ar)
    x, y, z = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
    return (x * c - y * s + origin[0], x * s + y * c + origin[1], z + origin[2])


def corners(model):
    pts = []
    for e in model.get('elements', []):
        f, t = e['from'], e['to']
        rot = e.get('rotation')
        origin = e.get('origin')
        for dx in (f[0], t[0]):
            for dy in (f[1], t[1]):
                for dz in (f[2], t[2]):
                    p = (dx, dy, dz)
                    if rot:
                        p = apply_rotation(p, rot, origin)
                    pts.append(p)
    return pts


def project_iso(p):
    """MC GUI 等轴测正交投影, camera rotation [30,225,0]:
    屏幕 x 向右, y 向下 (MC 屏幕坐标)。225° yaw 让相机从 north(-Z) 侧看,
    看到模型正面 (家具正面画在 north 面) 与 east(+X) 侧面:
      sx = (x + z) * cos(45)
      sy = -(y * cos(30) - ((x - z) / sqrt2) * sin(30))   # y 轴取反 (MC 屏幕向下)"""
    sx = (p[0] + p[2]) * math.cos(math.radians(45))
    sy = -(p[1] * math.cos(math.radians(30)) - ((p[0] - p[2]) / math.sqrt(2)) * math.sin(math.radians(30)))
    return (sx, sy)


def measure(model, scale=1.0, ty=0.0):
    pts = [project_iso(p) for p in corners(model)]
    # 应用 scale/translation
    xs = [p[0] * scale for p in pts]
    ys = [p[1] * scale - ty for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    return {
        'w': w, 'h': h,
        'center': (cx, cy),
        'bounds': (x0, y0, x1, y1),
        # 图标格 16x16 有效区 (留 12% 边距=14.1)
        'optimal_scale': round(14.1 / max(w, h), 4) if max(w, h) > 0 else 1.0,
        # 【实测校准】scale ×1.022 补偿 (from 纺车实测 0.5807→0.5938)
        'recommended_scale': round(14.1 / max(w, h) * 1.022, 4) if max(w, h) > 0 else 0.625,
        # ty is positive-up while projected screen Y is positive-down; use the
        # visible-alpha centering pipeline for final placement, not box bounds.
        # 实测基准: 同类扁平模型 (wooden_stool=+0.3, firewood_bundle=+0.6) 均远小于居中值,
        # 视觉对齐以同类模型实测点为准, 勿直接套用居中公式。
        'recommended_ty': round(cy - 8, 3),  # center projected box on the GUI cell's y=8 line
    }


if __name__ == '__main__':
    model = load(sys.argv[1])
    scale = float(sys.argv[sys.argv.index('--scale') + 1]) if '--scale' in sys.argv else 1.0
    ty = float(sys.argv[sys.argv.index('--ty') + 1]) if '--ty' in sys.argv else 0.0
    r = measure(model, scale, ty)
    print(f'model {sys.argv[1].split("/")[-1]}')
    print(f'  scale={scale} ty={ty}:')
    print(f'  投影边界 w={r["w"]:.2f} h={r["h"]:.2f}')
    print(f'  中心=({r["center"][0]:.2f}, {r["center"][1]:.2f})  图标格中心=(0, 8)')
    print(f'  超格: w>16? {r["w"] > 16}  h>16? {r["h"] > 16}')
    print(f'  最优: scale={r.get("recommended_scale","?")}  ty={r.get("recommended_ty","?")}')
