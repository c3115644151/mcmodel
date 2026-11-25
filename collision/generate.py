#!/usr/bin/env python3
"""
碰撞箱生成器 - 从 BlockBench 模型生成 Java VoxelShape 代码。

算法:
1. 体素化: 把每个 cube 占据的体素标记进三维数组
2. 合并: 贪心合并相邻体素成 axis-aligned box
3. 输出: Shapes.or(box(x1,y1,z1,x2,y2,z2), ...) 的 Java 代码

纯几何路径: 碰撞箱 = 模型 cube 几何的体素化 + 合并。
不处理纹理镂空 (视觉缺口由美术在 BlockBench 里拆几何表达)。

用法:
    python generate.py <模型文件> [--resolution 16] [--exclude 名称1,名称2] [--prefix 前缀]
"""
import argparse
from parse_model import load_cubes, cube_aabb


class VoxelGrid:
    """体素网格: 每个 cube 占据的轴对齐体素"""

    def __init__(self, resolution=16, tex_img=None, tex_size=(0,0)):
        self.res = resolution          # 每单位体素数
        self.voxel_size = 1.0 / resolution
        self.shell_thickness = 1.0 / resolution  # 面壳厚度(默认1/16格)
        self.tex_img = tex_img        # 纹理图 (RGBA), 用于面覆盖率检测
        self.tex_w, self.tex_h = tex_size

    def _face_solid(self, cube, face):
        """该面实心占比 (读纹理). 无纹理图则退回 tex 引用判断."""
        if self.tex_img is not None:
            from face_coverage import face_solid_ratio
            return face_solid_ratio(cube, face, self.tex_img, self.tex_w, self.tex_h)
        from parse_model import has_face_texture
        return 1.0 if has_face_texture(cube, face) else 0.0

    def mark_cube(self, cube, grid, ox, oy, oz, w, h, d):
        """把一个 cube 占据的体素标记进 grid。
        对旋转 cube 用逆旋转+中心点采样判断体素是否真在旋转体内(细粒度斜切面)。
        对面壳/局部镂空 cube(某面覆盖率低)只在该实心方向建薄壳碰撞。"""
        x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
        vx0 = max(0, int(round(x0 * self.res)) - ox)
        vy0 = max(0, int(round(y0 * self.res)) - oy)
        vz0 = max(0, int(round(z0 * self.res)) - oz)
        vx1 = min(w, int(round(x1 * self.res)) - ox)
        vy1 = min(h, int(round(y1 * self.res)) - oy)
        vz1 = min(d, int(round(z1 * self.res)) - oz)

        rot = cube.get('rotation')
        # 面壳识别: 某面覆盖率低(镂空/局部空气) → 只建实心方向薄壳
        from parse_model import is_hollow_cube
        # 用纹理覆盖率判断是否面壳(替代只看tex引用)
        solid_low = [f for f in ('north','east','south','west','up','down') if self._face_solid(cube, f) < 0.5]
        is_hollow = is_hollow_cube(cube) or len(solid_low) >= 2
        # 局部镂空面: 该面覆盖率在 (0,1) 之间(不是全实心也不是全空) → 需逐体素重建
        has_partial = any(0.0 < self._face_solid(cube, f) < 1.0
                          for f in ('north','east','south','west','up','down'))
        if is_hollow and rot is None:
            self._mark_hollow(cube, grid, ox, oy, oz, w, h, d, vx0, vy0, vz0, vx1, vy1, vz1)
            return
        if rot is None and self.tex_img is not None and has_partial:
            # 有局部镂空面(如箱盖楔形) → 按"对面相交+UV映射"逐体素重建
            from face_coverage import rebuild_voxels_from_texture
            rebuild_voxels_from_texture(cube, self.tex_img, self.tex_w, self.tex_h,
                                        grid, ox, oy, oz, w, h, d, self.res)
            return
        if rot is None:
            # 非旋转实心: 快路径
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
        f_min = (min(frm[0], to[0]), min(frm[1], to[1]), min(frm[2], to[2]))
        f_max = (max(frm[0], to[0]), max(frm[1], to[1]), max(frm[2], to[2]))
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
        """面壳 cube: 只在实心程度高的面方向建薄壳碰撞, 其余镂空。
        用纹理覆盖率(face_solid)判定哪些面真正渲染, 而非仅 tex 引用。"""
        x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
        thick = self.shell_thickness
        shells = []
        # 各面实心判定 (覆盖率>=0.5 = 该面渲染, 建薄壳; 否则镂空)
        def is_solid(face):
            return self._face_solid(cube, face) >= 0.5
        # up/down: y 方向
        if is_solid('up'):
            shells.append((x0, y1 - thick, z0, x1, y1, z1))
        if is_solid('down'):
            shells.append((x0, y0, z0, x1, y0 + thick, z1))
        # north/south: z 方向
        if is_solid('north'):
            shells.append((x0, y0, z0, x1, y1, z0 + thick))
        if is_solid('south'):
            shells.append((x0, y0, z1 - thick, x1, y1, z1))
        # east/west: x 方向
        if is_solid('east'):
            shells.append((x1 - thick, y0, z0, x1, y1, z1))
        if is_solid('west'):
            shells.append((x0, y0, z0, x0 + thick, y1, z1))

        for sh in shells:
            sx0, sy0, sz0, sx1, sy1, sz1 = sh
            svx0 = max(0, int(round(sx0 * self.res)) - ox)
            svy0 = max(0, int(round(sy0 * self.res)) - oy)
            svz0 = max(0, int(round(sz0 * self.res)) - oz)
            svx1 = min(w, int(round(sx1 * self.res)) - ox)
            svy1 = min(h, int(round(sy1 * self.res)) - oy)
            svz1 = min(d, int(round(sz1 * self.res)) - oz)
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
        ox = int(bx0 * self.res)
        oy = int(by0 * self.res)
        oz = int(bz0 * self.res)
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


