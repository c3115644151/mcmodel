#!/usr/bin/env node
// Deterministic in-game probe harness.
//
// Every in-game check in this repo follows the same shape: reset the arena, stage a scene,
// point a camera, then read numbers back. Doing that by hand costs minutes per iteration and
// produces answers that cannot be diffed. This tool runs a job file end to end and writes one
// JSON report, so a regression shows up as a changed number, not as a changed screenshot.
//
// Usage:
//   node tools/mcpfabric/scene_probe.mjs build/probes/jobs/<job>.json
//
// Job shape (only name is required):
// {
//   "name": "rope_lamps",
//   "reload": {"command": "pastoral_home_preview reload", "settleMs": 25000},
//   "reset":  ["kill @e[type=pastoral_home:bridge_rope]"],
//   "script": "build/scenes/rope_lamps.js",
//   "after":  ["tp Dev 119.5 -61 -196 180 15"],
//   "waitMs": 500,
//   "commands": ["data get entity @e[type=pastoral_home:bridge_rope,limit=1]"],
//   "entities": [{"type": "pastoral_home:bridge_rope", "radius": 32,
//                 "position": [120, -60, -200]}],
//   "blocks": [[117, -62, -200], [122, -62, -200]],
//   "shots": [{"name": "front", "out": "build/shots/rope.png",
//              "camera": {"x": 119.5, "y": -61, "z": -196, "yaw": 180, "pitch": 15}}]
// }
//
// Report: build/probes/<name>.json, and the same JSON on stdout.

import { execFileSync } from "node:child_process";
import { shotFor, projectBox, azimuthAway } from "./frame.mjs";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CALL = resolve(ROOT, "tools/mcpfabric/call-tool.mjs");

function run(tool, argString, imageOut = null) {
  const env = { ...process.env };
  if (imageOut) env.MCPFABRIC_IMAGE_OUT = resolve(ROOT, imageOut);
  let raw;
  try {
    raw = execFileSync(process.execPath, [CALL, tool, argString], {
      cwd: ROOT, env, encoding: "utf8", maxBuffer: 64 * 1024 * 1024,
    });
  } catch (error) {
    return { ok: false, error: String(error.stdout || error.message).slice(-2000) };
  }
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start < 0 || end < start) return { ok: true, raw: raw.slice(-2000) };
  try {
    return { ok: true, value: JSON.parse(raw.slice(start, end + 1)) };
  } catch {
    return { ok: true, raw: raw.slice(-2000) };
  }
}

const tool = (name, args, imageOut) => run(name, JSON.stringify(args), imageOut);
const command = (text) => tool("run_command", { command: text });
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const rel = (path) => path.replace(/\\/g, "/");

// get_screen answers flat today, but tool payloads have moved between builds, so dig by key name
// instead of hard-coding one nesting level.
function dig(value, key) {
  if (value === null || typeof value !== "object") return undefined;
  if (key in value) return value[key];
  for (const child of Object.values(value)) {
    const found = dig(child, key);
    if (found !== undefined) return found;
  }
  return undefined;
}

function screenState() {
  const answer = tool("get_screen", {});
  return {
    inWorld: dig(answer, "inWorld"),
    screen: dig(answer, "screen"),
    paused: dig(answer, "paused"),
  };
}

const RESUME_WORDS = ["回到游戏", "back to game", "继续游戏", "resume", "关闭", "close", "done", "完成"];

// A screenshot taken while a screen is open photographs the menu, not the scene: the job then looks
// like it ran fine and the numbers are garbage. Leave the screen first, and stop the job if it stays.
function leaveScreen(where) {
  let state = screenState();
  if (state.screen === "none") return state;
  tool("close_container", {});
  sleep(700);
  state = screenState();
  if (state.screen === "none") return state;
  const ui = tool("get_ui", {});
  const widgets = (dig(ui, "widgets") ?? []);
  const texts = widgets.map((widget) => String(widget.text ?? widget.label ?? "").trim());
  const pick = RESUME_WORDS.find((word) => texts.some((text) => text.toLowerCase() === word));
  if (pick) {
    const exact = texts.find((text) => text.toLowerCase() === pick);
    tool("click_widget", { widget: exact });
    sleep(900);
    state = screenState();
  }
  if (state.screen !== "none") {
    throw new Error(where + ": a screen is open (" + state.screen + ", paused=" + state.paused
      + ", buttons=" + JSON.stringify(texts) + "); a screenshot would photograph the menu");
  }
  return state;
}

// A shot can say what has to be in frame ("subject") instead of where to stand. The camera is
// derived, so a hand-written yaw/pitch cannot silently point at the sky, and the report carries the
// pixel box the subject should occupy -- the crop that used to be guessed per screenshot.
function frameShot(shot) {
  if (!shot.subject) return { camera: shot.camera ?? null, frame: null };
  const width = shot.width ?? 1920;
  const height = shot.height ?? 1080;
  const own = shotFor({ blocks: shot.subject, azimuth: 0, feet: null });
  const away = shot.away ? azimuthAway(own.subject.center, shot.away) : null;
  const placed = shotFor({
    blocks: shot.subject,
    azimuth: shot.azimuth ?? away ?? 0,
    elevation: shot.elevation ?? 15,
    distance: shot.distance ?? null,
    zoom: shot.zoom ?? undefined,
    feet: shot.feet ?? null,
    width, height,
    pad: shot.pad ?? 0,
  });
  const eye = placed.eye;
  const box = projectBox(placed.subject, eye, placed.camera.yaw, placed.camera.pitch, width, height);
  return { camera: placed.camera, frame: box };
}

