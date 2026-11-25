#!/usr/bin/env node
// Takes a preview client from "process is up" to "player is standing in the preview world" without
// a human in the loop. The launcher lands on whatever screen the previous session left behind - a
// mod update notice, the title screen, or the world - so the only reliable driver is: look at the
// screen, press the button that moves forward, repeat.
//
// Usage: node tools/mcpfabric/enter_world.mjs [--world=sp:PastoralHomeVisualPreview] [--timeout=300]

import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CALL = resolve(ROOT, "tools/mcpfabric/call-tool.mjs");
const args = process.argv.slice(2);
const world = (args.find((entry) => entry.startsWith("--world=")) ?? "--world=sp:PastoralHomeVisualPreview")
  .slice("--world=".length);
const timeoutMs = Number((args.find((entry) => entry.startsWith("--timeout=")) ?? "--timeout=300")
  .slice("--timeout=".length)) * 1000;

const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const log = (message) => console.log("[enter] " + message);

function raw(name, payload = "{}") {
  const result = spawnSync(process.execPath, [CALL, name, payload], { cwd: ROOT, encoding: "utf8" });
  return (result.stdout || "") + (result.stderr || "");
}

// call-tool.mjs prints its own [mcpfabric] log lines before the payload, so cut everything before
// the first line that starts a JSON object and parse from there.
function json(name, payload = "{}") {
  const text = raw(name, payload);
  const lines = text.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    if (!lines[index].trimStart().startsWith("{")) continue;
    for (let end = lines.length; end > index; end -= 1) {
      try {
        return JSON.parse(lines.slice(index, end).join("\n"));
      } catch {}
    }
  }
  return null;
}

// Tool payloads wrap their fields at different depths depending on the call, so read by key name
// anywhere in the tree instead of hard-coding one path.
function dig(value, key) {
  if (value === null || typeof value !== "object") return undefined;
  if (Array.isArray(value)) {
    for (const entry of value) {
      const hit = dig(entry, key);
      if (hit !== undefined) return hit;
    }
    return undefined;
  }
  if (key in value) return value[key];
  for (const entry of Object.values(value)) {
    const hit = dig(entry, key);
    if (hit !== undefined) return hit;
  }
  return undefined;
}

// Ordered by how early they appear: acknowledging the mod update notice also skips the title
// screen, so a single press can carry the client all the way into the world.
const ADVANCE = ["don't show again", "继续进入", "继续", "continue", "是", "yes", "回到游戏", "back to game"];

function press(widgets) {
  for (const wanted of ADVANCE) {
    const hit = widgets.find((widget) => (widget.text || "").toLowerCase().includes(wanted));
    if (hit) {
      log("pressing " + JSON.stringify(hit.text));
      raw("click_widget", JSON.stringify({ widget: hit.text }));
      return true;
    }
  }
  return false;
}

const started = Date.now();
let lastScreen = "";
while (Date.now() - started < timeoutMs) {
  const screen = json("get_screen");
  const inWorld = screen ? dig(screen, "inWorld") === true : false;
  const screenName = screen ? dig(screen, "screen") : undefined;
  if (inWorld && (!screenName || screenName === "none")) {
    log("in world after " + Math.round((Date.now() - started) / 1000) + "s");
    process.exit(0);
  }
  // Already in the world but a container or similar GUI is open: close it instead of hunting for a
  // button, because those GUIs have no "forward" widget and pressing their arrows changes the view.
  if (inWorld && screenName && screenName !== "none") {
    if (lastScreen !== screenName) log("closing screen: " + screenName);
    lastScreen = screenName;
    // A container screen has its own closing tool; screen.close exists only as a bridge capability.
    raw("close_container");
    sleep(1200);
    continue;
  }
  const ui = json("get_ui");
  if (ui) {
    const name = dig(ui, "screen") || dig(ui, "title") || "?";
    if (name !== lastScreen) {
      log("screen: " + name);
      lastScreen = name;
    }
    if (press(dig(ui, "widgets") || [])) {
      sleep(2500);
      continue;
    }
    if (/title|main menu|mainmenu/i.test(String(name))) {
      raw("join_world", JSON.stringify({ worldId: world }));
      sleep(6000);
      continue;
    }
  }
  sleep(2000);
}
console.error("[enter] timed out without reaching the world");
process.exit(1);
