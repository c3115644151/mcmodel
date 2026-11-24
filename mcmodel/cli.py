"""Entry point: python -m mcmodel <command>.

The toolkit is a pipeline, so this is a dispatcher and nothing else. Each command runs the script
that already implements it, with the project root as the working directory, using the interpreter
that has Pillow installed. Duplicating logic here would create a second source of truth.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "tools/deploy"
from .registry import BY_NAME, STAGES, gate_commands, stage_commands


def interpreter() -> str:
    """Prefer the project venv: the gates need Pillow, and the system Python may not have it."""
    venv = ROOT / ".venv/Scripts/python.exe"
    if venv.exists():
        return str(venv)
    return sys.executable


def run_script(script: str, extra: list[str]) -> int:
    if script.startswith("gradle:"):
        # A couple of commands are Gradle tasks, not scripts: the artefact they produce (a jar) is
        # the thing under test, so re-implementing the packaging here would test something else.
        task = script.split(":", 1)[1]
        wrapper = ROOT / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
        # gradlew.bat is a batch file: CreateProcess cannot run it directly, so it needs cmd /c.
        # Calling it bare fails inside the wrapper's own file locking, which reads like a broken
        # Gradle install instead of a broken invocation.
        gradle = ["cmd", "/c", str(wrapper), "--offline", "--console=plain", task] + extra
        return subprocess.run(gradle, cwd=ROOT).returncode
    path = DEPLOY / script
    if not path.exists():
        print(f"missing script: {path}", file=sys.stderr)
        return 2
    if script.endswith(".ps1"):
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)] + extra
    else:
        command = [interpreter(), str(path)] + extra
    return subprocess.run(command, cwd=ROOT).returncode


def expand(commands: list) -> list:
    """Put every prerequisite before the command that reads its output, once."""
    ordered: list = []
    seen: set[str] = set()

    def visit(command) -> None:
        if command.name in seen:
            return
        for dependency in command.requires:
            visit(BY_NAME[dependency])
        seen.add(command.name)
        ordered.append(command)

    for command in commands:
        visit(command)
    return ordered


def describe() -> None:
    for stage in STAGES:
        commands = stage_commands(stage)
        print(f"\n{stage}  ({len(commands)})")
        for command in commands:
            marks = []
            if command.ci:
                marks.append("gate")
            if command.needs_game:
                marks.append("needs game")
            if not command.batch and command.args:
                marks.append("needs args")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            print(f"  {command.name:22} {command.summary}{suffix}")
            if command.args:
                print(f"  {'':22} args: {' '.join(command.args)}")


def doctor() -> int:
    """Report the facts a run depends on, instead of failing somewhere deep in a gate."""
    print(f"project      {ROOT}")
    checks: list[tuple[str, bool, str]] = []
    python = interpreter()
    checks.append(("python", True, python))
    pillow = subprocess.run([python, "-c", "import PIL; print(PIL.__version__)"],
                            capture_output=True, text=True)
    checks.append(("pillow", pillow.returncode == 0, (pillow.stdout or pillow.stderr).strip()))
    node = shutil.which("node")
    checks.append(("node", node is not None, node or "not on PATH (needed for observe)"))
    bridge = ROOT / "tools/mcpfabric/call-tool.mjs"
    checks.append(("bridge script", bridge.exists(), str(bridge)))
    build = ROOT / "build.gradle"
    checks.append(("gradle project", build.exists(), str(build)))
    models = ROOT / "tools/deploy/model_sources"
    count = len(list(models.rglob("*.bbmodel"))) if models.exists() else 0
    checks.append(("source models", count > 0, f"{count} .bbmodel under {models}"))
    bad = 0
    for name, ok, detail in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {name:14} {detail}")
        bad += 0 if ok else 1
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m mcmodel <command> [args...]\n")
        describe()
        return 0

    head, rest = argv[0], argv[1:]

    if head == "list":
        describe()
        return 0
    if head == "doctor":
        return doctor()
    if head == "gate":
        rebuild = "--no-build" not in rest
        rest = [item for item in rest if item != "--no-build"]
        targets = [BY_NAME[item] for item in rest] if rest else list(gate_commands())
        if rebuild and not rest:
            # A full gate run has to start from regenerated resources: every generator rewrites src
            # models, and the normalisers only clean what they find there. Running the whole batch
            # build first is what build.gradle gets from the processResources chain. A single gate
            # does not, so it declares its own requires instead of rebuilding the world.
            batch = [command for command in stage_commands("build") if command.batch]
            ordered = list({command.name: command for command in batch + expand(targets)}.values())
            print(f"rebuilding {len(batch)} build commands before {len(targets)} gates")
        else:
            ordered = expand(targets)
            if not rebuild:
                # --no-build means the resources are already where they belong: honour that for the
                # requires too, or a gate that names a build step still regenerates the tree.
                skipped = [command for command in ordered if command.stage == "build"]
                ordered = [command for command in ordered if command.stage != "build"]
                if skipped:
                    print(f"skipping {len(skipped)} build command(s): "
                          + ", ".join(command.name for command in skipped))
        failures = []
        for command in ordered:
            print(f"\n=== {command.name} ===")
            if run_script(command.script, list(command.default_args)) != 0:
                failures.append(command.name)
                if command.stage == "gate" and len(targets) == 1:
                    break
        gates = [command.name for command in ordered if command.stage == "gate"]
        print("\n" + (f"{len(failures)} gate(s) failed: {', '.join(failures)}" if failures
                       else f"all {len(gates)} gates passed"))
        return 1 if failures else 0
    if head == "run":
        if not rest:
            print("run needs a command name; python -m mcmodel list", file=sys.stderr)
            return 2
        name, extra = rest[0], rest[1:]
        command = BY_NAME.get(name)
        if command is None:
            print(f"unknown command: {name}\n", file=sys.stderr)
            describe()
            return 2
        return run_script(command.script, extra or list(command.default_args))

    command = BY_NAME.get(head)
    if command is None:
        print(f"unknown command: {head}\n", file=sys.stderr)
        describe()
        return 2
    return run_script(command.script, rest or list(command.default_args))


if __name__ == "__main__":
    raise SystemExit(main())
