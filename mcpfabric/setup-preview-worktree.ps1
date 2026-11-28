param(
    [string]$Path = '',
    [string]$Ref = ''
)
# Prepare a checkout that pins the preview client's NeoForge version, next to this repository.
#
# Why a second checkout: NeoGradle transforms Minecraft sources per NeoForge version, and that
# transform re-runs whenever the active version changes - measured at 6 to 11 minutes per
# direction on this machine. The preview client needs 26.1.2.109 while the project pins
# 26.1.2.80, so running both from one project pays that cost on every preview start. A separate
# checkout has its own .gradle and build trees, keeps 109 warm, and leaves the pin untouched.
#
# Usage (once):  npm --prefix tools/mcpfabric run setup-preview-worktree
# Afterwards:    cd <repo>-preview, then npm --prefix tools/mcpfabric run start-preview
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $Path) {
    $Path = Join-Path (Split-Path $projectRoot -Parent) ((Split-Path $projectRoot -Leaf) + '-preview')
}
if (-not $Ref) { $Ref = 'origin/main' }

Push-Location $projectRoot
try {
    git fetch origin --quiet
    $resolved = (git rev-parse --verify ($Ref + '^{commit}')).Trim()
    Write-Output ('[preview] ref ' + $Ref + ' -> ' + $resolved)

    if (Test-Path (Join-Path $Path '.git')) {
        git -C $Path checkout --detach $resolved
    } else {
        git worktree add $Path --detach $resolved
    }
    git -C $Path submodule update --init --recursive tools

    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) { throw 'npm is required to install the preview tooling' }
    $nodeModules = Join-Path $Path 'tools/mcpfabric/node_modules'
    if (-not (Test-Path $nodeModules)) {
        Push-Location (Join-Path $Path 'tools/mcpfabric')
        try { & $npm.Source ci } finally { Pop-Location }
    }

    # The preview run directory (mods, the PastoralHomeVisualPreview copy, options, MCP config) is
    # git-ignored, and so is the Minecraft jar cache; a fresh checkout has neither, and --offline
    # cannot fetch them.
    $sourceRun = Join-Path $projectRoot 'run/mcpfabricPreview'
    $targetRun = Join-Path $Path 'run/mcpfabricPreview'
    if (-not (Test-Path $targetRun)) {
        if (-not (Test-Path $sourceRun)) {
            throw ('no run/mcpfabricPreview in ' + $projectRoot + ' to copy; start the preview client there once first')
        }
        New-Item -ItemType Directory -Force $targetRun | Out-Null
        & robocopy $sourceRun $targetRun /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) { throw ('robocopy failed with ' + $LASTEXITCODE) }
        Remove-Item -LiteralPath (Join-Path $targetRun 'mcpfabric-preview.pid') -ErrorAction SilentlyContinue
    }
    $sourceCache = Join-Path $projectRoot '.gradle/caches/minecraft'
    $targetCache = Join-Path $Path '.gradle/caches/minecraft'
    if ((Test-Path $sourceCache) -and -not (Test-Path $targetCache)) {
        New-Item -ItemType Directory -Force $targetCache | Out-Null
        & robocopy $sourceCache $targetCache /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) { throw ('robocopy failed with ' + $LASTEXITCODE) }
    }

    # Warm the 109 transform now instead of on the first preview start (~11 minutes, once).
    Push-Location $Path
    try {
        cmd /c ('gradlew.bat compileJava -PmcpfabricPreview=true -Pneo_version=26.1.2.109 --offline --console=plain')
        if ($LASTEXITCODE -ne 0) { throw 'warming the 26.1.2.109 build failed' }
    } finally { Pop-Location }

    Write-Output ('[preview] ready: ' + $Path)
    Write-Output '[preview] start the client from there:'
    Write-Output ('  cd "' + $Path + '"')
    Write-Output '  npm --prefix tools/mcpfabric run start-preview'
} finally { Pop-Location }
