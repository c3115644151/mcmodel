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
from parse_model import load_cubes, merge_overlapping_hollow_cubes, all_bounds, cube_aabb
from generate import VoxelGrid, compress_voxels, compress_adaptive


def calc_air(grid, origin, w, h, d, res, boxes):
    """空气暴露率 = 碰撞箱体积 超出 模型渲染体积 的比例 (你的定义)。

    正确基准 (统一模型坐标, 逐体素):
      - 模型渲染体积 = 真几何占据体素数 (grid 中为真的体素)      → render_vol
      - 碰撞箱体积     = 被任何 box 覆盖的体素数 (box 盖住的体素) → coll_vol
      - 暴露率 = (coll_vol - render_vol) / render_vol * 100
        碰撞箱 > 渲染 = 多盖了不存在的空气 = 暴露。

    air > 0: 碰撞箱盖多了(空气暴露); air = 0: 完全贴合; 若有漏(<0)另计。
    """
    render_vol = 0
    coll_vol = 0
    for x in range(w):
        for y in range(h):
            for z in range(d):
                mx = (x + origin[0]) / res
                my = (y + origin[1]) / res
                mz = (z + origin[2]) / res
                in_geom = grid[x][y][z]
                in_box = any(b[0] <= mx < b[3] and b[1] <= my < b[4] and b[2] <= mz < b[5] for b in boxes)
                if in_geom:
                    render_vol += 1
                if in_box:
                    coll_vol += 1
    if render_vol == 0:
        return 0.0
    return (coll_vol - render_vol) / render_vol * 100


def solve_zero_exposure(cubes, res=16, seg_count=6, source=None):
    """默认求解: 体素化"实际渲染结构"并压缩, 碰撞箱 == 渲染结构 (空气暴露 0%)。

    思路 (纹理覆盖驱动, 实证为能到 0% 的稳健路径):
      - 从 bbmodel 源读内嵌纹理图 (Pillow)
      - VoxelGrid.mark_cube 用面覆盖率判定: 高覆盖=实心(建薄壳/实心), 低覆盖=镂空(空气)
      - 这样"只画部分纹理/局部透明"的 cube 不再按 AABB 全填, 槽壁生成正确薄壳
      - 直接压缩该体素网格 → 碰撞箱 == 渲染结构

    背景: 旧版用 face_pair_boxes 会把面实心区沿整轴映射成实心板, 无法生成薄墙,
    对"开放顶槽"类模型(陶土盆花架)只能到 ~49% 空气。改为压缩纹理感知网格可得 0.00%。
    全实心 cube 被 mark_cube 体素化为整块, 该路径天然等价于 AABB, 无需特判。

    返回 (boxes, air%, box_count)。
    """
    from generate import VoxelGrid, compress_voxels

    # 加载纹理图 (Pillow) 供面覆盖检测
    tex_img, tex_w, tex_h = None, 0, 0
    if source:
        try:
            from face_coverage import load_texture_from_bbmodel
            tex_img, tex_w, tex_h = load_texture_from_bbmodel(source)
        except Exception:
            tex_img, tex_w, tex_h = None, 0, 0

    # 体素化真渲染结构 (mark_cube 对镂空/薄壳 cube 建薄壳, 对全实心 cube 建整块)
    vg = VoxelGrid(res, tex_img=tex_img, tex_size=(tex_w, tex_h))
    grid, origin, (w, h, d) = vg.build_grid(cubes)
    # 压缩体素 → 轴对齐 box 列表 (碰撞箱 == 渲染结构)
    boxes = compress_voxels(grid, origin, w, h, d, res)
    air = calc_air(grid, origin, w, h, d, res, boxes)
    return boxes, air, len(boxes)


    """扫描不同分段数, 返回 [(seg_count, boxes, box_count, air_rate), ...]
    用 res=8 扫描(快), 真实体积只算一次。"""
    # 预计算真实占据体积(一次)
    vg = VoxelGrid(res)
    grid, origin, (w, h, d) = vg.build_grid(cubes)
    true_vol = sum(1 for x in range(w) for y in range(h) for z in range(d) if grid[x][y][z])
    options = []
    for seg in range(1, 9):
        # skip_rotated_decor=False: 需求模式要评估分段拟合空气率 (旋转元素也分段)
        main, rotated = compress_adaptive(cubes, res=res, seg_count=seg, skip_rotated_decor=False)
        air = calc_air(grid, origin, w, h, d, res, main)
        options.append((seg, main, len(main), air))
    return options


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
