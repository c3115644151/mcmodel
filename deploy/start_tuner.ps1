param([int]$Port = 8765)

# 启动 GUI 图标 tuner（无控制台窗口）。
#
# 用 pythonw.exe：python.exe 是控制台程序，会开一个终端窗口，关掉窗口服务就没了。
# 用 Start-Process -WindowStyle Hidden：与调用它的 shell 分离，关掉终端不影响服务。
#
# 注意：由 agent 的作业进程启动时，进程会在该作业结束时被回收（实测：WMI 与
# Start-Process 都会被连带杀掉）。所以这个脚本要由人（或常驻的服务管理器）来跑。

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$script = Join-Path $root 'tools\deploy\icon_tuner.py'
foreach ($path in @($pythonw, $script)) {
    if (-not (Test-Path $path)) { throw "missing: $path" }
}

if (Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue) {
    Write-Output "tuner already listening on http://127.0.0.1:$Port/"
    return
}

Start-Process -FilePath $pythonw -ArgumentList @($script, '--port', $Port) `
    -WorkingDirectory $root -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 300
    if (Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue) {
        Write-Output "tuner -> http://127.0.0.1:$Port/"
        return
    }
}
throw "tuner did not open port $Port within 9s"
