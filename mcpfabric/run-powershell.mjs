import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import path from "node:path";

// Windows PowerShell 5.1 (powershell.exe) ships with the OS; PowerShell 7 (pwsh.exe) is an
// optional install. The store/MSIX copy of pwsh.exe is an app-execution alias: the file name
// exists in the directory but resolving it through stat fails, so existence checks are useless
// here. Resolve by name in a directory listing, then prove the engine starts.

function dirHas(dir, name) {
  try {
    return readdirSync(dir).includes(name);
  } catch {
    return false;
  }
}

function whereExe(name) {
  const result = spawnSync("where.exe", [name], { encoding: "utf8" });
  if (result.status !== 0 || !result.stdout) return undefined;
  return result.stdout.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)[0];
}

function probe(engine) {
  const result = spawnSync(
    engine,
    ["-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.Major"],
    { encoding: "utf8" },
  );
  if (result.error || result.status !== 0) return undefined;
  const major = Number.parseInt((result.stdout ?? "").trim(), 10);
  return Number.isInteger(major) ? major : undefined;
}

function candidates() {
  const seen = new Set();
  const list = [];
  const push = (value) => {
    if (!value) return;
    const key = value.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    list.push(value);
  };

  push(process.env.PWSH_EXE);
  push(whereExe("pwsh.exe"));

  const localAppData = process.env.LOCALAPPDATA;
  const programFiles = process.env.ProgramFiles;
  const pathEntries = (process.env.PATH ?? "").split(path.delimiter).filter(Boolean);
  if (localAppData) push(path.join(localAppData, "Microsoft", "WindowsApps", "pwsh.exe"));
  if (programFiles) push(path.join(programFiles, "PowerShell", "7", "pwsh.exe"));
  if (localAppData) push(path.join(localAppData, "Programs", "PowerShell", "pwsh.exe"));
  for (const dir of pathEntries) {
    if (dirHas(dir, "pwsh.exe")) push(path.join(dir, "pwsh.exe"));
  }

  push(whereExe("powershell.exe"));
  push(path.join(process.env.SystemRoot ?? "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe"));
  return list;
}

function resolvePowerShell() {
  const tried = [];
  for (const candidate of candidates()) {
    const major = probe(candidate);
    if (major === undefined) {
      tried.push(`${candidate} (did not start)`);
      continue;
    }
    if (process.env.PWSH_DEBUG) console.error(`[run-powershell] engine ${candidate} (PowerShell ${major})`);
    return candidate;
  }
  throw new Error(`No working PowerShell engine found. Tried: ${tried.join("; ")}`);
}

const [script, ...rest] = process.argv.slice(2);
if (!script) {
  console.error("usage: node run-powershell.mjs <script.ps1> [args...]");
  process.exit(2);
}

const engine = resolvePowerShell();
const result = spawnSync(
  engine,
  ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, ...rest],
  { stdio: "inherit" },
);
if (result.error) throw result.error;
process.exit(result.status ?? 1);
