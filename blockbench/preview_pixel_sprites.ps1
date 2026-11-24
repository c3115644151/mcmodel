param()
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$nativeRoot = Join-Path $root 'artwork/brewing-ui/blockbench/native'
$referenceRoot = Join-Path $root 'artwork/brewing-ui/blockbench/reference'
$outputRoot = Join-Path $root 'build/pixel-sprite-review'
New-Item -ItemType Directory -Force $outputRoot | Out-Null
Add-Type -AssemblyName System.Drawing

$sprites = @(
    @{ Name = 'water'; Folder = $nativeRoot; File = 'brewing_water_arc.png'; SourceX = 0; SourceY = 0; SourceWidth = 16; SourceHeight = 16; Width = 28; Height = 18 },
    @{ Name = 'arrow-jei'; Folder = $referenceRoot; File = 'bnc_down_arrow_16x16.png'; SourceX = 4; SourceY = 3; SourceWidth = 7; SourceHeight = 10; Width = 10; Height = 10 },
    @{ Name = 'arrow-main'; Folder = $referenceRoot; File = 'bnc_down_arrow_16x16.png'; SourceX = 4; SourceY = 3; SourceWidth = 7; SourceHeight = 10; Width = 8; Height = 8 },
    @{ Name = 'clock'; Folder = $referenceRoot; File = 'fd_timer_gray_16x16.png'; SourceX = 4; SourceY = 2; SourceWidth = 8; SourceHeight = 11; Width = 8; Height = 11 }
)
$scale = 12
foreach ($sprite in $sprites) {
    $sourcePath = Join-Path $sprite.Folder $sprite.File
    $source = [System.Drawing.Bitmap]::FromFile($sourcePath)
    $target = New-Object System.Drawing.Bitmap $sprite.Width, $sprite.Height
    $targetGraphics = [System.Drawing.Graphics]::FromImage($target)
    $targetGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
    $targetGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
    $targetGraphics.DrawImage($source,
        (New-Object System.Drawing.Rectangle 0,0,$sprite.Width,$sprite.Height),
        (New-Object System.Drawing.Rectangle $sprite.SourceX,$sprite.SourceY,$sprite.SourceWidth,$sprite.SourceHeight),
        [System.Drawing.GraphicsUnit]::Pixel)
    $preview = New-Object System.Drawing.Bitmap ($sprite.Width * $scale), ($sprite.Height * $scale)
    $graphics = [System.Drawing.Graphics]::FromImage($preview)
    $graphics.Clear([System.Drawing.Color]::FromArgb(205,198,184))
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
    $graphics.DrawImage($target,
        (New-Object System.Drawing.Rectangle 0,0,($sprite.Width * $scale),($sprite.Height * $scale)),
        (New-Object System.Drawing.Rectangle 0,0,$sprite.Width,$sprite.Height),
        [System.Drawing.GraphicsUnit]::Pixel)
    $preview.Save((Join-Path $outputRoot ($sprite.Name + '.png')),[System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose(); $preview.Dispose(); $targetGraphics.Dispose(); $target.Dispose(); $source.Dispose()
    Write-Output "Rendered exact ${($sprite.Width)}x${($sprite.Height)} preview for $($sprite.Name)."
}
