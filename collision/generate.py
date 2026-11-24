#!/usr/bin/env python3
"""
Collision helper routines for exported BlockBench geometry.

The standard deployment path uses one full AABB per positive-volume element,
including rotated and partial-face shell elements. The VoxelGrid routines below
remain available for rendering/occupancy diagnostics, but are not the default
collision policy because a missing face/UV must not create a hollow collider.

用法:
    python generate.py <模型文件> [--resolution 16] [--exclude 名称1,名称2] [--prefix 前缀]
"""
import argparse
import math
from parse_model import load_cubes, cube_aabb


class VoxelGrid:
    """体素网格: 每个 cube 占据的轴对齐体素"""

    def __init__(self, resolution=16, tex_img=None, tex_size=(0,0), tex_uv=(16,16)):
        self.res = resolution          # 每单位体素数
        self.voxel_size = 1.0 / resolution
        self.shell_thickness = 1.0 / resolution  # 面壳厚度(默认1/16格)
        self.tex_img = tex_img        # 纹理图 (RGBA), 用于面覆盖率检测
        self.tex_w, self.tex_h = tex_size
        self.tex_uvw, self.tex_uvh = tex_uv  # 模型 UV 坐标系尺寸(bb resolution), 供 uv→像素换算

    def _face_solid(self, cube, face):
        """该面实心占比 (读纹理). 无纹理图则退回 tex 引用判断."""
        if self.tex_img is not None:
            from face_coverage import face_solid_ratio
            return face_solid_ratio(cube, face, self.tex_img, self.tex_w, self.tex_h,
                                     self.tex_uvw, self.tex_uvh)
        from parse_model import has_face_texture
        return 1.0 if has_face_texture(cube, face) else 0.0

    def _axis_range(self, low, high, origin, limit):
        """Return occupied voxel indices, retaining visible zero-thickness planes."""
        start = math.floor(low * self.res) - origin
        end = math.floor(high * self.res) - origin
        if high - low <= 1e-9:
            coordinate = low * self.res
            nearest = round(coordinate)
            # Put a plane exactly on a voxel boundary in the preceding interior cell;
            # otherwise use the cell containing the plane. Clamp outer model faces in.
            index = (nearest - 1 if abs(coordinate - nearest) <= 1e-8
                     else math.floor(coordinate)) - origin
            index = max(0, min(max(0, limit - 1), index))
            return index, min(limit, index + 1)
        return max(0, start), min(limit, max(start, end))

    def mark_cube(self, cube, grid, ox, oy, oz, w, h, d):
        """Legacy diagnostic rasterizer; standard collision uses ``compress_adaptive``.

        This voxel path marks a cube into a grid for visual/occupancy analysis.
        对旋转 cube 用逆旋转+中心点采样判断体素是否真在旋转体内(细粒度斜切面)。
        对面壳/局部镂空 cube(某面覆盖率低)只在该实心方向建薄壳碰撞。"""
        x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
        # 体素索引 = floor(坐标*res) - floor(全局min*res)。用 floor 对齐 build_grid 的偏移,
        # 避免 int(round()) 对负值向零截断导致范围错位(模型负坐标时循环膨胀/网格错位)。
        vx0, vx1 = self._axis_range(x0, x1, ox, w)
        vy0, vy1 = self._axis_range(y0, y1, oy, h)
        vz0, vz1 = self._axis_range(z0, z1, oz, d)

        rot = cube.get('rotation')
        from parse_model import is_hollow_cube

        # 判定"空心壳": 面数少 或 存在"真空面"(实心率≈0, 即该面没贴图)。
        # 阈值 0.1 = 只把"几乎全透明(没贴图)"的面算空。
        # 不能用 0.5: 实心板上某面带透明区(如顶板 north=0.31)会被误判成空心壳,
        # 导致整块被拆成边缘薄壁、中间镂空(顶部碰撞缺失的根因)。
        # 真正没贴图的面实心率 ≈0.0, 与"带透明的面"区分开。
        # Collision follows model geometry, not transparent pixels in the material.
        # Only elements explicitly modeled as open shells are treated as hollow.
        is_hollow = is_hollow_cube(cube) and rot is None

        if is_hollow and rot is None:
            # 空心壳(如鸡舍墙盒): 逐面薄壳 + 投射 —— 顶面空则顶不建墙, 内部留空
            self._mark_hollow(cube, grid, ox, oy, oz, w, h, d, vx0, vy0, vz0, vx1, vy1, vz1)
            return
        if rot is None:
            # 全实心: 快路径
            for x in range(vx0, vx1):
                for y in range(vy0, vy1):
                    for z in range(vz0, vz1):
                        grid[x][y][z] = True
            return

        # 旋转: 细粒度采样。每个体素中心逆旋转后判断是否在 from/to 内
        # 体素中心在模型坐标
        from parse_model import inverse_rotate_point
        origin = rot['origin']
        frm = cube['from']
        to = cube['to']
        raw_min = (min(frm[0], to[0]), min(frm[1], to[1]), min(frm[2], to[2]))
        raw_max = (max(frm[0], to[0]), max(frm[1], to[1]), max(frm[2], to[2]))
        # A plane cube has visible area despite having no volume. Give only its
        # zero-width local axes half a voxel on either side for center sampling.
        f_min = tuple(raw_min[i] - self.voxel_size / 2 if raw_max[i] - raw_min[i] <= 1e-9 else raw_min[i]
                      for i in range(3))
        f_max = tuple(raw_max[i] + self.voxel_size / 2 if raw_max[i] - raw_min[i] <= 1e-9 else raw_max[i]
                      for i in range(3))
        for x in range(vx0, vx1):
            for y in range(vy0, vy1):
                for z in range(vz0, vz1):
                    # 体素中心模型坐标
                    mx = (x + ox + 0.5) / self.res
                    my = (y + oy + 0.5) / self.res
                    mz = (z + oz + 0.5) / self.res
                    # 逆旋转到立方体局部坐标系
                    lp = inverse_rotate_point([mx, my, mz], rot['angles'], origin)
                    if (f_min[0] <= lp[0] <= f_max[0] and
                            f_min[1] <= lp[1] <= f_max[1] and
                            f_min[2] <= lp[2] <= f_max[2]):
                        grid[x][y][z] = True

    def _mark_hollow(self, cube, grid, ox, oy, oz, w, h, d, vx0, vy0, vz0, vx1, vy1, vz1):
        """面壳 cube: 映射筛实体 → 只对这个有效形状建薄壁碰撞。

        两层(用户模型):
          1. 映射: face_shape_rows 逐行读面纹理实体范围, 筛掉空气, 得"有效结构形状"
             (如墙盒前/背墙 = 顶部梯形收窄 + 底部矩形全宽; 门洞行空气)。
          2. 薄壳: 只对这些有效行建薄壁(厚度方向 1/16), 按行范围分段合并成 box。
        不再建"整面等厚薄壁"(旧版没筛形状 → 南/北整条, 未反映梯形/开口)。

        对 6 面分别处理。up(顶空)/无实体面跳过。
        """
        from face_coverage import face_shape_rows
        x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
        thick = self.shell_thickness
        # 面 → 该面厚度方向的轴范围(z/x/y) 用于薄壁
        faces = {
            'north': (z0, z0 + thick, (x0, x1), (y0, y1)),
            'south': (z1 - thick, z1, (x0, x1), (y0, y1)),
            'east':  (x1 - thick, x1, (z0, z1), (y0, y1)),
            'west':  (x0, x0 + thick, (z0, z1), (y0, y1)),
            'up':    (y1 - thick, y1, (x0, x1), (z0, z1)),
            'down':  (y0, y0 + thick, (x0, x1), (z0, z1)),
        }
        for face, (nav_lo, nav_hi, u_ax, h_ax) in faces.items():
            r = face_shape_rows(cube, face, self.tex_img, self.tex_w, self.tex_h,
                                self.tex_uvw, self.tex_uvh, steps=8)
            if r['empty']:
                continue  # 该面无实体(顶面空) → 不建
            # 把每行(高度区间 + u实体范围) 合并: 相邻行 u 范围相近(差<0.5)则归一段
            def close(rng1, rng2):
                return abs(rng1[0] - rng2[0]) < 0.5 and abs(rng1[1] - rng2[1]) < 0.5
            segs = []
            cur = None
            for (my0, my1, u0, u1) in r['rows']:
                if cur and close((cur[3], cur[4]), (u0, u1)):
                    cur = (cur[0], my1, cur[2], u0, u1)  # 合并: 高度扩展, 范围取该行
                else:
                    if cur: segs.append(cur)
                    cur = (my0, my1, face, u0, u1)
            if cur: segs.append(cur)
            for (my0, my1, f, u0, u1) in segs:
                # 该段: 高度[my0,my1], u实体[u0,u1], 法线方向薄壁[nav_lo,nav_hi]
                # 用该面的轴: nav 是厚度z/x/y, u_ax 是横向, h_ax=高度y
                if face in ('east', 'west'):
                    bx0, bx1 = nav_lo, nav_hi
                    by0, by1 = my0, my1
                    bz0, bz1 = u0, u1
                elif face in ('north', 'south'):
                    bx0, bx1 = u0, u1
                    by0, by1 = my0, my1
                    bz0, bz1 = nav_lo, nav_hi
                else:  # up/down
                    bx0, bx1 = u0, u1
                    by0, by1 = nav_lo, nav_hi
                    bz0, bz1 = my0, my1
                self._fill_box(grid, ox, oy, oz, w, h, d,
                               bx0, by0, bz0, bx1, by1, bz1)

    def _fill_box(self, grid, ox, oy, oz, w, h, d, bx0, by0, bz0, bx1, by1, bz1):
        svx0 = max(0, math.floor(bx0 * self.res) - ox)
        svy0 = max(0, math.floor(by0 * self.res) - oy)
        svz0 = max(0, math.floor(bz0 * self.res) - oz)
        svx1 = min(w, math.floor(bx1 * self.res) - ox)
        svy1 = min(h, math.floor(by1 * self.res) - oy)
        svz1 = min(d, math.floor(bz1 * self.res) - oz)
        for x in range(svx0, svx1):
            for y in range(svy0, svy1):
                for z in range(svz0, svz1):
                    grid[x][y][z] = True

    def build_grid(self, cubes):
        """返回 (grid, origin) origin 是模型坐标到体素数组的偏移"""
        bx0, by0, bz0 = 1e9, 1e9, 1e9
        bx1, by1, bz1 = -1e9, -1e9, -1e9
        for c in cubes:
            x0, y0, z0, x1, y1, z1 = cube_aabb(c)
            bx0 = min(bx0, x0); by0 = min(by0, y0); bz0 = min(bz0, z0)
            bx1 = max(bx1, x1); by1 = max(by1, y1); bz1 = max(bz1, z1)
        ox = math.floor(bx0 * self.res)
        oy = math.floor(by0 * self.res)
        oz = math.floor(bz0 * self.res)
        w = int(bx1 * self.res) - ox
        h = int(by1 * self.res) - oy
        d = int(bz1 * self.res) - oz
        # 容忍零宽薄元素 (如 z1==z0 的平面装饰): clamp 到最小 1
        if w <= 0:
            w = 1
        if h <= 0:
            h = 1
        if d <= 0:
            d = 1
        grid = [[[False] * d for _ in range(h)] for __ in range(w)]
        for c in cubes:
            self.mark_cube(c, grid, ox, oy, oz, w, h, d)
        return grid, (ox, oy, oz), (w, h, d)


