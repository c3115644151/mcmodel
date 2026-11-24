"""Gate: the command table still describes the disk.

registry.py is hand-maintained. A rename, a deleted script, or a gate added without its
requires all leave the table looking healthy while the command it names is broken or runs
before the file it reads. This gate is the only thing that keeps the table honest.

It also enforces the two rules the table exists for:
  * a gate names what has to run before it (or says in notes why nothing does);
  * a command that needs a path is marked batch=False, so a full build never guesses one.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcmodel.registry import BY_NAME, COMMANDS, STAGES  # noqa: E402

DEPLOY = Path(__file__).resolve().parent
problems: list[str] = []

names = [command.name for command in COMMANDS]
duplicates = {name for name in names if names.count(name) > 1}
for name in sorted(duplicates):
    problems.append(f"{name}: registered twice")

for command in COMMANDS:
    if command.stage not in STAGES:
        problems.append(f"{command.name}: unknown stage {command.stage!r}")
    if not command.summary.strip():
        problems.append(f"{command.name}: no summary; the table is the only documentation")
    if not command.script:
        problems.append(f"{command.name}: no script")
    elif not command.script.startswith("gradle:"):
        if not (DEPLOY / command.script).is_file():
            problems.append(f"{command.name}: script {command.script} does not exist")
    if command.stage == "gate":
        if not command.requires and not command.notes.strip():
            problems.append(
                f"{command.name}: a gate must declare requires or explain in notes why it needs none; "
                "reading a file a generator has not written yet fails on the wrong assertion")
        for requirement in command.requires:
            if requirement not in BY_NAME:
                problems.append(f"{command.name}: requires unknown command {requirement!r}")
            elif requirement == command.name:
                problems.append(f"{command.name}: requires itself")
    if not command.batch and not (command.args or command.notes):
        problems.append(
            f"{command.name}: batch=False but args is empty; describe the required arguments so "
            "the command is not run bare")

if problems:
    print(f"{len(problems)} problem(s) in the command table:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    raise SystemExit(1)

gates = sum(1 for command in COMMANDS if command.stage == "gate")
print(f"command table: {len(COMMANDS)} commands across {len(STAGES)} stages, {gates} gates, "
      f"{sum(1 for command in COMMANDS if not command.batch)} needing arguments.")
