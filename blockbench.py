#!/usr/bin/env python3
"""Start Blockbench, optionally opening a .bbmodel, then verify MCP."""
import argparse
import os
import subprocess
import time
import urllib.request

DEFAULT_EXE = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blockbench\Blockbench.exe")


def wait_for_mcp(timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:3000/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="?", help=".bbmodel file to open")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--exe", default=DEFAULT_EXE)
    args = parser.parse_args()
    if not os.path.isfile(args.exe):
        raise SystemExit(f"Blockbench executable not found: {args.exe}")
    command = [args.exe]
    if args.model:
        model = os.path.abspath(args.model)
        if not os.path.isfile(model) or not model.lower().endswith(".bbmodel"):
            raise SystemExit(f"Model must be an existing .bbmodel file: {model}")
        command.append(model)
    subprocess.Popen(command, close_fds=True)
    if not wait_for_mcp(args.timeout):
        raise SystemExit("Blockbench started, but MCP health check timed out")
    print("PASS: Blockbench MCP is ready")
    print(f"  opened: {os.path.abspath(args.model) if args.model else 'recent-projects page'}")


if __name__ == "__main__":
    main()
