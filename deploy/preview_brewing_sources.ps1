param(
    [string[]]$Models = @("glass_cup", "wooden_mug", "beer_bottle"),
    # Absolute or workspace-relative .bbmodel paths. When given, they replace the
    # brewing model list so the same native-viewport capture works for any source.
    [string[]]$SourcePaths = @(),
    [switch]$CloseWhenDone,
    # Capture from the Blockbench the user already has open instead of refusing to run. This is the
    # normal case: the artist keeps Blockbench up all day, so a hard "close it first" rule makes the
    # source viewport - the only trustworthy basis for "does the model look right" - unavailable
    # exactly when it is needed. Nothing is closed or replaced in this mode.
    [switch]$ReuseRunning
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$sourceRoot = Join-Path $PSScriptRoot "model_sources/brewing"
$previewRoot = Join-Path $root "build/blockbench_source_previews"
$blockbench = Join-Path $env:LOCALAPPDATA "Programs/Blockbench/Blockbench.exe"
$mcpUri = "http://[::1]:3000/bb-mcp"

if (-not (Test-Path -LiteralPath $blockbench)) {
    throw "Blockbench executable not found at $blockbench"
}
New-Item -ItemType Directory -Force -Path $previewRoot | Out-Null

function Get-BlockbenchMainProcesses {
    @(Get-CimInstance Win32_Process -Filter "Name='Blockbench.exe'" |
        Where-Object { $_.CommandLine -notmatch '--type=' })
}

function Wait-ForBlockbenchMcp {
    param([int]$ProcessId, [int]$TimeoutSeconds = 60)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $process) { throw "Blockbench exited before starting its MCP server." }
        $listener = Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -eq "::" -or $_.LocalAddress -eq "::1" }
        if ($listener) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Blockbench MCP did not listen on [::1]:3000 within $TimeoutSeconds seconds."
}

function Invoke-BlockbenchMcp {
    param(
        [string]$Method,
        [hashtable]$Params,
        [hashtable]$Headers,
        [int]$Id
    )
    $request = @{ jsonrpc = "2.0"; id = $Id; method = $Method; params = $Params } |
        ConvertTo-Json -Depth 32 -Compress
    $response = Invoke-WebRequest -Uri $mcpUri -Method Post -Headers $Headers `
        -ContentType "application/json" -Body $request -TimeoutSec 30
    $result = $response.Content | ConvertFrom-Json
    if ($result.error) { throw "Blockbench MCP $Method failed: $($result.error.message)" }
    return $result.result
}

$reuse = $ReuseRunning -and (Get-BlockbenchMainProcesses).Count -gt 0
if (-not $reuse -and (Get-BlockbenchMainProcesses).Count -gt 0) {
    throw "Blockbench is already running. Re-run with -ReuseRunning to capture from that instance, or close it so this script can start its own."
}

$fromPaths = @($SourcePaths).Count -gt 0
$models = if ($fromPaths) { @($SourcePaths) } else { @($Models) }
for ($index = 0; $index -lt $models.Count; $index++) {
    if ($fromPaths) {
        $sourceFile = (Resolve-Path -LiteralPath $models[$index]).Path
        $name = [IO.Path]::GetFileNameWithoutExtension($sourceFile)
    } else {
        $name = $models[$index]
        if ($name -notin @("glass_cup", "wooden_mug", "beer_bottle")) {
            throw "Unsupported brewing source model '$name'."
        }
        $sourceFile = Join-Path $sourceRoot "$name.bbmodel"
    }
    if (-not (Test-Path -LiteralPath $sourceFile)) { throw "Missing source model: $sourceFile" }

    $process = if ($reuse) { $null } else { Start-Process -FilePath $blockbench -ArgumentList @($sourceFile) -WindowStyle Hidden -PassThru }
    try {
        if (-not $reuse) { Wait-ForBlockbenchMcp -ProcessId $process.Id }
        $initBody = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"pastoral-home-source-preview","version":"1.0.0"}}}'
        $init = Invoke-WebRequest -Uri $mcpUri -Method Post `
            -Headers @{ Accept = "application/json, text/event-stream" } `
            -ContentType "application/json" -Body $initBody -TimeoutSec 15
        $sessionId = [string]$init.Headers["mcp-session-id"]
        if (-not $sessionId) { throw "Blockbench MCP did not return an MCP session id." }
        $headers = @{
            Accept = "application/json, text/event-stream"
            "Mcp-Session-Id" = $sessionId
            "MCP-Protocol-Version" = "2025-03-26"
        }
        $project = Invoke-BlockbenchMcp -Method "tools/call" `
            -Params @{ name = "get_project_info"; arguments = @{} } -Headers $headers -Id 2
        $projectInfo = ($project.content | Where-Object { $_.type -eq "text" } | Select-Object -First 1).text |
            ConvertFrom-Json
        $expectedPath = [IO.Path]::GetFullPath($sourceFile)
        $loadedPath = if ($projectInfo.project.save_path) {
            [IO.Path]::GetFullPath([string]$projectInfo.project.save_path)
        } else { "" }
        if (-not [string]::Equals($expectedPath, $loadedPath, [StringComparison]::OrdinalIgnoreCase)) {
            $openName = if ($loadedPath) { "'$loadedPath'" } else { "an unsaved project" }
            throw "Blockbench has $openName open, expected '$expectedPath'. Open that model in the running Blockbench (or close it and drop -ReuseRunning)."
        }
        $capture = Invoke-BlockbenchMcp -Method "tools/call" `
            -Params @{ name = "capture_screenshot"; arguments = @{} } -Headers $headers -Id 3
        $image = $capture.content | Where-Object { $_.type -eq "image" } | Select-Object -First 1
        if (-not $image) { throw "Blockbench MCP returned no native viewport image for $name." }
        $extension = if ($image.mimeType -eq "image/jpeg") { ".jpg" } else { ".png" }
        $previewPath = Join-Path $previewRoot ($name + $extension)
        [IO.File]::WriteAllBytes($previewPath, [Convert]::FromBase64String($image.data))
        $projectInfo | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $previewRoot "$name.project.json") -Encoding utf8
        Write-Output "Captured $name from its native Blockbench project: $previewPath"
    }
    finally {
        if ($null -ne $process) {
            $isLast = $index -eq ($models.Count - 1)
            if ($CloseWhenDone -or -not $isLast) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                $deadline = (Get-Date).AddSeconds(10)
                while ((Get-Date) -lt $deadline -and (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
                    Start-Sleep -Milliseconds 250
                }
            }
        }
    }
}
