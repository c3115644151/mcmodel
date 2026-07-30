/**
 * 模型结构分析工具
 *
 * 功能：
 * 1. 读取 BlockBench 导出的 JSON 模型
 * 2. 处理元素级 rotation（任意轴任意角度）→ 旋转后 AABB
 * 3. 处理模型级 transform.translation（Y 偏移）
 * 4. 可选应用 blockstate CW Y 旋转（模拟 facing=south/east/west 的视觉模型）
 * 5. 输出：
 *    a. 模型概览（几何范围、占用格子）
 *    b. 组件清单（每个元素的索引、AABB、尺寸、所属格子、旋转轴）
 *    c. 分层结构图解（按 Y 每 16 像素分层，每层 3×3 格子的 box 列表）
 *
 * 用法：
 *   node tools/analyze_model.js <模型json> [y旋转角度]
 *
 * 示例：
 *   node tools/analyze_model.js src/main/resources/assets/pastoral_home/models/block/wishing_well.json
 *   node tools/analyze_model.js src/main/resources/assets/pastoral_home/models/block/wishing_well.json 180
 */

const fs = require('fs');
const path = require('path');

// ==== 参数 ====
const modelPath = process.argv[2];
if (!modelPath) {
  console.error('用法: node tools/analyze_model.js <模型json> [y旋转角度]');
  process.exit(1);
}
const yRot = parseInt(process.argv[3]) || 0;

const model = JSON.parse(fs.readFileSync(modelPath, 'utf-8'));

// 模型级 transform.translation（模型导出时整体偏移）
const transY = (model.transform && model.transform.translation)
  ? model.transform.translation[1] : 0;

// ==== 计算元素旋转后的 AABB ====
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
      return [origin[0] + dx,
              origin[1] + dy * cos - dz * sin,
              origin[2] + dy * sin + dz * cos];
    } else if (rot.axis === 'y') {
      return [origin[0] + dx * cos + dz * sin,
              origin[1] + dy,
              origin[2] - dx * sin + dz * cos];
    } else if (rot.axis === 'z') {
      return [origin[0] + dx * cos - dy * sin,
              origin[1] + dx * sin + dy * cos,
              origin[2] + dz];
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

// ==== MC CW Y 旋转（绕方块中心 (8,8,8)）====
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
    from: [
      Math.min(...pts.map(p => p[0])),
      Math.min(...pts.map(p => p[1])),
      Math.min(...pts.map(p => p[2]))
    ],
    to: [
      Math.max(...pts.map(p => p[0])),
      Math.max(...pts.map(p => p[1])),
      Math.max(...pts.map(p => p[2]))
    ]
  };
}

const r = v => Math.round(v * 100) / 100;
const pad = (s, n) => String(s).padEnd(n);

// ==== 计算所有元素的 AABB（应用 Y 偏移 + 可选 CW 旋转）====
const elements = model.elements.map((el, i) => {
  const base = getRotatedAABB(el);
  // Y 偏移：模型 transform.translation[1] 表示模型整体上移 transY，
  // 同时如果原始 yMin<0，也需要上移使 yMin=0 对应方块底部。
  // generate_collision_v3 的 yOffset = abs(min(0, minY))，这里复用同样逻辑（后续统一加）
  let aabb = { from: [...base.from], to: [...base.to] };
  return {
    index: i,
    aabb: aabb,
    rotation: el.rotation || null,
    name: el.name || ''
  };
});

// 计算全局 Y 偏移
let rawMinY = Infinity, rawMaxY = -Infinity;
let minX = Infinity, maxX = -Infinity;
let minZ = Infinity, maxZ = -Infinity;
elements.forEach(el => {
  if (el.aabb.from[0] < minX) minX = el.aabb.from[0];
  if (el.aabb.to[0] > maxX) maxX = el.aabb.to[0];
  if (el.aabb.from[1] < rawMinY) rawMinY = el.aabb.from[1];
  if (el.aabb.to[1] > rawMaxY) rawMaxY = el.aabb.to[1];
  if (el.aabb.from[2] < minZ) minZ = el.aabb.from[2];
  if (el.aabb.to[2] > maxZ) maxZ = el.aabb.to[2];
});

