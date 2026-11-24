import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const url = new URL(process.env.BB_MCP_URL ?? "http://127.0.0.1:3000/bb-mcp");
const [mode, name, rawArgs] = process.argv.slice(2);
const client = new Client({ name: "dsh-blockbench-control", version: "1.0.0" });
const transport = new StreamableHTTPClientTransport(url);

try {
  await client.connect(transport);
  if (mode === "--list") {
    const tools = await client.listTools();
    for (const t of tools.tools) console.log(t.name + "\t" + (t.description ?? "").split("\n")[0]);
  } else if (mode === "--schema") {
    const tools = await client.listTools();
    const tool = tools.tools.find((t) => t.name === name);
    if (!tool) throw new Error("unknown tool " + name);
    console.log(JSON.stringify(tool, null, 2));
  } else {
    const result = await client.callTool({ name: mode, arguments: JSON.parse(rawArgs ?? "{}") });
    for (const b of result.content ?? []) {
      if (b.type === "text") console.log(b.text);
      else if (b.type === "image") {
        const out = process.env.BB_IMAGE_OUT;
        if (out) {
          const ext = (b.mimeType || "image/png").split("/")[1];
          const target = out.endsWith(".png") || out.endsWith(".jpg") ? out : out + "." + ext;
          const { writeFileSync } = await import("node:fs");
          writeFileSync(target, Buffer.from(b.data, "base64"));
          console.log("[image saved] " + target + " (" + b.data.length + " base64 chars)");
        } else {
          console.log("[image " + b.mimeType + " " + b.data.length + " chars]");
        }
      }
      else console.log("[" + b.type + "]");
    }
    if (result.isError) process.exitCode = 1;
  }
} catch (error) {
  console.error("BB-MCP-ERROR:", error?.message ?? error);
  process.exitCode = 2;
} finally {
  await client.close().catch(() => {});
}
