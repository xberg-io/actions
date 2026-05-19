$ErrorActionPreference = "Stop"

$version = $args[0]
if ([string]::IsNullOrWhiteSpace($version)) {
  throw "Usage: windows.ps1 <version>"
}

if (Get-Command gh -ErrorAction SilentlyContinue) {
  Write-Output "gh already installed: $((Get-Command gh).Source)"
  exit 0
}

$binDir = "$env:USERPROFILE\AppData\Local\gh"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

if ($version -eq "latest") {
  $headers = @{}
  if ($env:GITHUB_TOKEN) {
    $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
    $headers["X-GitHub-Api-Version"] = "2022-11-28"
  }
  $release = Invoke-RestMethod -Uri "https://api.github.com/repos/cli/cli/releases/latest" -Headers $headers
  $version = $release.tag_name -replace '^v', ''
  Write-Output "Resolved latest gh version: $version"
}
$version = $version -replace '^v', ''

$arch = if ([System.Environment]::Is64BitOperatingSystem -and $env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
$target = "windows_${arch}"
$archiveName = "gh_${version}_${target}.zip"
$url = "https://github.com/cli/cli/releases/download/v${version}/${archiveName}"

$tmpDir = Join-Path $env:TEMP "ensure-gh-$([System.IO.Path]::GetRandomFileName())"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

try {
  $zipPath = Join-Path $tmpDir $archiveName
  Write-Output "Downloading gh v${version} (${target})..."
  Invoke-WebRequest -Uri $url -OutFile $zipPath

  Expand-Archive -Path $zipPath -DestinationPath $tmpDir -Force

  $extractedGh = Join-Path $tmpDir "gh_${version}_${target}\bin\gh.exe"
  if (-not (Test-Path $extractedGh)) {
    throw "gh.exe not found at expected path: $extractedGh"
  }

  Move-Item -Force -Path $extractedGh -Destination "$binDir\gh.exe"
  Write-Output "gh v${version} installed at $binDir\gh.exe"

  "$binDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
} finally {
  if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
}