// Y 偏移 = transform.translation[1]（模型整体上移） + abs(min(0, rawMinY))（负 Y 拉回 0）
// 注意：transform.translation[1] 为正表示模型上移，方块坐标需要减去它使底部对齐 0；
// 但 generate_collision_v3 的逻辑是 yOffset = abs(min(0, minY))，未处理 transform。
// 这里统一：先减 transY，再加 abs(min(0, minY-transY))
const adjustedMinY = rawMinY - transY;
const yOff = Math.abs(Math.min(0, adjustedMinY));

// 应用 Y 偏移 + CW 旋转
elements.forEach(el => {
  el.aabb.from[1] = el.aabb.from[1] - transY + yOff;
  el.aabb.to[1]   = el.aabb.to[1]   - transY + yOff;
  if (yRot) el.aabb = rotateAABBCW(el.aabb, yRot);
});

// 重新计算范围
let minY = Infinity, maxY = -Infinity;
elements.forEach(el => {
  if (el.aabb.from[0] < minX) minX = el.aabb.from[0];
  if (el.aabb.to[0] > maxX) maxX = el.aabb.to[0];
  if (el.aabb.from[1] < minY) minY = el.aabb.from[1];
  if (el.aabb.to[1] > maxY) maxY = el.aabb.to[1];
  if (el.aabb.from[2] < minZ) minZ = el.aabb.from[2];
  if (el.aabb.to[2] > maxZ) maxZ = el.aabb.to[2];
});

const gridXMin = Math.floor(minX / 16);
const gridXMax = Math.ceil(maxX / 16);
const gridZMin = Math.floor(minZ / 16);
const gridZMax = Math.ceil(maxZ / 16);
const gridYMin = Math.floor(minY / 16);
const gridYMax = Math.ceil(maxY / 16);

const BAR = '='.repeat(70);
console.log(BAR);
console.log(`模型结构分析: ${path.basename(modelPath)}`);
console.log(BAR);
console.log(`几何范围: X[${r(minX)},${r(maxX)}]  Y[${r(minY)},${r(maxY)}]  Z[${r(minZ)},${r(maxZ)}]`);
console.log(`transform.translation[1] = ${transY}, Y偏移(拉回0) = ${yOff}`);
console.log(`占用格子: X[${gridXMin},${gridXMax-1}] × Z[${gridZMin},${gridZMax-1}] × Y[${gridYMin},${gridYMax-1}]`);
console.log(`CW Y旋转: ${yRot}°`);
console.log('');

// ==== 组件清单 ====
console.log(BAR);
console.log('组件清单（旋转后 AABB，已应用 Y 偏移' + (yRot ? ` + CW ${yRot}°` : '') + '）');
console.log(BAR);
console.log(pad('idx',4) + pad('from → to', 52) + pad('尺寸', 18) + pad('格(X,Y,Z)', 14) + '旋转');
elements.forEach(el => {
  const a = el.aabb;
  const sx = r(a.to[0]-a.from[0]), sy = r(a.to[1]-a.from[1]), sz = r(a.to[2]-a.from[2]);
  const cx = (a.from[0]+a.to[0])/2, cy = (a.from[1]+a.to[1])/2, cz = (a.from[2]+a.to[2])/2;
  const gx = Math.floor(cx/16), gy = Math.floor(cy/16), gz = Math.floor(cz/16);
  const aabbStr = `(${r(a.from[0])},${r(a.from[1])},${r(a.from[2])})→(${r(a.to[0])},${r(a.to[1])},${r(a.to[2])})`;
  const sizeStr = `${sx}×${sy}×${sz}`;
  const gridStr = `X${gx},Y${gy},Z${gz}`;
  const rotStr = el.rotation ? `${el.rotation.axis}@${el.rotation.angle}°` : '-';
  console.log(pad('['+el.index+']',4) + pad(aabbStr, 52) + pad(sizeStr, 18) + pad(gridStr, 14) + rotStr);
});
console.log('');

