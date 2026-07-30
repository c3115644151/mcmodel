/**
 * 纺车结构深度分析工具
 *
 * 在 analyze_model.js 基础上增加：
 * 1. 按几何特征自动聚类元素（桌腿/斜板/轮盘/辐条/线/支架）
 * 2. 输出每个元素的角色推断
 * 3. 输出俯视图、侧视图（XZ, XY, YZ 投影）
 * 4. 输出建议的碰撞箱（按部件分组）
 *
 * 用法: node tools/analyze_spinning.js <模型json> [y旋转]
 */

const fs = require('fs');
const path = require('path');

const modelPath = process.argv[2];
if (!modelPath) {
  console.error('用法: node tools/analyze_spinning.js <模型json> [y旋转]');
  process.exit(1);
}
const yRot = parseInt(process.argv[3]) || 0;
const model = JSON.parse(fs.readFileSync(modelPath, 'utf-8'));
const transY = (model.transform && model.transform.translation)
  ? model.transform.translation[1] : 0;

function getRotatedAABB(el) {
  if (!el.rotation || el.rotation.angle === 0) {
    return { from: [...el.from], to: [...el.to] };
  }
  const rot = el.rotation;
  const origin = rot.origin || [8, 8, 8];
  const angle = rot.angle * Math.PI / 180;
  const corners = [
    [el.from[0], el.from[1], el.from[2]],
    [el.to[0],   el.from[1], el.from[2]],
    [el.from[0], el.to[1],   el.from[2]],
    [el.to[0],   el.to[1],   el.from[2]],
    [el.from[0], el.from[1], el.to[2]],
    [el.to[0],   el.from[1], el.to[2]],
    [el.from[0], el.to[1],   el.to[2]],
    [el.to[0],   el.to[1],   el.to[2]]
  ];
  const transformed = corners.map(p => {
    const [x, y, z] = p;
    const dx = x - origin[0], dy = y - origin[1], dz = z - origin[2];
    const cos = Math.cos(angle), sin = Math.sin(angle);
    if (rot.axis === 'x') {
      return [origin[0] + dx, origin[1] + dy * cos - dz * sin, origin[2] + dy * sin + dz * cos];
    } else if (rot.axis === 'y') {
      return [origin[0] + dx * cos + dz * sin, origin[1] + dy, origin[2] - dx * sin + dz * cos];
    } else if (rot.axis === 'z') {
      return [origin[0] + dx * cos - dy * sin, origin[1] + dx * sin + dy * cos, origin[2] + dz];
    }
    return p;
  });
  return {
    from: [
      Math.min(...transformed.map(p => p[0])),
      Math.min(...transformed.map(p => p[1])),
      Math.min(...transformed.map(p => p[2]))
    ],
    to: [
      Math.max(...transformed.map(p => p[0])),
      Math.max(...transformed.map(p => p[1])),
      Math.max(...transformed.map(p => p[2]))
    ]
  };
}

function rotateCW(coord, deg) {
  const [x, y, z] = coord;
  const dx = x - 8, dz = z - 8;
  switch (deg) {
    case 0:   return [x, y, z];
    case 90:  return [8 - dz, y, 8 + dx];
    case 180: return [8 - dx, y, 8 - dz];
    case 270: return [8 + dz, y, 8 - dx];
    default:  return [x, y, z];
  }
}

