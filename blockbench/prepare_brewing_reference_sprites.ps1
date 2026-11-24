param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$fdTexture = Join-Path $projectRoot 'build/ui-reference/FarmersDelight-26.1/src/main/resources/assets/farmersdelight/textures/gui/cooking_pot.png'
$bncTexture = Join-Path $projectRoot 'build/ui-reference/BrewinAndChewin-1.21.1/common/src/main/resources/assets/brewinandchewin/textures/gui/jei/keg.png'
$outputRoot = Join-Path $projectRoot 'artwork/brewing-ui/blockbench/reference'
New-Item -ItemType Directory -Force $outputRoot | Out-Null
Add-Type -AssemblyName System.Drawing

# Farmer's Delight MIT timer icon: crop the real 8x11 glyph and key out the adjacent GUI panel color.
$fd = [System.Drawing.Bitmap]::FromFile($fdTexture)
$fdCrop = $fd.Clone((New-Object System.Drawing.Rectangle 176,32,8,11),[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$fdCanvas = New-Object System.Drawing.Bitmap 16,16
for ($y=0; $y -lt 11; $y++) {
    for ($x=0; $x -lt 8; $x++) {
        $pixel = $fdCrop.GetPixel($x,$y)
        if ($pixel.R -eq 198 -and $pixel.G -eq 198 -and $pixel.B -eq 198) {
            $fdCanvas.SetPixel($x+4,$y+2,[System.Drawing.Color]::Transparent)
        } else {
            $fdCanvas.SetPixel($x+4,$y+2,$pixel)
        }
    }
}
$fdCanvas.Save((Join-Path $outputRoot 'fd_timer_gray_16x16.png'),[System.Drawing.Imaging.ImageFormat]::Png)
$fd.Dispose();$fdCrop.Dispose();$fdCanvas.Dispose()

# Brewin' and Chewin' MIT JEI arrow: reuse its horizontal arrow, rotate down, and fit it in the vertical slot gap.
$bnc = [System.Drawing.Bitmap]::FromFile($bncTexture)
$arrow = $bnc.Clone((New-Object System.Drawing.Rectangle 171,4,23,16),[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$bnc.Dispose()
for ($y=0; $y -lt $arrow.Height; $y++) {
    for ($x=0; $x -lt $arrow.Width; $x++) {
        $pixel = $arrow.GetPixel($x,$y)
        if ($pixel.R -eq 198 -and $pixel.G -eq 198 -and $pixel.B -eq 198) {
            $arrow.SetPixel($x,$y,[System.Drawing.Color]::Transparent)
        } elseif ($pixel.R -ge 230 -and $pixel.G -ge 230 -and $pixel.B -ge 230) {
            $arrow.SetPixel($x,$y,[System.Drawing.Color]::FromArgb(255,244,226,178))
        } elseif ($pixel.R -eq 104 -and $pixel.G -eq 104) {
            $arrow.SetPixel($x,$y,[System.Drawing.Color]::FromArgb(255,54,36,25))
        } else {
            $arrow.SetPixel($x,$y,[System.Drawing.Color]::FromArgb(255,142,98,52))
        }
    }
}
$arrow.RotateFlip([System.Drawing.RotateFlipType]::Rotate90FlipNone)
$arrowGlyph = New-Object System.Drawing.Bitmap 7,10
$arrowGraphics = [System.Drawing.Graphics]::FromImage($arrowGlyph)
$arrowGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$arrowGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$arrowGraphics.DrawImage($arrow,(New-Object System.Drawing.Rectangle 0,0,7,10),
    (New-Object System.Drawing.Rectangle 0,0,$arrow.Width,$arrow.Height),[System.Drawing.GraphicsUnit]::Pixel)
$arrowCanvas = New-Object System.Drawing.Bitmap 16,16
$arrowCanvasGraphics = [System.Drawing.Graphics]::FromImage($arrowCanvas)
$arrowCanvasGraphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
$arrowCanvasGraphics.DrawImage($arrowGlyph,4,3)
$arrowCanvas.Save((Join-Path $outputRoot 'bnc_down_arrow_16x16.png'),[System.Drawing.Imaging.ImageFormat]::Png)
$arrowJei = New-Object System.Drawing.Bitmap 10,10
$arrowJeiGraphics = [System.Drawing.Graphics]::FromImage($arrowJei)
$arrowJeiGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$arrowJeiGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$arrowJeiGraphics.DrawImage($arrowGlyph,(New-Object System.Drawing.Rectangle 0,0,10,10),
    (New-Object System.Drawing.Rectangle 0,0,$arrowGlyph.Width,$arrowGlyph.Height),[System.Drawing.GraphicsUnit]::Pixel)
$arrowJei.Save((Join-Path $outputRoot 'bnc_down_arrow_10x10.png'),[System.Drawing.Imaging.ImageFormat]::Png)
$arrow.Dispose();$arrowGlyph.Dispose();$arrowGraphics.Dispose();$arrowCanvas.Dispose();$arrowCanvasGraphics.Dispose()
$arrowJei.Dispose();$arrowJeiGraphics.Dispose()

Write-Output "Prepared the licensed Farmer's Delight timer crop and Brewin' and Chewin' down-arrow crop."
