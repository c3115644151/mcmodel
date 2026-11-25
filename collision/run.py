#!/usr/bin/env python3
"""
碰撞箱一键生成命令
  python run.py <模型文件> [--res 16] [--exclude "握把,装饰"]
  python run.py <模型文件> [--grid x:0] [--visualize]

流程: 解析 -> 自动检测单/多格 -> 体素化合并(多格则切割) -> 输出 Java 代码 -> 可视化

自动检测: 模型某轴跨度 > 16 单位即判定跨格, 自动推断格子边界。
手动覆盖: --grid x:0 可手动指定切割边界。
"""
import argparse
import sys
import os
from generate import (load_cubes, VoxelGrid, compress_voxels, compress_adaptive,
                      dedupe_boxes, merge_exact_union_boxes, to_java, format_boxlist)
from optimize import solve_zero_exposure
from parse_model import all_bounds, cube_aabb, filter_collision_cubes
from visualize import render_plane, print_plane


def to_java_facing(boxes):
    """生成带 FACING 四朝向的完整碰撞箱 Java 模板。
    解决方向变体+碰撞箱不随旋转这一反复出现的问题。
    参照项目 OakHighBackChairBlock/WoodenStoolBlock 的标准写法。"""
    body = to_java(boxes)
    return f'''// 朝北基准碰撞箱 (tools/collision 生成, 斜腿已分段)
private static final VoxelShape SHAPE_BASE = {body};

private static Rotation rotationFor(Direction facing) {{
    return switch (facing) {{
        case EAST -> Rotation.CLOCKWISE_90;
        case SOUTH -> Rotation.CLOCKWISE_180;
        case WEST -> Rotation.COUNTERCLOCKWISE_90;
        default -> Rotation.NONE;
    }};
}}

@Override
protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext ctx) {{
    Rotation rot = rotationFor(state.getValue(FACING));
    return rot == Rotation.NONE ? SHAPE_BASE : Shapes.rotate(SHAPE_BASE, rot.rotation());
}}

@Override
protected VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext ctx) {{
    return getShape(state, level, pos, ctx);
}}'''


SEGMENT_COUNT = 3


def _clip_boxes(boxes, bounds):
    """Clip boxes to {axis: (low, high)} and drop the ones that collapse."""
    out = []
    for box in boxes:
        edges = [float(value) for value in box]
        for axis, (low, high) in bounds.items():
            edges[axis] = max(edges[axis], float(low))
            edges[axis + 3] = min(edges[axis + 3], float(high))
        if all(edges[axis + 3] - edges[axis] > 1e-9 for axis in range(3)):
            out.append(tuple(round(value, 6) for value in edges))
    return out


def clip_cubes_to_bounds(cubes, bounds):
    """Return copies of cubes trimmed to bounds ({axis index: (low, high)}, model px).

    The copies own their from/to lists because the layer audit shifts them in place.
    Clipping a rotated cube clips its box, not its rotated hull: the profile files
    only clip axis-aligned layers, and pretending to reshape a rotated part would
    quietly change what the audit measures.
    """
    out = []
    for cube in cubes:
        trimmed = dict(cube)
        trimmed['from'] = [float(value) for value in cube['from']]
        trimmed['to'] = [float(value) for value in cube['to']]
        trimmed.pop('corners', None)
        keep = True
        for axis, (low, high) in bounds.items():
            forward = trimmed['from'][axis] <= trimmed['to'][axis]
            edges = sorted((trimmed['from'][axis], trimmed['to'][axis]))
            lo, hi = max(edges[0], float(low)), min(edges[1], float(high))
            if hi - lo <= 1e-9:
                keep = False
                break
            trimmed['from'][axis], trimmed['to'][axis] = (lo, hi) if forward else (hi, lo)
        if keep:
            out.append(trimmed)
    return out


def _solid_cube(box):
    """A collision box as a cube whose six faces are opaque, so it fills its voxels.

    VoxelGrid treats a cube with fewer than five textured faces as a hollow shell
    and only marks thin plates; a collision box carries volume, so every face is
    declared.
    """
    return {
        'index': None,
        'name': 'collision',
        'from': [box[0], box[1], box[2]],
        'to': [box[3], box[4], box[5]],
        'rotation': None,
        'faces': {face: {'texture': '#solid', 'uv': [0, 0, 1, 1]}
                  for face in ('north', 'south', 'east', 'west', 'up', 'down')},
    }


