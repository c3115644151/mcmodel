#!/usr/bin/env node
// Block until the running game answers a tool call, then print one line and exit.
//
// node tools/mcpfabric/wait-bridge.mjs [timeoutSeconds]
//
// A fixed sleep either wastes time or guesses wrong: the client is ready the moment the bridge
// answers, which is minutes after launch and not predictable. Callers run this in the background
// and read its single READY line instead of polling by hand.
import { withBridge, resultText } from "./bridge.mjs";

const timeoutSeconds = Number(process.argv[2] ?? 600);
const deadline = Date.now() + timeoutSeconds * 1000;
const started = Date.now();

for (;;) {
  try {
    const status = await withBridge(async (client) => {
      const result = await client.callTool({ name: "get_status", arguments: {} });
      return resultText(result).trim();
    });
    const seconds = ((Date.now() - started) / 1000).toFixed(1);
    process.stdout.write(`READY after ${seconds}s ${status.slice(0, 400)}\n`);
    process.exit(0);
  } catch {
    if (Date.now() > deadline) {
      process.stdout.write(`NOT-READY after ${timeoutSeconds}s\n`);
      process.exit(1);
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}