def to_java(boxes, normalize=True):
    """生成 Java Shapes.or(box(...)) 代码。
    normalize=True: 坐标 ÷16 归一化到 0~1 (Shapes.box 需要)。
    normalize=False: 原始模型坐标 (0~16)。"""
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
    lines.append(")")
    return "\n".join(lines)


def format_boxlist(boxes):
    """生成 box 列表 (便于人工审阅)"""
    out = []
    for i, b in enumerate(boxes):
        x0, y0, z0, x1, y1, z1 = b
        out.append(f"  [{i}] box({x0:.1f}, {y0:.1f}, {z0:.1f}, {x1:.1f}, {y1:.1f}, {z1:.1f})")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description='生成碰撞箱 Java 代码 (纯几何路径)')
    parser.add_argument('model', help='bbmodel 或 model JSON 路径')
    parser.add_argument('--resolution', type=int, default=16, help='每单位体素数 (默认16=精确到0.0625格)')
    parser.add_argument('--exclude', default='', help='排除的 cube 名称, 逗号分隔')
    parser.add_argument('--prefix', default='', help='排除名称前缀 (如 noCollision_)')
    args = parser.parse_args()

    cubes = load_cubes(args.model)
    if args.exclude or args.prefix:
        ex = set(n.strip() for n in args.exclude.split(',') if n.strip())
        before = len(cubes)
        cubes = [c for c in cubes if c['name'] not in ex and not (args.prefix and c['name'].startswith(args.prefix))]
        print(f"过滤: {before} -> {len(cubes)} 个 cube")

    vg = VoxelGrid(args.resolution)
    grid, origin, (w, h, d) = vg.build_grid(cubes)
    boxes = compress_voxels(grid, origin, w, h, d, args.resolution)

    print(f"\n=== 体素化结果 ===")
    print(f"体素网格: {w}x{h}x{d} ({w*h*d} voxels, res={args.resolution})")
    print(f"合并后: {len(boxes)} 个 box")
    print(f"\n=== box 列表 ===")
    print(format_boxlist(boxes))
    print(f"\n=== Java 代码 ===")
    print(to_java(boxes))


if __name__ == '__main__':
    main()


def _is_gradient(cube, res=8):
    """检测 cube 是否斜面(旋转立方体 = 斜面, 如斜腿)。
    旋转 cube 的几何是斜的, 轴对齐 box 无法精确贴合, 需分段处理。"""
    if cube.get('rotation'):
        return 'y'
    return None


def segment_rotated(cube, seg_count=3, res=16):
    """把旋转 cube 沿最优轴分成 seg_count 段阶梯碰撞箱。
    每段用体素中心逆旋转采样, 得到该段的紧凑 AABB (空气率远小于整体外接盒)。

    防护 (薄元素/退化段):
    - AABB 直径 < 3 单位 (薄条/面片): 直接返回外接 AABB 单 box (分段无意义)
    - 段无命中体素: 跳过
    - 段边界非法 (负数/超出 AABB): 夹紧
    返回 [(x0,y0,z0,x1,y1,z1)] — 至少 1 段 (兜底外接 AABB)。
    """
    from parse_model import inverse_rotate_point
    aabb = cube_aabb(cube)
    x0, y0, z0, x1, y1, z1 = aabb
    # 薄元素防护: 最小边 < 3 单位 → 分段没意义, 直接外接盒
    if min(x1 - x0, y1 - y0, z1 - z0) < 3.0:
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


