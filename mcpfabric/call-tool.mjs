import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { fileURLToPath } from "node:url";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { existsSync, readdirSync } from "node:fs";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

// mcpfabric-mcp-server needs node:sqlite (Node 22.16+ / 23+ / 24+). The default shell
// Node may be older (nvm4w keeps several engines side by side), which silently drops the
// server's agent runtime, so spawn the server with a Node that can load node:sqlite.
function nodeSupportsSqlite(version) {
  const match = /^v(\d+)\.(\d+)\./.exec(version.trim());
  if (!match) return false;
  const major = Number(match[1]);
  const minor = Number(match[2]);
  return major > 22 || (major === 22 && minor >= 16);
}

function resolveServerNode() {
  const explicit = process.env.MCPFABRIC_NODE;
  if (explicit && existsSync(explicit)) return explicit;
  const nvmHome = process.env.NVM_HOME ?? process.env.NVM_ROOT;
  if (nvmHome && existsSync(nvmHome)) {
    const candidates = readdirSync(nvmHome)
      .filter((entry) => entry.startsWith("v"))
      .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
      .reverse();
    for (const entry of candidates) {
      if (!nodeSupportsSqlite(entry)) continue;
      const exe = path.join(nvmHome, entry, process.platform === "win32" ? "node.exe" : "bin/node");
      if (existsSync(exe)) return exe;
    }
  }
  return process.execPath;
}

const serverNode = resolveServerNode();
if (!nodeSupportsSqlite(process.versions.node) && serverNode === process.execPath) {
  process.stderr.write(
    "[mcpfabric-bridge] WARNING: running bridge on Node " + process.versions.node +
    " (no node:sqlite). Set MCPFABRIC_NODE to a Node 22.16+ executable to enable the server agent runtime.\n",
  );
}
const [name, rawArguments = "{}"] = process.argv.slice(2);
if (!name) throw new Error("Usage: node call-tool.mjs <tool-name> [arguments-json]");
const transport = new StdioClientTransport({
  command: serverNode,
  args: [path.join(projectRoot, "tools/mcpfabric/node_modules/mcpfabric-mcp-server/dist/index.js")],
  cwd: projectRoot,
  stderr: "inherit",
});
const client = new Client({ name: "pastoral-home-mcpfabric-control", version: "1.0.0" });
try {
  await client.connect(transport);
  if (name === "--schema") {
    const toolName = rawArguments;
    const tools = await client.listTools();
    const tool = tools.tools.find((entry) => entry.name === toolName);
    if (!tool) throw new Error(`Unknown tool: ${toolName}`);
    process.stdout.write(JSON.stringify(tool, null, 2) + "\n");
  } else if (name === "--list") {
    const tools = await client.listTools();
    for (const tool of tools.tools) process.stdout.write(`${tool.name}\t${tool.description ?? ""}\n`);
    process.exitCode = 0;
  } else {
  // Accept @path so PowerShell/cmd quoting cannot mangle JSON payloads.
  const payload = rawArguments.startsWith("@")
    ? await readFile(rawArguments.slice(1), "utf8")
    : rawArguments;
  const result = await client.callTool({ name, arguments: JSON.parse(payload.replace(/^\uFEFF/, "")) });
  for (const block of result.content ?? []) {
    if (block.type === "text") process.stdout.write(`${block.text}\n`);
    else if (block.type === "image") {
      const out = process.env.MCPFABRIC_IMAGE_OUT;
      if (out) {
        const { writeFile } = await import("node:fs/promises");
        await writeFile(out, Buffer.from(block.data, "base64"));
        process.stdout.write(`[image saved] ${out} (${block.data.length} base64 chars)\n`);
      } else {
        process.stdout.write(`[image ${block.mimeType} ${block.data.length} base64 chars]\n`);
      }
    }
    else process.stdout.write(`[${block.type}]\n`);
  }
  if (result.isError) process.exitCode = 1;
  }
} finally {
  await client.close();
}
