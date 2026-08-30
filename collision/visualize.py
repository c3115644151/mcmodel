#!/usr/bin/env python3
"""
碰撞箱可视化 - 三视图叠加 (模型 vs 碰撞箱)
  '#' = 模型元素   '@' = 碰撞箱   '*' = 重叠   '.' = 空

用法:
    python visualize.py <模型文件> --boxes "x0,y0,z0,x1,y1,z1;..."
    python visualize.py <模型文件> --boxes-file out.txt
"""
import sys
import argparse
from parse_model import load_cubes, cube_aabb


def aabb(c):
    """cube 或 box 元组 -> (x0,y0,z0,x1,y1,z1)"""
    if isinstance(c, dict):
        return cube_aabb(c)
    return c


def model_bounds(cubes):
    xs, ys, zs = [], [], []
    for c in cubes:
        x0, y0, z0, x1, y1, z1 = aabb(c)
        xs += [x0, x1]; ys += [y0, y1]; zs += [z0, z1]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def parse_boxes(s):
    if not s:
        return []
    out = []
    for part in s.split(';'):
        if part.strip():
            v = [float(x) for x in part.strip().split(',')]
            if len(v) == 6:
                out.append(tuple(v))
    return out


def render_plane(cubes, boxes, res, axis_h, axis_v):
    """按两个轴投影。axis_h/axis_v 是 (0,1,2) 之一 (0=x,1=y,2=z)"""
    bx = model_bounds(cubes)
    lo = [bx[0], bx[1], bx[2]]
    hi = [bx[3], bx[4], bx[5]]
    hmin, hmax = lo[axis_h], hi[axis_h]
    vmin, vmax = lo[axis_v], hi[axis_v]

    hcells = int(round((hmax - hmin) * res))
    vcells = int(round((vmax - vmin) * res))
    # grid[v][h] 0=空 1=模型 2=碰撞 3=both
    gh = [[0] * (hcells + 1) for _ in range(vcells + 1)]

    def to_cell(val, mn, cells):
        idx = int(round((val - mn) * res))
        return max(0, min(cells, idx))

    def fill(a, flag):
        x0, y0, z0, x1, y1, z1 = a
        p = [x0, y0, z0]; q = [x1, y1, z1]
        h0, h1 = p[axis_h], q[axis_h]
        v0, v1 = p[axis_v], q[axis_v]
        if h0 > h1: h0, h1 = h1, h0
        if v0 > v1: v0, v1 = v1, v0
        for vi in range(to_cell(v0, vmin, vcells), to_cell(v1, vmin, vcells) + 1):
            for hi in range(to_cell(h0, hmin, hcells), to_cell(h1, hmin, hcells) + 1):
                gh[vi][hi] |= flag

    for c in cubes:
        fill(aabb(c), 1)
    for b in boxes:
        fill(b, 2)
    return gh, hmin, vmin, res


def print_plane(gh, hmin, vmin, res, hlabel, vlabel):
    # 打印横向轴刻度 (稀疏)
    print(f"    ", end='')
    for hi in range(len(gh[0])):
        if hi % 2 == 0:
            val = hmin + hi / res
            if abs(val - round(val)) < 0.01:
                print(f"{int(round(val)):>3}", end='')
            else:
                print(f"{val:>5.1f}", end='')
        else:
            print("   ", end='')
    print()
    for vi in range(len(gh) - 1, -1, -1):
        vval = vmin + vi / res
        if abs(vval - round(vval)) < 0.01:
            label = f"{int(round(vval)):>4}"
        else:
            label = f"{vval:>4.1f}"
        print(f"{label} ", end='')
        for hi in range(len(gh[0])):
            v = gh[vi][hi]
            print('#' if v == 1 else ('@' if v == 2 else ('*' if v == 3 else '.')), end='')
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('model')
    ap.add_argument('--boxes', default='')
    ap.add_argument('--res', type=int, default=2)
    args = ap.parse_args()
    cubes = load_cubes(args.model)
    boxes = parse_boxes(args.boxes)

    views = [
        ("前视图 XY (从南看)", 0, 1, 'x', 'y'),  # x横 y纵
        ("侧视图 YZ (从东看)", 2, 1, 'z', 'y'),  # z横 y纵
        ("俯视图 XZ (从上看)", 0, 2, 'x', 'z'),  # x横 z纵
    ]
    for name, ah, av, hl, vl in views:
        gh, hmin, vmin, res = render_plane(cubes, boxes, args.res, ah, av)
        print(f"=== {name} ===")
        print_plane(gh, hmin, vmin, res, hl, vl)
        print()
    print("图例: #=模型  @=碰撞箱  *=重叠  .=空")


if __name__ == '__main__':
    main()
