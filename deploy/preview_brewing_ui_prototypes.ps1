param(
    [string]$GameCapture = 'build/mcpfabric-brewing-gui-final.png',
    [string]$Output = 'build/brewing_gui_prototypes.png'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$capturePath = Join-Path $root $GameCapture
$paperPath = Join-Path $root 'src/main/resources/assets/pastoral_home/textures/gui/brewing_barrel.png'
$outputPath = Join-Path $root $Output
if (-not (Test-Path $capturePath)) { throw "Missing validated MCP screenshot: $capturePath" }
if (-not (Test-Path $paperPath)) { throw "Missing current parchment texture: $paperPath" }
Add-Type -AssemblyName System.Drawing
Remove-Item Alias:R -Force -ErrorAction SilentlyContinue

$canvas = [System.Drawing.Bitmap]::new(1440, 486)
$g = [System.Drawing.Graphics]::FromImage($canvas)
$g.Clear([System.Drawing.Color]::FromArgb(37,43,52))
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::SingleBitPerPixelGridFit
$headingFont = [System.Drawing.Font]::new('Microsoft YaHei', 17, [System.Drawing.FontStyle]::Bold)
$screenTitleFont = [System.Drawing.Font]::new('Microsoft YaHei', 18, [System.Drawing.FontStyle]::Regular)
$bodyFont = [System.Drawing.Font]::new('Microsoft YaHei', 14, [System.Drawing.FontStyle]::Regular)
$smallFont = [System.Drawing.Font]::new('Microsoft YaHei', 12, [System.Drawing.FontStyle]::Regular)
$icons = [System.Drawing.Bitmap]::FromFile($capturePath)
$paper = [System.Drawing.Bitmap]::FromFile($paperPath)
$script:ox = 0; $script:oy = 0

function R([int]$x,[int]$y,[int]$w,[int]$h,[string]$color) {
    $b = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml($color))
    $g.FillRectangle($b,$script:ox+2*$x,$script:oy+2*$y,2*$w,2*$h); $b.Dispose()
}
function T([int]$x,[int]$y,[string]$s,$face=$bodyFont,[string]$color='#453522') {
    $b = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml($color))
    $g.DrawString($s,$face,$b,[single]($script:ox+2*$x),[single]($script:oy+2*$y)); $b.Dispose()
}
function Slot([int]$x,[int]$y,[bool]$vanilla=$false) {
    if($vanilla){$edge='#161616';$rim='#eeeeee';$inside='#656565';$well='#4a4a4a'}else{$edge='#50351f';$rim='#d6b779';$inside='#60452c';$well='#75634d'}
    R ($x-1) ($y-1) 18 18 $edge; R $x $y 16 16 $rim; R ($x+1) ($y+1) 14 14 $inside; R ($x+2) ($y+2) 12 12 $well
}
function Icon([int]$slotX,[int]$slotY,[int]$x,[int]$y) {
    $src=[System.Drawing.Rectangle]::new((512+4*$slotX),(124+4*$slotY),64,64)
    $dst=[System.Drawing.Rectangle]::new(($script:ox+2*$x),($script:oy+2*$y),32,32)
    $g.DrawImage($icons,$dst,$src,[System.Drawing.GraphicsUnit]::Pixel)
}
function A([int]$x,[int]$y,[string]$color) {
    R $x ($y+3) 15 3 $color
    for($row=0;$row -le 10;$row++){$end=24-[Math]::Abs($row-5)*2;if($end -gt 14){R ($x+14) ($y+$row) ($end-14) 1 $color}}
}
function Inv([int]$x,[int]$y,[bool]$vanilla) {
    for($row=0;$row -lt 3;$row++){for($col=0;$col -lt 9;$col++){Slot ($x+18*$col) ($y+18*$row) $vanilla}}
    for($col=0;$col -lt 9;$col++){Slot ($x+18*$col) ($y+58) $vanilla}
}
function SetPanel([int]$x,[int]$y){$script:ox=$x;$script:oy=$y}

