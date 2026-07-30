/**
 * 纹理分析工具 - 输出纹理的像素布局，帮助理解 UV 映射
 *
 * 用法：node tools/analyze_texture.js <纹理png> [网格大小]
 */
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const texPath = process.argv[2];
if (!texPath) {
  console.error('用法: node tools/analyze_texture.js <纹理png> [网格大小]');
  process.exit(1);
}
const grid = parseInt(process.argv[3]) || 16;

const buf = fs.readFileSync(texPath);
const w = buf.readUInt32BE(16);
const h = buf.readUInt32BE(20);
console.log(`纹理: ${path.basename(texPath)} ${w}x${h}`);

const py = `C:/Users/32800/AppData/Local/Programs/Python/Python313-32/python.exe`;
// 写临时脚本避免转义
const script = `
from PIL import Image
import json
img = Image.open(r'${texPath.replace(/\\/g, '\\\\')}').convert('RGBA')
w, h = img.size
grid = ${grid}
data = {}
for gy in range(0, h, grid):
    for gx in range(0, w, grid):
        px = min(gx + grid//2, w-1)
        py = min(gy + grid//2, h-1)
        r,g,b,a = img.getpixel((px, py))
        data[str(gx)+"_"+str(gy)] = [r,g,b,a]
pixels = list(img.getdata())
non_transparent = [p for p in pixels if p[3] > 0]
if non_transparent:
    avg = tuple(sum(p[i] for p in non_transparent)//len(non_transparent) for i in range(3))
    data["_avg"] = list(avg)
    data["_count"] = len(non_transparent)
    data["_total"] = len(pixels)
print(json.dumps(data))
`;
fs.writeFileSync('_tex_tmp.py', script);
const out = execSync(`"${py}" _tex_tmp.py`, { encoding: 'utf8' });
fs.unlinkSync('_tex_tmp.py');
const data = JSON.parse(out.trim());

console.log(`平均色: RGB(${data._avg.join(',')}) 非透明像素: ${data._count}/${data._total}`);

const cellsX = Math.ceil(w / grid);
const cellsY = Math.ceil(h / grid);
console.log(`\n=== ${w}x${h} 纹理布局（每格 ${grid}px）===`);
for (let gy = 0; gy < cellsY; gy++) {
  let line = '';
  for (let gx = 0; gx < cellsX; gx++) {
    const key = `${gx * grid}_${gy * grid}`;
    const px = data[key];
    if (!px || px[3] === 0) {
      line += '··';
    } else {
      const lum = (px[0] * 0.3 + px[1] * 0.59 + px[2] * 0.11);
      const chars = ' .:-=+*#%@';
      const idx = Math.min(Math.floor(lum / 256 * chars.length), chars.length - 1);
      line += chars[idx] + chars[idx];
    }
  }
  console.log(`y=${(gy * grid).toString().padStart(3)} ${line}`);
}

console.log('\n=== 格子颜色详情 ===');
let count = 0;
for (let gy = 0; gy < cellsY && count < 30; gy++) {
  for (let gx = 0; gx < cellsX && count < 30; gx++) {
    const key = `${gx * grid}_${gy * grid}`;
    const px = data[key];
    if (px && px[3] > 0) {
      console.log(`  (${gx * grid},${gy * grid}): RGB(${px[0]},${px[1]},${px[2]}) a=${px[3]}`);
      count++;
    }
  }
}
