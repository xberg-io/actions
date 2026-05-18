$ErrorActionPreference = "Stop"

$alefVersion = $args[0]
if ([string]::IsNullOrWhiteSpace($alefVersion)) {
  throw "Usage: windows.ps1 <alefVersion>"
}

$alefBinDir = "$env:USERPROFILE\AppData\Local\alef"
New-Item -ItemType Directory -Force -Path $alefBinDir | Out-Null

$alefExe = "$alefBinDir\alef.exe"

if (Test-Path $alefExe) {
  Write-Output "Alef already installed at $alefExe"
  "$alefBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
  exit 0
}

function Ensure-Cargo {
  if (Get-Command cargo -ErrorAction SilentlyContinue) { return }
  Write-Output "cargo not found - bootstrapping minimal Rust toolchain via rustup..."
  $rustupInit = "$env:TEMP\rustup-init.exe"
  Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustupInit
  & $rustupInit --default-toolchain stable --profile minimal -y --no-modify-path
  if ($LASTEXITCODE -ne 0) { throw "rustup-init failed with exit code $LASTEXITCODE" }
  $env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
}

if ($alefVersion -eq "main") {
  Write-Output "Installing alef from main branch via cargo install..."
  Ensure-Cargo
  $env:CARGO_INSTALL_ROOT = $alefBinDir
  cargo install --git https://github.com/kreuzberg-dev/alef --locked alef-cli
  "$alefBinDir\bin" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
  exit 0
}

# Resolve "latest" — check alef.toml for a pinned version first, then fall back to GitHub
if ($alefVersion -eq "latest") {
  if (Test-Path "alef.toml") {
    # Read either:
    #   - top-level `version = "..."` (alef's own repo convention; before first [section])
    #   - `alef_version = "..."` (consumer convention; may live under [workspace])
    $pinned = $null
    $beforeSection = $true
    foreach ($line in Get-Content "alef.toml") {
      if ($line -match '^\[') { $beforeSection = $false }
      if ($beforeSection -and $line -match '^\s*version\s*=\s*"([^"]+)"') {
        $pinned = $Matches[1]; break
      }
      if ($line -match '^\s*alef_version\s*=\s*"([^"]+)"') {
        $pinned = $Matches[1]; break
      }
    }
    if ($pinned) {
      Write-Output "Using pinned version from alef.toml: $pinned"
      $alefVersion = $pinned
    }
  }
  if ($alefVersion -eq "latest") {
    $headers = @{}
    if ($env:GITHUB_TOKEN) {
      $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
      $headers["X-GitHub-Api-Version"] = "2022-11-28"
    }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/kreuzberg-dev/alef/releases/latest" -Headers $headers
    $alefVersion = $release.tag_name -replace '^v', ''
    Write-Output "Resolved latest version: $alefVersion"
  }
}

$zipPath = "$alefBinDir\alef.zip"
# Strip leading 'v' if present so we don't form vv-tagged URLs when callers pass an already-prefixed tag.
$alefVersion = $alefVersion -replace '^v', ''
$directUrl = "https://github.com/kreuzberg-dev/alef/releases/download/v$alefVersion/alef-x86_64-pc-windows-gnu.zip"

try {
  Invoke-WebRequest -Uri $directUrl -OutFile $zipPath
} catch {
  $headers = @{}
  if ($env:GITHUB_TOKEN) {
    $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
    $headers["X-GitHub-Api-Version"] = "2022-11-28"
  }
  $release = Invoke-RestMethod -Uri "https://api.github.com/repos/kreuzberg-dev/alef/releases/tags/v$alefVersion" -Headers $headers
  $asset = $release.assets | Where-Object { $_.name -match "windows.*\.zip" } | Select-Object -First 1

  if (-not $asset) {
    throw "Could not find Windows release for alef v$alefVersion"
  }

  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
}

$extractDir = "$alefBinDir\extract"
if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
Remove-Item $zipPath

$found = Get-ChildItem -Path $extractDir -Recurse -Filter "alef.exe" | Select-Object -First 1
if (-not $found) {
  throw "alef.exe not found in extracted archive at $extractDir"
}
Move-Item -Force -Path $found.FullName -Destination $alefExe
Remove-Item -Recurse -Force $extractDir

if (-not (Test-Path $alefExe)) {
  throw "Failed to install alef.exe at $alefExe"
}
Write-Output "Alef installed at $alefExe"

"$alefBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