function rotateAABBCW(aabb, deg) {
  if (deg === 0) return { from: [...aabb.from], to: [...aabb.to] };
  const pts = [
    rotateCW([aabb.from[0], aabb.from[1], aabb.from[2]], deg),
    rotateCW([aabb.to[0],   aabb.from[1], aabb.from[2]], deg),
    rotateCW([aabb.from[0], aabb.to[1],   aabb.from[2]], deg),
    rotateCW([aabb.to[0],   aabb.to[1],   aabb.from[2]], deg),
    rotateCW([aabb.from[0], aabb.from[1], aabb.to[2]], deg),
    rotateCW([aabb.to[0],   aabb.from[1], aabb.to[2]], deg),
    rotateCW([aabb.from[0], aabb.to[1],   aabb.to[2]], deg),
    rotateCW([aabb.to[0],   aabb.to[1],   aabb.to[2]], deg)
  ];
  return {
    from: [Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1])), Math.min(...pts.map(p => p[2]))],
    to:   [Math.max(...pts.map(p => p[0])), Math.max(...pts.map(p => p[1])), Math.max(...pts.map(p => p[2]))]
  };
}

const r = v => Math.round(v * 100) / 100;
const pad = (s, n) => String(s).padEnd(n);

const elements = model.elements.map((el, i) => {
  const base = getRotatedAABB(el);
  let aabb = { from: [...base.from], to: [...base.to] };
  return {
    index: i,
    aabb: aabb,
    rawFrom: el.from,
    rawTo: el.to,
    rotation: el.rotation || null,
    name: el.name || ''
  };
});

let rawMinY = Infinity;
elements.forEach(el => {
  if (el.aabb.from[1] < rawMinY) rawMinY = el.aabb.from[1];
});
const adjustedMinY = rawMinY - transY;
const yOff = Math.abs(Math.min(0, adjustedMinY));

elements.forEach(el => {
  el.aabb.from[1] = el.aabb.from[1] - transY + yOff;
  el.aabb.to[1]   = el.aabb.to[1]   - transY + yOff;
  if (yRot) el.aabb = rotateAABBCW(el.aabb, yRot);
});

// ==== 按特征聚类 ====
console.log('='.repeat(80));
console.log(`纺车结构分析: ${path.basename(modelPath)} (CW Y旋转 ${yRot}°)`);
console.log('='.repeat(80));

console.log('\n【元素清单 + 角色推断】');
console.log(pad('idx',4) + pad('角色', 12) + pad('AABB(from->to)', 50) + pad('尺寸(X×Y×Z)', 16) + pad('旋转', 14) + '特征');
elements.forEach(el => {
  const a = el.aabb;
  const sx = r(a.to[0]-a.from[0]), sy = r(a.to[1]-a.from[1]), sz = r(a.to[2]-a.from[2]);
  const cx = (a.from[0]+a.to[0])/2, cy = (a.from[1]+a.to[1])/2, cz = (a.from[2]+a.to[2])/2;
  const aabbStr = `(${r(a.from[0])},${r(a.from[1])},${r(a.from[2])})->(${r(a.to[0])},${r(a.to[1])},${r(a.to[2])})`;
  const sizeStr = `${sx}×${sy}×${sz}`;
  const rotStr = el.rotation ? `${el.rotation.axis}@${el.rotation.angle}°` : '-';

  // 角色推断
  let role = '?';
  let feat = [];
  // 桌腿：底部(y<2)、单格大小、柱状
  if (a.from[1] < 1.5) {
    if (sx < 3 && sz < 5 && sy > 6) { role = '桌腿'; feat.push('底柱'); }
  }
  // 斜板：覆盖大范围、薄板
  if (sx > 6 && sz > 14 && sy < 7) { role = '斜板'; feat.push('大板'); }
  // 薄片(Z向跨度小但XY大)：可能是轮盘面或线
  if (sy > 10 && sz > 10 && sx < 1.2) { role = '轮盘面?'; feat.push('薄板X'); }
  if (sx < 1.2 && sy < 1.2 && sz > 6) { role = '线?'; feat.push('细长Z'); }
  // 立柱(纵向)
  if (sy > 5 && sx < 1.5 && sz < 2.5 && a.from[1] > 5) { role = '支架/立柱'; feat.push('立柱'); }
  // 辐条/小支架
  if (sx < 1.5 && sy < 5 && sz < 5) { role = '辐条?'; feat.push('小块'); }

  console.log(pad('['+el.index+']',4) + pad(role, 12) + pad(aabbStr, 50) + pad(sizeStr, 16) + pad(rotStr, 14) + feat.join(','));
});