def _shared_grids(cube_sets, res):
    """Voxelise several cube lists into one shared voxel frame.

    build_grid derives its origin from the cubes it is handed, so two lists marked
    separately would sit in different frames and their overlap would mean nothing.
    One frame sized by the union keeps the comparison honest.
    """
    aabbs = [cube_aabb(cube) for cubes in cube_sets for cube in cubes]
    if not aabbs:
        return [], (0, 0, 0), (0, 0, 0)
    ox = int(min(aabb[0] for aabb in aabbs) * res)
    oy = int(min(aabb[1] for aabb in aabbs) * res)
    oz = int(min(aabb[2] for aabb in aabbs) * res)
    w = max(1, int(max(aabb[3] for aabb in aabbs) * res) - ox)
    h = max(1, int(max(aabb[4] for aabb in aabbs) * res) - oy)
    d = max(1, int(max(aabb[5] for aabb in aabbs) * res) - oz)
    grids = []
    for cubes in cube_sets:
        grid = [[[False] * d for _ in range(h)] for _ in range(w)]
        voxels = VoxelGrid(res)
        for cube in cubes:
            voxels.mark_cube(cube, grid, ox, oy, oz, w, h, d)
        grids.append(grid)
    return grids, (ox, oy, oz), (w, h, d)


def _limit_to_cell(grids, origin, dims, res):
    """Blank every voxel whose centre falls outside the 0..16 block cell.

    A shape cannot collide outside a block face, and a barrel tilted far enough to
    poke through one is not something the player can walk into. Measuring the whole
    model would report that protrusion as permanent missed collision, so the audit
    compares the part of the model that lives inside the cell.
    """
    ranges = []
    for axis, size in enumerate(dims):
        low = max(0, -origin[axis])
        high = min(size, 16 * res - origin[axis])
        ranges.append((low, high))
    (ix, jx), (iy, jy), (iz, jz) = ranges
    for grid in grids:
        for x in range(dims[0]):
            inside_x = ix <= x < jx
            for y in range(dims[1]):
                line = grid[x][y]
                if not inside_x or not (iy <= y < jy):
                    line[:] = [False] * dims[2]
                    continue
                for z in range(dims[2]):
                    if not (iz <= z < jz):
                        line[z] = False


def _grid_columns(grid, dims):
    """Map each (x, y) column to its filled z spans, so volume work stays cheap."""
    w, h, d = dims
    columns = {}
    for x in range(w):
        for y in range(h):
            line = grid[x][y]
            spans = []
            z = 0
            while z < d:
                if not line[z]:
                    z += 1
                    continue
                start = z
                while z < d and line[z]:
                    z += 1
                spans.append((start, z))
            if spans:
                columns[(x, y)] = spans
    return columns


def _column_volume(columns):
    return sum(high - low for spans in columns.values() for low, high in spans)


def _column_overlap(left, right):
    total = 0
    for key, spans in left.items():
        other = right.get(key)
        if not other:
            continue
        for low, high in spans:
            for other_low, other_high in other:
                shared = min(high, other_high) - max(low, other_low)
                if shared > 0:
                    total += shared
    return total


