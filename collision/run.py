#!/usr/bin/env python3
"""
碰撞箱一键生成命令
  python run.py <模型文件> [--res 16] [--exclude "握把,装饰"]
  python run.py <模型文件> [--grid x:0] [--visualize]

流程: 解析 -> 自动检测单/多格 -> 正体积元素完整 AABB -> 精确并集合并(多格则切割) -> Java

自动检测: 模型某轴跨度 > 16 单位即判定跨格, 自动推断格子边界。
手动覆盖: --grid x:0 可手动指定切割边界。
"""
import argparse
import copy
import sys
import os
import json
from generate import load_cubes, VoxelGrid, compress_voxels, to_java, format_boxlist, ensure_collidable_boxes
from parse_model import all_bounds, cube_aabb, filter_collision_cubes
from visualize import render_plane, print_plane

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def select_collision_elements(cubes, include_indices=None, exclude_indices=None):
    """Filter collision source elements by original 0-based model indices."""
    excluded = set(exclude_indices or ())
    included = None if include_indices is None else set(include_indices)
    return [cube for cube in cubes
            if cube.get('index') not in excluded
            and (included is None or cube.get('index') in included)]


def single_collision_envelope(cubes):
    """Return one enclosing AABB for a selected structural subset."""
    if not cubes:
        return []
    return [all_bounds(cubes)]


def collision_group_envelopes(cubes, groups):
    """Create one model-space envelope per named structural element group."""
    from generate import merge_exact_union_boxes
    by_index = {cube.get("index"): cube for cube in cubes}
    boxes = []
    for group in groups or ():
        indices = group.get("indices", ()) if isinstance(group, dict) else group
        members = [by_index[index] for index in indices if index in by_index]
        if members:
            boxes.append(all_bounds(members))
    return merge_exact_union_boxes(boxes)


def clip_cubes_to_bounds(cubes, bounds):
    """Clip selected collision geometry to world-cell bounds (e.g. ladder y=0..32).

    Rotated elements are first converted to the same conservative AABB used by the
    standard collision policy. Zero/negative remnants are discarded.
    """
    clipped = []
    for cube in cubes:
        low, high = cube_aabb(cube)[:3], cube_aabb(cube)[3:]
        out_low, out_high = list(low), list(high)
        for axis, (bound_low, bound_high) in bounds.items():
            out_low[axis] = max(out_low[axis], bound_low)
            out_high[axis] = min(out_high[axis], bound_high)
        if any(out_high[axis] <= out_low[axis] for axis in range(3)):
            continue
        element = copy.deepcopy(cube)
        element["from"] = out_low
        element["to"] = out_high
        element.pop("rotation", None)
        # load_cubes caches rotated corners. Once a cube has been converted to
        # its clipped axis-aligned envelope, discard that stale cache too.
        element.pop("corners", None)
        clipped.append(element)
    return clipped


def parse_clip_bounds(specs):
    """Parse repeated ``axis:low:high`` cell-bound restrictions."""
    axis_index = {"x": 0, "y": 1, "z": 2}
    result = {}
    for spec in specs or ():
        parts = spec.split(":")
        if len(parts) != 3 or parts[0] not in axis_index:
            raise ValueError(f"Invalid clip bound {spec!r}; expected axis:low:high")
        axis, low, high = parts
        result[axis_index[axis]] = (float(low), float(high))
    return result


def measure_collision(cubes, boxes, res, tex_img=None, tex_size=(0, 0), tex_uv=(16, 16),
                      exclude_rotated=False):
    """Measure boxes against full element AABBs (including tilted and shell parts)."""
    from optimize import build_collision_reference_grid, calc_metrics, metric_resolution
    reference = [cube for cube in cubes if not (
        exclude_rotated and cube.get('rotation') and any(
            abs(angle / 90.0 - round(angle / 90.0)) > 1e-6
            for angle in cube['rotation'].get('angles', [0, 0, 0]))) ]
    if not reference:
        return {
            'air_percent': 0.0, 'miss_percent': 0.0, 'coverage_percent': 0.0,
            'precision_percent': 0.0, 'render_voxels': 0, 'collision_voxels': 0,
            'air_voxels': 0, 'miss_voxels': 0, 'resolution': res,
        }
    metric_res = metric_resolution(reference, res)
    grid, origin, dims = build_collision_reference_grid(reference, metric_res)
    metrics = calc_metrics(grid, origin, *dims, metric_res, boxes)
    metrics['resolution'] = metric_res
    return metrics


