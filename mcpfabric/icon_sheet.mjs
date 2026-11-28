// Capture every registered item's real in-game GUI icon into one contact sheet.
//
// Offline previews approximate the game; this walks a real container screen and
// photographs the actual slots, so art decisions rest on what the player sees.
// One chest holds 27 slots, so 94 items take four rounds. The fill order is written
// next to the shots so the cropper can map slot -> item without guessing.
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';

const ROOT = resolve(import.meta.dirname, '../..');
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const SLOTS_PER_CHEST = 27;

function argsOf(argv) {
  const parsed = { out: 'build/shots/game_icon_sheet', zoom: 5, limit: 0, items: '', all: false, wait: 0 };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--out') parsed.out = argv[i + 1];
    else if (argv[i] === '--zoom') parsed.zoom = Number(argv[i + 1]);
    else if (argv[i] === '--limit') parsed.limit = Number(argv[i + 1]);
    else if (argv[i] === '--items') parsed.items = argv[i + 1];
    else if (argv[i] === '--all') parsed.all = true;
    else if (argv[i] === '--wait') parsed.wait = Number(argv[i + 1]);
  }
  return parsed;
}

function call(tool, payload) {
  const text = execFileSync(process.execPath,
    ['build/probes/mcp.mjs', tool, JSON.stringify(payload ?? {})],
    { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim();
  // Logs can share stdout with the payload; parse the last complete JSON object.
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start >= 0 && end > start) {
    try { return JSON.parse(text.slice(start, end + 1)); } catch { /* fall through */ }
  }
  return text;
}

function shot(path) {
  const abs = resolve(ROOT, path);
  mkdirSync(resolve(abs, '..'), { recursive: true });
  process.env.MCPFABRIC_IMAGE_OUT = abs;
  const result = call('screenshot', { marks: false });
  delete process.env.MCPFABRIC_IMAGE_OUT;
  return result;
}

// MCP responses are wrapped: { untrusted, notice, data: {...} }.
function data(response) { return response && typeof response === 'object' ? (response.data ?? response) : response; }
function command(text) { return call('run_command', { command: text }); }

// open_container answers with a human-readable line like
//   "opened chest @ x y z (generic_9x3, 27 slots) · memory #9\ncontents: id\u00d71 id\u00d71 ..."
// Parsing it back lets a round fail loudly instead of shipping a screenshot of the
// previous round's contents. It answered exactly that way once already: /setblock
// refuses to replace a chest that still holds items ("can't place block"), so a
// reused chest kept the old stacks and the shot silently showed them.
// Vanilla ids are kept qualified ("minecraft:stone") so the enumerated contents can be
// matched against the requested batch without guessing a namespace.
function containerContents(response) {
  const text = typeof response === 'string' ? response : JSON.stringify(response);
  const ids = [];
  for (const match of text.matchAll(/(?:pastoral_home|minecraft):([a-z0-9_]+)/g)) ids.push(match[1]);
  return ids;
}

function sameContents(found, batch) {
  if (found.length !== batch.length) return false;
  const left = found.slice().sort();
  const right = batch.slice().sort();
  return left.every((id, index) => id === right[index]);
}

// The item set comes from tools/deploy/item_ids.py so the capture, the tuner and the
// offline preview all agree: registration alone would also pull in internal render
// parts (globe_sphere_render, wheelbarrow_wheel, weather_vane_base, bulletin_page).
function catalogIds(all) {
  const python = process.env.PASTORAL_PYTHON ?? join(ROOT, '.venv/Scripts/python.exe');
  const args = [join(ROOT, 'tools/deploy/item_ids.py'), '--root', ROOT];
  if (all) args.push('--all');
  const output = execFileSync(python, args, { encoding: 'utf8' }).trim();
  return new Set(output.split(/\s+/).filter(Boolean));
}

// Only items that actually ship a generated GUI proxy can be photographed as icons.
function itemsWithProxy(ids) {
  const dir = join(ROOT, 'src/main/resources/assets/pastoral_home/models/item_icons');
  let dirs = [];
  try { dirs = readdirSync(dir, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name); }
  catch { return []; }
  return dirs.filter((id) => ids.has(id) && readFileSync(join(dir, id, 'variant_0.json'), 'utf8').length > 0).sort();
}

const opts = argsOf(process.argv.slice(2));
let ids = itemsWithProxy(catalogIds(opts.all));
const requested = opts.items ? opts.items.split(',').map((value) => value.trim()).filter(Boolean) : [];
if (requested.length) ids = requested;
// Probe captures may name vanilla items ("minecraft:stone") to compare against the
// engine's own rendering; they never own a pastoral_home proxy.
const qualified = (id) => (id.includes(':') ? id : `pastoral_home:${id}`);
if (opts.limit > 0) ids = ids.slice(0, opts.limit);
if (ids.length === 0) throw new Error('no registered items with a GUI proxy found');
console.log('[icon_sheet] ' + ids.length + ' items');

// A capture that fails halfway through a round burns a client restart, so the bridge
// is probed once up front with a short, explicit timeout.
function waitForBridge(seconds) {
  const deadline = Date.now() + seconds * 1000;
  let last = null;
  while (Date.now() < deadline) {
    try {
      const state = data(call('get_screen', {}));
      if (state && state.inWorld !== undefined) return state;
      last = state;
    } catch (error) {
      last = error.message;
    }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1000);
  }
  throw new Error('mcpfabric bridge not reachable after ' + seconds + 's: ' + last);
}

