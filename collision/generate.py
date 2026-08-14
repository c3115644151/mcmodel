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

    def __init__(self, resolution=16):
        self.res = resolution          # 每单位体素数
        self.voxel_size = 1.0 / resolution
        self.shell_thickness = 1.0 / resolution  # 面壳厚度(默认1/16格)

    def mark_cube(self, cube, grid, ox, oy, oz, w, h, d):
        """把一个 cube 占据的体素标记进 grid。
        对旋转 cube 用逆旋转+中心点采样判断体素是否真在旋转体内(细粒度斜切面)。
        对面壳 cube(部分面无纹理)只在有纹理方向建薄壳碰撞。"""
        x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
        vx0 = max(0, int(round(x0 * self.res)) - ox)
        vy0 = max(0, int(round(y0 * self.res)) - oy)
        vz0 = max(0, int(round(z0 * self.res)) - oz)
        vx1 = min(w, int(round(x1 * self.res)) - ox)
        vy1 = min(h, int(round(y1 * self.res)) - oy)
        vz1 = min(d, int(round(z1 * self.res)) - oz)

        rot = cube.get('rotation')
        # 面壳识别: 部分面无纹理 → 薄壳碰撞
        from parse_model import is_hollow_cube, textured_faces, has_face_texture
        if is_hollow_cube(cube) and rot is None:
            self._mark_hollow(cube, grid, ox, oy, oz, w, h, d, vx0, vy0, vz0, vx1, vy1, vz1)
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
        """面壳 cube: 只在有纹理的面方向建薄壳碰撞(厚度=shell_thickness), 其余镂空。
        有纹理面 → 该方向薄层; 无纹理面 → 该方向镂空。"""
        from parse_model import has_face_texture
        x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
        thick = self.shell_thickness
        # 各面的薄壳范围: (对应轴的 lo/hi 边界, 薄壳在法线方向向内厚 thick)
        shells = []
        # up/down: y 方向
        if has_face_texture(cube, 'up'):
            shells.append((x0, y1 - thick, z0, x1, y1, z1))     # up 面薄层 (y1-thick ~ y1)
        if has_face_texture(cube, 'down'):
            shells.append((x0, y0, z0, x1, y0 + thick, z1))     # down 面薄层
        # north/south: z 方向
        if has_face_texture(cube, 'north'):
            shells.append((x0, y0, z0, x1, y1, z0 + thick))     # north 面薄层 (z0 ~ z0+thick)
        if has_face_texture(cube, 'south'):
            shells.append((x0, y0, z1 - thick, x1, y1, z1))     # south 面薄层
        # east/west: x 方向
        if has_face_texture(cube, 'east'):
            shells.append((x1 - thick, y0, z0, x1, y1, z1))     # east 面薄层
        if has_face_texture(cube, 'west'):
            shells.append((x0, y0, z0, x0 + thick, y1, z1))     # west 面薄层

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
        if w <= 0 or h <= 0 or d <= 0:
            raise ValueError("模型范围无效")
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


def to_java(boxes):
    """生成 Java Shapes.or(box(...)) 代码"""
    lines = []
    if not boxes:
        return "Shapes.empty()"
    lines.append("Shapes.or(")
    for i, b in enumerate(boxes):
        x0, y0, z0, x1, y1, z1 = b
        comma = "," if i < len(boxes) - 1 else ""
        lines.append(f"        box({x0:.1f}, {y0:.1f}, {z0:.1f}, {x1:.1f}, {y1:.1f}, {z1:.1f}){comma}")
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



def compress_adaptive(cubes, res=16, seg_count=3):
    """自适应合并: 旋转 cube 用旋转后外接 AABB 单 box 覆盖(牺牲空气率换完整覆盖),
    其他 cube 精确合并。

    设计权衡(用户反馈): 斜向元素(如绕Y轴旋转的木条)碰撞箱无法斜向,
    若用未旋转的轴对齐 box 会盖不住斜向伸出的角; 若沿 y 多段贴合则对
    绕 Y 旋转的水平长条无效(旋转在水平面)。因此优先单 box 外接覆盖,
    宁可多包空气也要完整包住模型。后续要精细可调 seg_count/手动改。
    返回 [(x0,y0,z0,x1,y1,z1)] 模型坐标(全局)。"""
    from parse_model import cube_aabb
    result = []
    for cube in cubes:
        if cube.get('rotation'):
            # 旋转元素: 直接用旋转后 8 角点的外接 AABB (单 box, 完整覆盖)
            x0, y0, z0, x1, y1, z1 = cube_aabb(cube)
            result.append((x0, y0, z0, x1, y1, z1))
        else:
            # 非旋转: 精确合并
            vg = VoxelGrid(res)
            g, o, dims = vg.build_grid([cube])
            result.extend(compress_voxels(g, o, dims[0], dims[1], dims[2], res))
    return result