// ==== 投影图：俯视 XZ（按Y层）====
function drawProjection(planes, axis, w, h, wRange, hRange, label) {
  // axis: 'XY' (前视，X横Y纵), 'XZ'(俯视，X横Z纵), 'YZ'(侧视，Z横Y纵)
  const grid = [];
  for (let i = 0; i < h; i++) {
    grid.push(new Array(w).fill(' '));
  }
  const [wMin, wMax] = wRange;
  const [hMin, hMax] = hRange;
  const wScale = w / (wMax - wMin);
  const hScale = h / (hMax - hMin);

  elements.forEach(el => {
    const a = el.aabb;
    let w1, w2, h1, h2;
    if (axis === 'XZ') { w1 = a.from[0]; w2 = a.to[0]; h1 = a.from[2]; h2 = a.to[2]; }
    else if (axis === 'XY') { w1 = a.from[0]; w2 = a.to[0]; h1 = a.from[1]; h2 = a.to[1]; }
    else if (axis === 'YZ') { w1 = a.from[2]; w2 = a.to[2]; h1 = a.from[1]; h2 = a.to[1]; }
    const wi1 = Math.max(0, Math.floor((w1 - wMin) * wScale));
    const wi2 = Math.min(w-1, Math.floor((w2 - wMin) * wScale));
    const hi1 = Math.max(0, Math.floor((hMax - h2) * hScale)); // 反转Y
    const hi2 = Math.min(h-1, Math.floor((hMax - h1) * hScale));
    const ch = (el.index % 10).toString();
    for (let i = hi1; i <= hi2; i++) {
      for (let j = wi1; j <= wi2; j++) {
        if (grid[i][j] === ' ') grid[i][j] = ch;
        else if (grid[i][j] !== ch) grid[i][j] = '#';
      }
    }
  });

  console.log('\n' + label);
  let header = '       ';
  if (axis === 'XZ' || axis === 'XY') {
    for (let j = 0; j < w; j++) {
      const x = wMin + (j+0.5) / wScale;
      header += (Math.round(x) % 4 === 0) ? '|' : ' ';
    }
  } else {
    for (let j = 0; j < w; j++) {
      const z = wMin + (j+0.5) / wScale;
      header += (Math.round(z) % 4 === 0) ? '|' : ' ';
    }
  }
  console.log(header);
  grid.forEach((row, i) => {
    let label2 = '      ';
    const hv = hMax - (i+0.5) / hScale;
    if (Math.round(hv) % 4 === 0) label2 = String(Math.round(hv)).padStart(4) + '--';
    console.log(label2 + row.join(''));
  });
}

// 俯视 XZ（整模型）
console.log('\n' + '='.repeat(80));
console.log('俯视图 XZ（顶视，X横=东西，Z纵=北(+上)南(-下)）');
console.log('='.repeat(80));
drawProjection(null, 'XZ', 32, 32, [3, 13], [-2, 22], '俯视 XZ（数字=元素idx末位，#=多个重叠）');

// 前视 XY（从南看，+Z方向看过来）
console.log('\n' + '='.repeat(80));
console.log('前视图 XY（从南向北看，X横=东西，Y纵=上下）');
console.log('='.repeat(80));
drawProjection(null, 'XY', 24, 32, [3, 13], [0, 26], '前视 XY');

// 侧视 YZ（从东看，+X方向看过来）
console.log('\n' + '='.repeat(80));
console.log('侧视图 YZ（从东向西看，Z横=北(右)南(左)，Y纵=上下）');
console.log('注：玩家在东侧向西看，所以右侧=北(-Z)，左侧=南(+Z)');
console.log('='.repeat(80));
drawProjection(null, 'YZ', 32, 32, [-2, 22], [0, 26], '侧视 YZ');

