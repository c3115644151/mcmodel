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
import math
from parse_model import load_cubes, merge_overlapping_hollow_cubes, all_bounds, filter_collision_cubes
from generate import VoxelGrid, compress_voxels, compress_adaptive, ensure_collidable_boxes


def calc_metrics(grid, origin, w, h, d, res, boxes):
    """逐体素比较几何与碰撞，空气误占和漏碰独立计数。

    采样点取体素中心；扫描范围包含几何和碰撞箱的并集，因而不会漏掉
    模型边界外的碰撞，也不会让多占空气与漏掉模型互相抵消。
    """
    gx0, gy0, gz0 = origin
    gx1, gy1, gz1 = gx0 + w, gy0 + h, gz0 + d
    bx0 = min((math.floor(b[0] * res) for b in boxes), default=gx0)
    by0 = min((math.floor(b[1] * res) for b in boxes), default=gy0)
    bz0 = min((math.floor(b[2] * res) for b in boxes), default=gz0)
    bx1 = max((math.ceil(b[3] * res) for b in boxes), default=gx1)
    by1 = max((math.ceil(b[4] * res) for b in boxes), default=gy1)
    bz1 = max((math.ceil(b[5] * res) for b in boxes), default=gz1)
    x0, y0, z0 = min(gx0, bx0), min(gy0, by0), min(gz0, bz0)
    x1, y1, z1 = max(gx1, bx1), max(gy1, by1), max(gz1, bz1)

    nx, ny, nz = x1 - x0, y1 - y0, z1 - z0
    collision = bytearray(nx * ny * nz)
    for box in boxes:
        ix0 = max(x0, math.floor(box[0] * res)); iy0 = max(y0, math.floor(box[1] * res)); iz0 = max(z0, math.floor(box[2] * res))
        ix1 = min(x1, math.ceil(box[3] * res)); iy1 = min(y1, math.ceil(box[4] * res)); iz1 = min(z1, math.ceil(box[5] * res))
        for ix in range(ix0, ix1):
            base_x = (ix - x0) * ny * nz
            for iy in range(iy0, iy1):
                base_y = base_x + (iy - y0) * nz
                for iz in range(iz0, iz1):
                    collision[base_y + iz - z0] = 1

    rendered = collided = overlap = false_positive = false_negative = 0
    for ix in range(x0, x1):
        for iy in range(y0, y1):
            for iz in range(z0, z1):
                idx = ((ix - x0) * ny + iy - y0) * nz + iz - z0
                in_box = collision[idx] != 0
                inside_grid = gx0 <= ix < gx1 and gy0 <= iy < gy1 and gz0 <= iz < gz1
                in_geom = inside_grid and grid[ix - gx0][iy - gy0][iz - gz0]
                rendered += bool(in_geom)
                collided += in_box
                overlap += bool(in_geom and in_box)
                false_positive += bool(in_box and not in_geom)
                false_negative += bool(in_geom and not in_box)

    pct = lambda n, total: (n / total * 100) if total else 0.0
    return {
        'air_percent': pct(false_positive, rendered),
        'miss_percent': pct(false_negative, rendered),
        'coverage_percent': pct(overlap, rendered),
        'precision_percent': pct(overlap, collided),
        'render_voxels': rendered,
        'collision_voxels': collided,
        'air_voxels': false_positive,
        'miss_voxels': false_negative,
    }


def calc_air(grid, origin, w, h, d, res, boxes):
    """兼容旧调用：返回独立计算的空气误占率。"""
    return calc_metrics(grid, origin, w, h, d, res, boxes)['air_percent']


def metric_resolution(cubes, requested_res, max_voxels=2_000_000):
    """Choose a bounded evaluation resolution without changing generated boxes."""
    from parse_model import cube_aabb
    if not cubes:
        return requested_res
    bounds = [cube_aabb(cube) for cube in cubes]
    extents = [max(b[i + 3] for b in bounds) - min(b[i] for b in bounds) for i in range(3)]
    volume = max(1.0, extents[0] * extents[1] * extents[2])
    bounded = max(1, int((max_voxels / volume) ** (1.0 / 3.0)))
    return min(requested_res, bounded)


def build_collision_reference_grid(cubes, res):
    """Rasterize positive-volume source cuboids; ignore missing texture faces.

    Rotated elements are sampled in their actual orientation so the measured
    air-exposure rate reflects the single-AABB approximation instead of comparing
    the generated AABB against itself.
    """
    if not cubes:
        return [], (0, 0, 0), (0, 0, 0)
    from generate import VoxelGrid
    face = {"texture": "#collision_geometry", "uv": [0, 0, 1, 1]}
    solid_cubes = []
    for cube in cubes:
        solid = dict(cube)
        solid["faces"] = {direction: face for direction in
                          ("north", "east", "south", "west", "up", "down")}
        solid_cubes.append(solid)
    return VoxelGrid(res).build_grid(solid_cubes)


def solve_zero_exposure(cubes, res=16, seg_count=6, source=None):
    """Compatibility entry point: generate full element AABBs and measure coverage.

    Faces and UV transparency describe rendering, not player occupancy. Positive-
    volume shells and tilted elements therefore use their full (rotated) source
    bounds; zero-volume planes are filtered by the caller by default.
    """
    from generate import ensure_collidable_boxes, merge_exact_union_boxes
    from parse_model import cube_aabb
    boxes = merge_exact_union_boxes([cube_aabb(cube) for cube in cubes])
    boxes = ensure_collidable_boxes(boxes)
    metric_res = metric_resolution(cubes, res)
    grid, origin, dims = build_collision_reference_grid(cubes, metric_res)
    air = calc_metrics(grid, origin, *dims, metric_res, boxes)['air_percent'] if cubes else 0.0
    return boxes, air, len(boxes)


def scan_options(cubes, res=8, include_thin=False):
    """Return the single standard full-AABB plan and its volume metrics."""
    eval_res = metric_resolution(cubes, res)
    grid, origin, dims = build_collision_reference_grid(cubes, eval_res)
    main, _rotated = compress_adaptive(cubes, res=res, skip_rotated_decor=False,
                                       include_thin=include_thin)
    main = ensure_collidable_boxes(main)
    return [(1, main, len(main), calc_air(grid, origin, *dims, eval_res, main))]


def _box_vol(boxes, res, origin):
    """box 列表的总体积(体素)。(遗留函数, 保留兼容)"""
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
    ap.add_argument('--include-thin', action='store_true', help='显式纳入薄片/零厚度元素')
    ap.add_argument('--exclude-shells', action='store_false', dest='include_shells', default=True,
                    help='显式排除开口面壳 (默认按完整 AABB 碰撞)')
    ap.add_argument('--exclude-rotated', action='store_false', dest='include_rotated', default=True,
                    help='显式排除斜体 (默认每个正体积斜体使用一个 AABB)')
    args = ap.parse_args()

    cubes = load_cubes(args.model)
    cubes, skipped = filter_collision_cubes(
        cubes, include_thin=args.include_thin,
        include_shells=args.include_shells, include_rotated=args.include_rotated)
    for cube, reasons in skipped:
        print(f"[默认视觉件不碰撞] #{cube['index']} {cube['name']}: {', '.join(reasons)}")
    cubes = merge_overlapping_hollow_cubes(cubes)
    # 扫描用 res=8(快), 精确输出用 args.res
    options = scan_options(cubes, 8, include_thin=args.include_thin)
    seg, boxes, nb, air = choose_option(options, args.max_boxes, args.max_air)

    print(f"=== 参数优化结果 ===")
    print("碰撞方案: 每个正体积模型元素使用完整 AABB")
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
