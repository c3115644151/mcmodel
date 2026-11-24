param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pidFile = Join-Path $projectRoot 'run/mcpfabricPreview/mcpfabric-preview.pid'
if (-not (Test-Path $pidFile)) { throw 'No tracked MCPFabric preview client is running.' }
$gamePid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$gamePid" -ErrorAction SilentlyContinue
if (-not $processInfo -or $processInfo.Name -ne 'java.exe' -or
    $processInfo.CommandLine -notlike '*net.neoforged.fml.startup.Client*' -or
    $processInfo.CommandLine -notlike "*$projectRoot*build*classes*java*main*" -or
    $processInfo.CommandLine -notlike '*neoforge*26.1.2.109*') {
    throw 'Tracked PID is not the isolated preview client.'
}
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class PreviewCaptureWindow {
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
$game = Get-Process -Id $gamePid
$window = $game.MainWindowHandle
if ($window -eq [IntPtr]::Zero) { throw 'Preview window is not ready.' }
$absoluteOutput = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
$node = 'D:\Program Files\nodejs\node.exe'
if (-not (Test-Path $node)) { throw 'The verified Node 24 runtime was not found.' }
try {
    # SW_SHOWNOACTIVATE (4) redraws the framebuffer without taking mouse focus.
    [void][PreviewCaptureWindow]::ShowWindowAsync($window, 4)
    Start-Sleep -Milliseconds 120
    # The MCP screenshot tool performs a second guard: it refuses to capture a
    # screen-less world view, where Minecraft could grab the mouse. Container
    # and JEI screens keep the cursor released even if Windows focuses the window.
    & $node (Join-Path $PSScriptRoot 'capture-screenshot.mjs') $absoluteOutput
    if ($LASTEXITCODE -ne 0) { throw "MCPFabric screenshot capture failed with exit code $LASTEXITCODE." }
} finally {
    [void][PreviewCaptureWindow]::ShowWindowAsync($window, 6)
    Start-Sleep -Milliseconds 250
    if (-not [PreviewCaptureWindow]::IsIconic($window)) { throw 'Preview window could not be re-minimized.' }
}
