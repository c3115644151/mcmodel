"""用 Python 渲染纺车模型的 3 视图（俯/前/侧），显示实际视觉外观"""
import json
import math
import struct
from PIL import Image, ImageDraw

MODEL = 'src/main/resources/assets/pastoral_home/models/block/spinning_wheel.json'
TEX = 'src/main/resources/assets/pastoral_home/textures/block/spinning_wheel.png'

model = json.load(open(MODEL, encoding='utf-8'))
tex = Image.open(TEX).convert('RGBA')
TEX_SIZE = tex.size[0]  # 128
UV_FACTOR = TEX_SIZE / 16  # 8

# ========== 旋转矩阵 ==========
def apply_rotation(from_pt, to_pt, rot):
    """返回8个顶点，应用旋转（无旋转则返回原始8个点）"""
    corners = [
        [from_pt[0], from_pt[1], from_pt[2]],
        [to_pt[0],   from_pt[1], from_pt[2]],
        [from_pt[0], to_pt[1],   from_pt[2]],
        [to_pt[0],   to_pt[1],   from_pt[2]],
        [from_pt[0], from_pt[1], to_pt[2]],
        [to_pt[0],   from_pt[1], to_pt[2]],
        [from_pt[0], to_pt[1],   to_pt[2]],
        [to_pt[0],   to_pt[1],   to_pt[2]],
    ]
    if not rot or rot['angle'] == 0:
        return corners
    origin = rot.get('origin', [8, 8, 8])
    angle = math.radians(rot['angle'])
    cos, sin = math.cos(angle), math.sin(angle)
    axis = rot['axis']
    result = []
    for p in corners:
        x, y, z = p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]
        if axis == 'x':
            nx, ny, nz = x, y*cos - z*sin, y*sin + z*cos
        elif axis == 'y':
            nx, ny, nz = x*cos + z*sin, y, -x*sin + z*cos
        else:  # z
            nx, ny, nz = x*cos - y*sin, x*sin + y*cos, z
        result.append([nx+origin[0], ny+origin[1], nz+origin[2]])
    return result

def get_element_aabb(el):
    pts = apply_rotation(el['from'], el['to'], el.get('rotation'))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]

# ========== 渲染：简单 Z-buffer 面渲染 ==========
def render_view(project_to_xy, width, height, x_range, y_range):
    """通用渲染器：project_to_xy(vertex) -> (x,y) """
    img = Image.new('RGBA', (width, height), (0,0,0,0))
    pixels = img.load()
    zbuf = [[-1e9 for _ in range(width)] for _ in range(height)]

    # 收集所有元素的面
    faces = []
    for el_idx, el in enumerate(model['elements']):
        pts = apply_rotation(el['from'], el['to'], el.get('rotation'))
        # 6个面：north(z-), south(z+), west(x-), east(x+), down(y-), up(y+)
        # 识别每个面对应的顶点索引
        # 寻找每对面中 z 最小/最大等
        corners = pts  # 8个顶点
        face_data = [
            ('north', [0,1,3,2]),  # z- 面
            ('south', [4,5,7,6]),  # z+ 面
            ('west',  [0,2,6,4]),  # x- 面
            ('east',  [1,3,7,5]),  # x+ 面
            ('down',  [0,1,5,4]),  # y- 面
            ('up',    [2,3,7,6]),  # y+ 面
        ]
        for face_name, idxs in face_data:
            face_pts = [corners[i] for i in idxs]
            # 平均深度（z值）用于排序
            avg_z = sum(p[2] for p in face_pts) / 4
            uv = el.get('faces', {}).get(face_name, {}).get('uv')
            faces.append((avg_z, el, face_name, face_pts, uv))

    # 按深度从前到后排序（远到近）
    faces.sort(key=lambda f: f[0], reverse=True)

    for avg_z, el, face_name, face_pts, uv in faces:
        # 投影到 2D
        pts_2d = [project_to_xy(p) for p in face_pts]
        # 检查是否有效
        xs = [p[0] for p in pts_2d if p is not None]
        ys = [p[1] for p in pts_2d if p is not None]
        if not xs:
            continue
        # 获取 UV
        if uv:
            u1, v1, u2, v2 = uv
            # 纹理像素坐标
            tu1 = int(u1 * UV_FACTOR)
            tv1 = int(v1 * UV_FACTOR)
            tu2 = int(u2 * UV_FACTOR)
            tv2 = int(v2 * UV_FACTOR)
            # 纹理区域
            tex_face = tex.crop((tu1, tv1, tu2, tv2))
            # 透视变换
            src_pts = [(0,0), (tex_face.width,0), (tex_face.width,tex_face.height), (0,tex_face.height)]
            dst_pts = pts_2d
            try:
                # 使用简单仿射变换（足够好了）
                coeffs = find_coeffs(src_pts, dst_pts)
                transformed = tex_face.transform(
                    (width, height),
                    Image.PERSPECTIVE,
                    coeffs,
                    Image.BICUBIC
                )
                # 用 Z-buffer 混合
                for py in range(height):
                    for px in range(width):
                        r, g, b, a = transformed.getpixel((px, py))
                        if a > 0 and avg_z > zbuf[py][px]:
                            pixels[px, py] = (r, g, b, 255)
                            zbuf[py][px] = avg_z
            except Exception:
                # 如果透视变换失败，画纯色
                draw = ImageDraw.Draw(img)
                draw.polygon([(p[0], p[1]) for p in pts_2d], fill=(128,128,128,200))
    return img

