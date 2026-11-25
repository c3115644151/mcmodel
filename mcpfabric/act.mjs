#!/usr/bin/env node
// Run a list of bridge tool calls in one MCP session.
//
// node tools/mcpfabric/act.mjs @steps.json       steps = [{ "tool": "...", "args": {...}, "note": "..." }]
//
// A single call-tool.mjs process costs a handshake, so a whole interaction (give item -> look at
// the rope -> right-click -> read the entity) is one session instead of eight shells. Prints one
// line per step: the note, then the JSON the tool answered, condensed.
import { readFile } from "node:fs/promises";
import { withBridge, resultText, firstJson } from "./bridge.mjs";

const source = process.argv[2];
if (!source) throw new Error("Usage: node act.mjs @steps.json");
const text = source.startsWith("@") ? await readFile(source.slice(1), "utf8") : source;
const plan = JSON.parse(text.replace(/^\uFEFF/, ""));
const steps = plan.steps ?? plan;
let failures = 0;

await withBridge(async (client) => {
  for (const [index, step] of steps.entries()) {
    const label = step.note ?? step.tool;
    process.stdout.write(`[${index + 1}/${steps.length}] ${step.tool}  ${label}\n`);
    const result = await client.callTool({ name: step.tool, arguments: step.args ?? {} });
    const body = resultText(result).trim();
    if (result.isError) failures += 1;
    // Game tools wrap every answer in an "untrusted game data" envelope; printing it on each
    // step buries the payload, so show the data object when there is one.
    const envelope = firstJson(body);
    const payload = envelope && typeof envelope === "object" && "data" in envelope ? envelope.data : null;
    const shown = payload === null ? body : JSON.stringify(payload);
    const compact = shown.length > 900 ? shown.slice(0, 900) + " ..." : shown;
    process.stdout.write(`    ${compact}\n`);
    if (step.expect) {
      const ok = step.expect.every((needle) => body.includes(needle));
      process.stdout.write(`    expect ${ok ? "ok" : "MISSING"}: ${step.expect.join(", ")}\n`);
      if (!ok) failures += 1;
    }
    if (result.isError && step.tolerate) process.stdout.write("    (tolerated)\n");
  }
});

process.stdout.write(failures === 0 ? "[act] all steps ok\n" : `[act] ${failures} step(s) failed\n`);
process.exitCode = failures === 0 ? 0 : 1;