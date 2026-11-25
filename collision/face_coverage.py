#!/usr/bin/env python3
"""纹理覆盖检测 — 从 bbmodel 内嵌纹理图, 判断每个 cube 面的真实渲染覆盖。

BlockBench 中 cube 面常"只画了部分纹理/局部透明", 而 from/to AABB 是全填充的,
导致碰撞箱按 AABB 超出实际渲染结构(空气暴露)。此模块用 Pillow 读纹理图,
按面 UV 区域的透明像素占比判定面的真实状态。

用法:
    from face_coverage import load_texture, face_solid_ratio
"""
from PIL import Image
import io, base64, os
import json


def load_texture_from_bbmodel(source):
    """从 bbmodel 解出第一个纹理图, 返回 (ImageRGBA, width, height) 或 (None,0,0)."""
    try:
        with open(source, encoding='utf-8') as f:
            data = json.load(f)
        for t in data.get('textures', []):
            src = t.get('source', '')
            if src.startswith('data:image/png;base64,'):
                png = base64.b64decode(src.split(',', 1)[1])
                img = Image.open(io.BytesIO(png)).convert('RGBA')
                return img, t.get('width', 128), t.get('height', 128)
        return None, 0, 0
    except Exception:
        return None, 0, 0


def face_uv_px(cube, face, W, H):
    """返回该面的 UV 像素矩形 (u1p,v1p,u2p,v2p), uv 单位是像素. 退化返回 None."""
    fd = cube.get('faces', {}).get(face)
    if not fd:
        return None
    uv = fd.get('uv')
    if not uv or len(uv) != 4:
        return None
    u1, v1, u2, v2 = uv
    u1p, u2p = int(min(u1, u2)), int(max(u1, u2))
    v1p, v2p = int(min(v1, v2)), int(max(v1, v2))
    u1p, u2p = max(0, min(W, u1p)), max(0, min(W, u2p))
    v1p, v2p = max(0, min(H, v1p)), max(0, min(H, v2p))
    if u2p <= u1p or v2p <= v1p:
        return None
    return (u1p, v1p, u2p, v2p)


def face_solid_ratio(cube, face, img, W, H, alpha_thresh=0.1):
    """该面实心占比 (像素 alpha >= thresh*255 的比例). 1.0=全实心, 0=全透明空气."""
    rect = face_uv_px(cube, face, W, H)
    if rect is None:
        return 0.0
    region = img.crop(rect)
    data = list(region.getdata())
    if not data:
        return 0.0
    solid = sum(1 for p in data if p[3] >= alpha_thresh * 255)
    return solid / len(data)


def cube_solid_faces(cube, img=None, W=0, H=0, thresh=0.5):
    """返回该 cube 实心面集合 (覆盖率 >= thresh). 依赖图形时读纹理."""
    if img is None:
        # 无纹理图(外部json)时退回 tex 引用判断
        from parse_model import textured_faces
        return set(textured_faces(cube))
    solid = set()
    for f in ('north', 'east', 'south', 'west', 'up', 'down'):
        r = face_solid_ratio(cube, f, img, W, H)
        if r >= thresh:
            solid.add(f)
    return solid


def is_solid_cube(cube, img=None, W=0, H=0, thresh=0.5):
    """cube 是否实心(6面全实心). 若某面覆盖率低=该方向镂空."""
    solid = cube_solid_faces(cube, img, W, H, thresh)
    return len(solid) >= 6


def rebuild_voxel_from_faces(cube, img, W, H, res, model_min):
    """按"相对面对齐"规则重建 cube 实体体素。

    规则 (用户直觉): 对每对相对面(顶/底, 前/后, 左/右), 取两个面实心区在
    "共同方向轴"上的交集区间 —— 窄面(实心区小)约束宽面(实心区大), 形成收缩柱体。

    返回 set[(vx,vy,vz)] 模型坐标体素 (归一化到 res 网格).
    """
    a = cube_aabb(cube)
    x0, y0, z0, x1, y1, z1 = a

    def rect(face):
        r = _face_solid_rect(cube, face, img, W, H)
        return r  # (umin,vmin,umax,vmax) or None

    # 提取每对相对面实心区间. 需要把面uv的2D实心区映射到体素的(轴范围).
    # 这里用"该面色块在该方向轴的跨度" — 但轴映射有歧义, 用保守推断:
    # 体素实心 = 它被每个方向的相对面实心区都覆盖.
    # 为简化且稳, 这里直接用"3轴都落在相对实心区间内".
    # 具体: 对axis, 由两个相对面的实心区在"该轴"上的范围取交集.
    # 由于无可靠轴映射, 我们用启发式: up/down 面的 v 高 → y轴? north/south 的 u宽→x?
    # 这块依赖轴映射, 暂不自动推断. 由调用方传入 axis_map.
    raise NotImplementedError("轴映射需显式提供, 见 rebuild: axis_map")