function shoot(rawShot) {
  const framed = frameShot(rawShot);
  const shot = { ...rawShot, camera: framed.camera };
  const camera = shot.camera;
  const before = leaveScreen("shot " + (shot.name ?? shot.out));
  if (camera) {
    const player = camera.player ?? "Dev";
    command("tp " + player + " " + camera.x + " " + camera.y + " " + camera.z
      + " " + (camera.yaw ?? 180) + " " + (camera.pitch ?? 0));
    sleep(250);
  }
  leaveScreen("shot " + (shot.name ?? shot.out) + " after teleport");
  tool("world.setTime", { time: shot.time ?? 1000 });
  sleep(400);
  const after = screenState();
  if (after.paused) throw new Error("shot " + (shot.name ?? shot.out) + ": the world is paused");
  const image = tool("screenshot", { marks: false }, shot.out);
  // The report has to describe what it shot: the audit derives the model's pixel box from the block
  // state, so the subject coordinates it looked up have to travel with the shot.
  return {
    out: shot.out,
    subject: shot.subject ?? null,
    camera,
    frame: framed.frame,
    expect: shot.expect ?? null,
    screen: after,
    image,
  };
}

function main() {
  const jobPath = process.argv[2];
  if (!jobPath) {
    console.error("usage: node tools/mcpfabric/scene_probe.mjs <job.json>");
    process.exit(2);
  }
  const job = JSON.parse(readFileSync(resolve(ROOT, jobPath), "utf8"));
  const name = job.name ?? "scene";
  const report = { name, startedAt: new Date().toISOString(), status: tool("get_status", {}) };
  report.screenAtStart = tool("get_screen", {});

  // A resource reload rebuilds the atlases and drops the player's view state, so it has to run
  // before the arena is staged - staging first photographs an empty wall, and the frame looks
  // like a world, not like an error.
  if (job.reload) {
    report.reload = command(job.reload.command ?? "pastoral_home_preview reload");
    sleep(job.reload.settleMs ?? 25000);
  }

  report.reset = (job.reset ?? []).map((text) => ({ text, result: command(text) }));

  if (job.script) {
    const source = readFileSync(resolve(ROOT, job.script), "utf8");
    const payloadPath = resolve(ROOT, "build/probes/" + name + "-script.json");
    mkdirSync(dirname(payloadPath), { recursive: true });
    writeFileSync(payloadPath, JSON.stringify({ code: source }), "utf8");
    report.script = run("run_script", "@" + rel(payloadPath));
  }

  report.after = (job.after ?? []).map((text) => ({ text, result: command(text) }));
  // run_script acknowledges before its queued commands have run, so a job that reads the
  // world straight afterwards sees the state from before the script. Settle first, always.
  sleep(job.waitMs ?? 800);

  report.commands = {};
  for (const text of job.commands ?? []) report.commands[text] = command(text);

  report.entities = {};
  report.entityChecks = [];
  for (const probe of job.entities ?? []) {
    const key = probe.type + "@" + (probe.position ?? []).join(",");
    const found = tool("query_entities", {
      type: probe.type,
      radius: probe.radius ?? 32,
      position: { x: probe.position[0], y: probe.position[1], z: probe.position[2] },
    });
    report.entities[key] = found;
    const payload = (found && found.value) || {};
    const total = payload.data ? payload.data.total : null;
    if (typeof probe.min === "number") {
      const ok = typeof total === "number" && total >= probe.min;
      report.entityChecks.push({ type: probe.type, want: probe.min, total, ok });
      if (!ok) {
        console.error("[probe] " + probe.type + " near " + key.split("@")[1]
          + ": expected >= " + probe.min + ", found " + total);
      }
    }
  }

  report.blocks = {};
  // A block probe is written as [x,y,z] or {position:[x,y,z]}; accept both so a job file copied
  // from an entities entry does not fail on the shape alone.
  for (const entry of job.blocks ?? []) {
    const pos = Array.isArray(entry) ? entry : (entry && entry.position);
    if (!Array.isArray(pos) || pos.length !== 3) {
      throw new Error("blocks entry needs [x,y,z] or {position:[x,y,z]}: " + JSON.stringify(entry));
    }
    report.blocks[pos.join(",")] = tool("get_block", { x: pos[0], y: pos[1], z: pos[2] });
  }

  report.shots = {};
  for (const shot of job.shots ?? []) report.shots[shot.name ?? shot.out] = shoot(shot);

  report.finishedAt = new Date().toISOString();
  const outPath = resolve(ROOT, "build/probes/" + name + ".json");
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
  console.log("report written: " + rel(outPath));
}

main();
