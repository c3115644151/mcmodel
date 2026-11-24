param([ValidateRange(0,600)][int]$WatchSeconds = 0)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pidFile = Join-Path $projectRoot 'run/mcpfabricPreview/mcpfabric-preview.pid'
if (-not (Test-Path $pidFile)) { throw 'No tracked MCPFabric preview client is running.' }

$gamePid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$gamePid" -ErrorAction SilentlyContinue
if (-not $process -or $process.Name -ne 'java.exe' -or
    $process.CommandLine -notlike '*net.neoforged.fml.startup.Client*' -or
    $process.CommandLine -notlike "*$projectRoot*build*classes*java*main*" -or
    $process.CommandLine -notlike '*neoforge*26.1.2.109*') {
    throw 'The tracked PID is no longer the isolated NeoForge 26.1.2.109 preview client.'
}

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class McpPreviewMinimize {
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
}
'@
$game = Get-Process -Id $gamePid
if ($game.MainWindowHandle -eq [IntPtr]::Zero) { throw 'Preview client window is not ready.' }
$deadline = (Get-Date).AddSeconds($WatchSeconds)
do {
    $game.Refresh()
    if ($game.MainWindowHandle -eq [IntPtr]::Zero) { throw 'Preview client window is not ready.' }
    if (-not [McpPreviewMinimize]::IsIconic($game.MainWindowHandle)) {
        [void][McpPreviewMinimize]::ShowWindowAsync($game.MainWindowHandle, 6)
    }
    Start-Sleep -Milliseconds 250
    $minimized = [McpPreviewMinimize]::IsIconic($game.MainWindowHandle)
} while ($WatchSeconds -gt 0 -and (Get-Date) -lt $deadline)
$gameFocused = [McpPreviewMinimize]::GetForegroundWindow() -eq $game.MainWindowHandle
if (-not $minimized -or $gameFocused) { throw 'Preview client is not safely minimized and unfocused.' }
[pscustomobject]@{ clientPid = $gamePid; minimized = $true; gameFocused = $false } | ConvertTo-Json -Compress
