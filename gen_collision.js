/**
 * 纺车碰撞箱生成器
 * 基于结构分析，输出每个部件的精确碰撞箱坐标
 */
const fs = require('fs');
const model = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));

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
    if (rot.axis === 'x') return [origin[0]+dx, origin[1]+dy*cos-dz*sin, origin[2]+dy*sin+dz*cos];
    if (rot.axis === 'y') return [origin[0]+dx*cos+dz*sin, origin[1]+dy, origin[2]-dx*sin+dz*cos];
    if (rot.axis === 'z') return [origin[0]+dx*cos-dy*sin, origin[1]+dx*sin+dy*cos, origin[2]+dz];
    return p;
  });
  return {
    from: [Math.min(...transformed.map(p=>p[0])), Math.min(...transformed.map(p=>p[1])), Math.min(...transformed.map(p=>p[2]))],
    to:   [Math.max(...transformed.map(p=>p[0])), Math.max(...transformed.map(p=>p[1])), Math.max(...transformed.map(p=>p[2]))]
  };
}

const r = v => Math.round(v * 100) / 100;
const transY = (model.transform && model.transform.translation) ? model.transform.translation[1] : 0;
let rawMinY = Infinity;
model.elements.forEach(el => {
  const a = getRotatedAABB(el);
  if (a.from[1] < rawMinY) rawMinY = a.from[1];
});
const yOff = Math.abs(Math.min(0, rawMinY - transY));

// 部件分组定义（基于结构分析）
const groups = {
  '桌腿[19]东南': [19],
  '桌腿[20]中北(第三腿)': [20],
  '桌腿[21]西南': [21],
  '斜板[18]': [18],
  '大轮盘支架[16]西': [16],
  '大轮盘支架[17]东': [17],
  '大轮盘[0]西侧板': [0],
  '大轮盘[9]东侧板': [9],
  '大轮盘[2]中心轴': [2],
  '小轮盘[22]底横块': [22],
  '小轮盘[23]东立柱': [23],
  '小轮盘[24]西立柱': [24],
  '小轮盘[25]倾斜盘面': [25],
  '线[26]上': [26],
  '线[27]下': [27],
};

console.log('部件AABB汇总（已应用Y偏移）:');
console.log('='.repeat(80));
for (const [name, idxs] of Object.entries(groups)) {
  const aabbs = idxs.map(i => {
    const a = getRotatedAABB(model.elements[i]);
    a.from[1] = a.from[1] - transY + yOff;
    a.to[1] = a.to[1] - transY + yOff;
    return { idx: i, a };
  });
  // 合并AABB
  const xs = aabbs.flatMap(a => [a.a.from[0], a.a.to[0]]);
  const ys = aabbs.flatMap(a => [a.a.from[1], a.a.to[1]]);
  const zs = aabbs.flatMap(a => [a.a.from[2], a.a.to[2]]);
  const merged = {
    from: [Math.min(...xs), Math.min(...ys), Math.min(...zs)],
    to:   [Math.max(...xs), Math.max(...ys), Math.max(...zs)]
  };
  const sz = (m) => `${r(m.to[0]-m.from[0])}×${r(m.to[1]-m.from[1])}×${r(m.to[2]-m.from[2])}`;
  console.log(`${name.padEnd(28)} box(${r(merged.from[0])}, ${r(merged.from[1])}, ${r(merged.from[2])}, ${r(merged.to[0])}, ${r(merged.to[1])}, ${r(merged.to[2])})  尺寸=${sz(merged)}`);
}

console.log('\n\n建议的Java代码（四舍五入到合理精度）:');
console.log('='.repeat(80));

// 定义建议的碰撞箱（四舍五入）
const boxes = [
  { name: '桌腿[19]东南',      box: [9, 0, 11, 11, 8, 15] },
  { name: '桌腿[20]中北',      box: [7, 0, 1, 9, 9, 5] },
  { name: '桌腿[21]西南',      box: [5, 0, 11, 7, 8, 15] },
  { name: '斜板[18]',          box: [5, 6, 0, 11, 12, 16] },
  { name: '支架[16]西',        box: [5, 9, 10, 6, 19, 15] },
  { name: '支架[17]东',        box: [10, 9, 10, 11, 19, 15] },
  { name: '大轮盘[0]西板',     box: [6, 10, 6, 7, 25, 21] },
  { name: '大轮盘[9]东板',     box: [9, 10, 6, 10, 25, 21] },
  { name: '大轮盘[2]中心轴',   box: [7, 13, 9, 9, 22, 18] },
  { name: '小轮盘整体',        box: [6, 11, 0, 10, 19, 3] },
  { name: '线[27]下',          box: [7, 14, 2, 9, 15, 10] },
  { name: '线[26]上',          box: [7, 18, 2, 9, 22, 11] },
];

boxes.forEach(b => {
  console.log(`box(${b.box.join(', ')}).padEnd(40)  // ${b.name}`);
});

// 验证：检查每个box是否覆盖对应元素的AABB
console.log('\n\n验证：每个box是否完整覆盖对应元素AABB:');
console.log('='.repeat(80));
for (const b of boxes) {
  const idx = parseInt(b.name.match(/\[(\d+)\]/)?.[1] || -1);
  if (idx < 0) continue;
  const a = getRotatedAABB(model.elements[idx]);
  a.from[1] = a.from[1] - transY + yOff;
  a.to[1] = a.to[1] - transY + yOff;
  const [bx1, by1, bz1, bx2, by2, bz2] = b.box;
  const covers = a.from[0] >= bx1 - 0.5 && a.to[0] <= bx2 + 0.5 &&
                 a.from[1] >= by1 - 0.5 && a.to[1] <= by2 + 0.5 &&
                 a.from[2] >= bz1 - 0.5 && a.to[2] <= bz2 + 0.5;
  const status = covers ? '✓ 覆盖' : '✗ 未完全覆盖';
  console.log(`${b.name.padEnd(28)} ${status}  元素AABB=(${r(a.from[0])},${r(a.from[1])},${r(a.from[2])})->(${r(a.to[0])},${r(a.to[1])},${r(a.to[2])})`);
}

// 统计空气覆盖率
console.log('\n\n空气覆盖分析:');
console.log('='.repeat(80));
let totalBoxVolume = 0;
let totalElementVolume = 0;
for (const b of boxes) {
  const [bx1, by1, bz1, bx2, by2, bz2] = b.box;
  const vol = (bx2-bx1) * (by2-by1) * (bz2-bz1);
  totalBoxVolume += vol;
  const idx = parseInt(b.name.match(/\[(\d+)\]/)?.[1] || -1);
  if (idx >= 0) {
    const a = getRotatedAABB(model.elements[idx]);
    a.from[1] = a.from[1] - transY + yOff;
    a.to[1] = a.to[1] - transY + yOff;
    const elVol = (a.to[0]-a.from[0]) * (a.to[1]-a.from[1]) * (a.to[2]-a.from[2]);
    totalElementVolume += elVol;
    const airPct = (1 - elVol/vol) * 100;
    console.log(`${b.name.padEnd(28)} box体积=${r(vol)} 元素AABB体积=${r(elVol)} 空气率=${r(airPct)}%`);
  }
}
console.log(`\n总计: box体积=${r(totalBoxVolume)} 元素体积=${r(totalElementVolume)} 整体空气率=${r((1-totalElementVolume/totalBoxVolume)*100)}%`);