let state = opts.wait ? waitForBridge(opts.wait) : data(call('get_screen', {}));
if (!state.inWorld) {
  const worlds = data(call('list_worlds', {}));
  const worldId = worlds.lastWorldId ?? worlds.worlds?.[0]?.worldId ?? worlds.worlds?.[0];
  console.log('[icon_sheet] joining ' + worldId);
  call('join_world', { worldId });
  for (let i = 0; i < 30; i += 1) { await sleep(1000); state = data(call('get_screen', {})); if (state.inWorld) break; }
}
console.log('[icon_sheet] inWorld=' + state.inWorld + ' screen=' + state.screen);
// A leftover chat screen would steal every container screenshot.
call('close_screen', {});
await sleep(200);

const player = data(call('get_player', { player: 'Dev' }));
command('time set noon');
command('weather clear');
command('gamemode creative');
// The player drifts (a chest placed on top of them pushes them out), and an
// out-of-reach chest returns no contents at all, which reads like an empty fill.
// Teleporting to a fixed anchor before every round keeps the chest in reach.
const anchor = { x: Math.round(player.x), y: Math.round(player.y), z: Math.round(player.z) };
const chest = { x: anchor.x + 2, y: anchor.y, z: anchor.z };

const rounds = [];

// A chest that still holds items refuses /setblock ("can't place block"), so the
// block is cleared to air first and then re-created; both steps report success.
function blockAt(x, y, z) {
  const body = data(call('get_block', { x, y, z }));
  return String(body?.id ?? body?.block ?? body?.state ?? '');
}

// /setblock fails with "can't place block" when the target already holds that very
// block (the server reports "nothing changed"). So the block is read first and the
// command only runs when it actually changes something: air first (which drops any
// leftover stacks), then a fresh chest, which therefore starts empty.
function ensureBlock(id) {
  const current = blockAt(chest.x, chest.y, chest.z);
  if (current === id) return;
  const result = command(`setblock ${chest.x} ${chest.y} ${chest.z} ${id} replace`);
  const body = result?.data ?? result;
  if (body?.success !== true && blockAt(chest.x, chest.y, chest.z) !== id) {
    throw new Error('could not place ' + id + ' at ' + [chest.x, chest.y, chest.z].join(' ')
      + ': ' + JSON.stringify(body?.output ?? body));
  }
}

function placeChest() {
  ensureBlock('minecraft:air');
  ensureBlock('minecraft:chest');
}

// Every slot is emptied with /item replace instead of relying on /setblock: a chest
// that still holds items refuses the replace, and the stale stacks then end up in
// the next round's screenshot.
function clearChest() {
  for (let slot = 0; slot < SLOTS_PER_CHEST; slot += 1) {
    command(`item replace block ${chest.x} ${chest.y} ${chest.z} container.${slot} with air 1`);
  }
}

function fillChest(batch) {
  batch.forEach((id, slot) => {
    command(`item replace block ${chest.x} ${chest.y} ${chest.z} container.${slot} with ${qualified(id)} 1`);
  });
}

for (let start = 0; start < ids.length; start += SLOTS_PER_CHEST) {
  const batch = ids.slice(start, start + SLOTS_PER_CHEST);
  let verified = false;
  for (let attempt = 0; attempt < 3 && !verified; attempt += 1) {
    call('close_container', {});
    await sleep(200);
    command(`tp Dev ${anchor.x} ${anchor.y} ${anchor.z}`);
    await sleep(250);
    placeChest();
    clearChest();
    fillChest(batch);
    await sleep(200);
    const opened = call('open_container', chest);
    const found = containerContents(opened);
    verified = sameContents(found, batch);
    if (!verified) {
      const raw = typeof opened === 'string' ? opened.split('\n')[0] : JSON.stringify(opened).slice(0, 200);
      console.log('[icon_sheet] round ' + rounds.length + ' content mismatch at ' + chest.x + ': want '
        + batch.length + ', got ' + found.length + ' · ' + raw);
      await sleep(600);
    }
  }
  if (!verified) throw new Error('round ' + rounds.length + ' container contents never matched the plan');
  await sleep(700);
  const gui = data(call('get_screen', {}));
  if (gui.screen !== 'container') throw new Error('round ' + rounds.length + ' lost the container screen: ' + gui.screen);
  const name = `${opts.out}_r${rounds.length}.png`;
  shot(name);
  console.log('[icon_sheet] round ' + rounds.length + ' slots ' + batch.length + ' verified screen=' + gui.screen + ' -> ' + name);
  rounds.push({ image: name, items: batch });
  call('close_container', {});
  await sleep(250);
}
clearChest();
command(`setblock ${chest.x} ${chest.y} ${chest.z} minecraft:air replace`);


const planPath = resolve(ROOT, opts.out + '_plan.json');
writeFileSync(planPath, JSON.stringify({ zoom: opts.zoom, rounds }, null, 1), 'utf8');
console.log('[icon_sheet] plan -> ' + planPath);
