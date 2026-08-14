#!/usr/bin/env python3
"""
碰撞箱生成工具 - 模型解析器
读取 BlockBench .bbmodel 或已导出的 model JSON，提取 cube 几何。

rotation 兼容两种格式:
- BlockBench bbmodel 常见: [x, y, z] 欧拉角 (绕 x/y/z 依次旋转)
- 导出 JSON: {"axis":"x","angle":12.5,"origin":[..]}
内部统一标准化为 {"angles":[x,y,z], "origin":[x,y,z], "raw":...}
"""
import json
import os
import math


def normalize_rotation(rot, e=None):
    """把两种 rotation 格式标准化。返回 None(无旋转) 或 {"angles":[...], "origin":[...], "raw":...}"""
    if not rot:
        return None
    # 格式1: list [x, y, z] 欧拉角 (bbmodel 内嵌)
    if isinstance(rot, list) and len(rot) >= 3:
        angles = [float(rot[0]), float(rot[1]), float(rot[2])]
        if all(abs(a) < 1e-9 for a in angles):
            return None
        origin = e.get('origin', [8, 8, 8]) if e else [8, 8, 8]
        return {'angles': angles, 'origin': [float(x) for x in origin], 'raw': rot}
    # 格式2: dict {"axis","angle","origin"} (导出 JSON)
    if isinstance(rot, dict):
        axis = rot.get('axis', 'y')
        angle = float(rot.get('angle', 0))
        if abs(angle) < 1e-9:
            return None
        # 转成欧拉角: 绕单轴旋转
        angles = [0.0, 0.0, 0.0]
        ax_map = {'x': 0, 'y': 1, 'z': 2}
        if axis in ax_map:
            angles[ax_map[axis]] = angle
        origin = rot.get('origin', [8, 8, 8])
        return {'angles': angles, 'origin': [float(x) for x in origin], 'raw': rot}
    return None


def rotate_point(p, angles, origin):
    """把点 p 绕 origin 按欧拉角 (绕 x, 再 y, 再 z) 旋转。BlockBench 顺序: X then Y then Z"""
    x, y, z = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
    rx, ry, rz = math.radians(angles[0]), math.radians(angles[1]), math.radians(angles[2])

    # 绕 X 轴
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    # 绕 Y 轴
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    # 绕 Z 轴
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)

    return [x + origin[0], y + origin[1], z + origin[2]]


def inverse_rotate_point(p, angles, origin):
    """把点 p 绕 origin 做逆旋转(正旋转的精确逆)。
    正旋转 = Rx·Ry·Rz, 逆 = Rz⁻¹·Ry⁻¹·Rx⁻¹, 顺序反 + 角度反。"""
    x, y, z = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
    rx, ry, rz = math.radians(angles[0]), math.radians(angles[1]), math.radians(angles[2])

    # 绕 -Z 轴 (逆)
    x, y = x * math.cos(-rz) - y * math.sin(-rz), x * math.sin(-rz) + y * math.cos(-rz)
    # 绕 -Y 轴 (逆)
    x, z = x * math.cos(-ry) + z * math.sin(-ry), -x * math.sin(-ry) + z * math.cos(-ry)
    # 绕 -X 轴 (逆)
    y, z = y * math.cos(-rx) - z * math.sin(-rx), y * math.sin(-rx) + z * math.cos(-rx)

    return [x + origin[0], y + origin[1], z + origin[2]]


def cube_corners(cube):
    """cube 的 8 个角点(应用旋转后)。返回 [[x,y,z]*8]"""
    frm = cube['from']
    to = cube['to']
    corners = [
        [frm[0], frm[1], frm[2]], [to[0], frm[1], frm[2]],
        [frm[0], to[1], frm[2]], [to[0], to[1], frm[2]],
        [frm[0], frm[1], to[2]], [to[0], frm[1], to[2]],
        [frm[0], to[1], to[2]], [to[0], to[1], to[2]],
    ]
    rot = cube.get('rotation')
    if rot:
        origin = rot['origin']
        angles = rot['angles']
        corners = [rotate_point(c, angles, origin) for c in corners]
    return corners