def merge_exact_union_boxes(boxes):
    """Merge boxes that share one whole face while the other two axes match exactly.

    A source element split across a cell boundary leaves pieces that abut on the
    boundary plane; merging them restores the authored part instead of leaving a
    seam a player can catch on.
    """
    current = _dedupe_exact([tuple(round(float(value), 6) for value in box) for box in boxes])
    merged = True
    while merged:
        merged = False
        for left in range(len(current)):
            for right in range(left + 1, len(current)):
                union = _union_if_touching(current[left], current[right])
                if union is None:
                    continue
                current[left] = union
                current.pop(right)
                merged = True
                break
            if merged:
                break
    return current


def _dedupe_exact(boxes):
    seen, out = set(), []
    for box in boxes:
        if box not in seen:
            seen.add(box)
            out.append(box)
    return out


def _union_if_touching(left, right):
    """Return the merged box when the pair abuts on exactly one axis, else None."""
    for axis in range(3):
        others = [index for index in range(3) if index != axis]
        if any(left[index] != right[index] or left[index + 3] != right[index + 3]
               for index in others):
            continue
        low = min(left[axis], right[axis])
        high = max(left[axis + 3], right[axis + 3])
        if left[axis + 3] == right[axis] or right[axis + 3] == left[axis]:
            box = [left[index] for index in range(6)]
            box[axis], box[axis + 3] = low, high
            return tuple(round(value, 6) for value in box)
    return None


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


def compress_adaptive(cubes, res=16, seg_count=3, skip_rotated_decor=True):
    """自适应合并: 非旋转 cube 精确体素化合并; 旋转 cube 处理。

    【斜体处理】skip_rotated_decor=True (默认 — 报备模式):
    非轴向旋转元素 (22.5°/45°/135° 等) 尝试分段贴合 (segment_rotated, 沿斜度阶梯),
    得到低空气率的分段结果。若分段拟合后仍空气率过高 (>25%), 分离到 rotated 报备。

    返回 (main_boxes, rotated_boxes)。
    - main: 箱体/箱盖/屋脊 精确 + 斜体分段贴合(分段拟合优时)
    - rotated: 仅空气率过高的斜体(外接 AABB 报备, 由人类决定)
    轴向 (0/90/180/270) 旋转并入 main。
    """
    from parse_model import cube_aabb
    main = []
    rotated = []
    for cube in cubes:
        if cube.get('rotation'):
            r = cube['rotation']
            ang = max(abs(a) for a in r.get('angles', [0, 0, 0])) % 180
            if ang == 0:
                ang = abs(r.get('raw', {}).get('angle', 0)) % 180
            if ang not in (0, 90):
                # 斜体: 分段贴合 (沿斜度阶梯, 低空气率)
                segs = segment_rotated(cube, seg_count=seg_count, res=res)
                # 评估分段空气率
                seg_vol = sum((s[3]-s[0])*(s[4]-s[1])*(s[5]-s[2]) for s in segs)
                if segs:
                    vg = VoxelGrid(res); g,o,dims = vg.build_grid([cube])
                    tv = sum(1 for x in range(dims[0]) for y in range(dims[1]) for z in range(dims[2]) if g[x][y][z])
                    seg_air = (seg_vol - tv/(res*res*res)) / seg_vol if seg_vol else 1.0
                else:
                    seg_air = 1.0
                if seg_air <= 0.25 or skip_rotated_decor is False:
                    # 分段贴合优 → 并入 main
                    main.extend(segs if segs else [cube_aabb(cube)])
                else:
                    # 分段拟合空气率过高 → 分离报备 (外接 AABB)
                    rotated.append(cube_aabb(cube))
                continue
            main.append(cube_aabb(cube))
        else:
            vg = VoxelGrid(res)
            g, o, dims = vg.build_grid([cube])
            main.extend(compress_voxels(g, o, dims[0], dims[1], dims[2], res))
    return dedupe_boxes(main, res), dedupe_boxes(rotated, res)
