"""简化渲染：每个元素用纯色填充投影，按idx着色"""
import json
import math
from PIL import Image, ImageDraw

MODEL = 'src/main/resources/assets/pastoral_home/models/block/spinning_wheel.json'
model = json.load(open(MODEL, encoding='utf-8'))

def apply_rotation(from_pt, to_pt, rot):
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
        else:
            nx, ny, nz = x*cos - y*sin, x*sin + y*cos, z
        result.append([nx+origin[0], ny+origin[1], nz+origin[2]])
    return result

# 按元素idx分配颜色（HSV色环）
def idx_color(i):
    hue = (i * 360 / 28) % 360
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(hue/360, 0.85, 0.95)
    return (int(r*255), int(g*255), int(b*255), 255)

# 收集所有面
faces = []
for el_idx, el in enumerate(model['elements']):
    pts = apply_rotation(el['from'], el['to'], el.get('rotation'))
    face_data = [
        ('north', [0,1,3,2]),
        ('south', [4,5,7,6]),
        ('west',  [0,2,6,4]),
        ('east',  [1,3,7,5]),
        ('down',  [0,1,5,4]),
        ('up',    [2,3,7,6]),
    ]
    for face_name, idxs in face_data:
        face_pts = [pts[i] for i in idxs]
        avg_z = sum(p[2] for p in face_pts) / 4
        faces.append((avg_z, el_idx, face_name, face_pts))

faces.sort(key=lambda f: f[0], reverse=True)

def render(proj_fn, w, h, title):
    img = Image.new('RGBA', (w, h), (245, 245, 245, 255))
    draw = ImageDraw.Draw(img)
    # 画网格
    for gx in range(0, w, 20):
        draw.line([(gx, 0), (gx, h)], fill=(220,220,220,255))
    for gy in range(0, h, 20):
        draw.line([(0, gy), (w, gy)], fill=(220,220,220,255))

    for avg_z, el_idx, face_name, face_pts in faces:
        pts_2d = [proj_fn(p) for p in face_pts]
        color = idx_color(el_idx)
        draw.polygon(pts_2d, fill=color, outline=(50,50,50,255))

    return img

# 俯视图 XZ（顶视）
def proj_top(p):
    scale = 16
    cx, cy = 50, 30
    return (int(cx + (p[0]) * scale), int(cy - (p[2]) * scale))

img = render(proj_top, 320, 400, 'top')
img.save('tools/tmp/v2_top.png')

# 前视图 XY（从南看）
def proj_front(p):
    scale = 16
    cx, cy = 50, 380
    return (int(cx + (p[0]) * scale), int(cy - (p[1]) * scale))

img = render(proj_front, 320, 420, 'front')
img.save('tools/tmp/v2_front.png')

# 侧视图 YZ（从东看，Z横，Y纵）
def proj_side(p):
    scale = 16
    cx, cy = 30, 380
    return (int(cx + (p[2]) * scale), int(cy - (p[1]) * scale))

img = render(proj_side, 400, 420, 'side')
img.save('tools/tmp/v2_side.png')

# 等距视图
def proj_iso(p):
    scale = 11
    cx, cy = 200, 200
    x, y, z = p[0]-8, p[1]-12, p[2]-10
    px = (x - z) * math.cos(math.radians(30))
    py = y - (x + z) * math.sin(math.radians(30))
    return (int(cx + px * scale), int(cy - py * scale))

img = render(proj_iso, 400, 400, 'iso')
img.save('tools/tmp/v2_iso.png')

print('v2 渲染完成: v2_top.png, v2_front.png, v2_side.png, v2_iso.png')

# 转ASCII（用灰度）
for name, path in [('俯视图', 'tools/tmp/v2_top.png'),
                   ('前视图(从南看)', 'tools/tmp/v2_front.png'),
                   ('侧视图(从东看)', 'tools/tmp/v2_side.png'),
                   ('等距视图', 'tools/tmp/v2_iso.png')]:
    img = Image.open(path).convert('RGBA')
    w, h = img.size
    target_w = 90
    scale = target_w / w
    new_h = int(h * scale * 0.5)
    img = img.resize((target_w, new_h), Image.LANCZOS)
    print(f'\n{"="*target_w}')
    print(f'{name}')
    print(f'{"="*target_w}')
    chars = ' .:-=+*#%@'
    for y in range(new_h):
        line = ''
        for x in range(target_w):
            r, g, b, a = img.getpixel((x, y))
            if a < 30:
                line += ' '
            elif r > 240 and g > 240 and b > 240:
                line += '.'  # 背景
            else:
                lum = (r * 299 + g * 587 + b * 114) / 1000
                idx = min(len(chars)-1, int(lum / 256 * len(chars)))
                line += chars[idx]
        print(line)
