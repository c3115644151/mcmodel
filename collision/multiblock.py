#!/usr/bin/env python3
"""
多方块切割 - 把跨格模型的碰撞箱按格子边界切割，每格输出独立碰撞箱(局部坐标)。

原理:
MC 一个方块的碰撞箱必须在该方块内(坐标 0-16)。
跨格模型(如长桌桌面跨越两格)的碰撞 box 需沿格子边界切割，
每格分到属于自己的 box 段，并转换为该格原点的局部坐标。

格子定义: --grid 参数指定每个轴上的切割边界。
例如 --grid x:0  表示 x 方向在 0 处切(左半 -16..0, 右半 0..16)
     --grid x:-8,8 表示 x 方向切 3 格(边界 -8, 8)
格子原点: 最左格原点 = 模型轴最小值; 后续格原点 = 上一个切割点。
"""
import argparse
from parse_model import load_cubes, cube_aabb, all_bounds
from generate import VoxelGrid, compress_voxels, to_java, format_boxlist


def auto_detect_grid(cubes):
    """
    自动检测多方块网格。基于几何: 每轴跨度/16 得到格子数, 中心对齐到 8 的倍数。
    返回 {axis: [切割坐标]}, 无跨格轴返回空。
    """
    bx = all_bounds(cubes)
    axes_bounds = {
        'x': (bx[0], bx[3]),
        'y': (bx[1], bx[4]),
        'z': (bx[2], bx[5]),
    }
    grid = {}
    for axis, (lo, hi) in axes_bounds.items():
        span = hi - lo
        n = round(span / 16)  # 格子数
        if n <= 1:
            continue  # 单格
        center = (lo + hi) / 2
        # 中心对齐到最近的 8 倍数 (格中心坐标序列: ...-24,-8,8,24...)
        # 但偶数格时中心在边界(0, 16...), 需单独处理
        # 先求格中心序列: n 个格中心, 以离 center 最近的合法格中心对齐
        # 合法格中心 = 8 + 16k (格中心坐标是 ...-8, 8, 24... 即 8 的奇数倍)
        # 格中心序列:
        if n % 2 == 1:
            # 奇数格: 中间格中心 = center 对齐到最近的 (8 + 16k)
            mid_center = 8 + 16 * round((center - 8) / 16)
            centers = [mid_center + (i - n // 2) * 16 for i in range(n)]
        else:
            # 偶数格: 格子边界落在 center 附近(整数格), 格中心在边界两侧
            # center 应对齐到最近的 16 倍数(边界), 格中心在其两侧
            edge = 16 * round(center / 16)  # 最近的边界
            centers = [edge + 8 + (i - n // 2) * 16 for i in range(n)]
        # 格子边界 = 相邻格中心的中点
        cuts = []
        for i in range(len(centers) - 1):
            cuts.append((centers[i] + centers[i + 1]) / 2)
        grid[axis] = cuts
    return grid


def parse_grid(specs):
    """解析 'x:0,-8' 等网格边界。返回 {axis: [切割坐标列表]}"""
    grid = {}
    for spec in specs:
        axis, _, coords = spec.partition(':')
        axis = axis.strip().lower()
        if axis not in ('x', 'y', 'z'):
            raise ValueError(f"无效轴: {axis} (需 x/y/z)")
        cuts = [float(c.strip()) for c in coords.split(',') if c.strip()]
        grid[axis] = sorted(cuts)
    return grid


def compute_cell_origins(grid, model_min, model_max):
    """
    计算每个格子在该轴上的原点(格子局部坐标 0 对应模型坐标)。
    返回 {axis: [origins]}，origins[i] 是第 i 格的原点。
    """
    origins = {}
    for axis in ('x', 'y', 'z'):
        cuts = grid.get(axis, [])
        mn = model_min[axis]
        if not cuts:
            origins[axis] = [mn]  # 单格, 原点 = 模型最小值
            continue
        # 格子边界序列: [mn, cuts[0], cuts[1], ..., cuts[-1], mx]
        bounds = [mn] + cuts
        # 每个格子的原点 = 该格下界
        origins[axis] = bounds
    return origins


def split_box_by_axis(box, axis, cuts):
    """把 box 沿某轴切分，返回 [(box段, 格子索引)]。索引从 0 开始。"""
    x0, y0, z0, x1, y1, z1 = box
    lo, hi = (x0, x1) if axis == 'x' else ((y0, y1) if axis == 'y' else (z0, z1))
    if lo > hi:
        lo, hi = hi, lo
    inside_cuts = [c for c in cuts if lo < c < hi]
    if not inside_cuts:
        idx = _cell_index(lo, hi, cuts)
        return [(box, idx)]
    bounds = [lo] + inside_cuts + [hi]
    results = []
    for i in range(len(bounds) - 1):
        seg_lo, seg_hi = bounds[i], bounds[i + 1]
        idx = _cell_index(seg_lo, seg_hi, cuts)
        if axis == 'x':
            results.append(((seg_lo, y0, z0, seg_hi, y1, z1), idx))
        elif axis == 'y':
            results.append(((x0, seg_lo, z0, x1, seg_hi, z1), idx))
        else:
            results.append(((x0, y0, seg_lo, x1, y1, seg_hi), idx))
    return results


def _cell_index(lo, hi, cuts):
    mid = (lo + hi) / 2
    idx = 0
    for c in cuts:
        if mid > c:
            idx += 1
        else:
            break
    return idx


def split_all_boxes(boxes, grid):
    """对所有 box 沿各轴切割。返回 {格子key(x,y,z): [box(模型坐标)]}"""
    cells = {(0, 0, 0): boxes}
    for axis, cuts in grid.items():
        if not cuts:
            continue
        new_cells = {}
        for cell_key, cell_boxes in cells.items():
            for box in cell_boxes:
                for seg, seg_idx in split_box_by_axis(box, axis, cuts):
                    axis_pos = {'x': 0, 'y': 1, 'z': 2}[axis]
                    new_key = list(cell_key)
                    new_key[axis_pos] = seg_idx
                    new_cells.setdefault(tuple(new_key), []).append(seg)
        cells = new_cells
    return cells


def to_local(box, origins, grid):
    """把 box 从模型坐标转为格子局部坐标(格原点为 0)。"""
    x0, y0, z0, x1, y1, z1 = box
    cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
    ox = _origin_for(cx, origins['x'], grid.get('x', []))
    oy = _origin_for(cy, origins['y'], grid.get('y', []))
    oz = _origin_for(cz, origins['z'], grid.get('z', []))
    return (x0 - ox, y0 - oy, z0 - oz, x1 - ox, y1 - oy, z1 - oz)


def _origin_for(coord, origins, cuts):
    """坐标 coord 所在格子的原点"""
    idx = 0
    for c in cuts:
        if coord > c:
            idx += 1
        else:
            break
    # origins 长度 = 格子数 = len(cuts)+1
    idx = min(idx, len(origins) - 1)
    return origins[idx]


def main():
    ap = argparse.ArgumentParser(description='多方块碰撞切割')
    ap.add_argument('model')
    ap.add_argument('--grid', action='append', default=[], help='格子边界, 如 x:0 或 x:-8,8')
    ap.add_argument('--res', type=int, default=16)
    ap.add_argument('--exclude', default='')
    args = ap.parse_args()

    cubes = load_cubes(args.model)
    if args.exclude:
        ex = set(n.strip() for n in args.exclude.split(',') if n.strip())
        cubes = [c for c in cubes if c['name'] not in ex]

    # 自动检测网格 (若未手动指定)
    if args.grid:
        grid = parse_grid(args.grid)
        print(f"[网格] 手动指定: {grid}")
    else:
        grid = auto_detect_grid(cubes)
        print(f"[网格] 自动检测: {grid}")

    # 模型范围
    from parse_model import cube_aabb, all_bounds
    bx = all_bounds(cubes)
    model_min = {'x': bx[0], 'y': bx[1], 'z': bx[2]}
    model_max = {'x': bx[3], 'y': bx[4], 'z': bx[5]}
    origins = compute_cell_origins(grid, model_min, model_max)

    vg = VoxelGrid(args.res)
    grid_vox, origin, (w, h, d) = vg.build_grid(cubes)
    boxes = compress_voxels(grid_vox, origin, w, h, d, args.res)

    cells = split_all_boxes(boxes, grid)
    print(f"=== 多方块切割结果 (共 {len(boxes)} box -> {len(cells)} 格) ===")
    print(f"模型范围: x{model_min['x']:.0f}-{model_max['x']:.0f} y{model_min['y']:.0f}-{model_max['y']:.0f} z{model_min['z']:.0f}-{model_max['z']:.0f}")
    print(f"格子原点: {origins}")
    for key in sorted(cells.keys()):
        cell_boxes = cells[key]
        local = [to_local(b, origins, grid) for b in cell_boxes]
        print(f"\n格子 {key}: {len(cell_boxes)} box (局部坐标)")
        print(format_boxlist(local))
        print("Java:")
        print(to_java(local))


if __name__ == '__main__':
    main()
