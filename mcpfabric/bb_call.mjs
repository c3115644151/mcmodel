import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { readFileSync, writeFileSync } from "node:fs";

const CANDIDATES = [process.env.BB_MCP_URL, "http://[::1]:3000/bb-mcp", "http://127.0.0.1:3000/bb-mcp"]
  .filter((value) => value && value.length);
// Blockbench's MCP plugin binds the IPv6 wildcard on this machine, so 127.0.0.1 refuses while [::1]
// answers. Probe both instead of making the caller pass BB_MCP_URL every time.
async function pickUrl() {
  for (const candidate of CANDIDATES) {
    try {
      await fetch(candidate, { method: "GET", signal: AbortSignal.timeout(1500) });
      return new URL(candidate);
    } catch {
      // try the next address
    }
  }
  console.error("[bb] no Blockbench MCP answered on " + CANDIDATES.join(", "));
  process.exit(2);
}
const url = await pickUrl();
const [name, argsPath, outPath] = process.argv.slice(2);
const args = JSON.parse(readFileSync(argsPath, "utf8"));
const client = new Client({ name: "dsh-bb-call", version: "1.0.0" });
const transport = new StreamableHTTPClientTransport(url);
await client.connect(transport);
try {
  const result = await client.callTool({ name, arguments: args });
  const texts = [];
  for (const b of result.content ?? []) {
    if (b.type === "text") texts.push(b.text);
    else if (b.type === "image") {
      if (outPath) { writeFileSync(outPath, Buffer.from(b.data, "base64")); texts.push("[image saved] " + outPath); }
      else texts.push("[image " + b.data.length + " chars]");
    } else texts.push("[" + b.type + "]");
  }
  const text = texts.join("\n");
  if (outPath && !outPath.endsWith(".png")) writeFileSync(outPath, text, "utf8");
  console.log(text.slice(0, 6000));
  if (result.isError) process.exitCode = 1;
} finally {
  await client.close().catch(() => {});
}