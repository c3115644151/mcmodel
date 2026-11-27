$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pidFile = Join-Path $projectRoot 'run/mcpfabricPreview/mcpfabric-preview.pid'
# The preview marker is the only stable identity: it is set by the preview run config and does
# not change when the preview NeoForge version moves, so a stopped client is never missed.
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'java.exe' -and
    $_.CommandLine -like '*net.neoforged.fml.startup.Client*' -and
    $_.CommandLine -like "*$projectRoot*build*classes*java*main*" -and
    $_.CommandLine -like '*pastoral_home.dev_preview=true*'
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
# A launcher can outlive the client it started (it blocks on the wrapped process handle and the log
# stream). Left behind, it holds the build lock and blocks the next preview run, so stop it here.
$launchers = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*runClient*' -and $_.CommandLine -like '*mcpfabricPreview=true*'
})
$launchersKilled = 0
foreach ($launcher in $launchers) {
    Stop-Process -Id $launcher.ProcessId -Force -ErrorAction SilentlyContinue
    $launchersKilled++
}
if (Test-Path $pidFile) { Remove-Item -LiteralPath $pidFile }

# A preview run expands META-INF/neoforge.mods.toml with its own NeoForge version, and that
# versionRange is what the next official-pin run reads back from build/resources/main. Left alone it
# makes the mod refuse to load ("requires neoforge X, currently Y"), so drop the expanded resources
# whenever they no longer match the pin in gradle.properties.
$officialNeo = (Select-String -Path (Join-Path $projectRoot 'gradle.properties') -Pattern '^neo_version=(.+)$' |
    Select-Object -First 1).Matches.Groups[1].Value.Trim()
$expandedToml = Join-Path $projectRoot 'build/resources/main/META-INF/neoforge.mods.toml'
$resourcesReset = $false
if ((Test-Path $expandedToml) -and $officialNeo) {
    $expandedRange = (Select-String -Path $expandedToml -Pattern 'versionRange="\[(.+?),' |
        Select-Object -First 1).Matches.Groups[1].Value
    if ($expandedRange -and $expandedRange -ne $officialNeo) {
        Remove-Item -Recurse -Force (Join-Path $projectRoot 'build/resources')
        $resourcesReset = $true
    }
}
[pscustomobject]@{ stopped = $processes.Count -gt 0; count = $processes.Count; forced = $forced
    launchersKilled = $launchersKilled; resourcesReset = $resourcesReset } | ConvertTo-Json -Compress