def compress_voxels(grid, origin, w, h, d, res):
    """把占据体素合并成 axis-aligned box 列表，返回 [(x0,y0,z0,x1,y1,z1)] 模型坐标"""
    visited = [[[False] * d for _ in range(h)] for __ in range(w)]
    boxes = []

    for x in range(w):
        for y in range(h):
            z = 0
            while z < d:
                if not grid[x][y][z] or visited[x][y][z]:
                    z += 1
                    continue
                # 找连续 z 段
                z2 = z
                while z2 < d and grid[x][y][z2] and not visited[x][y][z2]:
                    z2 += 1
                # 尝试沿 x 扩展 (贪婪)
                x_ext = 0
                while x + x_ext + 1 < w:
                    nx = x + x_ext + 1
                    ok = True
                    for zz in range(z, z2):
                        if not grid[nx][y][zz] or visited[nx][y][zz]:
                            ok = False
                            break
                    if not ok:
                        break
                    x_ext += 1
                # 尝试沿 y 扩展
                y_ext = 0
                while y + y_ext + 1 < h:
                    ny = y + y_ext + 1
                    ok = True
                    for xx in range(x, x + x_ext + 1):
                        for zz in range(z, z2):
                            if not grid[xx][ny][zz] or visited[xx][ny][zz]:
                                ok = False
                                break
                        if not ok:
                            break
                    if not ok:
                        break
                    y_ext += 1
                # 标记 visited
                for xx in range(x, x + x_ext + 1):
                    for yy in range(y, y + y_ext + 1):
                        for zz in range(z, z2):
                            visited[xx][yy][zz] = True
                # 转回模型坐标
                bx0 = (x + origin[0]) / res
                by0 = (y + origin[1]) / res
                bz0 = (z + origin[2]) / res
                bx1 = (x + x_ext + 1 + origin[0]) / res
                by1 = (y + y_ext + 1 + origin[1]) / res
                bz1 = (z2 + origin[2]) / res
                boxes.append((bx0, by0, bz0, bx1, by1, bz1))
                z = z2
    return boxes