// 按 Y 分段输出元素
console.log('\n' + '='.repeat(80));
console.log('按 Y 高度分段（识别上中下三层）');
console.log('='.repeat(80));
const layers = [
  { name: '底层 (Y 0-7) - 桌腿区', min: 0, max: 7 },
  { name: '中层 (Y 7-12) - 斜板+支架区', min: 7, max: 12 },
  { name: '上层 (Y 12-25) - 框架+轮盘区', min: 12, max: 25 }
];
layers.forEach(l => {
  console.log(`\n▼ ${l.name}`);
  elements.forEach(el => {
    const a = el.aabb;
    // 元素的 Y 范围与本层有交集
    if (a.to[1] > l.min && a.from[1] < l.max) {
      const cx = (a.from[0]+a.to[0])/2, cz = (a.from[2]+a.to[2])/2;
      const sx = r(a.to[0]-a.from[0]), sy = r(a.to[1]-a.from[1]), sz = r(a.to[2]-a.from[2]);
      console.log(`  [${el.index}] X[${r(a.from[0])},${r(a.to[0])}] Y[${r(a.from[1])},${r(a.to[1])}] Z[${r(a.from[2])},${r(a.to[2])}]  尺寸 ${sx}×${sy}×${sz}  中心(${r(cx)},${r(cz)})`);
    }
  });
});

// 按 X 分段（区分左右轮盘）
console.log('\n' + '='.repeat(80));
console.log('按 X 位置分段（识别左右轮盘）');
console.log('='.repeat(80));
const xLayers = [
  { name: '西侧 (X 4-7) - 可能左轮盘', min: 4, max: 7.1 },
  { name: '中间 (X 7-9) - 可能线/支架', min: 7, max: 9 },
  { name: '东侧 (X 9-12) - 可能右轮盘', min: 9, max: 12 }
];
xLayers.forEach(l => {
  console.log(`\n▼ ${l.name}`);
  elements.forEach(el => {
    const a = el.aabb;
    if (a.to[0] > l.min && a.from[0] < l.max) {
      const sx = r(a.to[0]-a.from[0]), sy = r(a.to[1]-a.from[1]), sz = r(a.to[2]-a.from[2]);
      const rotStr = el.rotation ? `${el.rotation.axis}@${el.rotation.angle}°` : '-';
      console.log(`  [${el.index}] X[${r(a.from[0])},${r(a.to[0])}] Y[${r(a.from[1])},${r(a.to[1])}] Z[${r(a.from[2])},${r(a.to[2])}]  尺寸 ${sx}×${sy}×${sz}  旋转 ${rotStr}`);
    }
  });
});

// 按 Z 分段（区分前后）
console.log('\n' + '='.repeat(80));
console.log('按 Z 位置分段（识别前后）');
console.log('='.repeat(80));
const zLayers = [
  { name: '北端 (Z -1~3) - 第三条腿区', min: -2, max: 3 },
  { name: '中段 (Z 3~12) - 斜板中段', min: 3, max: 12 },
  { name: '南端 (Z 12~21) - 主桌腿区', min: 12, max: 22 }
];
zLayers.forEach(l => {
  console.log(`\n▼ ${l.name}`);
  elements.forEach(el => {
    const a = el.aabb;
    if (a.to[2] > l.min && a.from[2] < l.max) {
      const sx = r(a.to[0]-a.from[0]), sy = r(a.to[1]-a.from[1]), sz = r(a.to[2]-a.from[2]);
      const rotStr = el.rotation ? `${el.rotation.axis}@${el.rotation.angle}°` : '-';
      console.log(`  [${el.index}] X[${r(a.from[0])},${r(a.to[0])}] Y[${r(a.from[1])},${r(a.to[1])}] Z[${r(a.from[2])},${r(a.to[2])}]  尺寸 ${sx}×${sy}×${sz}  旋转 ${rotStr}`);
    }
  });
});
