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


def _element_groups(data, element_count):
    """Map element indices to their nearest Blockbench group, when present."""
    mapping = {}

    def visit_export_node(node, group_id):
        if isinstance(node, int) and not isinstance(node, bool):
            if 0 <= node < element_count:
                mapping[node] = group_id
        elif isinstance(node, dict):
            children = node.get('children', [])
            current = f"{group_id}/{node.get('name', 'group')}:{len(mapping)}"
            for child in children if isinstance(children, list) else []:
                visit_export_node(child, current)
        elif isinstance(node, list):
            for child in node:
                visit_export_node(child, group_id)

    groups = data.get('groups')
    if isinstance(groups, list):
        for i, group in enumerate(groups):
            if isinstance(group, dict):
                visit_export_node(group, f"group:{i}")
        if mapping:
            return mapping

    # Native .bbmodel outliners contain UUID references rather than element indices.
    elements = data.get('elements', [])
    uuids = {e.get('uuid'): i for i, e in enumerate(elements) if e.get('uuid') is not None}

    def visit_outliner(node, group_id=None):
        if isinstance(node, str):
            if group_id is not None and node in uuids:
                mapping[uuids[node]] = group_id
        elif isinstance(node, dict):
            children = node.get('children')
            if not isinstance(children, list):
                if group_id is not None and node.get('uuid') in uuids:
                    mapping[uuids[node['uuid']]] = group_id
                return
            current = f"outliner:{node.get('uuid', node.get('name', 'group'))}"
            for child in children:
                visit_outliner(child, current)
        elif isinstance(node, list):
            for child in node:
                visit_outliner(child, group_id)

    visit_outliner(data.get('outliner', []))
    return mapping


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
    group_map = _element_groups(data, len(data['elements']))
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
            'group': group_map.get(i),
            'faces': e.get('faces', {}),  # 面纹理信息(供面壳识别)
        }
        cube['corners'] = cube_corners(cube)
        cubes.append(cube)
    return cubes


def has_face_texture(cube, face):
    """判断 cube 的某面是否有有效纹理(uv 非零 且 tex 非空)。
    无纹理的面 = 该方向镂空(不渲染)。

    注意: BB 导出 Java 模型时 up/down 面 UV 常为负宽(纹理坐标反向), 属正常渲染,
    不能凭 UV 正负判"未画"。真正的"面剔除"需读面是否存在/被激活(如 get_face_material_instances),
    或面 UV 四点全同(退化)。此处仅以「tex 空 或 uv 全 0」判未画。"""
    fd = cube.get('faces', {}).get(face)
    if not fd:
        return False
    uv = fd.get('uv')
    tex = fd.get('texture')
    if tex is None:
        return False
    if isinstance(uv, list) and len(uv) == 4:
        if all(v == 0 for v in uv):
            return False
    return True


def textured_faces(cube):
    """返回 cube 有纹理的面列表"""
    return [f for f in ('north', 'east', 'south', 'west', 'up', 'down')
            if has_face_texture(cube, f)]


def is_hollow_cube(cube):
    """Detect a source element whose face set looks like an open shell.

    This is diagnostic metadata only. Collision generation deliberately uses
    that element's full geometric AABB unless it is a zero-volume plane.
    """
    # 内外壁配对被 merge 后显式标记为薄壳容器
    if cube.get('__hollow'):
        return True
    return len(textured_faces(cube)) <= 4


def collision_exclusion_reasons(cube, min_thickness=1.0):
    """Describe thin, shell-like, and rotated source geometry for diagnostics."""
    reasons = []
    extents = [abs(float(cube['to'][axis]) - float(cube['from'][axis])) for axis in range(3)]
    if any(extent <= 1e-9 for extent in extents):
        reasons.append('zero-thickness plane')
    elif min(extents) < min_thickness:
        reasons.append(f'thin element (<{min_thickness:g} model units)')

    rotation = cube.get('rotation')
    if rotation:
        angles = rotation.get('angles', [0, 0, 0])
        if any(abs(angle / 90.0 - round(angle / 90.0)) > 1e-6 for angle in angles):
            reasons.append('oblique rotation')

    if is_hollow_cube(cube):
        reasons.append('open/thin shell')
    return reasons


def filter_collision_cubes(cubes, min_thickness=1.0, include_thin=False,
                           include_shells=True, include_rotated=True):
    """Filter elements with no volume and return (kept, skipped-with-reasons).

    Positive-volume shells and rotated elements stay in the collision input:
    downstream generation wraps each in its full (rotated, when applicable)
    AABB. This avoids both a missing wall collider and a false hollow shell.
    Only zero-volume planes are visual-only by default; ``include_thin`` is an
    explicit opt-in that gives those planes a minimal collision thickness.
    """
    group_has_volume = set()
    for cube in cubes:
        group = cube.get('group')
        extents = [abs(cube['to'][axis] - cube['from'][axis]) for axis in range(3)]
        if group is not None and all(extent > 1e-9 for extent in extents):
            group_has_volume.add(group)

    kept, skipped = [], []
    for cube in cubes:
        reasons = collision_exclusion_reasons(cube, min_thickness)
        blocked_reasons = []
        for reason in reasons:
            if (reason == 'zero-thickness plane' and not include_thin
                    and cube.get('group') not in group_has_volume):
                blocked_reasons.append(reason)
            elif reason == 'open/thin shell' and not include_shells:
                blocked_reasons.append(reason)
            elif reason == 'oblique rotation' and not include_rotated:
                blocked_reasons.append(reason)
        if blocked_reasons:
            skipped.append((cube, blocked_reasons))
        else:
            kept.append(cube)
    return kept, skipped


def merge_overlapping_hollow_cubes(cubes):
    """
    合并几何完全重合的面壳 cube(如毛毯的外翻/内翻两个 cube)。
    重合 cube 被视为同一元素。只保留"外翻"cube(正方向 from<to)的有纹理面,
    忽略"内翻"cube(倒置 from>to)的面 —— 因为内翻只是同一表面的背面。
    返回新的 cube 列表。

    【薄壁容器】两个 cube AABB 相同、方向相反(一个 from<to 一个 from>to),
    是同一薄壁内外两面(如鸡舍箱体墙)。合并后标记 __hollow → 后续 mark_cube
    走薄壳分支(只建壁厚), 而非实心填满——箱体墙中空, 门洞可进。
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
        # 找重合的倒置 cube (AABB 相同即视为同一壳体两面)
        for j in range(i + 1, len(cubes)):
            if j in used:
                continue
            other = cubes[j]
            if cube_aabb(other) != aabb_c:
                continue
            of, ot = other['from'], other['to']
            other_forward = all(of[k] <= ot[k] for k in range(3))
            # 方向相反 + 同 AABB → 薄壁容器内外两面
            if is_forward != other_forward:
                merged['__hollow'] = True
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
