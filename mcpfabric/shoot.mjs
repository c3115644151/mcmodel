#!/usr/bin/env node
// One command per in-game photo session: stage the job, shoot it, then judge the pixels.
// The camera comes from the job's "subject", the crop comes from the probe report, and the verdict
// comes from shot_audit.py, so nothing here is eyeballed or hand-tuned between runs.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const job = process.argv[2];
if (!job) {
  console.error("usage: node tools/mcpfabric/shoot.mjs <job.json>");
  process.exit(2);
}
const name = JSON.parse(readFileSync(resolve(ROOT, job), "utf8")).name ?? "scene";

execFileSync(process.execPath, [resolve(ROOT, "tools/mcpfabric/scene_probe.mjs"), job], {
  cwd: ROOT, stdio: "ignore",
});
const report = "build/probes/" + name + ".json";
const code = execFileSync(resolve(ROOT, ".venv/Scripts/python.exe"),
  [resolve(ROOT, "tools/deploy/shot_audit.py"), report],
  { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
console.log(code.trim());
