"""在纺车纹理图上标注每个元素的 UV 区域，辅助识别各部件"""
import json
import os
from PIL import Image, ImageDraw, ImageFont

MODEL = 'src/main/resources/assets/pastoral_home/models/block/spinning_wheel.json'
TEX = 'src/main/resources/assets/pastoral_home/textures/block/spinning_wheel.png'
OUT = 'tools/tmp/spinning_wheel_uv_annotated.png'

# 纹理是 128x128，UV 单位 1 = 8 像素 (128/16)
TEX_SIZE = 128
UV_SCALE = TEX_SIZE / 16  # 8

model = json.load(open(MODEL, encoding='utf-8'))
img = Image.open(TEX).convert('RGBA')
# 放大 2 倍方便标注
img = img.resize((TEX_SIZE * 2, TEX_SIZE * 2), Image.NEAREST)
draw = ImageDraw.Draw(img)

try:
    font = ImageFont.truetype("arial.ttf", 14)
except:
    font = ImageFont.load_default()

# 颜色循环
colors = ['#FF0000','#00FF00','#0000FF','#FFFF00','#FF00FF','#00FFFF','#FF8800',
          '#8800FF','#0088FF','#FF0088','#88FF00','#00FF88','#FF4444','#44FF44',
          '#4444FF','#FFFF44','#FF44FF','#44FFFF','#FF8844','#8844FF','#44FF88',
          '#FFAA00','#AA00FF','#00AAFF','#FF00AA','#AAFF00','#00FFAA']

for i, el in enumerate(model['elements']):
    color = colors[i % len(colors)]
    # 对每个面标注 UV
    for face_name, face in el.get('faces', {}).items():
        uv = face['uv']  # [u1, v1, u2, v2]
        u1, v1, u2, v2 = uv
        # 转像素
        px1 = u1 * UV_SCALE * 2
        py1 = v1 * UV_SCALE * 2
        px2 = u2 * UV_SCALE * 2
        py2 = v2 * UV_SCALE * 2
        x1, y1 = min(px1, px2), min(py1, py2)
        x2, y2 = max(px1, px2), max(py1, py2)
        # 画框
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        # 标注 idx
        label = f'{i}'
        try:
            bbox = draw.textbbox((0,0), label, font=font)
            tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        except:
            tw, th = 10, 12
        # 在框的左上角写 idx
        tx = x1 + 1
        ty = y1 + 1
        # 加个背景
        draw.rectangle([tx-1, ty-1, tx+tw+2, ty+th+2], fill=color)
        draw.text((tx, ty), label, fill='black', font=font)

img.save(OUT)
print(f'已生成: {OUT}')
print(f'纹理尺寸: {TEX_SIZE}x{TEX_SIZE} (UV 1 = {UV_SCALE} 像素)')

# 同时输出每个元素的 UV 范围汇总
print('\n各元素 UV 范围（纹理坐标 0-16）：')
for i, el in enumerate(model['elements']):
    uvs = []
    for face_name, face in el.get('faces', {}).items():
        uv = face['uv']
        uvs.append(f'{face_name}:{uv[0]:.2f},{uv[1]:.2f}-{uv[2]:.2f},{uv[3]:.2f}')
    print(f'[{i:2d}] ' + ' '.join(uvs))