def find_coeffs(p1, p2):
    """找到从 p1 到 p2 的透视变换系数"""
    matrix = []
    for i in range(4):
        x, y = p1[i]
        u, v = p2[i]
        matrix.append([x, y, 1, 0, 0, 0, -u*x, -u*y])
        matrix.append([0, 0, 0, x, y, 1, -v*x, -v*y])
    A = []
    B = []
    for row in matrix:
        A.append(row)
    B = [p2[0][0], p2[0][1], p2[1][0], p2[1][1], p2[2][0], p2[2][1], p2[3][0], p2[3][1]]
    # 求解 Ax = B
    try:
        # 高斯消元
        n = 8
        for i in range(n):
            # 找主元
            max_row = max(range(i, n), key=lambda r: abs(A[r][i]))
            A[i], A[max_row] = A[max_row], A[i]
            B[i], B[max_row] = B[max_row], B[i]
            pivot = A[i][i]
            if abs(pivot) < 1e-10:
                return [1,0,0,0,1,0,0,0]
            for j in range(i, n):
                A[i][j] /= pivot
            B[i] /= pivot
            for k in range(n):
                if k != i:
                    factor = A[k][i]
                    for j in range(i, n):
                        A[k][j] -= factor * A[i][j]
                    B[k] -= factor * B[i]
        return B
    except:
        return [1,0,0,0,1,0,0,0]

# ========== 俯视图 XZ（顶视）==========
print("渲染俯视图...")
def proj_top(p):
    # X 横，Z 纵（上=+Z），但模型 Z[-2,22] 很大
    # 缩放
    scale = 4
    cx, cy = 200, 50
    return (int(cx + (p[0] - 8) * scale), int(cy - (p[2] - 10) * scale))

img_top = render_view(proj_top, 400, 300, None, None)
img_top.save('tools/tmp/spinning_top.png')

# ========== 前视图 XY（从南看）==========
print("渲染前视图（从南）...")
def proj_front(p):
    scale = 4
    cx, cy = 180, 100
    return (int(cx + (p[0] - 8) * scale), int(cy - (p[1] - 12) * scale))

img_front = render_view(proj_front, 360, 200, None, None)
img_front.save('tools/tmp/spinning_front.png')

# ========== 侧视图 YZ（从东看）==========
print("渲染侧视图（从东）...")
def proj_side(p):
    scale = 4
    cx, cy = 80, 100
    return (int(cx + (p[2] - 10) * scale), int(cy - (p[1] - 12) * scale))

img_side = render_view(proj_side, 300, 200, None, None)
img_side.save('tools/tmp/spinning_side.png')

# ========== 等距视图 ==========
print("渲染等距视图...")
def proj_iso(p):
    scale = 3.5
    cx, cy = 200, 120
    x, y, z = p[0]-8, p[1]-12, p[2]-10
    # 等距投影：绕Y轴45度，再倾斜
    px = (x - z) * math.cos(math.radians(30))
    py = y - (x + z) * math.sin(math.radians(30))
    return (int(cx + px * scale), int(cy - py * scale))

img_iso = render_view(proj_iso, 400, 250, None, None)
img_iso.save('tools/tmp/spinning_iso.png')

print("所有视图已生成:")
print("  tools/tmp/spinning_top.png  - 俯视图")
print("  tools/tmp/spinning_front.png - 前视图（从南看）")
print("  tools/tmp/spinning_side.png  - 侧视图（从东看）")
print("  tools/tmp/spinning_iso.png  - 等距视图")
print("  tools/tmp/spinning_wheel_uv_annotated.png - UV标注纹理")