def deploy_collision(model_path, res=16, seg_count=6, allow_exposure=True, exclude=None,
                     prefix=None, grid_args=None, skip_textures=None, exclude_indices=None,
                     include_indices=None, single_envelope=False, min_thickness=None,
                     include_thin=False, include_shells=True, include_rotated=True,
                     single_block=False, clip_bounds=None, collision_groups=None,
                     rotated_segments=0):
    """库函数: 生成完整碰撞箱, 供 deploy/cli.py 唯一调用。

    统一碰撞生成入口 —— positive-volume 元素都生成完整 AABB (斜体一元素一盒)。
    skip_textures: 可选 list[str], 指定这些纹理 key 的元素**不参与碰撞** (如 ["#1","#0"]
                    跳过火焰/内壁等装饰件)。元素所有面引用这些纹理时被过滤。
    exclude_indices: 可选 list[int], 按元素索引(0-based)精确排除装饰件
                    (如 炉膛内壁/火焰/柴火/炉床等非结构骨架), 最可靠。
    返回 dict:
      {
        'boxes': 主碰撞 box 列表(模型坐标, 未切割),
        'rotated': 斜体分离 box 列表,
        'air': 空气暴露率(float),
        'grid': 自动检测的切割边界 {axis: [cuts]},
        'cells': {格子key: [box(局部坐标)]} (若跨格),
        'java': 单格时的 Java Shapes.or 代码或 None,
        'meshes_java': {格key: Java代码} (多格时),
        'box_count': 主碰撞 box 数,
      }
    失败抛异常, 由调用方处理。
    """
    from parse_model import merge_overlapping_hollow_cubes, load_cubes as _lc
    from multiblock import auto_detect_grid, parse_grid, split_all_boxes, to_local, compute_cell_origins
    from optimize import solve_zero_exposure, compress_adaptive as _ca

    cubes = _lc(model_path)
    if exclude or prefix:
        ex = set(n.strip() for n in (exclude or '').split(',') if n.strip())
        cubes = [c for c in cubes if c['name'] not in ex and not (prefix and c['name'].startswith(prefix))]
    # 按元素索引排除装饰件
    # Select only structural elements when decorative planes/poses share a model.
    cubes = select_collision_elements(cubes, include_indices, exclude_indices)
    # 按纹理 key 过滤装饰元素: 元素所有面引用 skip_textures 中任一纹理 → 排除
    if skip_textures:
        skip = set(skip_textures)
        def _is_decor(cube):
            texs = set(str(f.get('texture')) for f in cube.get('faces', {}).values() if f.get('texture') is not None)
            return texs.issubset(skip)
        cubes = [c for c in cubes if not _is_decor(c)]
    cubes, skipped = filter_collision_cubes(
        cubes, min_thickness=1.0, include_thin=include_thin,
        include_shells=include_shells, include_rotated=include_rotated)
    # Grouped structural envelopes use original element indices. Do not fold
    # overlapping source elements first, or an index-based group can disappear.
    if not collision_groups:
        merged = merge_overlapping_hollow_cubes(cubes)
        if len(merged) < len(cubes):
            cubes = merged
    if clip_bounds:
        cubes = clip_cubes_to_bounds(cubes, clip_bounds)

    # Determine cell ownership independently of the envelope strategy. The old
    # branch skipped this whenever collision_groups was used, so callers got a
    # whole-model box even though the asset was a multiblock structure.
    if not cubes:
        grid = None
    elif grid_args:
        grid = parse_grid(grid_args)
    elif single_block or single_envelope:
        # Some intentionally tall props (e.g. telescopes) remain one blockstate
        # with a collision volume above y=16. Do not split those into fake blocks.
        grid = None
    else:
        g = auto_detect_grid(cubes)
        grid = g if g else None

    # 解析纹理图供面覆盖检测 (含 uv 坐标系尺寸, 供 uv→像素换算)
    tex_img, tex_w, tex_h, tex_uvw, tex_uvh = None, 0, 0, 16, 16
    try:
        from face_coverage import load_texture_from_bbmodel
        if not str(model_path).lower().endswith('.json'):
            tex_img, tex_w, tex_h, tex_uvw, tex_uvh = load_texture_from_bbmodel(model_path)
    except Exception:
        tex_img, tex_w, tex_h, tex_uvw, tex_uvh = None, 0, 0, 16, 16

    if collision_groups and cubes:
        boxes, rotated, air = collision_group_envelopes(cubes, collision_groups), [], None
        if include_rotated and rotated_segments > 0:
            from generate import segment_rotated
            grouped_indices = {index for group in collision_groups for index in group}
            for cube in cubes:
                if cube.get("rotation") and cube.get("index") not in grouped_indices:
                    boxes.extend(segment_rotated(cube, seg_count=rotated_segments, res=res))
    elif single_envelope and cubes:
        boxes, rotated, air = single_collision_envelope(cubes), [], None
    elif not cubes:
        boxes, rotated, air = [], [], 0.0
    elif allow_exposure:
        from generate import compress_adaptive
        boxes, rotated = compress_adaptive(cubes, res=res, seg_count=seg_count,
                                           skip_rotated_decor=(not include_rotated or rotated_segments > 0),
                                           include_thin=include_thin,
                                           tex_img=tex_img, tex_size=(tex_w, tex_h),
                                           tex_uv=(tex_uvw, tex_uvh))
        if include_rotated and rotated_segments > 0:
            from generate import segment_rotated
            for cube in cubes:
                if cube.get("rotation"):
                    boxes.extend(segment_rotated(cube, seg_count=rotated_segments, res=res))
            rotated = []
        air = None
    else:
        boxes, air, nb = solve_zero_exposure(cubes, res=res, seg_count=seg_count, source=model_path)
        rotated = []

    boxes = ensure_collidable_boxes(boxes)
    rotated = ensure_collidable_boxes(rotated)

    # Measure against the same full-AABB policy used to create the shapes.
    metrics = measure_collision(cubes, boxes, res, tex_img=tex_img,
                                tex_size=(tex_w, tex_h), tex_uv=(tex_uvw, tex_uvh),
                                exclude_rotated=not include_rotated)

    result = {
        'boxes': boxes,
        'rotated': rotated,
        'air': metrics['air_percent'],
        'metrics': metrics,
        'grid': grid,
        'cells': None,
        'cell_metrics': {},
        'java': None,
        'meshes_java': {},
        'box_count': len(boxes),
        'skipped_elements': [
            {'index': cube['index'], 'name': cube['name'], 'reasons': reasons}
            for cube, reasons in skipped
        ],
    }

    if grid:
        bx = all_bounds(cubes)
        model_min = {'x': bx[0], 'y': bx[1], 'z': bx[2]}
        origins = compute_cell_origins(grid, model_min, {'x': bx[3], 'y': bx[4], 'z': bx[5]})
        cells = split_all_boxes(boxes, grid)
        from generate import planar_merge, merge_exact_union_boxes
        result['cells'] = {}
        for k, cb in cells.items():
            local = [to_local(b, origins, grid) for b in cb]
            merged = merge_exact_union_boxes(planar_merge(local, min_thickness=min_thickness))
            result['cells'][k] = merged
            result['meshes_java'][str(k)] = to_java(merged)
        from multiblock import measure_cell_coverage
        result['cell_metrics'] = measure_cell_coverage(cubes, result['cells'], grid, resolution=res)
    else:
        from generate import planar_merge, merge_exact_union_boxes
        boxes = planar_merge(boxes, min_thickness=min_thickness)
        boxes = merge_exact_union_boxes(boxes)
        result['boxes'] = boxes
        result['java'] = to_java(boxes)
    result['box_count'] = len(result['boxes'])

    return result


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


