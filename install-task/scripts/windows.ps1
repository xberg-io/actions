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
# ~keep Resolve before Push-Location below, or a relative install-dir would land under RUNNER_TEMP.
$taskBinDir = (Resolve-Path -LiteralPath $taskBinDir).Path

$taskExe = "$taskBinDir\task.exe"

if (-not $env:MISE_GITHUB_TOKEN -and $env:GITHUB_TOKEN) {
  $env:MISE_GITHUB_TOKEN = $env:GITHUB_TOKEN
}
if (-not $env:MISE_HTTP_TIMEOUT) {
  $env:MISE_HTTP_TIMEOUT = "5m"
}
# ~keep setup-mise exports MISE_LOCKED=1 for the repository's lock; this install is outside that lock.
$env:MISE_LOCKED = "false"

$maxAttempts = 6

# Run a mise network call, retrying with exponential backoff; release lookups and downloads fail transiently.
function Invoke-MiseWithRetry {
  $wait = 5
  for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    $output = & mise @args
    if ($LASTEXITCODE -eq 0) {
      return $output
    }
    if ($attempt -eq $maxAttempts) {
      throw "'mise $($args -join ' ')' failed after $maxAttempts attempts"
    }
    Write-Host "'mise $($args -join ' ')' failed (attempt $attempt/$maxAttempts); retrying in ${wait}s"
    Start-Sleep -Seconds $wait
    $wait *= 2
  }
}

# ~keep Run outside the checkout: a repository mise.toml must neither decide this version nor have its
# ~keep mise.lock rewritten by this install.
Push-Location $env:RUNNER_TEMP
try {
  if ($taskVersion -eq "latest") {
    $resolvedVersion = [string](Invoke-MiseWithRetry latest task)
    if ([string]::IsNullOrWhiteSpace($resolvedVersion)) {
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

  Invoke-MiseWithRetry install "task@$resolvedVersion" | Out-Host

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