def ensure_collidable_boxes(boxes, min_thickness=1.0 / 16.0):
    """Give explicitly included flat model planes minimal thickness.

    Blockbench legitimately exports many visible paper/trim planes with from == to
    on one axis. The safe collision default filters those as visual-only before
    generation. This fallback exists only for callers that explicitly opt them in;
    Shapes.box with a zero extent is empty for collision.
    """
    fixed = []
    for box in boxes:
        coords = list(box)
        for axis in range(3):
            low, high = coords[axis], coords[axis + 3]
            if high - low <= 1e-9:
                center = (low + high) / 2.0
                coords[axis] = center - min_thickness / 2.0
                coords[axis + 3] = center + min_thickness / 2.0
        fixed.append(tuple(coords))
    return fixed


def to_java(boxes, normalize=True):
    """生成 Java Shapes.or(box(...)) 代码。
    normalize=True: 坐标 ÷16 归一化到 0~1 (Shapes.box 需要)。
    normalize=False: 原始模型坐标 (0~16)。"""
    boxes = ensure_collidable_boxes(boxes)
    lines = []
    if not boxes:
        return "Shapes.empty()"
    lines.append("Shapes.or(")
    for i, b in enumerate(boxes):
        if normalize:
            x0, y0, z0, x1, y1, z1 = [v / 16.0 for v in b]
        else:
            x0, y0, z0, x1, y1, z1 = b
        comma = "," if i < len(boxes) - 1 else ""
        lines.append(f"        Shapes.box({x0:.4f}, {y0:.4f}, {z0:.4f}, {x1:.4f}, {y1:.4f}, {z1:.4f}){comma}")
    # Optimize the voxel shape after combining boxes. Besides reducing runtime
    # shape complexity, this removes internal/shared faces that otherwise show
    # up as doubled selection-outline lines in-game.
    lines.append(").optimize()")
    return "\n".join(lines)


