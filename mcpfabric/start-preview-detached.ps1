# Launch the isolated preview client so it survives the shell that asked for it.
#
# start-preview.ps1 starts gradlew as a child and exits once the client is ready.
# When that shell belongs to a short-lived tool job, closing the job tears down the
# console and Minecraft stops minutes later - long captures then die mid-round and
# every restart costs another 2-4 minutes. Running the launcher as its own detached
# process keeps the client alive between captures.
#
# Readiness is taken from the pid file the launcher writes before printing its
# receipt (stdout redirection through a detached pwsh is not reliably flushed).
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$logs = Join-Path $projectRoot 'build/mcpfabricPreview'
$pidFile = Join-Path $projectRoot 'run/mcpfabricPreview/mcpfabric-preview.pid'
New-Item -ItemType Directory -Force $logs | Out-Null
$launcherLog = Join-Path $logs 'launcher.log'
$launcherErr = Join-Path $logs 'launcher.err.log'
Remove-Item -LiteralPath $launcherLog, $launcherErr -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
$launcher = Join-Path $PSScriptRoot 'start-preview.ps1'
$process = Start-Process -FilePath 'pwsh' `
    -ArgumentList @('-NoProfile', '-File', $launcher) `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $launcherLog -RedirectStandardError $launcherErr
$deadline = (Get-Date).AddMinutes(20)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (Test-Path $pidFile) {
        $clientPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
        if ($clientPid -and (Get-Process -Id $clientPid -ErrorAction SilentlyContinue)) {
            Write-Output ('{"clientPid":' + $clientPid + ',"launcherPid":' + $process.Id + '}')
            exit 0
        }
    }
    if ($process.HasExited -and -not (Test-Path $pidFile)) {
        $tail = @()
        if (Test-Path $launcherErr) { $tail += (Get-Content $launcherErr -Tail 12) }
        if (Test-Path $launcherLog) { $tail += (Get-Content $launcherLog -Tail 12) }
        throw ('Preview launcher exited before the client was ready. ' + ($tail -join [Environment]::NewLine))
    }
}
throw 'Timed out waiting for the detached preview launcher.'