def measure_collision(cubes, boxes, resolution):
    """Voxel volume of geometry vs collision boxes, at resolution voxels per block pixel.

    air_voxels is collision the model does not fill, miss_voxels is model the
    collision does not cover; the audit rejects a shape with too much of either.

    Both sides are voxelised, so a tilted element counts as the sliver it really is
    instead of its bounding box. Comparing against envelopes instead would punish
    the better shape: a stepped shape that follows a 15 degree tube covers it
    exactly, yet still leaves part of the tube's bounding box uncovered.
    """
    grids, origin, dims = _shared_grids(
        [list(cubes), [_solid_cube(box) for box in boxes]], resolution)
    if not grids:
        return {'render_voxels': 0, 'collision_voxels': 0, 'coverage_voxels': 0,
                'air_voxels': 0, 'miss_voxels': 0, 'air_percent': 0.0,
                'miss_percent': 0.0, 'coverage_percent': 0.0,
                'precision_percent': 0.0, 'resolution': resolution}
    _limit_to_cell(grids, origin, dims, resolution)
    rendered = _grid_columns(grids[0], dims)
    collided = _grid_columns(grids[1], dims)
    render_voxels = _column_volume(rendered)
    collision_voxels = _column_volume(collided)
    overlap = _column_overlap(rendered, collided)
    air_voxels = collision_voxels - overlap
    miss_voxels = render_voxels - overlap
    return {
        'render_voxels': render_voxels,
        'collision_voxels': collision_voxels,
        'coverage_voxels': overlap,
        'air_voxels': air_voxels,
        'miss_voxels': miss_voxels,
        'air_percent': 100.0 * air_voxels / render_voxels if render_voxels else 0.0,
        'miss_percent': 100.0 * miss_voxels / render_voxels if render_voxels else 0.0,
        'coverage_percent': 100.0 * overlap / render_voxels if render_voxels else 0.0,
        'precision_percent': 100.0 * overlap / collision_voxels if collision_voxels else 0.0,
        'resolution': resolution,
    }


def _group_envelopes(cubes, collision_groups):
    """One axis-aligned envelope per authored group of source elements.

    Splitting a source element across cells (the board writes one element per cell)
    leaves the pieces carrying the same source index, so recovering the envelope
    gives back the authored part instead of a handful of quantised slivers.
    """
    by_index = {cube.get('index'): cube for cube in cubes}
    boxes = []
    for group in collision_groups:
        members = [by_index[index] for index in group if index in by_index]
        if not members:
            continue
        aabbs = [cube_aabb(cube) for cube in members]
        boxes.append(tuple(min(aabb[axis] for aabb in aabbs) for axis in range(3))
                     + tuple(max(aabb[axis + 3] for aabb in aabbs) for axis in range(3)))
    return boxes


def deploy_collision(source, res=16, allow_exposure=True, include_rotated=True,
                     single_block=True, collision_groups=None, include_indices=None,
                     clip_bounds=None):
    """Build the collision boxes for one model file or one cell of a multiblock.

    With collision_groups the caller has already decided which source elements
    fuse into one part, so each group becomes its envelope and nothing is voxelised.
    Without groups the geometry is voxelised at res, filling every cube it can
    and returning the parts a voxel grid cannot follow as plain envelopes.
    single_block is accepted for the callers that clip per cell themselves.
    """
    cubes = load_cubes(source)
    if include_indices is not None:
        wanted = {int(index) for index in include_indices}
        cubes = [cube for cube in cubes if cube.get('index') in wanted]
    cubes, _skipped = filter_collision_cubes(cubes)
    if not cubes:
        return {'boxes': [], 'metrics': measure_collision([], [], res)}
    if collision_groups:
        boxes = _group_envelopes(cubes, collision_groups)
    elif allow_exposure:
        main, rotated = compress_adaptive(cubes, res=res, seg_count=SEGMENT_COUNT,
                                          skip_rotated_decor=True)
        boxes = list(main) + (list(rotated) if include_rotated else [])
    else:
        boxes, _air, _count = solve_zero_exposure(cubes, res=res, seg_count=SEGMENT_COUNT,
                                                  source=source)
    if clip_bounds:
        boxes = _clip_boxes(boxes, clip_bounds)
    boxes = dedupe_boxes(merge_exact_union_boxes(boxes), res)
    return {'boxes': boxes, 'metrics': measure_collision(cubes, boxes, res)}


