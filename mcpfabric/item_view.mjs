// Review one item the way the game draws it: a real container slot and a real held copy.
//
// Both views use the model's display transforms, which no offline preview can confirm. A chest
// slot is used instead of the inventory because the creative and JEI panels crowd that screen.
// The slot grid is anchored on the container panel rather than hunted for by colour: JEI's list
// and the player's own copies of the item are the same amber, so colour cannot find it reliably.
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '../..');
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

function argsOf(argv) {
  const parsed = { item: null, out: 'build/shots/item_view', zoom: 6 };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--item') parsed.item = argv[i + 1];
    else if (argv[i] === '--out') parsed.out = argv[i + 1];
    else if (argv[i] === '--zoom') parsed.zoom = Number(argv[i + 1]);
  }
  return parsed;
}

function call(tool, payload) {
  const text = execFileSync(process.execPath,
    ['build/probes/mcp.mjs', tool, JSON.stringify(payload ?? {})],
    { cwd: ROOT, encoding: 'utf8' }).trim();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function shot(path) {
  process.env.MCPFABRIC_IMAGE_OUT = resolve(ROOT, path);
  const result = call('screenshot', { marks: false });
  delete process.env.MCPFABRIC_IMAGE_OUT;
  return result;
}

function command(text) {
  return call('run_command', { command: text });
}

function cropSlot(path, slot) {
  const text = execFileSync(resolve(ROOT, '.venv/Scripts/python.exe'),
    ['tools/deploy/icon_crop.py', '--image', path, '--slot', String(slot),
      '--zoom', String(opts.zoom), '--out', path.replace(/\.png$/, '_c.png')],
    { cwd: ROOT, encoding: 'utf8' }).trim();
  return text.split('\n').filter((line) => line.startsWith('{')).pop() ?? text;
}

function locate(path, region) {
  const text = execFileSync(resolve(ROOT, '.venv/Scripts/python.exe'),
    ['tools/deploy/find_icon.py', '--image', path, '--zoom', String(opts.zoom),
      '--region', region.join(','), '--out', path.replace(/\.png$/, '_c.png')],
    { cwd: ROOT, encoding: 'utf8' }).trim();
  return text.split('\n').filter((line) => line.startsWith('{')).pop() ?? text;
}

const opts = argsOf(process.argv.slice(2));
if (!opts.item) throw new Error('usage: item_view.mjs --item pastoral_home:party_lights [--out build/shots/name]');

const player = call('get_player', { player: 'Dev' });
const chest = { x: Math.round(player.x) + 1, y: Math.round(player.y), z: Math.round(player.z) - 1 };
command('time set noon');
command('weather clear');
command(`setblock ${chest.x} ${chest.y} ${chest.z} minecraft:chest replace`);
command(`item replace block ${chest.x} ${chest.y} ${chest.z} container.0 with ${opts.item} 1`);
call('close_container', {});
await sleep(400);
call('open_container', chest);
await sleep(900);
const screen = call('get_screen', {});
console.log('[item_view] screen ' + screen.screen);
shot(opts.out + '_gui.png');
console.log('[item_view] slot ' + cropSlot(opts.out + '_gui.png', 0));

call('close_container', {});
await sleep(400);
command(`item replace entity @p hotbar.0 with ${opts.item} 1`);
call('select_hotbar_slot', { slot: 0 });
await sleep(900);
shot(opts.out + '_hand.png');
console.log('[item_view] hand ' + locate(opts.out + '_hand.png', [1180, 560, 1920, 1080]));
command(`setblock ${chest.x} ${chest.y} ${chest.z} minecraft:air replace`);
