"""把渲染的等距视图转成彩色 ASCII art，验证纺车整体结构"""
from PIL import Image

for view_name, path in [
    ('等距视图', 'tools/tmp/spinning_iso.png'),
    ('侧视图(从东看)', 'tools/tmp/spinning_side.png'),
    ('前视图(从南看)', 'tools/tmp/spinning_front.png'),
    ('俯视图', 'tools/tmp/spinning_top.png'),
]:
    img = Image.open(path).convert('RGBA')
    w, h = img.size
    # 缩小到合适宽度
    target_w = 80
    scale = target_w / w
    new_h = int(h * scale * 0.5)  # 字符高宽比约2:1
    img = img.resize((target_w, new_h), Image.LANCZOS)

    print(f'\n{"="*target_w}')
    print(f'{view_name} ({path})')
    print(f'{"="*target_w}')
    chars = ' .:-=+*#%@'
    for y in range(new_h):
        line = ''
        for x in range(target_w):
            r, g, b, a = img.getpixel((x, y))
            if a < 30:
                line += ' '
            else:
                # 亮度
                lum = (r * 299 + g * 587 + b * 114) / 1000
                idx = min(len(chars)-1, int(lum / 256 * len(chars)))
                line += chars[idx]
        print(line)
