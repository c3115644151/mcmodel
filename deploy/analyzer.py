#!/usr/bin/env python3
"""
模型分析器 - 自动分类模型类型，零参数智能决策的核心。

判断:
- single:       单格方块 (所有元素在 0~16 内)
- multiblock:   多方块 (元素跨出 0~16, 需 N×M 格)
- variant:      多变体 (检测同目录下 name_0..N 的文件序列)
- has_rotation: 含旋转元素 (需外接盒碰撞箱)

返回 ModelAnalysis, 供 pipeline 选择 codegen 模板和验证器集。
"""
import os
import json
import math


def load_model(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def element_bounds(e):
    """元素 AABB, 含旋转角点外接盒"""
    frm = [float(x) for x in e.get('from', [0, 0, 0])]
    to = [float(x) for x in e.get('to', [16, 16, 16])]
    rot = e.get('rotation')
    if rot and isinstance(rot, dict):
        angle = float(rot.get('angle', 0))
        if abs(angle) > 0.01:
            axis = rot.get('axis', 'y')
            origin = [float(x) for x in rot.get('origin', [8, 8, 8])]
            corners = []
            for x in (frm[0], to[0]):
                for y in (frm[1], to[1]):
                    for z in (frm[2], to[2]):
                        corners.append(rotate_point([x, y, z], angle, axis, origin))
            xs = [c[0] for c in corners]; ys = [c[1] for c in corners]; zs = [c[2] for c in corners]
            return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    return [min(frm[0], to[0]), min(frm[1], to[1]), min(frm[2], to[2]),
            max(frm[0], to[0]), max(frm[1], to[1]), max(frm[2], to[2])]


def rotate_point(p, angle_deg, axis, origin):
    x, y, z = p[0]-origin[0], p[1]-origin[1], p[2]-origin[2]
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    if axis == 'x':
        y, z = y*c - z*s, y*s + z*c
    elif axis == 'z':
        x, y = x*c - y*s, x*s + y*c
    else:  # y
        x, z = x*c + z*s, -x*s + z*c
    return [x+origin[0], y+origin[1], z+origin[2]]


def detect_variants(path):
    """检测同目录下的变体序列 (name_0.json, name_1.json ...)。
    返回变体数量(含基模型), 非多变体返回 1。"""
    d = os.path.dirname(path)
    base = os.path.splitext(os.path.basename(path))[0]
    # 已经是 name_N 形式, 向上找基名
    if '_' in base:
        prefix = base.rsplit('_', 1)[0]
        if prefix:
            count = count_variant_files(d, prefix)
            if count > 1:
                return count, prefix
    count = count_variant_files(d, base)
    return (count if count > 1 else 1), base


def count_variant_files(d, base):
    """统计 base.json + base_N.json 数量。
    同时支持两种命名: 基文件是 level0 (base.json + base_1..N)
    或基文件本身是变体之一 (base_0..N)。"""
    n = 0
    if os.path.exists(os.path.join(d, base + '.json')):
        n += 1
    i = 1  # base_1, base_2, ...
    while os.path.exists(os.path.join(d, f'{base}_{i}.json')):
        n += 1; i += 1
    # 如果没有 base.json 但有 base_0.json, 从 0 开始数
    if n == 0:
        i = 0
        while os.path.exists(os.path.join(d, f'{base}_{i}.json')):
            n += 1; i += 1
    return n


def analyze(path):
    """分析模型, 返回 ModelAnalysis dict"""
    model = load_model(path)
    elements = model.get('elements', [])

    # 所有元素的总体包围盒
    all_b = [element_bounds(e) for e in elements]
    if all_b:
        x0 = min(b[0] for b in all_b); y0 = min(b[1] for b in all_b)
        z0 = min(b[2] for b in all_b); x1 = max(b[3] for b in all_b)
        y1 = max(b[4] for b in all_b); z1 = max(b[5] for b in all_b)
    else:
        x0, y0, z0, x1, y1, z1 = 0, 0, 0, 16, 16, 16

    has_rotation = any(
        e.get('rotation') and isinstance(e['rotation'], dict)
        and abs(float(e['rotation'].get('angle', 0))) > 0.01
        for e in elements
    )

    # 跨格判断: 只有 x 或 z 方向超出 0~16 才算真多方块。
    # y 方向超出 16 是"高单格模型"(如高背椅/木桶, 单格放置但模型向上延伸), 不算多方块。
    spans_cells = (x0 < -0.01 or x1 > 16.01 or z0 < -0.01 or z1 > 16.01)

    variant_count, base_name = detect_variants(path)

    if spans_cells:
        kind = 'multiblock'
        # 格子尺寸 (y 按实际跨格算, 用于碰撞箱切割)
        cells_x = int(math.ceil(x1 / 16)) - int(math.floor(x0 / 16))
        cells_y = int(math.ceil(y1 / 16)) - int(math.floor(y0 / 16))
        cells_z = int(math.ceil(z1 / 16)) - int(math.floor(z0 / 16))
    else:
        kind = 'variant' if variant_count > 1 else 'single'
        cells_x = cells_y = cells_z = 1

    return {
        'path': os.path.abspath(path),
        'kind': kind,
        'base_name': base_name,
        'elements': len(elements),
        'bounds': [x0, y0, z0, x1, y1, z1],
        'cells': [cells_x, cells_y, cells_z],
        'has_rotation': has_rotation,
        'variant_count': variant_count,
        'texture_size': model.get('texture_size'),
        'resolution': model.get('resolution', {'width': 16, 'height': 16}),
        'has_parent': bool(model.get('parent')),
        'has_gui': bool(model.get('display', {}).get('gui')),
    }


def format_analysis(a):
    lines = [f"模型: {os.path.basename(a['path'])}"]
    cells = a['cells']
    kind_name = {'single': '单格方块', 'multiblock': f'多方块 {cells[0]}×{cells[1]}×{cells[2]}',
                 'variant': f'多变体 ×{a["variant_count"]}'}[a['kind']]
    lines.append(f"类型: {kind_name}")
    b = a['bounds']
    lines.append(f"包围盒: x[{b[0]:.1f},{b[3]:.1f}] y[{b[1]:.1f},{b[4]:.1f}] z[{b[2]:.1f},{b[5]:.1f}]")
    lines.append(f"元素: {a['elements']}, 旋转: {'是' if a['has_rotation'] else '否'}, 变体: {a['variant_count']}")
    flags = []
    if not a['has_parent']: flags.append('缺parent')
    if a['texture_size']: flags.append(f"texture_size={a['texture_size']}")
    if not a['has_gui']: flags.append('缺gui视角')
    if flags:
        lines.append(f"待处理: {', '.join(flags)}")
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else 'model.json'
    a = analyze(p)
    print(format_analysis(a))