def main():
    ap = argparse.ArgumentParser(description='碰撞箱一键生成 + 可视化')
    ap.add_argument('model', help='bbmodel 或 model JSON 路径')
    ap.add_argument('--res', type=int, default=16, help='体素分辨率 (每单位体素数, 默认16)')
    ap.add_argument('--seg-count', type=int, default=6, help='兼容参数；默认完整 AABB 不再对斜体分段')
    ap.add_argument('--max-boxes', type=int, default=None, help='需求: 最大 box 数, 工具自动算分段数')
    ap.add_argument('--max-air', type=float, default=None, help='需求: 最大空气率(%%), 工具自动算分段数')
    ap.add_argument('--exclude', default='', help='排除的 cube 名称, 逗号分隔 (如握把,装饰)')
    ap.add_argument('--prefix', default='', help='排除名称前缀 (如 noCollision_)')
    ap.add_argument('--include-indices', default=None,
                    help='只纳入指定模型元素索引(0-based, 逗号分隔), 适合仅让支架/底座参与碰撞')
    ap.add_argument('--exclude-indices', default='',
                    help='按模型元素索引排除装饰件(0-based, 逗号分隔)')
    ap.add_argument('--single-envelope', action='store_true',
                    help='将筛选后全部碰撞元素包成一个总 AABB；适合不宜用多段盒的斜体/支架')
    ap.add_argument('--include-thin', action='store_true',
                    help='显式纳入薄片/零厚度元素 (默认仅渲染，不碰撞)')
    ap.add_argument('--exclude-shells', action='store_false', dest='include_shells', default=True,
                    help='显式跳过开口面壳 (默认按完整元素 AABB 碰撞)')
    ap.add_argument('--exclude-rotated', action='store_false', dest='include_rotated', default=True,
                    help='显式跳过斜体 (默认每个正体积斜体使用一个完整 AABB)')
    ap.add_argument('--zero-exposure', action='store_true',
                    help='兼容参数；碰撞以正体积元素 AABB 为目标，斜体空气暴露可接受')
    ap.add_argument('--allow-exposure', action='store_true',
                    help='兼容参数；输出仍按每个元素完整 AABB')
    ap.add_argument('--grid', action='append', default=[], help='手动指定格子边界, 如 x:0 或 x:-8,8')
    ap.add_argument('--single-block', action='store_true',
                    help='Keep the generated shape attached to one blockstate even if it extends past 16 units')
    ap.add_argument('--collision-group', action='append', default=[], metavar='IDX,IDX,...',
                    help='Build one tight collision envelope for the listed source element indices; repeat for components')
    ap.add_argument('--clip-bounds', action='append', default=[], metavar='AXIS:LOW:HIGH',
                    help='Clip collision geometry to explicit model bounds before grid splitting, e.g. y:0:32')
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

    exclude_indices = {int(index.strip()) for index in args.exclude_indices.split(',') if index.strip()}
    before = len(cubes)
    include_indices = None if args.include_indices is None else {
        int(index.strip()) for index in args.include_indices.split(',') if index.strip()
    }
    collision_groups = [[int(index.strip()) for index in group.split(',') if index.strip()]
                        for group in args.collision_group]
    cubes = select_collision_elements(cubes, include_indices, exclude_indices)
    if exclude_indices:
        print(f"[元素索引排除] {before - len(cubes)} 个: {sorted(exclude_indices)}")
    if include_indices is not None:
        print(f"[元素索引筛选] 保留 {len(cubes)}/{before} 个: {sorted(include_indices)}")

    cubes, skipped = filter_collision_cubes(
        cubes, include_thin=args.include_thin,
        include_shells=args.include_shells, include_rotated=args.include_rotated)
    clip_bounds = parse_clip_bounds(args.clip_bounds)
    if skipped:
        print(f"[零厚度视觉平面不碰撞] 跳过 {len(skipped)} 个元素:")
        for cube, reasons in skipped:
            print(f"  - #{cube['index']} {cube['name']}: {', '.join(reasons)}")

    # 合并几何重合的面壳 cube(如毛毯外翻/内翻)
    from parse_model import merge_overlapping_hollow_cubes
    merged = merge_overlapping_hollow_cubes(cubes)
    if len(merged) < len(cubes):
        print(f"[合并] 重合面壳合并: {len(cubes)} -> {len(merged)} 个 cube")
        cubes = merged

    if clip_bounds:
        cubes = clip_cubes_to_bounds(cubes, clip_bounds)
        print(f"[裁剪] 按 cell 物理边界裁剪元素包围盒: {clip_bounds}")

    # 自动检测多格
    from multiblock import auto_detect_grid, parse_grid
    grid = None
    if args.grid:
        grid = parse_grid(args.grid)
        print(f"[网格] 手动指定: {grid}")
    elif args.single_envelope:
        grid = None
        print("[网格] 单包围盒模式，不按超界坐标切分模型")
    elif args.single_block:
        grid = None
        print("[网格] 单方块状态模式；保留超出16单位的碰撞范围")
    else:
        grid = auto_detect_grid(cubes) if cubes else None
        if grid:
            print(f"[网格] 自动检测跨格: {grid} (多格模型)")
        else:
            print("[网格] 单格模型")

    # 自适应合并: 支持需求模式(max-boxes/max-air) 或 指定分段数
    from generate import compress_adaptive
    rotated_boxes = []
    if collision_groups and cubes:
        boxes, rotated_boxes = collision_group_envelopes(cubes, collision_groups), []
        print(f"[碰撞分组] 按结构组件生成 {len(boxes)} 个 envelope")
    elif args.single_envelope and cubes:
        boxes, rotated_boxes = single_collision_envelope(cubes), []
        print("[单包围盒] 将筛选后的结构合并为一个 AABB，避免斜体多段碰撞线")
    elif not cubes:
        boxes, rotated_boxes = [], []
        print("[碰撞] 当前默认规则下没有可碰撞的实心元素")
    elif args.max_boxes or args.max_air:
        # 需求模式: 扫描分段, 按约束选最优
        from optimize import scan_options, choose_option
        options = scan_options(cubes, 8, include_thin=args.include_thin)
        seg, boxes, nb, air = choose_option(options, args.max_boxes, args.max_air)
        rotated_boxes = []
        print(f"[需求] max_boxes={args.max_boxes}, max_air={args.max_air} → 分段{seg}, {nb} box, 空气{air:.1f}%")
        print("  可选方案:")
        for s, b, n, a in options:
            mark = ' ← 选中' if s == seg else ''
            print(f"    分段{s}: {n} box, 空气 {a:.1f}%{mark}")
    elif args.allow_exposure:
        # 可选: 允许暴露 (斜体分离报备, 非斜体按纹理覆盖, box 少贴轮廓)
        seg_count = args.seg_count
        # 读纹理图供面覆盖检测 (非旋转 cube 走薄壳/局部镂空分支)
        tex_img, tex_w, tex_h = None, 0, 0
        try:
            from face_coverage import load_texture_from_bbmodel
            if not args.model.lower().endswith('.json'):
                tex_img, tex_w, tex_h = load_texture_from_bbmodel(args.model)
        except Exception:
            tex_img, tex_w, tex_h = None, 0, 0
        boxes, rotated_boxes = compress_adaptive(cubes, res=args.res, seg_count=seg_count,
                                                 skip_rotated_decor=not args.include_rotated,
                                                 include_thin=args.include_thin,
                                                 tex_img=tex_img, tex_size=(tex_w, tex_h))
        print(f"[允许空气暴露] positive-volume 元素各自使用完整 AABB ({len(boxes)} box)")
        if rotated_boxes:
            print(f"  ⚠️ 分离 {len(rotated_boxes)} 个斜角碰撞箱 (外接空气大):")
    else:
        # 默认: 基于纹理覆盖检测, 对实际渲染结构体素化 (消除空气暴露)
        from optimize import solve_zero_exposure
        boxes, air, nb = solve_zero_exposure(cubes, res=args.res, seg_count=args.seg_count, source=args.model)
        print(f"[默认完整 AABB] → {nb} box, 空气暴露率 {air:.2f}%")

    # Only explicitly opted-in zero-thickness planes are inflated.
    # Normalize every generator path before quality measurement, display, and Java output.
    boxes = ensure_collidable_boxes(boxes)
    rotated_boxes = ensure_collidable_boxes(rotated_boxes)

    metric_texture, metric_w, metric_h, metric_uvw, metric_uvh = None, 0, 0, 16, 16
    try:
        from face_coverage import load_texture_from_bbmodel
        if not args.model.lower().endswith('.json'):
            metric_texture, metric_w, metric_h, metric_uvw, metric_uvh = load_texture_from_bbmodel(args.model)
    except Exception:
        pass
    metrics = measure_collision(cubes, boxes, args.res, tex_img=metric_texture,
                                tex_size=(metric_w, metric_h), tex_uv=(metric_uvw, metric_uvh),
                                exclude_rotated=not args.include_rotated)
    print("[碰撞质量 @ {:.3g} voxels/unit] 空气误占 {:.2f}% ({}), 漏碰 {:.2f}% ({}), 几何覆盖 {:.2f}%".format(
        metrics['resolution'], metrics['air_percent'], metrics['air_voxels'],
        metrics['miss_percent'], metrics['miss_voxels'], metrics['coverage_percent']))

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
