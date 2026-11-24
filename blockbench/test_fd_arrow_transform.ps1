param()

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$sourcePath = Join-Path $PSScriptRoot '../../build/ui-reference/FarmersDelight-26.1/src/main/resources/assets/farmersdelight/textures/gui/cooking_pot.png'
$source = [System.Drawing.Bitmap]::FromFile((Resolve-Path $sourcePath))
$arrow = $source.Clone((New-Object System.Drawing.Rectangle 176,15,24,17),[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$source.Dispose()
for ($y = 0; $y -lt $arrow.Height; $y++) {
    for ($x = 0; $x -lt $arrow.Width; $x++) {
        $pixel = $arrow.GetPixel($x, $y)
        if ($pixel.R -eq 198 -and $pixel.G -eq 198 -and $pixel.B -eq 198) {
            $arrow.SetPixel($x, $y, [System.Drawing.Color]::Transparent)
        } elseif ($pixel.R -ge 230 -and $pixel.G -ge 230 -and $pixel.B -ge 230) {
            $arrow.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255,193,145,72))
        } else {
            $arrow.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255,54,36,25))
        }
    }
}
$arrow.RotateFlip([System.Drawing.RotateFlipType]::Rotate90FlipNone)
$small = New-Object System.Drawing.Bitmap 10,10
$draw = [System.Drawing.Graphics]::FromImage($small)
$draw.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$draw.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$draw.DrawImage($arrow,(New-Object System.Drawing.Rectangle 0,0,10,10),
    (New-Object System.Drawing.Rectangle 0,0,$arrow.Width,$arrow.Height),[System.Drawing.GraphicsUnit]::Pixel)
$preview = New-Object System.Drawing.Bitmap 240,240
$graphics = [System.Drawing.Graphics]::FromImage($preview)
$graphics.Clear([System.Drawing.Color]::FromArgb(205,198,184))
$graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$graphics.DrawImage($small,(New-Object System.Drawing.Rectangle 0,0,240,240),
    (New-Object System.Drawing.Rectangle 0,0,10,10),[System.Drawing.GraphicsUnit]::Pixel)
$preview.Save((Join-Path (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path 'build/fd_down_arrow_10x10_review.png'),
    [System.Drawing.Imaging.ImageFormat]::Png)
$arrow.Dispose();$small.Dispose();$draw.Dispose();$preview.Dispose();$graphics.Dispose()
