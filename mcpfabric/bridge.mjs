import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { fileURLToPath } from "node:url";
import { existsSync, readdirSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

// mcpfabric-mcp-server needs node:sqlite (Node 22.16+ / 23+ / 24+). The default shell Node may
// be older (nvm4w keeps several engines side by side), which silently drops the server's agent
// runtime, so spawn the server with a Node that can load node:sqlite.
function nodeSupportsSqlite(version) {
  const match = /^v(\d+)\.(\d+)\./.exec(version.trim());
  if (!match) return false;
  const major = Number(match[1]);
  const minor = Number(match[2]);
  return major > 22 || (major === 22 && minor >= 16);
}

export function resolveServerNode() {
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

export function serverCommand() {
  return {
    command: resolveServerNode(),
    args: [path.join(projectRoot, "tools/mcpfabric/node_modules/mcpfabric-mcp-server/dist/index.js")],
    cwd: projectRoot,
    // The SDK hands the server a scrubbed default environment, which drops MCPFABRIC_URL/TOKEN and
    // leaves the server guessing from the global discovery file. Two clients can run side by side
    // (the preview build and a hand-started dev client), so the bridge address has to travel with
    // the run that asked for it.
    env: process.env,
    stderr: "inherit",
  };
}

/** Run fn(client) inside one MCP session, so a sequence of tool calls shares one handshake. */
export async function withBridge(fn) {
  const transport = new StdioClientTransport(serverCommand());
  const client = new Client({ name: "pastoral-home-mcpfabric-control", version: "1.0.0" });
  try {
    await client.connect(transport);
    return await fn(client);
  } finally {
    await client.close();
  }
}

/** Text blocks of a tool result, joined; images are reported as a marker, never inlined. */
/** Text blocks of a tool result, joined. An image is written to MCPFABRIC_IMAGE_OUT when that
 * variable is set (screenshot callers rely on it) and always reported as a marker, never inlined. */
export function resultText(result) {
  const parts = [];
  let sequence = 0;
  for (const block of result?.content ?? []) {
    if (block.type === "text") parts.push(block.text);
    else if (block.type === "image") {
      const target = process.env.MCPFABRIC_IMAGE_OUT;
      const suffix = sequence++ === 0 ? "" : `.${sequence}`;
      if (target) {
        const path = suffix ? target.replace(/(\.[^./\\]+)$/, suffix + "$1") : target;
        mkdirSync(path.slice(0, path.lastIndexOf("/") > -1 ? path.lastIndexOf("/") : path.lastIndexOf("\\")), { recursive: true });
        writeFileSync(path, Buffer.from(block.data, "base64"));
        parts.push(`[image ${block.mimeType} saved ${path}]`);
      } else {
        parts.push(`[image ${block.mimeType} ${block.data.length} base64 chars]`);
      }
    } else parts.push(`[${block.type}]`);
  }
  return parts.join("\n");
}

/** Parse the JSON payload a bridge tool prints, tolerating the [mcpfabric] noise lines. */
export function firstJson(text) {
  const whole = text.trim();
  if (whole.startsWith("{")) {
    try {
      return JSON.parse(whole);
    } catch {
      // pretty-printed answers are scanned line by line below
    }
  }
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("{")) continue;
    try {
      return JSON.parse(trimmed);
    } catch {
      // keep scanning
    }
  }
  return null;
}