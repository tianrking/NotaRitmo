param(
    [string]$OutputDir = "models"
)

$ErrorActionPreference = "Stop"

$modelName = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
$url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$modelName.tar.bz2"
$root = Join-Path (Get-Location) $OutputDir
$archive = Join-Path $root "$modelName.tar.bz2"
$extractDir = Join-Path $root "_extract"
$target = Join-Path $root $modelName

New-Item -ItemType Directory -Force -Path $root | Out-Null
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null

if (!(Test-Path $archive)) {
    Write-Host "Downloading $modelName ..."
    Invoke-WebRequest -Uri $url -OutFile $archive -Headers @{ "User-Agent" = "NotaRitmo" }
}

Write-Host "Extracting archive ..."
7z x $archive "-o$extractDir" -y | Out-Null
$tar = Get-ChildItem $extractDir -Filter "*.tar" | Select-Object -First 1
if ($tar) {
    7z x $tar.FullName "-o$extractDir" -y | Out-Null
}

$source = Join-Path $extractDir $modelName
if (!(Test-Path $source)) {
    throw "Model directory not found after extraction: $source"
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item (Join-Path $source "encoder.int8.onnx") $target -Force
Copy-Item (Join-Path $source "decoder.onnx") $target -Force
Copy-Item (Join-Path $source "joiner.int8.onnx") $target -Force
Copy-Item (Join-Path $source "tokens.txt") $target -Force

Write-Host ""
Write-Host "Prepared local model:"
Get-ChildItem $target | Select-Object Name,Length | Format-Table -AutoSize
Write-Host ""
Write-Host "Install the debug APK, launch once, then push with:"
Write-Host "adb push `"$target`" /sdcard/Android/data/com.example.notaritmo/files/models/"
