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
import json
from generate import load_cubes, VoxelGrid, compress_voxels, to_java, format_boxlist
from parse_model import all_bounds
from visualize import render_plane, print_plane


def deploy_collision(model_path, res=16, seg_count=6, allow_exposure=True, exclude=None,
                     prefix=None, grid_args=None):
    """库函数: 生成完整碰撞箱, 供 deploy/cli.py 唯一调用。

    统一碰撞生成入口 —— 读贴图(纹理覆盖)/自动检测单多格/跨格切割/斜体分离/输出 Java。
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
    merged = merge_overlapping_hollow_cubes(cubes)
    if len(merged) < len(cubes):
        cubes = merged

    # 网格切割边界
    grid = None
    if grid_args:
        grid = parse_grid(grid_args)
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

    if allow_exposure:
        from generate import compress_adaptive
        boxes, rotated = compress_adaptive(cubes, res=res, seg_count=seg_count,
                                           skip_rotated_decor=True, tex_img=tex_img, tex_size=(tex_w, tex_h),
                                           tex_uv=(tex_uvw, tex_uvh))
        air = None
    else:
        boxes, air, nb = solve_zero_exposure(cubes, res=res, seg_count=seg_count, source=model_path)
        rotated = []

    result = {
        'boxes': boxes,
        'rotated': rotated,
        'air': air,
        'grid': grid,
        'cells': None,
        'java': None,
        'meshes_java': {},
        'box_count': len(boxes),
    }

    if grid:
        bx = all_bounds(cubes)
        model_min = {'x': bx[0], 'y': bx[1], 'z': bx[2]}
        origins = compute_cell_origins(grid, model_min, {'x': bx[3], 'y': bx[4], 'z': bx[5]})
        cells = split_all_boxes(boxes, grid)
        from generate import planar_merge
        result['cells'] = {}
        for k, cb in cells.items():
            local = [to_local(b, origins, grid) for b in cb]
            merged = planar_merge(local)
            result['cells'][k] = merged
            result['meshes_java'][str(k)] = to_java(merged)
    else:
        from generate import planar_merge
        boxes = planar_merge(boxes)
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
                                                 skip_rotated_decor=True, tex_img=tex_img, tex_size=(tex_w, tex_h))
        print(f"[允许暴露] 斜体分离/不碰, 主碰撞按纹理覆盖 ({len(boxes)} box)")
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