def rebuild_voxels_from_texture(cube, img, W, H, grid, ox, oy, oz, w, h, d, res):
    """按"对面相交 + MC标准UV映射"逐体素重建 cube 实体。

    规则 (用户直觉): 体素实心 = 它在"x/east-west、y/up-down、z/north-south"
    三个方向都被相对面的实心纹理覆盖. 对面相交, 窄面(实心区小)自然收缩宽面.

    MC 标准 UV 映射 (Java Block 模型):
      up/down:   u=模型x, v=模型z
      north/south: u=模型x, v=模型y
      east/west:   u=模型z, v=模型y

    直接把体素标记进 grid (in-place).
    """
    from parse_model import cube_aabb
    a = cube_aabb(cube)
    x0, y0, z0, x1, y1, z1 = a

    def face_pixel(face, mx, my, mz):
        fd = cube['faces'].get(face)
        if not fd:
            return None
        uv = fd.get('uv')
        if not uv or len(uv) != 4:
            return None
        umin, umax = min(uv[0], uv[2]), max(uv[0], uv[2])
        vmin, vmax = min(uv[1], uv[3]), max(uv[1], uv[3])
        if face in ('up', 'down'):
            ax_u, ax_v = (x0, x1), (z0, z1)
        elif face in ('north', 'south'):
            ax_u, ax_v = (x0, x1), (y0, y1)
        else:  # east/west
            ax_u, ax_v = (z0, z1), (y0, y1)
        pu = (mx - ax_u[0]) / (ax_u[1] - ax_u[0]) if ax_u[1] > ax_u[0] else 0
        pv = (my - ax_v[0]) / (ax_v[1] - ax_v[0]) if ax_v[1] > ax_v[0] else 0
        px = int(umin + pu * (umax - umin)); py = int(vmin + pv * (vmax - vmin))
        px = max(0, min(W - 1, px)); py = max(0, min(H - 1, py))
        return (px, py)

    def solid_at(face, mx, my, mz):
        p = face_pixel(face, mx, my, mz)
        if p is None:
            return False
        return img.getpixel(p)[3] >= 25

    vx0 = max(0, int(round(x0 * res)) - ox)
    vy0 = max(0, int(round(y0 * res)) - oy)
    vz0 = max(0, int(round(z0 * res)) - oz)
    vx1 = min(w, int(round(x1 * res)) - ox)
    vy1 = min(h, int(round(y1 * res)) - oy)
    vz1 = min(d, int(round(z1 * res)) - oz)
    for vx in range(vx0, vx1):
        for vy in range(vy0, vy1):
            for vz in range(vz0, vz1):
                mx = (vx + ox + 0.5) / res
                my = (vy + oy + 0.5) / res
                mz = (vz + oz + 0.5) / res
                x_s = solid_at('east', mx, my, mz) or solid_at('west', mx, my, mz)
                y_s = solid_at('up', mx, my, mz) or solid_at('down', mx, my, mz)
                z_s = solid_at('north', mx, my, mz) or solid_at('south', mx, my, mz)
                if x_s and y_s and z_s:
                    grid[vx][vy][vz] = True


