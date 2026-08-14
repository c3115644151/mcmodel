#!/usr/bin/env python3
"""
参数优化器 - 根据用户需求(最大box数/最大空气率)自动计算碰撞箱参数。

职责:
- 扫描不同的斜面分段数(1-8), 计算每个方案的 (box数, 空气率)
- 按用户约束选择最优: --max-boxes N 或 --max-air P%
- 返回满足需求的 box 列表 + 实际 box 数 + 空气率

用法:
    python optimize.py <模型文件> --max-boxes 20
    python optimize.py <模型文件> --max-air 15
"""
import argparse
import sys
import os
from parse_model import load_cubes, merge_overlapping_hollow_cubes, all_bounds
from generate import VoxelGrid, compress_voxels, compress_adaptive


def calc_air(grid, origin, w, h, d, res, boxes):
    """计算 box 覆盖 vs 真实占据 的空气率。
    用 box 体积估算(每个 box 的体素体积 - 真实占据体积), 避免逐体素标记。"""
    true_vol = sum(1 for x in range(w) for y in range(h) for z in range(d) if grid[x][y][z])
    box_vol = 0
    for b in boxes:
        x0 = int(b[0] * res - origin[0]); y0 = int(b[1] * res - origin[1]); z0 = int(b[2] * res - origin[2])
        x1 = int(b[3] * res - origin[0]); y1 = int(b[4] * res - origin[1]); z1 = int(b[5] * res - origin[2])
        box_vol += max(0, x1 - x0) * max(0, y1 - y0) * max(0, z1 - z0)
    if box_vol == 0:
        return 0.0
    return (box_vol - true_vol) / box_vol * 100


def scan_options(cubes, res=8):
    """扫描不同分段数, 返回 [(seg_count, boxes, box_count, air_rate), ...]
    用 res=8 扫描(快), 真实体积只算一次。"""
    # 预计算真实占据体积(一次)
    vg = VoxelGrid(res)
    grid, origin, (w, h, d) = vg.build_grid(cubes)
    true_vol = sum(1 for x in range(w) for y in range(h) for z in range(d) if grid[x][y][z])
    options = []
    for seg in range(1, 9):
        boxes = compress_adaptive(cubes, res=res, seg_count=seg)
        box_vol = _box_vol(boxes, res, origin)
        air = (box_vol - true_vol) / box_vol * 100 if box_vol else 0
        options.append((seg, boxes, len(boxes), air))
    return options


def _box_vol(boxes, res, origin):
    """box 列表的总体积(体素)。"""
    total = 0
    for b in boxes:
        x0 = int(b[0] * res - origin[0]); y0 = int(b[1] * res - origin[1]); z0 = int(b[2] * res - origin[2])
        x1 = int(b[3] * res - origin[0]); y1 = int(b[4] * res - origin[1]); z1 = int(b[5] * res - origin[2])
        total += max(0, x1 - x0) * max(0, y1 - y0) * max(0, z1 - z0)
    return total


def choose_option(options, max_boxes=None, max_air=None):
    """按约束选最优方案。约束二选一, 都给了则同时满足。"""
    if max_boxes and max_air:
        cand = [o for o in options if o[2] <= max_boxes and o[3] <= max_air]
    elif max_boxes:
        cand = [o for o in options if o[2] <= max_boxes]
    elif max_air:
        cand = [o for o in options if o[3] <= max_air]
    else:
        cand = options
    if not cand:
        # 无满足项: 返回最接近的(空气率最低的, 若 max_boxes 则 box 最少的)
        if max_boxes:
            return min(options, key=lambda o: abs(o[2] - max_boxes))
        return min(options, key=lambda o: o[3])
    # 选 box 最少(满足约束下)
    return min(cand, key=lambda o: o[2])


def main():
    ap = argparse.ArgumentParser(description='碰撞箱参数优化器')
    ap.add_argument('model', help='bbmodel 或 model JSON 路径')
    ap.add_argument('--max-boxes', type=int, default=None, help='最大 box 数')
    ap.add_argument('--max-air', type=float, default=None, help='最大空气率(%)')
    ap.add_argument('--res', type=int, default=16, help='体素分辨率')
    args = ap.parse_args()

    cubes = load_cubes(args.model)
    cubes = merge_overlapping_hollow_cubes(cubes)
    # 扫描用 res=8(快), 精确输出用 args.res
    options = scan_options(cubes, 8)
    seg, boxes, nb, air = choose_option(options, args.max_boxes, args.max_air)

    print(f"=== 参数优化结果 ===")
    print(f"斜面分段数: {seg}")
    print(f"box 数: {nb} (约束: max_boxes={args.max_boxes}, max_air={args.max_air})")
    print(f"空气率: {air:.1f}%")
    print(f"\n可用方案扫描:")
    for s, b, n, a in options:
        mark = ' ← 选中' if s == seg else ''
        print(f"  分段{s}: {n} box, 空气 {a:.1f}%{mark}")
    from generate import to_java, format_boxlist
    print(f"\n=== box 列表 ===")
    print(format_boxlist(boxes))
    print(f"\n=== Java 代码 ===")
    print(to_java(boxes))


if __name__ == '__main__':
    main()