def main():
    ap = argparse.ArgumentParser(description='碰撞箱一键生成 + 可视化')
    ap.add_argument('model', help='bbmodel 或 model JSON 路径')
    ap.add_argument('--res', type=int, default=16, help='体素分辨率 (每单位体素数, 默认16)')
    ap.add_argument('--seg-count', type=int, default=6, help='斜面元素分段数 (默认6, 追0暴露兼顾box数)')
    ap.add_argument('--max-boxes', type=int, default=None, help='需求: 最大 box 数, 工具自动算分段数')
    ap.add_argument('--max-air', type=float, default=None, help='需求: 最大空气率(%), 工具自动算分段数')
    ap.add_argument('--exclude', default='', help='排除的 cube 名称, 逗号分隔 (如握把,装饰)')
    ap.add_argument('--prefix', default='', help='排除名称前缀 (如 noCollision_)')
    ap.add_argument('--zero-exposure', action='store_true',
                    help='默认: 追空气暴露率 0% (斜体整块填充覆盖, 宁可盖住下方空气也要无暴露)')
    ap.add_argument('--allow-exposure', action='store_true',
                    help='可选: 允许空气暴露 (斜体不碰/分离, 换取更少 box 和更贴轮廓, 但会有暴露)')
    ap.add_argument('--grid', action='append', default=[], help='手动指定格子边界, 如 x:0 或 x:-8,8')
    ap.add_argument('--visualize', action='store_true', help='生成后显示三视图叠加')
    ap.add_argument('--vres', type=int, default=2, help='可视化分辨率')
    ap.add_argument('--no-validate', action='store_true', help='跳过模型实装验证(UV越界/粒子/图标等)')
    ap.add_argument('--fix', action='store_true', help='验证器自动修复可修复的模型问题')
    ap.add_argument('--facing', action='store_true',
                    help='输出带 FACING 四朝向的完整 Java 模板(属性+rotationFor+getShape旋转)')
    args = ap.parse_args()

    # 模型实装验证(默认开启, 检测 UV 越界/粒子乱码/图标错位等常见坑)
    if not args.no_validate:
        try:
            from validate_model import load_model, detect_issues, apply_fixes
            vm = load_model(args.model)
            issues = detect_issues(vm, args.model)
            errors = [i for i in issues if i[0] == 'ERROR']
            warns = [i for i in issues if i[0] == 'WARN']
            if issues:
                print(f"\n[模型验证] {len(errors)} 错误, {len(warns)} 警告")
                for sev, code, msg, fix in issues:
                    icon = '❌' if sev == 'ERROR' else '⚠️'
                    print(f"  {icon} [{code}] {msg}")
                if args.fix:
                    fixes = apply_fixes(vm, args.model, issues)
                    if fixes:
                        import json as _json
                        with open(args.model, 'w', encoding='utf-8') as _f:
                            _json.dump(vm, _f, indent=2, ensure_ascii=False)
                        for fx in fixes:
                            print(f"  🔧 已修复: {fx}")
                if errors and not args.fix:
                    print("\n  ⚠️  存在 ERROR 级问题，模型可能无法渲染。加 --fix 自动修复，或手动处理后重试。")
            else:
                print("[模型验证] ✅ 未发现实装问题")
        except Exception as e:
            print(f"[模型验证] 跳过（验证器异常: {e}）")

    cubes = load_cubes(args.model)
    if args.exclude or args.prefix:
        ex = set(n.strip() for n in args.exclude.split(',') if n.strip())
        kept = [c for c in cubes if c['name'] not in ex and not (args.prefix and c['name'].startswith(args.prefix))]
        removed = [c for c in cubes if c not in kept]
        print(f"[过滤] 排除 {len(removed)} 个: {[c['name'] for c in removed]}")
        cubes = kept

    # 合并几何重合的面壳 cube(如毛毯外翻/内翻)
    from parse_model import merge_overlapping_hollow_cubes
    merged = merge_overlapping_hollow_cubes(cubes)
    if len(merged) < len(cubes):
        print(f"[合并] 重合面壳合并: {len(cubes)} -> {len(merged)} 个 cube")
        cubes = merged

    # 自动检测多格
    from multiblock import auto_detect_grid, parse_grid
    grid = None
    if args.grid:
        grid = parse_grid(args.grid)
        print(f"[网格] 手动指定: {grid}")
    else:
        grid = auto_detect_grid(cubes)
        if grid:
            print(f"[网格] 自动检测跨格: {grid} (多格模型)")
        else:
            print("[网格] 单格模型")

    # 自适应合并: 支持需求模式(max-boxes/max-air) 或 指定分段数
    from generate import compress_adaptive
    rotated_boxes = []
    if args.max_boxes or args.max_air:
        # 需求模式: 扫描分段, 按约束选最优
        from optimize import scan_options, choose_option
        options = scan_options(cubes, 8)
        seg, boxes, nb, air = choose_option(options, args.max_boxes, args.max_air)
        rotated_boxes = []
        print(f"[需求] max_boxes={args.max_boxes}, max_air={args.max_air} → 分段{seg}, {nb} box, 空气{air:.1f}%")
        print("  可选方案:")
        for s, b, n, a in options:
            mark = ' ← 选中' if s == seg else ''
            print(f"    分段{s}: {n} box, 空气 {a:.1f}%{mark}")
    elif args.allow_exposure:
        # 可选: 允许暴露 (斜体不碰/分离, box 少贴轮廓, 但有暴露)
        seg_count = args.seg_count
        boxes, rotated_boxes = compress_adaptive(cubes, res=args.res, seg_count=seg_count, skip_rotated_decor=True)
        print(f"[允许暴露] 斜体分离/不碰, 主碰撞贴合非斜体 ({len(boxes)} box)")
        if rotated_boxes:
            print(f"  ⚠️ 分离 {len(rotated_boxes)} 个斜角碰撞箱 (外接空气大):")
    else:
        # 默认: 基于纹理覆盖检测, 对实际渲染结构体素化 (消除空气暴露)
        from optimize import solve_zero_exposure
        boxes, air, nb = solve_zero_exposure(cubes, res=args.res, seg_count=args.seg_count, source=args.model)
        print(f"[默认 0暴露] 纹理覆盖检测 → {nb} box, 空气暴露率 {air:.2f}%")

    if grid:
        # 多格: 切割输出
        from multiblock import split_all_boxes, to_local, compute_cell_origins
        bx = all_bounds(cubes)
        model_min = {'x': bx[0], 'y': bx[1], 'z': bx[2]}
        origins = compute_cell_origins(grid, model_min, {'x': bx[3], 'y': bx[4], 'z': bx[5]})
        cells = split_all_boxes(boxes, grid)
        print(f"\n=== 多方块切割 (共 {len(boxes)} box -> {len(cells)} 格) ===")
        for key in sorted(cells.keys()):
            cell_boxes = cells[key]
            local = [to_local(b, origins, grid) for b in cell_boxes]
            print(f"\n格子 {key}: {len(cell_boxes)} box (局部坐标)")
            print(format_boxlist(local))
            print("Java:")
            print(to_java(local))
    else:
        # 单格: 直接输出
        print(f"\n=== 碰撞箱生成结果 (共 {len(cubes)} cube -> {len(boxes)} box) ===")
        print(format_boxlist(boxes))
        if args.facing:
            # 输出带 FACING 四朝向的完整模板 (解决"方向变体+碰撞箱旋转"反复出现的问题)
            print("\n=== Java 代码 (带 FACING 四朝向, 直接粘贴到 Block 类) ===")
            print(to_java_facing(boxes))
        else:
            print("\n=== Java 代码 (粘贴到 Block 类) ===")
            print(to_java(boxes))

        # ROTATED_EXTRA: 斜角碰撞箱代码单独提供 (AI 决定是否并入, 如 cargo 必要碰撞)
        if rotated_boxes:
            print("\n=== ROTATED_EXTRA (斜角碰撞箱, 非轴向 45°/135°, 外接空气大) ===")
            print("# 默认不并入主碰撞。若该斜杆是必需碰撞(货物/实体要支撑), 把下面 Shapes.or 并入 SHAPE:")
            print(to_java(rotated_boxes))

    # 可视化
    if args.visualize:
        print("\n\n### 三视图叠加 ( #=模型 @=碰撞 * =重叠 .=空 ) ###")
        for name, ah, av, hl, vl in [("前视图XY(从南看)", 0, 1, 'x', 'y'),
                                     ("侧视图YZ(从东看)", 2, 1, 'z', 'y'),
                                     ("俯视图XZ(从上看)", 0, 2, 'x', 'z')]:
            gh, hmin, vmin, res = render_plane(cubes, boxes, args.vres, ah, av)
            print(f"\n=== {name} ===")
            print_plane(gh, hmin, vmin, res, hl, vl)


if __name__ == '__main__':
    main()