def face_pair_boxes(cube, img, W, H):
    """用户算法: 6面3对相对面, 每对生成1个box(法线轴=完整, 另两轴=两面实心区交集).
    返回 3 个候选 box (模型坐标), 供去重.
    """
    from parse_model import cube_aabb
    a = cube_aabb(cube); x0,y0,z0,x1,y1,z1 = a

    def solid_px(face):
        fd = cube['faces'].get(face); uv = fd.get('uv') if fd else None
        if not uv: return None
        u1,v1,u2,v2 = uv
        u1p,u2p=int(min(u1,u2)),int(max(u1,u2)); v1p,v2p=int(min(v1,v2)),int(max(v1,v2))
        cells=[(x,y) for x in range(max(0,min(W,u1p)),min(W,u2p)) for y in range(max(0,min(H,v1p)),min(H,v2p)) if img.getpixel((x,y))[3]>=25]
        if not cells: return None
        xs=[cc[0] for cc in cells]; ys=[cc[1] for cc in cells]
        return (min(xs),max(xs),min(ys),max(ys))

    def px2ax(p_lo,p_hi,p0,p1,ax0,ax1):
        span=abs(p1-p0)
        if span==0: return (ax0,ax1)
        t1=(p_lo-min(p0,p1))/span; t2=(p_hi-min(p0,p1))/span
        lo=ax0+t1*(ax1-ax0); hi=ax0+t2*(ax1-ax0); return (min(lo,hi),max(lo,hi))

    def pair(fa,fb,axis):
        ra=solid_px(fa); rb=solid_px(fb)
        if ra is None or rb is None: return None
        uva=cube['faces'][fa]['uv']; uvb=cube['faces'][fb]['uv']
        if axis=='y':
            ua=px2ax(ra[0],ra[1],uva[0],uva[2],x0,x1); ub=px2ax(rb[0],rb[1],uvb[0],uvb[2],x0,x1)
            va=px2ax(ra[2],ra[3],uva[1],uva[3],z0,z1); vb=px2ax(rb[2],rb[3],uvb[1],uvb[3],z0,z1)
            xx=(max(ua[0],ub[0]),min(ua[1],ub[1])); zz=(max(va[0],vb[0]),min(va[1],vb[1]))
            if xx[0]>xx[1] or zz[0]>zz[1]: return None
            return (xx[0],y0,zz[0],xx[1],y1,zz[1])
        if axis=='x':
            ua=px2ax(ra[0],ra[1],uva[0],uva[2],z0,z1); ub=px2ax(rb[0],rb[1],uvb[0],uvb[2],z0,z1)
            va=px2ax(ra[2],ra[3],uva[1],uva[3],y0,y1); vb=px2ax(rb[2],rb[3],uvb[1],uvb[3],y0,y1)
            zz=(max(ua[0],ub[0]),min(ua[1],ub[1])); yy=(max(va[0],vb[0]),min(va[1],vb[1]))
            if zz[0]>zz[1] or yy[0]>yy[1]: return None
            return (x0,yy[0],zz[0],x1,yy[1],zz[1])
        if axis=='z':
            ua=px2ax(ra[0],ra[1],uva[0],uva[2],x0,x1); ub=px2ax(rb[0],rb[1],uvb[0],uvb[2],x0,x1)
            va=px2ax(ra[2],ra[3],uva[1],uva[3],y0,y1); vb=px2ax(rb[2],rb[3],uvb[1],uvb[3],y0,y1)
            xx=(max(ua[0],ub[0]),min(ua[1],ub[1])); yy=(max(va[0],vb[0]),min(va[1],vb[1]))
            if xx[0]>xx[1] or yy[0]>yy[1]: return None
            return (xx[0],yy[0],z0,xx[1],yy[1],z1)
    return [pair('up','down','y'), pair('east','west','x'), pair('north','south','z')]


def dedup_face_boxes(cands):
    """从 3 个面投影候选 box 去重, 求最优解 (覆盖实体、box 最少).

    规则:
    1. 删除被其他 box 完全包含的
    2. 高度在某一轴重叠、另两轴互补的 → 合并
    返回去重后的 box 列表.
    """
    def contain(b1,b2):
        return b1[0]>=b2[0] and b1[1]>=b2[1] and b1[2]>=b2[2] and b1[3]<=b2[3] and b1[4]<=b2[4] and b1[5]<=b2[5]
    # 去被包含
    ded=[b for i,b in enumerate(cands) if not any(i!=j and contain(b,cands[j]) for j in range(len(cands)))]
    return ded
