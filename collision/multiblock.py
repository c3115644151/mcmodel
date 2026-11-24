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
import math
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
        # Use the occupied Minecraft cells rather than rounding the visual span.
        # A model from -10 to 26 touches three cells (-16..0, 0..16, 16..32),
        # even though its span is only 36 model units.
        import math
        first_cell = math.floor(lo / 16.0)
        last_cell = math.floor((hi - 1.0e-6) / 16.0)
        if last_cell <= first_cell:
            continue
        grid[axis] = [16.0 * cell for cell in range(first_cell + 1, last_cell + 1)]
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
            # 该轴单格: 原点对齐 MC 方块局部 0, 不是模型 AABB min
            origins[axis] = [0.0]
            continue
        import math
        cell0 = 16.0 * math.floor(mn / 16.0)
        origins[axis] = [cell0] + [float(c) for c in cuts]
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
    # MC VoxelShape 必须在该格 0~16。切割浮点误差/跨格外接可能略超, clamp。
    def clamp16(v):
        return max(0.0, min(16.0, v))
    return (
        clamp16(x0 - ox), clamp16(y0 - oy), clamp16(z0 - oz),
        clamp16(x1 - ox), clamp16(y1 - oy), clamp16(z1 - oz),
    )


def measure_cell_coverage(cubes, cells, grid, resolution=8):
    """Measure collision air/misses independently inside each model grid cell.

    Whole-structure air ratios are misleading for sparse furniture because they
    count every empty space between legs, boards and roofs. This metric clips
    both rendered occupancy and collision boxes to each cell before comparing.
    Rotated elements use the same inverse-rotation voxel rasterizer as the main
    collision audit.
    """
    from generate import VoxelGrid
    from optimize import build_collision_reference_grid, metric_resolution
    from parse_model import all_bounds

    if not cubes:
        return {}
    bounds = all_bounds(cubes)
    cell_res = metric_resolution(cubes, resolution)
    model_grid, voxel_origin, dims = build_collision_reference_grid(cubes, cell_res)
    min_cell = tuple(math.floor(bounds[axis] / 16.0) for axis in range(3))
    split_axes = {"xyz".index(axis) for axis, cuts in grid.items() if cuts}
    measurements = {}
    for key, boxes in cells.items():
        cell_origin = tuple((min_cell[axis] + key[axis]) * 16.0 if axis in split_axes else 0.0
                            for axis in range(3))
        starts = [max(0, math.floor(cell_origin[axis] * cell_res) - voxel_origin[axis])
                  for axis in range(3)]
        ends = [min(dims[axis], math.ceil((cell_origin[axis] + 16.0) * cell_res) - voxel_origin[axis])
                for axis in range(3)]
        rendered = collided = overlap = false_positive = false_negative = 0
        for ix in range(starts[0], ends[0]):
            lx = (ix + voxel_origin[0] + 0.5) / cell_res - cell_origin[0]
            for iy in range(starts[1], ends[1]):
                ly = (iy + voxel_origin[1] + 0.5) / cell_res - cell_origin[1]
                for iz in range(starts[2], ends[2]):
                    lz = (iz + voxel_origin[2] + 0.5) / cell_res - cell_origin[2]
                    in_model = bool(model_grid[ix][iy][iz])
                    in_shape = any(box[0] <= lx < box[3] and box[1] <= ly < box[4]
                                   and box[2] <= lz < box[5] for box in boxes)
                    rendered += in_model
                    collided += in_shape
                    overlap += in_model and in_shape
                    false_positive += in_shape and not in_model
                    false_negative += in_model and not in_shape
        pct = lambda count, total: (100.0 * count / total) if total else 0.0
        measurements[key] = {
            "air_percent": pct(false_positive, rendered),
            "miss_percent": pct(false_negative, rendered),
            "precision_percent": pct(overlap, collided),
            "render_voxels": rendered,
            "collision_voxels": collided,
            "air_voxels": false_positive,
            "miss_voxels": false_negative,
            "resolution": cell_res,
        }
    return measurements


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
