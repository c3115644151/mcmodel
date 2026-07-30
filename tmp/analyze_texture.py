"""提取纺车关键元素的纹理面，分析视觉形状（圆形轮盘 vs 方形框架）"""
import json
import os
from PIL import Image

MODEL = 'src/main/resources/assets/pastoral_home/models/block/spinning_wheel.json'
TEX = 'src/main/resources/assets/pastoral_home/textures/block/spinning_wheel.png'

model = json.load(open(MODEL, encoding='utf-8'))
tex = Image.open(TEX).convert('RGBA')
TEX_SIZE = tex.size[0]
UV_FACTOR = TEX_SIZE / 16

# 为每个元素提取主要面（east/west，即X方向的面，最能显示轮盘形状）
# 并分析像素，判断是否是圆形
print(f'纹理尺寸: {TEX_SIZE}x{TEX_SIZE}')
print()

def analyze_region(uv, name, idx):
    u1, v1, u2, v2 = uv
    px1, py1 = int(u1 * UV_FACTOR), int(v1 * UV_FACTOR)
    px2, py2 = int(u2 * UV_FACTOR), int(v2 * UV_FACTOR)
    w, h = px2 - px1, py2 - py1
    if w <= 0 or h <= 0:
        return
    region = tex.crop((px1, py1, px2, py2))
    # 分析非透明像素的分布
    pixels = region.load()
    non_transparent = 0
    bbox_x_min, bbox_y_min = w, h
    bbox_x_max, bbox_y_max = 0, 0
    # 按8x8网格统计
    grid_w, grid_h = max(8, w), max(8, h)
    grid = [['.' for _ in range(grid_w)] for _ in range(grid_h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a > 30:
                non_transparent += 1
                if x < bbox_x_min: bbox_x_min = x
                if x > bbox_x_max: bbox_x_max = x
                if y < bbox_y_min: bbox_y_min = y
                if y > bbox_y_max: bbox_y_max = y
                # 映射到grid
                gx = int(x * grid_w / w)
                gy = int(y * grid_h / h)
                if 0 <= gx < grid_w and 0 <= gy < grid_h:
                    # 用亮度字符
                    lum = (r + g + b) // 3
                    if lum > 200: grid[gy][gx] = ' '
                    elif lum > 150: grid[gy][gx] = '·'
                    elif lum > 100: grid[gy][gx] = '+'
                    elif lum > 50: grid[gy][gx] = '#'
                    else: grid[gy][gx] = '@'

    print(f'[{idx:2d}] {name} UV={uv} 像素区域 {w}x{h}')
    print(f'     非透明像素: {non_transparent}/{w*h} ({100*non_transparent/(w*h):.0f}%)')
    if non_transparent > 0:
        print(f'     内容边界: x[{bbox_x_min},{bbox_x_max}] y[{bbox_y_min},{bbox_y_max}]')
        # 判断是否圆形：非透明像素比例
        ratio = non_transparent / (w * h)
        if ratio < 0.6:
            shape = '可能圆形/不规则（非填满）'
        else:
            shape = '填满矩形'
        print(f'     形状推断: {shape} (填充率 {ratio:.2f})')
        # 输出ASCII
        print('     ASCII预览:')
        for row in grid:
            print('       ' + ''.join(row))
    print()

# 重点分析轮盘相关元素
print('=' * 70)
print('大轮盘相关元素（[0][1][2][3][9][10]）')
print('=' * 70)
for idx in [0, 1, 2, 3, 9, 10]:
    el = model['elements'][idx]
    # east 面（X+ 方向）
    for face_name in ['east', 'west', 'up']:
        if face_name in el.get('faces', {}):
            uv = el['faces'][face_name]['uv']
            analyze_region(uv, f'el[{idx}].{face_name}', idx)
            break  # 只看一个面

print('=' * 70)
print('小轮盘相关元素（[22][23][24][25]）')
print('=' * 70)
for idx in [22, 23, 24, 25]:
    el = model['elements'][idx]
    for face_name in ['east', 'west', 'up', 'north']:
        if face_name in el.get('faces', {}):
            uv = el['faces'][face_name]['uv']
            analyze_region(uv, f'el[{idx}].{face_name}', idx)
            break

print('=' * 70)
print('斜板 [18] 和支架 [16][17]')
print('=' * 70)
for idx in [18, 16, 17]:
    el = model['elements'][idx]
    for face_name in ['up', 'east', 'west']:
        if face_name in el.get('faces', {}):
            uv = el['faces'][face_name]['uv']
            analyze_region(uv, f'el[{idx}].{face_name}', idx)
            break

print('=' * 70)
print('两根线 [26][27]')
print('=' * 70)
for idx in [26, 27]:
    el = model['elements'][idx]
    for face_name in ['up', 'east', 'west']:
        if face_name in el.get('faces', {}):
            uv = el['faces'][face_name]['uv']
            analyze_region(uv, f'el[{idx}].{face_name}', idx)
            break

print('=' * 70)
print('桌腿 [19][20][21]')
print('=' * 70)
for idx in [19, 20, 21]:
    el = model['elements'][idx]
    for face_name in ['east', 'west', 'north']:
        if face_name in el.get('faces', {}):
            uv = el['faces'][face_name]['uv']
            analyze_region(uv, f'el[{idx}].{face_name}', idx)
            break
