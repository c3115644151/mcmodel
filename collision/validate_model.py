#!/usr/bin/env python3
"""
模型实装验证器 - 检测 BlockBench 导出模型的常见实装问题。

检测项（来自实际踩坑经验）:
1. UV 越界: UV 超出纹理尺寸, 导致 "Cannot compute translucency out of bounds"
2. texture_size 非标准: MC 26.1 新模型系统对 32 坐标 UV + texture_size 声明处理有 bug,
   应去掉 texture_size 并把 UV 缩放到 0~16（项目惯例）
3. 破坏粒子: textures.particle 指向自定义纹理会导致破坏粒子乱码, 应用原版纹理
4. 图标位置: display.gui 缺失或无 3D 旋转, 物品栏会显示平面视图
5. 元素越界: cube from/to 超出 [-16,32] 合法范围
6. 非法旋转: element rotation 角度非 22.5 的倍数（MC element rotation 限制）
7. parent 缺失: 模型 JSON 缺 parent, 无法被 MC 加载

用法:
    python validate_model.py <model.json> [--fix]
    --fix: 自动修复可修复的问题（UV 缩放、补 parent、补 display.gui、particle 改原版）
"""
import json
import sys
import os
import argparse

# MC element rotation 只允许 -45/-22.5/0/22.5/45
VALID_ROTATION_ANGLES = {-45.0, -22.5, 0.0, 22.5, 45.0}
# 方块合法坐标范围
# 26.1 实际接受超 [-16,32] 的坐标 (水井 y到47 先例正常渲染)。
# CuboidModelElement 的 MIN/MAX_EXTENT 仅作烘焙参考, 非硬性崩溃线。
MIN_COORD, MAX_COORD = -16.0, 48.0


