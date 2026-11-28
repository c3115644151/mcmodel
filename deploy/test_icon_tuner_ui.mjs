// GUI Icon Tuner 前端行为测试：直接驱动真实页面断言状态，不靠截图猜。
// 用 Edge 的 CDP 跑，零依赖：Node 20 加 --experimental-websocket 提供全局 WebSocket。
// 用法：node --experimental-websocket tools/deploy/test_icon_tuner_ui.mjs [--url URL]
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const argv = process.argv.slice(2);
const urlIdx = argv.indexOf('--url');
const TUNER_URL = urlIdx >= 0 ? argv[urlIdx + 1] : 'http://127.0.0.1:8765/';
const CDP_PORT = 9333;
const BROWSERS = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Cdp {
  constructor(ws) {
    this.ws = ws; this.seq = 0; this.pending = new Map();
    this.exceptions = []; this.consoleErrors = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const p = this.pending.get(msg.id); this.pending.delete(msg.id);
        if (msg.error) p.reject(new Error(msg.error.message)); else p.resolve(msg.result);
        return;
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        this.exceptions.push((d.exception && d.exception.description) || d.text || 'exception');
      } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
        this.consoleErrors.push(msg.params.args.map((a) => (a.value !== undefined ? a.value : a.description)).join(' '));
      }
    });
  }
  send(method, params) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params: params || {} }));
    });
  }
  async evaluate(expression, opts) {
    const awaitPromise = !opts || opts.awaitPromise !== false;
    const r = await this.send('Runtime.evaluate', {
      expression, awaitPromise, returnByValue: true, userGesture: true,
    });
    if (r.exceptionDetails) {
      const d = r.exceptionDetails.exception;
      throw new Error('page threw: ' + ((d && d.description) || JSON.stringify(r.exceptionDetails)));
    }
    return r.result.value;
  }
}

async function connect() {
  const list = await (await fetch('http://127.0.0.1:' + CDP_PORT + '/json/list')).json();
  const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!page) throw new Error('no page target');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener('open', res);
    ws.addEventListener('error', () => rej(new Error('ws error')));
  });
  const cdp = new Cdp(ws);
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  return cdp;
}

async function waitForPage(cdp, timeoutMs) {
  const deadline = Date.now() + (timeoutMs || 40000);
  while (Date.now() < deadline) {
    try {
      const ready = await cdp.evaluate(
        '(function(){var n=document.querySelectorAll(".cell").length;' +
        'var b=document.getElementById("big");' +
        'return n>10 && !!b && String(b.src).indexOf("data:image/png")===0})()');
      if (ready) return;
    } catch (e) { /* 页面还在加载 */ }
    await sleep(300);
  }
  throw new Error('page not ready (cells + big preview)');
}

