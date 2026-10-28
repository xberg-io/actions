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

if (-not $env:MISE_GITHUB_TOKEN -and $env:GITHUB_TOKEN) {
  $env:MISE_GITHUB_TOKEN = $env:GITHUB_TOKEN
}

# ~keep Run outside the checkout: a repository mise.toml must neither decide this version nor have its
# ~keep mise.lock rewritten by this install.
Push-Location $env:RUNNER_TEMP
try {
  if ($taskVersion -eq "latest") {
    $resolvedVersion = [string](& mise latest task)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($resolvedVersion)) {
      throw "mise could not resolve the latest Task release"
    }
    $resolvedVersion = $resolvedVersion.Trim()
    Write-Host "Resolved 'latest' to v$resolvedVersion"
  } elseif ($taskVersion.StartsWith("v")) {
    $resolvedVersion = $taskVersion.Substring(1)
  } else {
    $resolvedVersion = $taskVersion
  }

  Write-Host "Installing Task v$resolvedVersion"

  & mise install "task@$resolvedVersion"
  if ($LASTEXITCODE -ne 0) {
    throw "mise install task@$resolvedVersion failed with exit code $LASTEXITCODE"
  }

  $taskSource = [string](& mise which task --tool "task@$resolvedVersion")
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($taskSource)) {
    throw "mise could not locate the task binary for task@$resolvedVersion"
  }
  Copy-Item -LiteralPath $taskSource.Trim() -Destination $taskExe -Force
} finally {
  Pop-Location
}

if (-not (Test-Path -LiteralPath $taskExe)) {
  throw "Task binary not found at $taskExe"
}

& $taskExe --version
"$taskBinDir" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