def format_boxlist(boxes):
    """生成 box 列表 (便于人工审阅)"""
    out = []
    for i, b in enumerate(boxes):
        x0, y0, z0, x1, y1, z1 = b
        out.append(f"  [{i}] box({x0:.1f}, {y0:.1f}, {z0:.1f}, {x1:.1f}, {y1:.1f}, {z1:.1f})")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description='按元素完整几何 AABB 生成碰撞箱 Java 代码')
    parser.add_argument('model', help='bbmodel 或 model JSON 路径')
    parser.add_argument('--resolution', type=int, default=16, help='每单位体素数 (默认16=精确到0.0625格)')
    parser.add_argument('--exclude', default='', help='排除的 cube 名称, 逗号分隔')
    parser.add_argument('--prefix', default='', help='排除名称前缀 (如 noCollision_)')
    parser.add_argument('--include-thin', action='store_true', help='显式纳入薄片/零厚度元素')
    parser.add_argument('--exclude-shells', action='store_false', dest='include_shells', default=True,
                        help='显式排除正体积的开口面壳 (默认完整 AABB 碰撞)')
    parser.add_argument('--exclude-rotated', action='store_false', dest='include_rotated', default=True,
                        help='显式排除旋转元素 (默认每元素一个完整 AABB)')
    args = parser.parse_args()

    cubes = load_cubes(args.model)
    if args.exclude or args.prefix:
        ex = set(n.strip() for n in args.exclude.split(',') if n.strip())
        before = len(cubes)
        cubes = [c for c in cubes if c['name'] not in ex and not (args.prefix and c['name'].startswith(args.prefix))]
        print(f"过滤: {before} -> {len(cubes)} 个 cube")

    from parse_model import filter_collision_cubes
    cubes, skipped = filter_collision_cubes(
        cubes, include_thin=args.include_thin,
        include_shells=args.include_shells, include_rotated=args.include_rotated)
    for cube, reasons in skipped:
        print(f"[默认视觉件不碰撞] #{cube['index']} {cube['name']}: {', '.join(reasons)}")
    if not cubes:
        print("没有可碰撞的实心元素; 输出 Shapes.empty()")
        print("\n=== Java 代码 ===\nShapes.empty()")
        return

    boxes, _rotated = compress_adaptive(
        cubes, res=args.resolution, skip_rotated_decor=not args.include_rotated,
        include_thin=args.include_thin)
    boxes = ensure_collidable_boxes(boxes)

    print(f"\n=== 几何 AABB 结果 ===")
    print(f"按元素几何 AABB 构建 (薄壳填满、斜体单盒, res={args.resolution})")
    print(f"合并后: {len(boxes)} 个 box")
    print(f"\n=== box 列表 ===")
    print(format_boxlist(boxes))
    print(f"\n=== Java 代码 ===")
    print(to_java(boxes))


