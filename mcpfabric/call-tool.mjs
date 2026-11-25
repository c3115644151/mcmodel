import { readFile } from "node:fs/promises";
import { withBridge, resultText, resolveServerNode, serverCommand } from "./bridge.mjs";

// Spawn the MCP server with a Node that can load node:sqlite (the agent runtime needs it).
const serverNode = resolveServerNode();
const spawned = serverCommand();
if (!process.versions.node.startsWith("v") || serverNode === process.execPath) {
  // serverCommand already chose the best available node; warn only when nothing better exists.
  const major = Number(process.versions.node.replace(/^v/, "").split(".")[0]);
  const minor = Number(process.versions.node.replace(/^v/, "").split(".")[1] ?? 0);
  const sqlite = major > 22 || (major === 22 && minor >= 16);
  if (!sqlite) {
    process.stderr.write(
      "[mcpfabric-bridge] WARNING: running bridge on Node " + process.versions.node +
      " (no node:sqlite). Set MCPFABRIC_NODE to a Node 22.16+ executable to enable the server agent runtime.\n",
    );
  }
}
const [name, rawArguments = "{}"] = process.argv.slice(2);
if (!name) throw new Error("Usage: node call-tool.mjs <tool-name> [arguments-json]");

await withBridge(async (client) => {
  if (name === "--schema") {
    const tools = await client.listTools();
    const tool = tools.tools.find((entry) => entry.name === rawArguments);
    if (!tool) throw new Error(`Unknown tool: ${rawArguments}`);
    process.stdout.write(JSON.stringify(tool, null, 2) + "\n");
  } else if (name === "--list") {
    const tools = await client.listTools();
    for (const tool of tools.tools) process.stdout.write(`${tool.name}\t${tool.description ?? ""}\n`);
  } else {
    // Accept @path so PowerShell/cmd quoting cannot mangle JSON payloads.
    const payload = rawArguments.startsWith("@")
      ? await readFile(rawArguments.slice(1), "utf8")
      : rawArguments;
    const result = await client.callTool({ name, arguments: JSON.parse(payload.replace(/^\uFEFF/, "")) });
    process.stdout.write(resultText(result) + "\n");
    if (result.isError) process.exitCode = 1;
  }
});
