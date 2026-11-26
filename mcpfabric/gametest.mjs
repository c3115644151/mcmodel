#!/usr/bin/env node
// Run GameTestServer and return the moment the verdict lands in the log.
// The dedicated test JVM hangs on sodium-workaround-cleanup at shutdown; killing
// the process tree right after the verdict saves several minutes every run.
import { spawn, spawnSync } from "node:child_process";
import { openSync, readFileSync, existsSync, writeSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const LOG = resolve(ROOT, "build/gametest_run.log");
const GRADLE = resolve(ROOT, "gradlew.bat");
const TIMEOUT_MS = 20 * 60 * 1000;

const fd = openSync(LOG, "w");
const child = spawn(GRADLE,
  ["--offline", "--console=plain", "--no-daemon", "runGameTestServer"],
  { cwd: ROOT, shell: true, windowsHide: true, stdio: ["ignore", fd, fd] });
child.on("error", (e) => writeSync(fd, "\n[spawn error] " + String(e) + "\n"));

function verdict() {
  if (!existsSync(LOG)) return null;
  const text = readFileSync(LOG, "utf8");
  if (!text.includes("GAME TESTS COMPLETE")) return null;
  if (text.includes("required tests passed")) return "PASS";
  if (text.includes("required tests failed")) return "FAIL";
  return null;
}

const started = Date.now();
const timer = setInterval(() => {
  const v = verdict();
  if (!v && Date.now() - started < TIMEOUT_MS) return;
  clearInterval(timer);
  try { spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true }); } catch (e) {}
  setTimeout(() => {
    const text = existsSync(LOG) ? readFileSync(LOG, "utf8") : "";
    for (const line of text.split(/\r?\n/)) {
      if (line.includes("GAME TESTS COMPLETE") || line.includes("required tests"))
        console.log(line.trim());
    }
    const final = v || "TIMEOUT";
    console.log("[gametest] " + final);
    process.exit(final === "PASS" ? 0 : final === "FAIL" ? 1 : 2);
  }, 800);
}, 1500);