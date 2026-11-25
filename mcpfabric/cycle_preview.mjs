#!/usr/bin/env node
// One command that turns "I changed Java code" into "there is a running client in the preview
// world". The manual version is five steps (stop, compile, start, wait, join) and each one costs
// minutes when it is done by hand and forgotten halfway.
//
// Usage:
//   node tools/mcpfabric/cycle_preview.mjs [--skip-compile] [--world=sp:PastoralHomeVisualPreview]
//
// Order matters: the client runs from compiled classes, so compileJava must finish before the
// launcher starts, and Gradle cannot be running twice in the same project.

import { execFileSync, spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CALL = resolve(ROOT, "tools/mcpfabric/call-tool.mjs");
const args = process.argv.slice(2);

// A bare "--help" used to fall through and run the whole cycle: it stopped the client and started a
// four minute compile. Reject anything that is not a known flag before touching the client.
const KNOWN = new Set(["--skip-compile", "--help", "-h"]);
const unknown = args.filter((entry) => !KNOWN.has(entry) && !entry.startsWith("--world="));
if (args.includes("--help") || args.includes("-h") || unknown.length) {
  if (unknown.length) console.log("[cycle] unknown argument: " + unknown.join(" "));
  console.log("usage: node tools/mcpfabric/cycle_preview.mjs [--skip-compile] [--world=sp:PastoralHomeVisualPreview]");
  process.exit(unknown.length ? 2 : 0);
}

const skipCompile = args.includes("--skip-compile");
const world = (args.find((entry) => entry.startsWith("--world=")) ?? "--world=sp:PastoralHomeVisualPreview")
  .slice("--world=".length);

const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const log = (message) => console.log("[cycle] " + message);

function node(args, options = {}) {
  return spawnSync(process.execPath, args, { cwd: ROOT, encoding: "utf8", stdio: "inherit", ...options });
}

function call(name, payload = "{}") {
  const result = spawnSync(process.execPath, [CALL, name, payload], { cwd: ROOT, encoding: "utf8" });
  return (result.stdout || "") + (result.stderr || "");
}

function probe(timeoutMs, predicate, label) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const text = call("get_status");
    if (predicate(text)) {
      log(label + " after " + Math.round((Date.now() - started) / 1000) + "s");
      return text;
    }
    sleep(5000);
  }
  throw new Error("timed out waiting for " + label);
}

log("stopping any running preview client");
node(["run-powershell.mjs", "stop-preview.ps1"], { cwd: resolve(ROOT, "tools/mcpfabric") });

if (!skipCompile) {
  log("compiling (gradlew compileJava)");
  const compiled = spawnSync("cmd", ["/c", "gradlew.bat --offline --console=plain compileJava"], {
    cwd: ROOT, encoding: "utf8", stdio: "inherit",
  });
  if (compiled.status !== 0) throw new Error("compileJava failed");
}

log("launching the preview client");
const launched = spawnSync("npm", ["--prefix", "tools/mcpfabric", "run", "start-preview"], {
  cwd: ROOT, encoding: "utf8", shell: true,
});
const launchText = (launched.stdout || "") + (launched.stderr || "");
console.log(launchText.trim().split("\n").slice(-3).join("\n"));
if (launched.status !== 0) throw new Error("start-preview failed");

probe(480_000, (text) => !/bridge not reachable|Bridge unreachable/.test(text), "bridge reachable");
// Screens in between change from session to session (mod update notice, title, world), so hand the
// rest to the driver that presses whatever moves forward instead of assuming a fixed sequence.
const entered = spawnSync(process.execPath, [resolve(ROOT, "tools/mcpfabric/enter_world.mjs"),
  "--world=" + world, "--timeout=300"], { cwd: ROOT, encoding: "utf8", stdio: "inherit" });
if (entered.status !== 0) throw new Error("did not reach the world");
log("ready");