def _model_max_span(model):
    """模型 3 轴最大跨度 (单位) — 用于 GUI scale 计算"""
    xs, ys, zs = [], [], []
    for e in model.get('elements', []):
        f, t = e.get('from', [0, 0, 0]), e.get('to', [16, 16, 16])
        xs += [f[0], t[0]]; ys += [f[1], t[1]]; zs += [f[2], t[2]]
    if not xs:
        return 16.0
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def load_model(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def detect_issues(model, path):
    """返回 [(severity, code, message, fix_info)]"""
    issues = []
    is_bbmodel = path.endswith('.bbmodel')

    # 确定纹理尺寸
    tex_size = model.get('texture_size')
    if is_bbmodel:
        # .bbmodel 的 resolution 字段
        res = model.get('resolution', {})
        tw = res.get('width', 16)
        th = res.get('height', 16)
    elif tex_size:
        tw, th = tex_size[0], tex_size[1]
    else:
        tw, th = 16, 16  # MC 默认方块纹理尺寸

    # .bbmodel 非 16 分辨率: 转换为 MC 模型时需把 UV 缩放到 0~16
    # (MC 26.1 对 texture_size>16 + 大 UV 处理有 bug, 会导致 translucency out of bounds)
    if is_bbmodel and (tw != 16 or th != 16):
        issues.append(('ERROR', 'BBMODEL_RESOLUTION_NONSTANDARD',
            f'.bbmodel resolution 为 {tw}x{th} (非默认 16x16)。'
            f'转换为 MC 模型时必须去掉 texture_size 并把所有 UV 缩放到 0~16, '
            f'否则会触发 "Cannot compute translucency out of bounds"',
            'scale_uv'))

    elements = model.get('elements', [])

    # 1. parent 缺失（仅 .json）
    if not is_bbmodel and not model.get('parent'):
        issues.append(('ERROR', 'MISSING_PARENT',
            '模型 JSON 缺 parent 字段, MC 无法加载（应设为 minecraft:block/block）',
            'set_parent'))

    # 2. texture_size 非标准（本次实际 bug）
    if tex_size and (tex_size[0] != 16 or tex_size[1] != 16):
        issues.append(('ERROR', 'TEXTURE_SIZE_NONSTANDARD',
            f'texture_size 声明为 {tex_size}, 但 MC 26.1 新模型系统对此处理有 bug '
            f'(会导致 "Cannot compute translucency out of bounds")。'
            f'应去掉 texture_size 并把所有 UV 从 {tex_size[0]} 坐标缩放到 16 坐标',
            'scale_uv'))

    # 3. 遍历每个 cube 检测 UV 越界 / 旋转 / 坐标
    for i, e in enumerate(elements):
        frm = e.get('from', [0, 0, 0])
        to = e.get('to', [16, 16, 16])
        name = e.get('name', f'cube{i}')

        # 坐标越界
        for k, (v, lo, hi) in enumerate(zip(['x','y','z'], [MIN_COORD]*3, [MAX_COORD]*3)):
            if frm[k] < lo or frm[k] > hi or to[k] < lo or to[k] > hi:
                issues.append(('ERROR', 'COORD_OUT_OF_BOUNDS',
                    f'元素[{i}]({name}) 的 {v} 坐标 {frm[k]}~{to[k]} 超出 [{lo},{hi}]', None))

        # 旋转角度 — 仅提示, 不修复: MC 26.1 CuboidRotation 支持任意角度 (EulerXYZ),
        # snap 会破坏 30°/-17.5° 等真实摆放角度 (独轮推车 cargo 教训)。
        rot = e.get('rotation')
        if rot and isinstance(rot, dict):
            angle = float(rot.get('angle', 0))
            if abs(angle) > 0.01 and angle not in VALID_ROTATION_ANGLES:
                issues.append(('WARN', 'INVALID_ROTATION_ANGLE',
                    f'元素[{i}]({name}) 旋转角 {angle}° 不是 22.5 的倍数'
                    f'（26.1 支持任意角, 仅供参考; 若为真实摆放角度请勿归整）',
                    None))

        # UV 越界
        faces = e.get('faces', {})
        for side, face in faces.items():
            uv = face.get('uv')
            # 26.1 CuboidFace.getTexture 是 GsonHelper.getAsString 必填 —
            # face 缺 texture 字段会抛 "Missing texture, expected to find a string" → 紫黑/加载失败
            if 'texture' not in face or not face['texture'] or face.get('texture') == '#missing':
                issues.append(('ERROR', 'MISSING_FACE_TEXTURE',
                    f'元素[{i}]({name}) {side} 面缺失/无效 texture 字段'
                    f'（26.1 CuboidFace 要求每面必有有效 texture 字符串, #missing 或空壳应删除该 face）',
                    'drop_null_texture_faces'))
            if not uv or len(uv) != 4:
                continue
            u1, v1, u2, v2 = uv
            # 越界检测: 任何 UV 分量超出纹理尺寸
            if min(u1, u2) < 0 or max(u1, u2) > tw or min(v1, v2) < 0 or max(v1, v2) > th:
                issues.append(('ERROR', 'UV_OUT_OF_BOUNDS',
                    f'元素[{i}]({name}) {side} 面 UV {uv} 超出纹理 {tw}x{th}',
                    'scale_uv'))

    # 4. 破坏粒子（仅 .json, 且 textures 存在）
    textures = model.get('textures', {})
    if not is_bbmodel and 'particle' in textures:
        particle = textures['particle']
        # 自定义纹理 = 非 minecraft: 开头
        if particle and not particle.startswith('minecraft:'):
            issues.append(('WARN', 'CUSTOM_PARTICLE_TEXTURE',
                f'textures.particle 指向自定义纹理 "{particle}", 破坏粒子可能乱码'
                f'（应改为原版纹理如 minecraft:block/oak_log 或 minecraft:block/oak_planks）',
                'fix_particle'))

    # 5. display.gui（物品图标 3D 视角）
    if not is_bbmodel:
        display = model.get('display', {})
        gui = display.get('gui')
        if not gui:
            issues.append(('WARN', 'MISSING_GUI_DISPLAY',
                '缺 display.gui 配置, 物品栏图标可能显示异常（应加等轴测视角 rotation:[30,225,0]）',
                'add_gui_display'))
        elif gui:
            rot = gui.get('rotation', [0, 0, 0])
            if all(abs(r) < 0.1 for r in rot):
                issues.append(('WARN', 'GUI_NO_ROTATION',
                    'display.gui.rotation 为 [0,0,0], 物品栏显示平面正视图而非 3D 视角'
                    '（建议 rotation:[30,225,0]）',
                    'add_gui_display'))

        # 图标过大检测: 模型跨格(元素坐标超出 0~16 或宽度>16)时 scale 必须缩小
        xs, ys, zs = [], [], []
        for e in model.get('elements', []):
            f, t = e.get('from', [0, 0, 0]), e.get('to', [16, 16, 16])
            xs += [f[0], t[0]]; ys += [f[1], t[1]]; zs += [f[2], t[2]]
        if xs:
            span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
            if span > 16:
                # 跨格模型, 图标 scale 应 <= 0.5, 否则物品栏显示过大
                scale = gui.get('scale', [1, 1, 1]) if gui else [1, 1, 1]
                max_scale = max(scale) if isinstance(scale, list) else 1
                if max_scale > 0.5:
                    suggest = 0.32 if span > 30 else 0.45
                    issues.append(('WARN', 'GUI_SCALE_TOO_LARGE',
                        f'模型跨格(尺寸 {span:.0f} 单位), 但 display.gui.scale={max_scale} 过大,'
                        f'物品栏图标会显示不全/过大。建议 scale ≤ {suggest}（参照水车 0.32）。',
                        'shrink_gui_scale'))

        # 6. 方向性检测: 模型有"同一侧偏侧元素"时需 FACING 方向变体
        #    (信箱旗杆偏左、木桩斧把偏上 — 放置朝向固定不符合直觉)
        #    对称分布(桶四角各一个边框)不触发 — 非对称元素必须偏向同一象限才提示
        off_center = []  # (cx-8, cz-8)
        for e in model.get('elements', []):
            f, t = e.get('from', [0, 0, 0]), e.get('to', [16, 16, 16])
            cx = (f[0] + t[0]) / 2
            cz = (f[2] + t[2]) / 2
            w = abs(t[0] - f[0])
            d = abs(t[2] - f[2])
            if w > 1.0 or d > 1.0:  # 排除零宽装饰
                if abs(cx - 8) > 2.0 or abs(cz - 8) > 2.0:
                    off_center.append((cx - 8, cz - 8))
        asym = False
        if off_center:
            # 多数偏侧(≥2/3 同侧)提示; 容忍少量反向装饰元素
            from collections import Counter
            cx_count = Counter(1 if dx > 0 else (-1 if dx < 0 else 0) for dx, dz in off_center)
            cz_count = Counter(1 if dz > 0 else (-1 if dz < 0 else 0) for dx, dz in off_center)
            cx_count.pop(0, None)
            cz_count.pop(0, None)
            total = len(off_center)
            for cnt in (cx_count, cz_count):
                if cnt and max(cnt.values()) >= max(2, total * 2 / 3):
                    asym = True
                    break
        if asym:
            issues.append(('WARN', 'NEEDS_FACING',
                '模型有"同一侧偏侧"元素 — 放置时应朝向玩家视角,'
                '需 extends HorizontalDirectionalBlock + blockstate facing 4方向 y 映射'
                ' + 碰撞箱 rotationFor/Shapes.rotate (参照 spinning_wheel.json 标准)',
                None))

    return issues


def detect_variant_collision(model_dir, base_name, num_variants):
    """检测多变体模型是否应该按变体分层做碰撞箱。
    当 firewood_bundle_0..N 等变体的几何 AABB 差异显著时，
    提示「各变体应独立碰撞箱，不要全用最大碰撞箱」。
    返回 issue 列表。"""
    issues = []
    aabbs = []
    for i in range(num_variants):
        name = base_name if i == 0 else f'{base_name}_{i}'
        p = os.path.join(model_dir, name + '.json')
        if not os.path.exists(p):
            continue
        try:
            m = json.load(open(p, encoding='utf-8'))
            xs, ys, zs = [], [], []
            for e in m.get('elements', []):
                f, t = e.get('from', [0, 0, 0]), e.get('to', [16, 16, 16])
                xs += [f[0], t[0]]; ys += [f[1], t[1]]; zs += [f[2], t[2]]
            if xs:
                aabbs.append((min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)))
        except Exception:
            continue
    if len(aabbs) >= 2:
        # 比较各变体总体积，差异超过 30% 提示分层
        vols = [abs((a[3]-a[0])*(a[4]-a[1])*(a[5]-a[2])) for a in aabbs]
        vmin, vmax = min(vols), max(vols)
        if vmin > 0 and (vmax - vmin) / vmax > 0.3:
            issues.append(('WARN', 'VARIANT_COLLISION_MISMATCH',
                f'{len(aabbs)} 个变体几何体积差异 {(vmax-vmin)/vmax*100:.0f}% '
                f'(最小 {vmin:.0f} vs 最大 {vmax:.0f})。'
                f'应按变体分层做碰撞箱(每变体独立 VoxelShape), '
                f'不要所有变体共用最大碰撞箱, 否则低变体时碰撞箱悬空/过大。'
                f'参考 FirewoodBundleBlock.SHAPES[level] 按层合并 AABB。',
                None))
    return issues


