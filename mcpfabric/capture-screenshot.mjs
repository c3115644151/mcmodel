import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const projectRoot = process.cwd();
const output = path.resolve(process.argv[2] ?? "build/mcpfabric-preview.png");
const serverPath = path.join(
  projectRoot,
  "tools/mcpfabric/node_modules/mcpfabric-mcp-server/dist/index.js",
);
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [serverPath],
  cwd: projectRoot,
  stderr: "inherit",
});
const client = new Client({ name: "pastoral-home-preview-capture", version: "1.0.0" });

try {
  await client.connect(transport);
  const screenResult = await client.callTool({ name: "get_screen", arguments: {} });
  const screenText = screenResult.content.find((entry) => entry.type === "text")?.text;
  let screenState = screenText ? JSON.parse(screenText) : null;
  // Showing a minimized client without activating it can surface Minecraft's
  // pause screen when focus was lost. Resume through the game bridge before
  // capture so the screenshot represents the live world.
  if (screenState?.data?.inWorld && screenState.data.screen === "pause") {
    await client.callTool({ name: "close_screen", arguments: {} });
    const resumed = await client.callTool({ name: "get_screen", arguments: {} });
    const resumedText = resumed.content.find((entry) => entry.type === "text")?.text;
    screenState = resumedText ? JSON.parse(resumedText) : null;
  }
  if (!screenState?.data?.inWorld || !["container", "other"].includes(screenState.data.screen)) {
    throw new Error("Safe preview capture requires an open GUI (container or JEI); refusing a mouse-grabbing world view.");
  }
  const result = await client.callTool({ name: "screenshot", arguments: {} });
  const image = result.content.find((entry) => entry.type === "image");
  if (!image) {
    throw new Error(`MCPFabric screenshot returned no image: ${JSON.stringify(result.content)}`);
  }
  await mkdir(path.dirname(output), { recursive: true });
  const bytes = Buffer.from(image.data, "base64");
  await writeFile(output, bytes);
  console.log(JSON.stringify({ path: output, mimeType: image.mimeType, bytes: bytes.length }));
} finally {
  await client.close();
}