def _is_gradient(cube, res=8):
    """检测 cube 是否斜面(旋转立方体 = 斜面, 如斜腿)。
    旋转 cube 的几何是斜的, 轴对齐 box 无法精确贴合, 需分段处理。"""
    if cube.get('rotation'):
        return 'y'
    return None


THIN_PLATE_THICKNESS = 1.5


def segment_rotated(cube, seg_count=3, res=16):
    """把旋转 cube 沿最优轴分成 seg_count 段阶梯碰撞箱。
    每段用体素中心逆旋转采样, 得到该段的紧凑 AABB (空气率远小于整体外接盒)。

    防护 (薄元素/退化段):
    - AABB 所有轴跨度 < 3 单位 (小型装饰): 直接返回外接 AABB 单 box
    - 任一轴厚度 <= THIN_PLATE_THICKNESS 的薄板: 直接返回外接 AABB 单 box。
      薄板的体素命中率极低, 分段只会把一片斜面拆成几十个 1 单位小盒, 于是
      选中轮廓在模型周围画出一圈小方框 (唱片机喇叭就是这样暴露的)。一片薄板
      一个外接盒既省盒数, 又不会把大片空气算进碰撞。
    - 有厚度的细长斜体仍允许沿长轴分段, 避免大斜面把整片空气纳入碰撞
    - 段无命中体素: 跳过
    - 段边界非法 (负数/超出 AABB): 夹紧
    返回 [(x0,y0,z0,x1,y1,z1)] — 至少 1 段 (兜底外接 AABB)。
    """
    from parse_model import inverse_rotate_point
    aabb = cube_aabb(cube)
    x0, y0, z0, x1, y1, z1 = aabb
    # 小型装饰防护: 三个方向都短时分段收益有限。
    if max(x1 - x0, y1 - y0, z1 - z0) < 3.0:
        return [aabb]
    # 薄板防护: 体素命中率极低, 分段只会产生一堆 1 单位小盒。
    if min(x1 - x0, y1 - y0, z1 - z0) <= THIN_PLATE_THICKNESS:
        return [aabb]
    rot = cube['rotation']
    origin = rot['origin']
    frm = cube['from']
    to = cube['to']
    f_min = (min(frm[0], to[0]), min(frm[1], to[1]), min(frm[2], to[2]))
    f_max = (max(frm[0], to[0]), max(frm[1], to[1]), max(frm[2], to[2]))
    # 体素命中标记: 对 AABB 内所有体素中心先采样一次 (逆旋转判定)
    hits = {}
    for xi in range(int(round(x0 * res)), int(round(x1 * res))):
        for yi in range(int(round(y0 * res)), int(round(y1 * res))):
            for zi in range(int(round(z0 * res)), int(round(z1 * res))):
                mx = (xi + 0.5) / res
                my = (yi + 0.5) / res
                mz = (zi + 0.5) / res
                lp = inverse_rotate_point([mx, my, mz], rot['angles'], origin)
                if (f_min[0] <= lp[0] <= f_max[0] and
                        f_min[1] <= lp[1] <= f_max[1] and
                        f_min[2] <= lp[2] <= f_max[2]):
                    hits[(xi, yi, zi)] = True
    if not hits:
        return [aabb]
    # 逐轴试分段, 选总空气率最小的轴
    def segs_for_axis(axis):
        """沿 axis 切 seg_count 段, 每段取命中体素紧凑 AABB(对体素边界对齐)"""
        lo = aabb[axis]
        hi = aabb[axis + 3]
        step = (hi - lo) / seg_count
        out = []
        for s in range(seg_count):
            s_lo = lo + s * step
            s_hi = lo + (s + 1) * step
            seg_hits = [k for k in hits if s_lo <= k[axis] / res < s_hi]
            if not seg_hits:
                continue
            sxs = [k[0] for k in seg_hits]; sys_ = [k[1] for k in seg_hits]; szs = [k[2] for k in seg_hits]
            # +1 是右端开 (体素单元右边界)
            out.append((min(sxs) / res, min(sys_) / res, min(szs) / res,
                        (max(sxs) + 1) / res, (max(sys_) + 1) / res, (max(szs) + 1) / res))
        return out
    best = None
    for axis in range(3):
        segs = segs_for_axis(axis)
        if not segs:
            continue
        box_vol = sum((b[3] - b[0]) * (b[4] - b[1]) * (b[5] - b[2]) for b in segs)
        true_vol = len(hits) / (res * res * res)
        air = (box_vol - true_vol) / box_vol if box_vol else 1.0
        if best is None or air < best[0]:
            best = (air, segs)
    if best is None:
        return [aabb]
    return best[1]