def apply_fixes(model, path, issues):
    """自动修复可修复的问题，返回修复说明列表"""
    fixes = []
    is_bbmodel = path.endswith('.bbmodel')
    tex_size = model.get('texture_size')
    tw = tex_size[0] if tex_size else (model.get('resolution',{}).get('width',16) if is_bbmodel else 16)

    for sev, code, msg, fix in issues:
        if fix is None:
            continue
        if fix == 'set_parent':
            model['parent'] = 'minecraft:block/block'
            fixes.append('已设 parent: minecraft:block/block')
        elif fix == 'scale_uv':
            # 去掉 texture_size。仅当 UV 看起来仍是 tex_size 网格 (max>16) 才缩放,
            # BB java_block 导出已把 128/64 网格 UV 除到 16 网格, 再缩会破坏模型。
            if 'texture_size' in model:
                del model['texture_size']
            uv_max = 0.0
            for e in model.get('elements', []):
                for face in e.get('faces', {}).values():
                    for v in face.get('uv') or []:
                        uv_max = max(uv_max, abs(v))
            if uv_max > 16.01 and tw and tw != 16:
                scale = 16.0 / tw
                for e in model.get('elements', []):
                    for face in e.get('faces', {}).values():
                        if 'uv' in face:
                            face['uv'] = [v * scale for v in face['uv']]
                fixes.append(f'已去掉 texture_size, UV 从 {tw} 坐标缩放到 16（×{scale}）')
            else:
                fixes.append(f'已去掉 texture_size (UV 已是 16 网格, max={uv_max:.2f}, 未再缩放)')
        elif fix == 'fix_particle':
            # 启发式: 木制模型用 oak_planks
            model.setdefault('textures', {})['particle'] = 'minecraft:block/oak_planks'
            fixes.append('已将 particle 改为 minecraft:block/oak_planks')
        elif fix == 'add_gui_display':
            # 智能 scale: span≤16(满格) 用原版标准 0.625; span>16(跨格) 用 10/span 缩进格内
            span = _model_max_span(model)
            scale = round(10.0 / span, 3) if span > 16 else 0.625
            model.setdefault('display', {})['gui'] = {
                'rotation': [30, 225, 0],
                'scale': [scale, scale, scale]
            }
            fixes.append(f'已添加 display.gui 等轴测视角 (scale={scale}, max_span={span}, {"跨格公式" if span > 16 else "满格标准0.625"})')
        elif fix == 'snap_rotation':
            for e in model.get('elements', []):
                rot = e.get('rotation')
                if rot and isinstance(rot, dict):
                    angle = float(rot.get('angle', 0))
                    if abs(angle) > 0.01 and angle not in VALID_ROTATION_ANGLES:
                        rot['angle'] = round(angle / 22.5) * 22.5
            fixes.append('已将非法旋转角归整到最近的 22.5 倍数')
        elif fix == 'drop_null_texture_faces':
            # 删除 texture 为 null/缺失的 face (26.1 必填 texture, 不可见面应删除而非留空壳)
            dropped = 0
            for e in model.get('elements', []):
                for side in list(e.get('faces', {}).keys()):
                    f = e['faces'][side]
                    if not f.get('texture') or f.get('texture') == '#missing':
                        del e['faces'][side]
                        dropped += 1
                # 全部面被删 → 该元素无处渲染, 删除元素
            model['elements'] = [e for e in model['elements'] if e.get('faces')]
            fixes.append(f'已删除 {dropped} 个无纹理 face (+对应空元素)')
        elif fix == 'shrink_gui_scale':
            # 跨格模型: 智能 scale = 10/max_span + 居中平移 (参照满格 0.625 公式)
            span = _model_max_span(model)
            if span > 16:
                scale = round(10.0 / span, 3)
                model.setdefault('display', {})['gui'] = {
                    'rotation': [30, 225, 0],
                    'scale': [scale, scale, scale]
                }
                fixes.append(f'已将跨格模型图标 scale 自动适配为 {scale} (max_span={span})')
            else:
                fixes.append('模型未超格, 无需缩放')

    return fixes


