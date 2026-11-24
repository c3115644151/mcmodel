$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runDirectory = Join-Path $projectRoot 'run/mcpfabricPreview'
$pidFile = Join-Path $runDirectory 'mcpfabric-preview.pid'
$logs = Join-Path $projectRoot 'build/mcpfabricPreview'
New-Item -ItemType Directory -Force $logs | Out-Null

function Get-McpfabricPreviewProcesses {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'java.exe' -and
        $_.CommandLine -like '*net.neoforged.fml.startup.Client*' -and
        $_.CommandLine -like "*$projectRoot*build*classes*java*main*" -and
        $_.CommandLine -like '*neoforge*26.1.2.109*'
    }
}

if (Test-Path $pidFile) {
    $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
    $old = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue
    if ($old -and $old.CommandLine -like '*net.neoforged.fml.startup.Client*' -and
        $old.CommandLine -like "*$projectRoot*build*classes*java*main*" -and
        $old.CommandLine -like '*neoforge*26.1.2.109*') {
        throw "The isolated MCPFabric preview client is already running (PID $oldPid)."
    }
    Remove-Item -LiteralPath $pidFile
}
$existing = @(Get-McpfabricPreviewProcesses)
if ($existing.Count -gt 0) {
    $pids = ($existing | ForEach-Object { $_.ProcessId }) -join ', '
    throw "Found an existing isolated preview client (PID $pids); refusing to start a duplicate. Run stop-preview first."
}

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class McpPreviewWindow {
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr hWnd);
}
'@

$wrapper = Join-Path $projectRoot 'gradlew.bat'
$stdout = Join-Path $logs 'gradle.stdout.log'
$stderr = Join-Path $logs 'gradle.stderr.log'
$gameLog = Join-Path $runDirectory 'logs/latest.log'
# The preview client never needs a network fetch: every dependency is already in the Gradle cache,
# and leaving it online only lets NeoGradle block on piston-meta when the host has no proxy running.
$gradle = Start-Process -FilePath $wrapper `
    -ArgumentList @('runClient', '-PmcpfabricPreview=true', '-Pneo_version=26.1.2.109', '--console=plain', '--offline') `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$deadline = (Get-Date).AddMinutes(20)
while ((Get-Date) -lt $deadline) {
    $candidates = @(Get-McpfabricPreviewProcesses)
    foreach ($candidate in $candidates) {
        $game = Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue
        $gameLogInfo = Get-Item -LiteralPath $gameLog -ErrorAction SilentlyContinue
        $titleScreenReady = $gameLogInfo -and $gameLogInfo.LastWriteTime -gt $game.StartTime -and
            (Select-String -Path $gameLog -Pattern 'Created: \d+x\d+x\d+ jei:textures/atlas/gui\.png-atlas' -Quiet)
        if ($game -and $game.MainWindowHandle -ne [IntPtr]::Zero -and $titleScreenReady) {
            Set-Content -LiteralPath $pidFile -Value $game.Id -Encoding ascii
            # Do not minimize the loading splash; wait until Minecraft has completed
            # its initial atlas reload while still in the title screen.
            [void][McpPreviewWindow]::ShowWindowAsync($game.MainWindowHandle, 6)
            Start-Sleep -Milliseconds 250
            if (-not [McpPreviewWindow]::IsIconic($game.MainWindowHandle)) {
                Stop-Process -Id $game.Id -Force
                Remove-Item -LiteralPath $pidFile
                throw 'Could not minimize the preview window safely; the preview client was stopped.'
            }
            [pscustomobject]@{
                clientPid = $game.Id
                gradlePid = $gradle.Id
                runDirectory = $runDirectory
                windowMinimized = $true
                audioMuted = $true
                log = $stdout
            } | ConvertTo-Json -Compress
            exit 0
        }
    }
    $gradle.Refresh()
    if ($gradle.HasExited) {
        foreach ($candidate in (Get-McpfabricPreviewProcesses)) {
            Stop-Process -Id $candidate.ProcessId -Force -ErrorAction SilentlyContinue
        }
        $tail = if (Test-Path $stderr) { (Get-Content $stderr -Tail 30) -join "`n" } else { '' }
        throw "Gradle exited before the Minecraft window was ready. See $stdout and $stderr. $tail"
    }
    Start-Sleep -Milliseconds 250
}
foreach ($candidate in (Get-McpfabricPreviewProcesses)) {
    Stop-Process -Id $candidate.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($gradle -and -not $gradle.HasExited) { Stop-Process -Id $gradle.Id -Force -ErrorAction SilentlyContinue }
throw "Timed out waiting for the isolated client window. See $stdout and $stderr."