# Three distinct first-impression structures, all using actual in-game ingredient icons.
$headings=@(
    @{x=24;title='A · 原版配方台';note='2×2 配方格 · 自动开酿 · R/U 查配方'},
    @{x=496;title='B · 工序横线';note='原料 → 发酵 → 选器皿'},
    @{x=968;title='C · 酒桶主轴';note='设备居中，批次状态优先'}
)
foreach($h in $headings){
    $b=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(242,238,225))
    $g.DrawString($h.title,$headingFont,$b,[single]$h.x,3)
    $g.DrawString($h.note,$smallFont,$b,[single]$h.x,27)
    $b.Dispose()
}

# A: familiar 2×2 input grid, animated recipe arrow, one result slot, standard inventory.
SetPanel 48 94
R 0 0 176 166 '#c6c6c6';R 2 2 172 162 '#c6c6c6'
R 2 2 172 2 '#ffffff';R 2 2 2 162 '#ffffff';R 2 162 172 2 '#555555';R 172 2 2 162 '#555555'
T 97 6 '酿造桶' $screenTitleFont '#303030'
# Repurpose the mannequin well as a compact barrel/status rail; keep the standard 2×2 recipe matrix and player grid.
R 7 8 72 70 '#adadad';R 8 9 70 68 '#c6c6c6'
R 33 17 18 26 '#50351f';R 30 15 24 4 '#d6b779';R 30 42 24 4 '#d6b779';R 36 22 12 15 '#795332'
R 14 48 58 4 '#3b3b3b';R 15 49 10 2 '#c98535'
Slot 20 59 $true;Slot 42 59 $true
Slot 98 18 $true;Slot 116 18 $true;Slot 98 36 $true;Slot 116 36 $true
Icon 12 45 98 18;Icon 40 45 116 18;Icon 68 45 98 36;Icon 124 45 116 36
A 136 25 '#777777';Slot 154 27 $true
T 8 72 '物品栏' $smallFont '#303030';Inv 8 84 $true

# B: a single horizontal batch lane, with the game's oak-and-paper visual language.
SetPanel 496 52
$g.DrawImage($paper,[System.Drawing.Rectangle]::new($script:ox,$script:oy,448,416))
T 12 7 '酿造桶' $screenTitleFont '#443321'
Slot 12 43;Slot 40 43;Slot 68 43;Slot 124 43;Slot 184 43
Icon 12 45 12 44;Icon 40 45 40 44;Icon 68 45 68 44;Icon 124 45 124 44
A 94 47 '#8a6842';R 12 74 90 5 '#392719';R 14 76 20 1 '#c98535'
Slot 124 78;Slot 144 78
Inv 31 120 $false

# C: the barrel owns the visual center; ingredient and vessel choices sit on opposing rails.
SetPanel 968 52
R 0 0 224 208 '#302a25';R 4 4 216 200 '#674a2e';R 8 8 208 192 '#e5d2a8'
T 12 8 '酿造桶' $screenTitleFont '#48351f'
Slot 12 30;Slot 12 52;Slot 12 74;Icon 12 45 12 31;Icon 40 45 12 53;Icon 68 45 12 75
R 84 25 52 48 '#50351f';R 88 22 44 6 '#d6b779';R 88 69 44 5 '#d6b779';R 92 30 36 35 '#775332';R 97 39 26 17 '#573b28';R 99 55 22 6 '#954546'
R 92 74 36 5 '#392719';R 94 76 9 1 '#c98535'
Slot 166 32;Slot 166 54;Icon 124 45 167 33;A 139 44 '#8a6842'
Inv 31 120 $false

$g.Dispose();$headingFont.Dispose();$screenTitleFont.Dispose();$bodyFont.Dispose();$smallFont.Dispose();$icons.Dispose();$paper.Dispose()
$canvas.Save($outputPath,[System.Drawing.Imaging.ImageFormat]::Png);$canvas.Dispose()
Write-Output $outputPath
