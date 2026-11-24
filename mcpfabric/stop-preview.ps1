$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pidFile = Join-Path $projectRoot 'run/mcpfabricPreview/mcpfabric-preview.pid'
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'java.exe' -and
    $_.CommandLine -like '*net.neoforged.fml.startup.Client*' -and
    $_.CommandLine -like "*$projectRoot*build*classes*java*main*" -and
    $_.CommandLine -like '*neoforge*26.1.2.109*'
})
$forced = 0
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class McpPreviewClose {
    [DllImport("user32.dll", SetLastError=true)]
    public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
}
'@
foreach ($process in $processes) {
    $game = Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
    if ($game -and $game.MainWindowHandle -ne [IntPtr]::Zero) {
        # WM_CLOSE lets Minecraft save the integrated world and close normally.
        [void][McpPreviewClose]::PostMessage($game.MainWindowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline -and (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
            Start-Sleep -Milliseconds 250
        }
    }
    if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        $forced++
    }
}
if (Test-Path $pidFile) { Remove-Item -LiteralPath $pidFile }
[pscustomobject]@{ stopped = $processes.Count -gt 0; count = $processes.Count; forced = $forced } | ConvertTo-Json -Compress
