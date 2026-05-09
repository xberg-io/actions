[CmdletBinding()]
param(
    [string]$Version = "latest"
)

$ErrorActionPreference = "Stop"

$indexUrl = "https://ziglang.org/download/index.json"
$index = Invoke-RestMethod -Uri $indexUrl -TimeoutSec 30

$arch = if ([Environment]::Is64BitOperatingSystem) {
    if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64" -or $env:PROCESSOR_IDENTIFIER -match "ARM") {
        "aarch64"
    } else {
        "x86_64"
    }
} else {
    "x86"
}
$platform = "$arch-windows"

$key =
    if ($Version -eq "latest") {
        ($index.PSObject.Properties.Name |
            Where-Object { $_ -ne "master" } |
            Sort-Object { [version]$_ } |
            Select-Object -Last 1)
    } elseif ($Version -eq "master") {
        "master"
    } else {
        $Version
    }

$entry = $index.$key
if (-not $entry) {
    throw "Zig version '$Version' not found in ziglang.org index"
}

$asset = $entry.$platform
if (-not $asset) {
    throw "No $platform asset for Zig $key"
}

$resolved = if ($entry.version) { $entry.version } else { $key }
Write-Host "Resolved Zig $Version -> $resolved"
Write-Host "Downloading $($asset.tarball)"

$installDir = Join-Path ${env:RUNNER_TEMP} "zig"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$archive = Join-Path $installDir "zig.zip"

for ($i = 1; $i -le 3; $i++) {
    try {
        Invoke-WebRequest -Uri $asset.tarball -OutFile $archive -TimeoutSec 600 -UseBasicParsing
        break
    } catch {
        Write-Host "Download attempt $i failed: $_"
        if ($i -eq 3) { throw }
        Start-Sleep -Seconds 2
    }
}

Expand-Archive -Path $archive -DestinationPath $installDir -Force
$extracted = Get-ChildItem -Path $installDir -Directory -Filter "zig-*" | Select-Object -First 1
if (-not $extracted) {
    throw "Could not locate extracted zig directory under $installDir"
}

Add-Content -Path $env:GITHUB_PATH -Value $extracted.FullName
& (Join-Path $extracted.FullName "zig.exe") version