def dedupe_boxes(boxes, res=16):
    """按体素网格量化去重 (嵌套双壳/重合元素在 res 分辨率下归并出相同 box)。"""
    seen = set()
    out = []
    for b in boxes:
        key = tuple(round(v / (1.0 / res)) for v in b)
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


def planar_merge(boxes, tol=0.02, min_thickness=None):
    """【去重·消除黑线】删被包含 box + 合并同向相邻 box。

    映射/薄壳分段会产生: ①被其他 box 完全包含的多余 box; ②同一薄片面被切成
    多个边界错位的 box。两者都是 MC 画出多余黑线轮廓的来源。

    规则:
    1. 删"被另一个 box 完全包含"的 box (维度被动被内层盖住, 多余)。
    2. 合并两个 box: 共享一个厚度方向(一个维度区间相同/近同), 且在其余两个轴
       上相邻(一个的 hi ≈ 另一个的 lo, 容差 tol) → 并成一个更大 box。
    3. (新增) min_thickness: 过滤极薄装饰盒 — 体素化会把纹理边缘/贴图缝体素化
       成 <min_thickness 的超薄盒(1/256格装饰边框), 这些不是实体碰撞。任一轴
       厚度 < min_thickness 的盒移除。默认 None=不过滤。
    """
    # 0. 过滤极薄装饰盒
    if min_thickness is not None:
        boxes = [b for b in boxes
                 if (b[3]-b[0]) >= min_thickness or (b[4]-b[1]) >= min_thickness or (b[5]-b[2]) >= min_thickness]
    # 1. 删被包含
    def contains(outer, inner):
        return (outer[0] <= inner[0] + tol and outer[1] <= inner[1] + tol and outer[2] <= inner[2] + tol
                and outer[3] >= inner[3] - tol and outer[4] >= inner[4] - tol and outer[5] >= inner[5] - tol)
    kept = []
    for i, b in enumerate(boxes):
        if any(i != j and contains(boxes[j], b) for j in range(len(boxes))):
            continue
        kept.append(b)
    # 2. 合并同向相邻 (沿 x/y/z 任一轴厚度相同, 另两轴相邻)
    changed = True
    while changed:
        changed = False
        out = []
        used = [False] * len(kept)
        for i in range(len(kept)):
            if used[i]:
                continue
            a = kept[i]
            merged = False
            for j in range(i + 1, len(kept)):
                if used[j]:
                    continue
                b = kept[j]
                # 判定: 某个轴方向上, a 与 b 的一个轴区间"重合"(同厚), 且另两轴相接
                for axis in range(3):
                    o1 = (axis + 1) % 3; o2 = (axis + 2) % 3
                    # axis=厚度主方向: a,b 在该轴区间近似重合
                    if not (abs(a[axis] - b[axis]) < tol and abs(a[axis + 3] - b[axis + 3]) < tol):
                        continue
                    # 其余两轴区间近似重合
                    ok = all(abs(a[o1] - b[o1]) < tol and abs(a[o1 + 3] - b[o1 + 3]) < tol
                             and abs(a[o2] - b[o2]) < tol and abs(a[o2 + 3] - b[o2 + 3]) < tol
                             for o in [o1, o2])
                    if not ok:
                        continue
                    # 余下需在"厚度轴"上相邻(一个hi≈另一个lo)才合并; 同面不同段(z向错位)不相邻不合并
                    if abs(a[axis + 3] - b[axis]) < tol or abs(b[axis + 3] - a[axis]) < tol:
                        lo = min(a[axis], b[axis]); hi = max(a[axis + 3], b[axis + 3])
                        nb = list(a); nb[axis] = lo; nb[axis + 3] = hi
                        used[j] = True; merged = True
                        break
            if merged:
                changed = True
                # 用合并后的 box 继续比较 (简单: 重新开始一轮)
            else:
                out.append(a)
            used[i] = True
        kept = out
    return kept