// ==== 格子命名 ====
const partNames = {
  '0,0': 'CENTER',
  '-1,0': 'WEST', '1,0': 'EAST',
  '0,1': 'NORTH', '0,-1': 'SOUTH',
  '-1,1': 'NW', '1,1': 'NE',
  '-1,-1': 'SW', '1,-1': 'SE'
};

// ==== 分层结构图解 ====
console.log(BAR);
console.log('分层结构图解（每格的碰撞箱，按 Y 每 16 像素分层）');
console.log('坐标: X 西-东, Z 北+南-（Minecraft: +Z=南）, Y 上+');
console.log(BAR);

// 收集每个 (gx, gz, gy) 的 box 列表
const grid = {};
for (let gy = gridYMin; gy < gridYMax; gy++) {
  for (let gz = gridZMax - 1; gz >= gridZMin; gz--) {
    for (let gx = gridXMin; gx < gridXMax; gx++) {
      const key = `${gx},${gz},${gy}`;
      grid[key] = [];
      elements.forEach(el => {
        const a = el.aabb;
        // 裁剪到格子内
        const lx1 = Math.max(a.from[0] - gx*16, 0);
        const lx2 = Math.min(a.to[0]  - gx*16, 16);
        const lz1 = Math.max(a.from[2] - gz*16, 0);
        const lz2 = Math.min(a.to[2]  - gz*16, 16);
        const ly1 = Math.max(a.from[1] - gy*16, 0);
        const ly2 = Math.min(a.to[1]  - gy*16, 16);
        if (lx2 > lx1 + 0.01 && lz2 > lz1 + 0.01 && ly2 > ly1 + 0.01) {
          grid[key].push({
            idx: el.index,
            box: [r(lx1), r(ly1), r(lz1), r(lx2), r(ly2), r(lz2)]
          });
        }
      });
    }
  }
}

// 输出每层
for (let gy = gridYMin; gy < gridYMax; gy++) {
  console.log(`\n▼ 第 ${gy} 层  (世界 Y = ${gy*16} ~ ${(gy+1)*16})`);
  // 从北到南（Z 大到小 = 北到南，因为 +Z=南... 实际 +Z=南，所以 Z 大=南）
  // 为了俯视图直观：上=北(Z+)，下=南(Z-)，左=西(X-)，右=东(X+)
  for (let gz = gridZMax - 1; gz >= gridZMin; gz--) {
    let rowLabel = (gz === gridZMax-1) ? '北(Z+) ' : (gz === gridZMin) ? '南(Z-) ' : '       ';
    let line = rowLabel;
    for (let gx = gridXMin; gx < gridXMax; gx++) {
      const key = `${gx},${gz},${gy}`;
      const boxes = grid[key] || [];
      const partName = partNames[`${gx},${gz}`] || `(${gx},${gz})`;
      const tag = boxes.length === 0 ? '  ·  ' : ` ${partName.padEnd(6)}(${boxes.length})`;
      line += tag + '  |  ';
    }
    console.log(line);
  }
  // 详细列出每格的 box
  for (let gz = gridZMax - 1; gz >= gridZMin; gz--) {
    for (let gx = gridXMin; gx < gridXMax; gx++) {
      const key = `${gx},${gz},${gy}`;
      const boxes = grid[key] || [];
      const partName = partNames[`${gx},${gz}`] || `(${gx},${gz})`;
      if (boxes.length > 0) {
        console.log(`  [${partName}] 第${gy}层:`);
        boxes.forEach(b => {
          console.log(`      [${b.idx}] box(${b.box.join(', ')})`);
        });
      }
    }
  }
}

console.log('\n' + BAR);
console.log('说明：每个 box 为局部格子坐标 (x1,y1,z1, x2,y2,z2)，范围 0~16。');
console.log('      idx 对应上方组件清单的元素索引。');
console.log(BAR);
