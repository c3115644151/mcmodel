import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const cliPath = resolve("node_modules/minecraft-mod-mcp/dist/cli.js");
const transport = new StdioClientTransport({
  command: process.env.MCPMOD_NODE ?? process.execPath,
  args: [cliPath],
  env: { ...process.env },
  stderr: "pipe",
});
const client = new Client({ name: "pastoral-home-mcpmod-bridge", version: "1.0.0" }, { capabilities: {} });
await client.connect(transport);

const [first, second] = process.argv.slice(2);
const list = await client.listTools();
const writeImages = (result) => {
  const out = process.env.MCPMOD_IMAGE_OUT;
  if (!out) return result;
  for (const [index, block] of (result.content ?? []).entries()) {
    if (block.type !== "image") continue;
    const target = (result.content ?? []).filter((b) => b.type === "image").length > 1
      ? out.replace(/\.png$/i, `_${index}.png`)
      : out;
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, Buffer.from(block.data, "base64"));
    block.savedPath = target;
    block.data = block.data.slice(0, 32) + "…";
  }
  return result;
};

if (!first || first === "--list") {
  console.log(JSON.stringify(list.tools.map((t) => ({ name: t.name, description: t.description })), null, 2));
} else if (first === "--schema") {
  const tool = list.tools.find((t) => t.name === second);
  console.log(JSON.stringify(tool ?? { error: "no such tool" }, null, 2));
} else {
  const payload = second ? JSON.parse(second.replace(/^\uFEFF/, "")) : {};
  const result = await client.callTool({ name: first, arguments: payload });
  console.log(JSON.stringify(writeImages(result), null, 2));
}
await client.close();
