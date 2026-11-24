# Sends F3+T to the running Minecraft client so resource changes (textures, models, lang,
# blockstates) are re-read without restarting. Java changes still need a full client restart.
#   node tools/mcpfabric/run-powershell.mjs tools/deploy/reload_client_f3t.ps1 [-ClientPid <pid>]
# Without -ClientPid the process is found by its window title, which is what the launcher sets.
param(
    [int]$ClientPid = 0
)
$ErrorActionPreference = "Stop"

$sig = @"
using System;
using System.Runtime.InteropServices;
public static class Kbd {
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
}
"@
Add-Type -TypeDefinition $sig
Add-Type -AssemblyName Microsoft.VisualBasic

if ($ClientPid -le 0) {
    $candidate = Get-Process java, javaw -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like "*Minecraft*" } |
        Select-Object -First 1
    if (-not $candidate) { throw "no Minecraft client window found; pass -ClientPid" }
    $ClientPid = $candidate.Id
}

# The launcher leaves the client minimised, and AppActivate cannot raise a minimised window, so
# restore it first and then claim the foreground explicitly.
$process = Get-Process -Id $ClientPid -ErrorAction Stop
$handle = $process.MainWindowHandle
if ($handle -eq [IntPtr]::Zero) { throw "pid $ClientPid has no main window" }
[void][Kbd]::ShowWindow($handle, 9)
Start-Sleep -Milliseconds 400
[void][Kbd]::SetForegroundWindow($handle)
Start-Sleep -Milliseconds 600

# The client ignores synthetic keys unless it owns the foreground, so verify before sending.
$foreground = [Kbd]::GetForegroundWindow()
$owner = 0
[void][Kbd]::GetWindowThreadProcessId($foreground, [ref]$owner)
if ($owner -ne $ClientPid) {
    throw "foreground window belongs to pid $owner, not $ClientPid; bring the client forward first"
}

$F3 = 0x72; $T = 0x54; $DOWN = 0; $UP = 2
[Kbd]::keybd_event($F3, 0, $DOWN, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 120
[Kbd]::keybd_event($T, 0, $DOWN, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 120
[Kbd]::keybd_event($T, 0, $UP, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 120
[Kbd]::keybd_event($F3, 0, $UP, [UIntPtr]::Zero)
# Put it back out of the way; a visible Game window grabs the mouse and stalls the run.
[void][Kbd]::ShowWindow($handle, 6)
Write-Output "sent F3+T to pid $ClientPid"