def merge_exact_union_boxes(boxes, tol=1e-6):
    """Remove contained boxes and merge overlapping/face-adjacent boxes only when
    their union is itself a rectangular box. This avoids the two-outline-line
    artifact without filling L-shaped air gaps."""
    def volume(b):
        return max(0.0, b[3]-b[0]) * max(0.0, b[4]-b[1]) * max(0.0, b[5]-b[2])
    current = []
    # Equal candidates can come from mutually exclusive states/material
    # variants. Removing every box as "contained by an identical box" would
    # leave an empty collision shape, so deduplicate before containment checks.
    for box in boxes:
        candidate = tuple(box)
        if volume(candidate) <= tol:
            continue
        if not any(all(abs(candidate[axis] - existing[axis]) <= tol
                       and abs(candidate[axis + 3] - existing[axis + 3]) <= tol
                       for axis in range(3)) for existing in current):
            current.append(candidate)
    changed = True
    while changed:
        changed = False
        # Remove boxes fully contained by another one.
        kept = []
        for i, b in enumerate(current):
            if any(i != j and all(current[j][a] <= b[a] + tol and current[j][a+3] >= b[a+3] - tol for a in range(3))
                   for j in range(len(current))):
                changed = True
                continue
            kept.append(b)
        current = kept
        for i in range(len(current)):
            a = current[i]
            for j in range(i + 1, len(current)):
                b = current[j]
                u = (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]),
                     max(a[3], b[3]), max(a[4], b[4]), max(a[5], b[5]))
                # A rectangular union has no missing volume. Permit only overlap
                # or shared faces, never diagonal/corner-only contact.
                inter = 1.0
                for axis in range(3):
                    inter *= max(0.0, min(a[axis+3], b[axis+3]) - max(a[axis], b[axis]))
                if abs(volume(u) - (volume(a) + volume(b) - inter)) <= tol:
                    current[i] = u
                    del current[j]
                    changed = True
                    break
            if changed:
                break
    return current