const results = [];
function record(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name + (detail ? '  - ' + detail : ''));
}
async function test(name, fn) {
  try { record(name, true, await fn()); }
  catch (e) { record(name, false, e.message); }
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

async function main() {
  const browser = BROWSERS.find((p) => existsSync(p));
  if (!browser) throw new Error('no Edge/Chrome found');
  const profile = mkdtempSync(join(tmpdir(), 'tuner-e2e-'));
  const child = spawn(browser, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--disable-sync', '--disable-background-networking',
    '--remote-allow-origins=*', '--remote-debugging-port=' + CDP_PORT,
    '--user-data-dir=' + profile, '--window-size=1500,900',
    '--force-device-scale-factor=1', TUNER_URL,
  ], { stdio: 'ignore' });

  let cdp = null;
  try {
    for (let i = 0; i < 60; i++) {
      await sleep(500);
      try { cdp = await connect(); break; } catch (e) { /* 还没起来 */ }
    }
    if (!cdp) throw new Error('CDP never came up on port ' + CDP_PORT);
    await waitForPage(cdp);
    const ev = (expr, opts) => cdp.evaluate(expr, opts);
    // 候选渲染随模型复杂度 0.7–2.7s 不等，固定 sleep 会让慢模型变成假失败；
    // 统一轮询条件，既快又稳。
    const waitFor = async (expr, timeoutMs) => {
      const end = Date.now() + (timeoutMs || 12000);
      while (Date.now() < end) {
        if (await ev(expr)) return true;
        await sleep(150);
      }
      return false;
    };

    await test('网格渲染出全部物品', async () => {
      const total = await ev("document.querySelectorAll('.cell').length");
      assert(total > 10, 'cell 数量 ' + total);
      return total + ' 格';
    });

    await test('点击图标不重置左侧栏滚动位置', async () => {
      await ev("(function(){var g=document.getElementById('grid');g.scrollTop=400;return g.scrollTop})()");
      const before = await ev("document.getElementById('grid').scrollTop");
      assert(before > 100, '先要真能滚动，实际 scrollTop=' + before);
      await ev("(function(){var c=document.querySelectorAll('.cell');c[Math.min(30,c.length-1)].click()})()");
      await sleep(700);
      const after = await ev("document.getElementById('grid').scrollTop");
      assert(after === before, '点击后 scrollTop ' + before + ' -> ' + after);
      return 'scrollTop 保持 ' + after;
    });

    await test('选中只移动高亮，不重建网格（DOM 节点保持）', async () => {
      const kept = await ev("(function(){var cs=document.querySelectorAll('.cell');cs[0].__probe=1;cs[cs.length-1].click();return document.querySelector('.cell').__probe===1})()");
      assert(kept, '第一格被重建，说明 buildGrid 又被调用');
      const selCount = await ev("document.querySelectorAll('.cell.sel').length");
      assert(selCount === 1, '.sel 数量应为 1，实际 ' + selCount);
      const selId = await ev("(function(){var e=document.querySelector('.cell.sel');return e?e.dataset.id:''})()");
      assert(selId.length > 0, '高亮格缺少 data-id');
      return '高亮 ' + selId;
    });

    await test('切换源模型下拉后点图标，滚动位置仍保持', async () => {
      await ev("(function(){var s=document.getElementById('source');if(s.options.length>1){s.selectedIndex=1;s.dispatchEvent(new Event('change'))}})()");
      await ev("(function(){document.getElementById('grid').scrollTop=300})()");
      const before = await ev("document.getElementById('grid').scrollTop");
      await ev("(function(){var c=document.querySelectorAll('.cell');c[5].click()})()");
      await sleep(700);
      const after = await ev("document.getElementById('grid').scrollTop");
      assert(after === before, '下拉 change 后点击：scrollTop ' + before + ' -> ' + after);
      return 'scrollTop 保持 ' + after;
    });

    await test('缩略图分辨率等于 16×zoom（与槽位同倍率，不会二次缩放）', async () => {
      const r = await ev("(function(){var cells=Array.prototype.slice.call(document.querySelectorAll('.cell'));var zoom=Math.round(cells[0].getBoundingClientRect().width/18);var want=zoom*16;var bad=cells.filter(function(c){var m=/px=([0-9]+)/.exec(c.querySelector('img').src);return !m||Number(m[1])!==want});return {zoom:zoom,want:want,bad:bad.length,n:cells.length}})()");
      assert(r.bad === 0, r.bad + '/' + r.n + ' 张不是 px=' + r.want + '（zoom ' + r.zoom + '）');
      return r.n + ' 张全部 px=' + r.want + '（zoom ' + r.zoom + '）';
    });

    await test('自绘滚动条尺寸与滚动同步', async () => {
      const geo = await ev("(function(){var g=document.getElementById('grid');g.scrollTop=0;var bar=document.querySelector('.scrollhost .sbar');var th=bar.querySelector('i');return {h:th.offsetHeight,track:bar.clientHeight,sh:g.scrollHeight,ch:g.clientHeight,expect:Math.max(26,Math.round(bar.clientHeight*g.clientHeight/g.scrollHeight))}})()");
      assert(geo.sh > geo.ch, '网格没有溢出，滚动条不该出现（' + geo.sh + '/' + geo.ch + '）');
      assert(Math.abs(geo.h - geo.expect) <= 2, 'thumb 高度 ' + geo.h + ' != ' + geo.expect);
      await ev("(function(){var g=document.getElementById('grid');g.scrollTop=g.scrollHeight;return 1})()");
      await sleep(120);
      const end = await ev("(function(){var bar=document.querySelector('.scrollhost .sbar');var th=bar.querySelector('i');return {top:parseFloat(th.style.top)||0,track:bar.clientHeight,h:th.offsetHeight}})()");
      const want = end.track - end.h;
      assert(Math.abs(end.top - want) <= 2, '滚到底 thumb top ' + end.top + ' != ' + want);
      await ev("(function(){document.getElementById('grid').scrollTop=0;return 1})()");
      return 'thumb ' + geo.h + 'px / track ' + geo.track + 'px';
    });

    await test('保存只更新一格，不重建网格', async () => {
      const r = await ev("(async function(){var real=window.fetch;window.fetch=function(u,o){var s=String(u);if(s.indexOf('/api/overrides')>=0&&o&&o.method==='POST'){var body=JSON.parse(o.body);return Promise.resolve(new Response(JSON.stringify({items:body.items,regenerated:[]}),{status:200,headers:{'Content-Type':'application/json'}}))}return real(u,o)};var cs=document.querySelectorAll('.cell');cs[1].click();await new Promise(function(r){setTimeout(r,600)});var g=document.getElementById('grid');g.scrollTop=220;var keepScroll=g.scrollTop;document.querySelector('.cell').__probe=1;var id=selected;await save();window.fetch=real;var cell=document.querySelector('.cell[data-id=\"' + id + '\"]');return {kept:document.querySelector('.cell').__probe===1,dot:!!(cell&&cell.querySelector('.dot')),ver:ver[id]||0,scroll:g.scrollTop,want:keepScroll}})()");
      assert(r.kept, '保存后网格被重建（第一格 __probe 丢失）');
      assert(r.dot, '保存后该格没有出现已调圆点');
      assert(r.ver >= 1, '缩略图版本号没递增，图片不会刷新');
      assert(r.scroll === r.want, '保存把滚动位置从 ' + r.want + ' 挪到 ' + r.scroll);
      return '节点保持、圆点已加、ver=' + r.ver + '、scrollTop ' + r.scroll;
    });

    await test('重置当前项也不重建网格、不动滚动', async () => {
      const r = await ev("(async function(){var real=window.fetch;window.fetch=function(u,o){var s=String(u);if(s.indexOf('/api/overrides')>=0&&o&&o.method==='POST'){var body=JSON.parse(o.body);return Promise.resolve(new Response(JSON.stringify({items:body.items}),{status:200,headers:{'Content-Type':'application/json'}}))}return real(u,o)};var g=document.getElementById('grid');g.scrollTop=260;var want=g.scrollTop;document.querySelector('.cell').__probe=1;await reset();window.fetch=real;return {kept:document.querySelector('.cell').__probe===1,scroll:g.scrollTop,want:want,sel:document.querySelectorAll('.cell.sel').length}})()");
      assert(r.kept, '重置后网格被重建（第一格 __probe 丢失）');
      assert(r.scroll === r.want, '重置把滚动位置从 ' + r.want + ' 挪到 ' + r.scroll);
      assert(r.sel === 1, '重置后高亮格数量 ' + r.sel);
      return '滚动保持 ' + r.scroll;
    });
    await test('格子就是原版槽位：18×整体、16×图标区、整数字号、1px 内边', async () => {
      const r = await ev("(function(){var cells=Array.prototype.slice.call(document.querySelectorAll('.cell'));var c=cells[0];var cb=c.getBoundingClientRect();var img=c.querySelector('img');var ib=img.getBoundingClientRect();var pxs={};cells.forEach(function(x){var m=/px=([0-9]+)/.exec(x.querySelector('img').src);if(m)pxs[m[1]]=1});return {w:Math.round(cb.width),h:Math.round(cb.height),iw:Math.round(ib.width),left:Math.round(ib.left-cb.left),top:Math.round(ib.top-cb.top),px:Object.keys(pxs)}})()");
      assert(r.w === r.h, '槽位不是正方形: ' + r.w + 'x' + r.h);
      assert(r.w % 18 === 0, '槽位宽度必须是 18×整数倍（1px 边框 + 16px 图标区），实际 ' + r.w);
      const zoom = r.w / 18;
      assert(zoom >= 2 && zoom <= 8 && Number.isInteger(zoom), 'zoom 应为 2–8 的整数，实际 ' + zoom);
      assert(r.iw === zoom * 16, '图标区应为 ' + zoom * 16 + 'px，实际 ' + r.iw);
      assert(r.left === zoom && r.top === zoom, '图标应内缩 1 游戏像素（' + zoom + 'px），实际 ' + r.left + ',' + r.top);
      assert(r.px.length === 1 && Number(r.px[0]) === zoom * 16, '缩略图应统一按 16×zoom=' + zoom * 16 + ' 渲染，实际 ' + r.px.join(','));
      // 槽位背景必须是原版 18×18 精灵（服务端从 NeoForm 资源取，取不到则合成同像素）。
      const slot = await ev("(async function(){var b=await (await fetch('/api/slot')).blob();var url=URL.createObjectURL(b);var im=new Image();await new Promise(function(res,rej){im.onload=res;im.onerror=rej;im.src=url});return {w:im.naturalWidth,h:im.naturalHeight}})()");
      assert(slot.w === 18 && slot.h === 18, '槽位精灵应是原版 18x18，实际 ' + slot.w + 'x' + slot.h);
      return 'zoom ' + zoom + '：槽位 ' + r.w + 'px，图标 ' + r.iw + 'px，缩略图 px=' + r.px[0];
    });
    await test('左栏是一个 GUI 面板：槽位无缝相连、大预览与相邻条也是槽位', async () => {
      const r = await ev("(function(){var cells=document.querySelectorAll('.cell');var a=cells[0].getBoundingClientRect(),b=cells[1].getBoundingClientRect();var g=document.getElementById('grid');var board=document.getElementById('board');var gs=getComputedStyle(board);var frame=document.querySelector('.tile .frame');var fs=getComputedStyle(frame);var f=frame.getBoundingClientRect();var big=document.getElementById('big').getBoundingClientRect();var ctx=Array.prototype.slice.call(document.querySelectorAll('.ctxcell'));var c0=ctx[0].getBoundingClientRect(),c1=ctx[1].getBoundingClientRect();return {gap:Math.round(b.left-a.right),panel:gs.backgroundImage.indexOf('/api/panel')>=0,panelSize:gs.backgroundSize,frameBg:fs.backgroundImage.indexOf('/api/slot')>=0,bigInset:Math.round(big.left-f.left),bigSize:Math.round(big.width),frameW:Math.round(f.width),ctxGap:Math.round(c1.left-c0.right)}})()");
      assert(r.gap === 0, '相邻槽位之间不该有缝（原版背包是无缝的），实际 ' + r.gap + 'px');
      assert(r.panel, '左栏底色不是 /api/panel 面板图，看不到容器边框: ' + r.panelSize);
      assert(r.frameBg, '大预览没有原版槽位底');
      const unit = Math.round(r.frameW / 18);
      assert(r.bigInset === unit, '大预览图标应内缩 1 游戏像素（' + unit + 'px），实际 ' + r.bigInset);
      assert(r.bigSize === r.frameW - 2 * unit, '大预览图标应是 16×' + unit + '，实际 ' + r.bigSize);
      assert(r.ctxGap === 0, '相邻条也应无缝，实际缝 ' + r.ctxGap + 'px');
      return '缝 0、面板 ' + r.panelSize + '、大预览 ' + r.frameW + 'px（图标 ' + r.bigSize + 'px）';
    });
    await test('面板随内容一起滚（背景不贴屏），且自适应当前栏宽', async () => {
      // 同一次求值里自己滚自己量：不依赖上一条用例留下的 scrollTop。
      const r = await ev("(function(){var g=document.getElementById('grid');var b=document.getElementById('board');var c=document.querySelector('.cell');var bgOnScroller=getComputedStyle(g).backgroundImage!=='none';g.scrollTop=0;var bt0=b.getBoundingClientRect().top,ct0=c.getBoundingClientRect().top,fill=Math.round(b.getBoundingClientRect().width),avail=Math.round(g.clientWidth);var want=Math.min(240,g.scrollHeight-g.clientHeight);g.scrollTop=want;var bt1=b.getBoundingClientRect().top,ct1=c.getBoundingClientRect().top;return {bgOnScroller:bgOnScroller,scroll:Math.round(g.scrollTop),boardMoved:Math.round(bt0-bt1),cellMoved:Math.round(ct0-ct1),fill:fill,avail:avail}})()");
      const before = r, after = r;
      assert(r.bgOnScroller === false, '面板背景仍挂在滚动容器上，滚动时会贴住屏幕');
      assert(r.scroll > 0, '页面内容不够滚，测试无效');
      assert(r.boardMoved === r.scroll, '面板没有跟着滚动 ' + r.boardMoved + ' vs ' + r.scroll);
      assert(r.cellMoved === r.scroll, '格子与面板滚动不同步：' + r.cellMoved);
      // 列数与整数倍缩放一起算：面板宽度占可用宽度的 85% 以上
      assert(r.fill >= r.avail * 0.85, '面板没有填满栏宽：' + r.fill + '/' + r.avail);
      return '滚动 ' + r.scroll + 'px 同步，面板 ' + r.fill + '/' + r.avail + 'px';
    });
    await test('相邻图标：7 个正方形格、当前项居中、可点邻居切过去', async () => {
      const r = await ev("(function(){var cells=Array.from(document.getElementById('ctxrow').children);var curIdx=cells.findIndex(function(c){return c.classList.contains('cur')});var rects=cells.map(function(c){var b=c.getBoundingClientRect();return [Math.round(b.width),Math.round(b.height)]});var labels=cells.filter(function(c){return c.querySelector('em')}).length;return {n:cells.length,curIdx:curIdx,ids:cells.map(function(c){return c.dataset.id}),sel:selected,rects:rects,labels:labels}})()");
      assert(r.n === 7, '相邻格数应为 7，实际 ' + r.n);
      assert(r.curIdx === 3, '当前项应在第 4 格（index 3），实际 ' + r.curIdx);
      assert(r.ids[r.curIdx] === r.sel, '第 4 格是 ' + r.ids[r.curIdx] + '，当前选中是 ' + r.sel);
      const skew = r.rects.filter(function (w) { return Math.abs(w[0] - w[1]) > 1;});
      assert(skew.length === 0, '这些格子不是正方形: ' + JSON.stringify(skew));
      assert(r.labels === 0, '格子里还有名字标签，会让格子变长条: ' + r.labels);
      // 点第 6 格（右二）应当切换选中，且不重建网格
      const click = await ev("(async function(){var cells=Array.from(document.getElementById('ctxrow').children);var want=cells[5].dataset.id;document.querySelector('.cell').__probe=1;cells[5].click();await new Promise(function(r){setTimeout(r,700)});return {want:want,sel:selected,kept:document.querySelector('.cell').__probe===1}})()");
      assert(click.sel === click.want, '点相邻格没切过去: ' + click.sel + ' != ' + click.want);
      assert(click.kept, '点相邻格把网格重建了');
      return '7 个正方形格，当前项 index 3 = ' + r.sel + '，点邻居可切换';
    });
    await test('拖动滑杆会更新数值标签并触发候选重渲', async () => {
      const before = await ev("document.getElementById('metrics').textContent");
      const label = await ev("(function(){var t=document.getElementById('target');t.value='9.9';t.dispatchEvent(new Event('input'));return document.getElementById('vT').textContent})()");
      assert(label === '9.9', '标签没跟着滑杆：' + label);
      const ok = await waitFor("document.getElementById('metrics').textContent.indexOf('target  9.9')===0", 15000);
      const after = await ev("document.getElementById('metrics').textContent");
      assert(ok, '滑杆改动后 metrics 一直没变：' + after.slice(0, 60));
      assert(after !== before, 'metrics 文本没变化');
      return 'label=' + label + '，metrics 已刷新';
    });

    await test('保存返回 regenerated 时提示语说明 proxy 已重建', async () => {
      const r = await ev("(async function(){var real=window.fetch;window.fetch=function(u,o){var s=String(u);if(s.indexOf('/api/overrides')>=0&&o&&o.method==='POST'){var body=JSON.parse(o.body);return Promise.resolve(new Response(JSON.stringify({items:body.items,regenerated:[selected]}),{status:200,headers:{'Content-Type':'application/json'}}))}return real(u,o)};await save();window.fetch=real;return {toast:document.getElementById('toast').textContent,badge:document.getElementById('badge').textContent}})()");
      assert(r.toast.indexOf('已重建') >= 0, '提示语没提到 proxy 重建：' + r.toast);
      assert(r.badge === '已调', 'badge 应为已调，实际 ' + r.badge);
      return 'toast: ' + r.toast;
    });

    await test('已调圆点数量等于 override 数量', async () => {
      const r = await ev("(function(){return {dots:document.querySelectorAll('.cell .dot').length,ov:Object.keys(overrides).length,stat:document.getElementById('stat').textContent}})()");
      assert(r.dots === r.ov, '圆点 ' + r.dots + ' != override ' + r.ov);
      assert(r.stat.indexOf('项已调') >= 0, '统计行文案异常：' + r.stat);
      return r.dots + ' 个圆点 / ' + r.ov + ' 项 override';
    });

    await test('重新选中已调项时参数从 override 回填', async () => {
      const r = await ev("(async function(){var d=document.querySelectorAll('.cell')[4];d.click();await new Promise(function(r){setTimeout(r,400)});var id=selected;var saved={target_px:12.3,offset_x:1.5,offset_y:-0.7,yaw:45,anchor:'floor',source:'',shade_strength:0,note:'t'};overrides[id]=saved;document.querySelector('.cell[data-id=\"' + id + '\"]').click();await new Promise(function(r){setTimeout(r,600)});return {id:id,target:document.getElementById('target').value,yaw:document.getElementById('yaw').value,anchor:document.getElementById('anchor').value,shade:document.getElementById('shadeStrength').value,badge:document.getElementById('badge').textContent}})()");
      assert(Math.abs(parseFloat(r.target) - 12.3) < 0.01, 'target 没回填：' + r.target);
      assert(String(r.yaw) === '45', 'yaw 没回填：' + r.yaw);
      assert(r.anchor === 'floor', 'anchor 没回填：' + r.anchor);
      assert(String(r.shade) === '0', '阴影强度没回填：' + r.shade);
      assert(r.badge === '已调', 'badge 没标记已调：' + r.badge);
      return '回填 target/yaw/anchor/shade 均生效';
    });

    await test('预览接口报错时显示 ERROR 且不崩，恢复后能继续渲染', async () => {
      const r = await ev("(async function(){var real=window.fetch;window.fetch=function(u,o){var s=String(u);if(s.indexOf('/api/preview')>=0){return Promise.resolve(new Response(JSON.stringify({error:'boom'}),{status:200,headers:{'Content-Type':'application/json'}}))}return real(u,o)};await preview();var err=document.getElementById('metrics').textContent;window.fetch=real;await preview();return {err:err,after:document.getElementById('metrics').textContent.slice(0,20),big:String(document.getElementById('big').src).slice(0,30)}})()");
      assert(r.err.indexOf('ERROR: boom') === 0, '报错没显示：' + r.err);
      assert(r.after.indexOf('target') === 0, '恢复后没重新渲染：' + r.after);
      assert(r.big.indexOf('data:image/png') === 0, '恢复后大预览没图');
      return '报错显示 ERROR，恢复后正常';
    });

    await test('列表短到不需要滚动时自绘条自动隐藏', async () => {
      const r = await ev("(async function(){var f=document.getElementById('filter');f.value='bed';f.dispatchEvent(new Event('input'));await new Promise(function(r){setTimeout(r,300)});var bar=document.querySelector('.scrollhost .sbar');var d=bar.style.display;var g=document.getElementById('grid');var sh=g.scrollHeight,ch=g.clientHeight;f.value='';f.dispatchEvent(new Event('input'));await new Promise(function(r){setTimeout(r,300)});return {d:d,sh:sh,ch:ch,afterBar:document.querySelector('.scrollhost .sbar').style.display}})()");
      assert(r.sh <= r.ch + 2, '过滤后仍溢出（' + r.sh + '/' + r.ch + '），本次断言前提不成立');
      assert(r.d === 'none', '短列表时滚动条没隐藏，display=' + r.d);
      assert(r.afterBar !== 'none', '清空搜索后滚动条没恢复');
      return '短列表隐藏、清空后恢复';
    });
    await test('额外朝向 = 相机旋转：换视角但不改几何（不压扁/不解体）', async () => {
      const r = await ev("(async function(){var y=document.getElementById('yaw');var before=document.getElementById('metrics').textContent;y.value='40';y.dispatchEvent(new Event('input'));var got=null;for(var i=0;i<80;i++){await new Promise(function(r){setTimeout(r,200)});var m=document.getElementById('metrics').textContent;if(m.indexOf('shade')>=0&&m!==before){got=m;break}}return {metrics:got||document.getElementById('metrics').textContent,yaw:y.value}})()");
      assert(r.yaw === '40', 'yaw 滑杆没接受 40：' + r.yaw);
      assert(r.metrics && r.metrics.indexOf('ERROR') < 0, '改 yaw 后预览报错：' + r.metrics);
      // 报告里必须带 gui_rotation，且 yaw 40 时是 [30,265,0]——画的是同一个模型换个视角。
      const report = await ev("(async function(){var c={target_px:15.7,offset_x:0,offset_y:0,yaw:40,anchor:'auto',source:'',shade_strength:1,note:''};var d=await (await fetch('/api/preview?item='+encodeURIComponent(selected)+'&candidate='+encodeURIComponent(JSON.stringify(c)))).json();return d.report||{error:d.error}})()");
      assert(!report.error, '预览接口报错：' + report.error);
      const rot = report.gui_rotation || [];
      assert(Math.abs(rot[1] - 265) < 1e-6, 'yaw 40 时相机应是 [30,265,0]，实际 ' + JSON.stringify(rot));
      assert(Math.abs(rot[0] - 30) < 1e-6 && Math.abs(rot[2]) < 1e-6, '只有 yaw 分量该变：' + JSON.stringify(rot));
      return 'yaw 40 → 相机 ' + JSON.stringify(rot) + '，预览无错';
    });
    await test('阴影强度滑杆：0–150% 连续可调，预览与保存都跟随', async () => {
      const range = await ev("(function(){var s=document.getElementById('shadeStrength');return {min:s.min,max:s.max,step:s.step,val:s.value}})()");
      assert(range.min === '0' && range.max === '150', '滑杆范围应为 0..150，实际 ' + range.min + '..' + range.max);
      const applied = await ev("(async function(){var s=document.getElementById('shadeStrength');s.value='45';s.dispatchEvent(new Event('input'));return new Promise(function(res){var tries=0;var t=setInterval(function(){var m=document.getElementById('metrics').textContent;if(m.indexOf('shade  0.45')>=0||++tries>60){clearInterval(t);res({label:document.getElementById('vShade').textContent,m:m})}},200)})})()");
      assert(applied.label === '45', '数值标签没跟着滑杆：' + applied.label);
      assert(applied.m.indexOf('shade  0.45') >= 0, '预览报告没反映强度：' + applied.m.slice(0, 60));
      const body = await ev("(async function(){var real=window.fetch;var seen=null;window.fetch=function(u,o){var s=String(u);if(s.indexOf('/api/overrides')>=0&&o&&o.method==='POST'){seen=JSON.parse(o.body);return Promise.resolve(new Response(JSON.stringify({items:seen.items,regenerated:[]}),{status:200,headers:{'Content-Type':'application/json'}}))}return real(u,o)};await save();window.fetch=real;return seen.items[selected]})()");
      assert(body && body.shade_strength === 0.45, '保存的 override 里没有 shade_strength=0.45：' + JSON.stringify(body));
      assert(!('shade' in (body || {})), '不该再写旧的 shade 档位：' + JSON.stringify(body));
      return '0..150%，45% 时预览与落盘一致';
    });
    await test('快速连点两个图标，最终展示最后点击的那个（预览竞态）', async () => {
      const r = await ev("(async function(){var real=window.fetch;window.fetch=function(u,o){var s=String(u);if(s.indexOf('/api/preview')>=0){var it=new URL(s,'http://x/').searchParams.get('item');var d=(it===window.__slowId)?900:120;return new Promise(function(res){setTimeout(function(){res(real(u,o))},d)})}return real(u,o)};var cs=document.querySelectorAll('.cell');var slow=cs[2],fast=cs[3];window.__slowId=slow.dataset.id;var fastId=fast.dataset.id;slow.click();await new Promise(function(r){setTimeout(r,80)});fast.click();await new Promise(function(r){setTimeout(r,1600)});window.fetch=real;return {selected:selected,fast:fastId,big:document.getElementById('big').dataset.item||null}})()");
      await waitFor("document.getElementById('big').dataset.item===selected", 15000);
      const settle = await ev("(function(){return {selected:selected,big:document.getElementById('big').dataset.item||null}})()");
      r.selected = settle.selected; r.big = settle.big;
      assert(r.selected === r.fast, 'selected 是 ' + r.selected + '，期望 ' + r.fast);
      assert(r.big === r.selected, '大预览停在 ' + r.big + '，而当前选中是 ' + r.selected + '（旧响应盖住了新选择）');
      return '预览跟随 ' + r.big;
    });

    await test('搜索过滤后格数与匹配数一致', async () => {
      const r = await ev("(async function(){var f=document.getElementById('filter');f.value='bed';f.dispatchEvent(new Event('input'));await new Promise(function(r){setTimeout(r,200)});var shown=document.querySelectorAll('.cell').length;var expect=items.filter(function(i){return i.id.toLowerCase().indexOf('bed')>=0}).length;f.value='';f.dispatchEvent(new Event('input'));await new Promise(function(r){setTimeout(r,200)});return {shown:shown,expect:expect,back:document.querySelectorAll('.cell').length,total:items.length}})()");
      assert(r.shown === r.expect, '过滤后格子 ' + r.shown + ' != 匹配 ' + r.expect);
      assert(r.back === r.total, '清空搜索后没恢复全部：' + r.back + ' != ' + r.total);
      return '过滤 ' + r.shown + ' 格，清空恢复 ' + r.back;
    });

    await test('窄窗口 1000x700 降 zoom、缩略图跟随，两条滚动条都在', async () => {
      await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1000, height: 700, deviceScaleFactor: 1, mobile: false });
      await cdp.send('Page.reload', { ignoreCache: true });
      await waitForPage(cdp);
      const r = await ev("(function(){var cells=Array.prototype.slice.call(document.querySelectorAll('.cell'));var zoom=Math.round(cells[0].getBoundingClientRect().width/18);var want=zoom*16;var bad=cells.filter(function(c){var m=/px=([0-9]+)/.exec(c.querySelector('img').src);return !m||Number(m[1])!==want}).length;var bars=Array.from(document.querySelectorAll('.sbar')).map(function(b){return {d:b.style.display,h:b.querySelector('i')?b.querySelector('i').offsetHeight:0}});var g=document.getElementById('grid');return {bad:bad,n:cells.length,bars:bars,iw:window.innerWidth,sh:g.scrollHeight,ch:g.clientHeight,zoom:zoom}})()");
      assert(r.bad === 0, r.bad + '/' + r.n + ' 张不是 px=' + r.zoom * 16 + '（zoom ' + r.zoom + '）');
      assert(r.bars.length === 2, '应有两条自绘滚动条，实际 ' + r.bars.length);
      assert(r.bars.every(function(b){return b.d !== 'none' && b.h > 20}), '滚动条没画出来: ' + JSON.stringify(r.bars));
      return 'innerWidth ' + r.iw + '，zoom ' + r.zoom + '，' + r.n + ' 张 px=' + r.zoom * 16 + '，两条条高 ' + r.bars.map(function(b){return b.h}).join('/');
    });

    await test('页面运行期间没有 JS 异常与 console.error', async () => {
      assert(cdp.exceptions.length === 0, '异常: ' + cdp.exceptions.slice(0, 3).join(' | '));
      assert(cdp.consoleErrors.length === 0, 'console.error: ' + cdp.consoleErrors.slice(0, 3).join(' | '));
      return '无异常';
    });
  } finally {
    try { child.kill(); } catch (e) { /* 已退出 */ }
    try { spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch (e) { /* 已退出 */ }
    try { rmSync(profile, { recursive: true, force: true }); } catch (e) { /* 目录被占用 */ }
  }

  const failed = results.filter((r) => !r.ok);
  console.log('');
  console.log(results.length + ' 条用例，' + (results.length - failed.length) + ' 通过，' + failed.length + ' 失败');
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error('HARNESS ERROR: ' + e.message); process.exit(2); });