#!/usr/bin/env python3
"""Verify the local Blockbench MCP endpoint and report available tools."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tmp"))
from mcp_client import init_session, list_tools, call_tool


def main():
    session = init_session()
    if not session:
        print("FAIL: Blockbench MCP is not reachable at http://localhost:3000/bb-mcp")
        return 1
    tools = list_tools(session)
    if not tools or tools[0][0] == "error":
        print("FAIL: MCP session initialized but tools/list failed")
        return 1
    info = call_tool("get_project_info", {}, session=session)
    content = info.get("content", []) if isinstance(info, dict) else []
    project_text = next((item.get("text", "") for item in content if item.get("type") == "text"), "")
    print(f"PASS: MCP session {session}")
    print(f"  tools: {len(tools)}")
    print(f"  project: {project_text or 'none (open a .bbmodel in Blockbench)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