def main():
    ap = argparse.ArgumentParser(description='模型实装验证器')
    ap.add_argument('model', help='模型 JSON/.bbmodel 路径')
    ap.add_argument('--fix', action='store_true', help='自动修复可修复的问题')
    ap.add_argument('--quiet', action='store_true', help='只输出错误，不输出 WARN')
    ap.add_argument('--variants', type=int, default=0,
                    help='检测多变体碰撞箱分层: 变体数量(如 firewood_bundle 有 6 个变体传 6)')
    ap.add_argument('--variant-base', default='',
                    help='变体基名(默认从 model 文件名推断)')
    args = ap.parse_args()

    if not os.path.exists(args.model):
        print(f"❌ 文件不存在: {args.model}")
        sys.exit(2)

    model = load_model(args.model)
    issues = detect_issues(model, args.model)

    # 多变体碰撞箱检测 (本次实际踩坑: 6 变体全用最大碰撞箱)
    if args.variants > 0:
        model_dir = os.path.dirname(args.model)
        base = args.variant_base or os.path.splitext(os.path.basename(args.model))[0]
        issues += detect_variant_collision(model_dir, base, args.variants)

    if not issues:
        print(f"✅ {os.path.basename(args.model)}: 验证通过，未发现实装问题")
        sys.exit(0)

    errors = [i for i in issues if i[0] == 'ERROR']
    warns = [i for i in issues if i[0] == 'WARN' and not args.quiet]

    print(f"\n{'='*60}")
    print(f"模型: {args.model}")
    print(f"发现 {len(errors)} 个错误, {len(warns)} 个警告")
    print(f"{'='*60}")
    for sev, code, msg, fix in issues:
        if sev == 'WARN' and args.quiet:
            continue
        icon = '❌' if sev == 'ERROR' else '⚠️'
        print(f"\n{icon} [{sev}] {code}")
        print(f"   {msg}")
        if fix:
            print(f"   可自动修复: --fix")

    if args.fix:
        fixes = apply_fixes(model, args.model, issues)
        if fixes:
            with open(args.model, 'w', encoding='utf-8') as f:
                json.dump(model, f, indent=2, ensure_ascii=False)
            print(f"\n🔧 自动修复 ({len(fixes)} 项):")
            for fx in fixes:
                print(f"   ✓ {fx}")

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