def compress_adaptive(cubes, res=16, seg_count=3, skip_rotated_decor=False, include_thin=False,
                      tex_img=None, tex_size=(0, 0), tex_uv=(16, 16)):
    """Build one full AABB per positive-volume model element.

    Collision follows geometric volume, not texture-face coverage: a partial
    face set must not turn a structural side into a hollow sliver. Rotated
    elements use one rotated AABB (air exposure is preferable to a missing
    collider or a staircase made of several boxes). Within a Blockbench group,
    coplanar cover/shell pieces close to a positive-volume core are folded into
    the same outer AABB, so book covers are included without turning a distant
    zero-thickness handle/flame into a collider. Standalone zero-volume planes
    are visual-only unless explicitly opted in.

    ``skip_rotated_decor`` remains as a compatibility opt-out for an explicit
    caller; the standard deployment path leaves it false.
    """
    from parse_model import cube_aabb
    main, rotated, groups = [], [], {}
    for cube in cubes:
        group = cube.get('group')
        if group is None:
            groups.setdefault(None, []).append(cube)
        else:
            groups.setdefault(group, []).append(cube)

    for group_id, members in groups.items():
        positive, planes = [], []
        for cube in members:
            target = positive if all(abs(cube['to'][axis] - cube['from'][axis]) > 1e-9
                                     for axis in range(3)) else planes
            target.append(cube)
        positive_boxes = [cube_aabb(cube) for cube in positive]

        def union(boxes):
            return (min(box[0] for box in boxes), min(box[1] for box in boxes), min(box[2] for box in boxes),
                    max(box[3] for box in boxes), max(box[4] for box in boxes), max(box[5] for box in boxes))

        nearby_plane_boxes = []
        if group_id is not None and positive_boxes:
            core = union(positive_boxes)
            margin = 1.25  # model pixels; covers paper skins, not distant handles/flame ornaments
            for plane in planes:
                box = cube_aabb(plane)
                if (box[0] >= core[0] - margin and box[1] >= core[1] - margin and box[2] >= core[2] - margin
                        and box[3] <= core[3] + margin and box[4] <= core[4] + margin
                        and box[5] <= core[5] + margin):
                    nearby_plane_boxes.append(box)

        if group_id is not None and positive_boxes and nearby_plane_boxes:
            group_box = union(positive_boxes + nearby_plane_boxes)
            group_is_rotated = any(cube.get('rotation') for cube in positive)
            if group_is_rotated and skip_rotated_decor:
                rotated.append(group_box)
            else:
                main.append(group_box)
            continue

        for cube in positive:
            box = cube_aabb(cube)
            is_rotated = cube.get('rotation') is not None
            if is_rotated and skip_rotated_decor:
                rotated.append(box)
            else:
                main.append(box)
        for plane in planes:
            if include_thin:
                main.append(cube_aabb(plane))
    main = merge_exact_union_boxes(dedupe_boxes(main, res))
    return main, dedupe_boxes(rotated, res)


if __name__ == '__main__':
    main()
