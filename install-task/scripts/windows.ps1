$ErrorActionPreference = "Stop"

$taskVersion = $args[0]
if ([string]::IsNullOrWhiteSpace($taskVersion)) {
  $taskVersion = "latest"
}

$taskBinDir = $args[1]
if ([string]::IsNullOrWhiteSpace($taskBinDir)) {
  $taskBinDir = Join-Path $env:RUNNER_TEMP "task-bin"
}
New-Item -ItemType Directory -Force -Path $taskBinDir | Out-Null

$taskExe = "$taskBinDir\task.exe"

$headers = @{
  "X-GitHub-Api-Version" = "2022-11-28"
}
if ($env:GITHUB_TOKEN) {
  $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
}

if ($taskVersion -eq "latest") {
  $release = Invoke-RestMethod -Uri "https://api.github.com/repos/go-task/task/releases/latest" -Headers $headers
} else {
  if (-not $taskVersion.StartsWith("v")) {
    $taskVersion = "v$taskVersion"
  }
  $release = Invoke-RestMethod -Uri "https://api.github.com/repos/go-task/task/releases/tags/$taskVersion" -Headers $headers
}

$asset = $release.assets | Where-Object { $_.name -match "windows_amd64\.zip" } | Select-Object -First 1
if (-not $asset) {
  throw "Could not find Windows amd64 release asset for Task $($release.tag_name)"
}

$zipPath = "$taskBinDir\task.zip"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
Expand-Archive -Path $zipPath -DestinationPath $taskBinDir -Force
Remove-Item $zipPath

if (-not (Test-Path $taskExe)) {
  throw "Task binary not found at $taskExe"
}

& $taskExe --version
"$taskBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
