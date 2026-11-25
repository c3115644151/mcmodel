#!/usr/bin/env node
// Reload Minecraft's resource manager on the running preview client, then prove it settled.
//
// Models, textures, blockstates and lang all live in the resource manager: `pastoral_home_preview reload`
// calls Minecraft.reloadResourcePacks(), the same path as F3+T, so a model edit costs ~20 s instead of the
// four-minute stop-preview/start-preview lap. Java constants and classes still need a real rebuild.
//
// Usage: node tools/mcpfabric/resource_reload.mjs [--settle 25000] [--dry]
//   --settle  how long to wait before trusting the framebuffer (the loading overlay hangs around)
//   --dry     only report the current screen, do not reload
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import process from 'node:process';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const callTool = path.join(here, 'call-tool.mjs');
const argv = process.argv.slice(2);
const settleIndex = argv.indexOf('--settle');
const settleMs = settleIndex >= 0 ? Number(argv[settleIndex + 1]) : 25000;
const dry = argv.includes('--dry');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function run(tool, payload) {
  return new Promise((resolve) => {
    execFile(process.execPath, [callTool, tool, JSON.stringify(payload ?? {})], { cwd: path.join(here, '../..'), maxBuffer: 8 * 1024 * 1024 },
      (error, stdout) => {
        const text = String(stdout ?? '');
        const start = text.indexOf('{');
        if (start < 0) return resolve({ ok: false, raw: text.trim().slice(0, 400), error: error ? String(error.message) : '' });
        try {
          const parsed = JSON.parse(text.slice(start));
          resolve({ ok: true, data: parsed.data ?? parsed });
        } catch (parseError) {
          resolve({ ok: false, raw: text.trim().slice(0, 400), error: String(parseError.message) });
        }
      });
  });
}

async function screen() {
  const reply = await run('get_screen');
  return reply.data ?? {};
}

async function main() {
  const before = await screen();
  if (!before.inWorld) { console.log('[reload] not in a world: ' + JSON.stringify(before)); return 1; }
  if (dry) { console.log('[reload] dry run: ' + JSON.stringify(before)); return 0; }
  const started = Date.now();
  const reply = await run('run_command', { command: 'pastoral_home_preview reload' });
  console.log('[reload] dispatched in ' + (Date.now() - started) + 'ms: ' + JSON.stringify(reply.data ?? reply.raw));
  await sleep(settleMs);
  let after = await screen();
  for (let i = 0; i < 20 && !(after.inWorld && after.screen === 'none'); i += 1) {
    await sleep(2000);
    after = await screen();
  }
  const ok = Boolean(after.inWorld && after.screen === 'none');
  console.log('[reload] ' + (ok ? 'ready' : 'still busy') + ' after ' + Math.round((Date.now() - started) / 1000) + 's: ' + JSON.stringify(after));
  return ok ? 0 : 1;
}

process.exit(await main());