def load_cubes(source: str):
    """
    从 bbmodel 或 model JSON 加载 cube 列表。
    返回: [{name, from, to, rotation, corners}]
    """
    if not os.path.exists(source):
        raise FileNotFoundError(f"文件不存在: {source}")

    with open(source, encoding='utf-8') as f:
        data = json.load(f)

    if 'elements' not in data:
        raise ValueError(f"不是有效的模型文件(缺 elements): {source}")

    cubes = []
    for i, e in enumerate(data['elements']):
        frm = e.get('from', [0, 0, 0])
        to = e.get('to', [16, 16, 16])
        outliner = data.get('outliner', [])
        name = e.get('name')
        if not name and isinstance(outliner, list) and i < len(outliner):
            name = outliner[i]
        rotation = normalize_rotation(e.get('rotation'), e)
        cube = {
            'name': str(name) if name is not None else f"cube{i}",
            'index': i,
            'from': [float(frm[0]), float(frm[1]), float(frm[2])],
            'to': [float(to[0]), float(to[1]), float(to[2])],
            'rotation': rotation,
            'faces': e.get('faces', {}),  # 面纹理信息(供面壳识别)
        }
        cube['corners'] = cube_corners(cube)
        cubes.append(cube)
    return cubes


def has_face_texture(cube, face):
    """判断 cube 的某面是否有有效纹理(uv 非零且 tex 非空)。
    无纹理的面 = 该方向镂空(不渲染)。"""
    fd = cube.get('faces', {}).get(face)
    if not fd:
        return False
    uv = fd.get('uv')
    tex = fd.get('texture')
    if tex is None:
        return False
    if isinstance(uv, list) and len(uv) == 4 and all(v == 0 for v in uv):
        return False
    return True


def textured_faces(cube):
    """返回 cube 有纹理的面列表"""
    return [f for f in ('north', 'east', 'south', 'west', 'up', 'down')
            if has_face_texture(cube, f)]


def is_hollow_cube(cube):
    """判断 cube 是否为面壳(至少 2 面无纹理 = 镂空成壳)。
    面壳(如毛毯 3面有纹理)应只建有纹理方向的薄壳碰撞。
    只有 1 面无纹理的 cube(如桶盖 5面有纹理)是实心, 碰撞保持完整。"""
    return len(textured_faces(cube)) <= 4


def merge_overlapping_hollow_cubes(cubes):
    """
    合并几何完全重合的面壳 cube(如毛毯的外翻/内翻两个 cube)。
    重合 cube 被视为同一元素。只保留"外翻"cube(正方向 from<to)的有纹理面,
    忽略"内翻"cube(倒置 from>to)的面 —— 因为内翻只是同一表面的背面。
    返回新的 cube 列表。
    """
    result = []
    used = set()
    for i, c in enumerate(cubes):
        if i in used:
            continue
        aabb_c = cube_aabb(c)
        merged = dict(c)
        # 是否正方向 (外翻): from 各分量 <= to 各分量
        f, t = c['from'], c['to']
        is_forward = all(f[k] <= t[k] for k in range(3))
        # 找重合的倒置 cube, 忽略其面 (只保留正方向的面)
        for j in range(i + 1, len(cubes)):
            if j in used:
                continue
            other = cubes[j]
            if not is_hollow_cube(other):
                continue
            if cube_aabb(other) == aabb_c:
                of, ot = other['from'], other['to']
                other_forward = all(of[k] <= ot[k] for k in range(3))
                # 若当前 cube 是倒置且 other 是正方向, 用 other 的面
                if not is_forward and other_forward:
                    merged['faces'] = dict(other.get('faces', {}))
                    merged['from'] = list(other['from'])
                    merged['to'] = list(other['to'])
                    is_forward = True
                # 无论方向, 标记为已处理 (避免重复)
                merged['name'] = f"{merged.get('name','')}+{other.get('name','')}"
                used.add(j)
        result.append(merged)
        used.add(i)
    return result


def cube_aabb(cube):
    """cube 的轴对齐包围盒(考虑旋转: 用旋转后角点的 min/max)"""
    corners = cube.get('corners')
    if not corners:
        corners = cube_corners(cube)
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    zs = [c[2] for c in corners]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def all_bounds(cubes):
    """所有 cube 的总体包围盒"""
    if not cubes:
        return (0, 0, 0, 16, 16, 16)
    xs, ys, zs = [], [], []
    for c in cubes:
        x0, y0, z0, x1, y1, z1 = cube_aabb(c)
        xs += [x0, x1]
        ys += [y0, y1]
        zs += [z0, z1]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


if __name__ == '__main__':
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/32800/Downloads/桌子 (1).bbmodel'
    cubes = load_cubes(src)
    print(f"加载 {len(cubes)} 个 cube 从 {src}")
    for c in cubes:
        r = c['rotation']
        rstr = f" rot={r['angles']}@origin{r['origin']}" if r else ""
        print(f"  [{c['index']}] {c['name']}: from={c['from']} to={c['to']}{rstr}")
