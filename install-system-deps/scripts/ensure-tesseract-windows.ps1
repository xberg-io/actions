Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-TesseractVersion {
  param([string]$Executable)
  if (-not (Test-Path -LiteralPath $Executable)) { return $null }
  $output = @(& $Executable --version 2>&1)
  if ($LASTEXITCODE -ne 0) { throw "Tesseract version probe failed: $LASTEXITCODE" }
  if ($output.Count -eq 0 -or $output[0] -notmatch '^tesseract\s+v?(\d+\.\d+\.\d+)') {
    throw 'Tesseract returned no recognized version'
  }
  return [version]$Matches[1]
}

function Ensure-Tesseract {
  param([string]$Executable, [string]$Installer)
  # Windows stays on 5.5.3 while Linux and macOS use 5.5.4: upstream published no 5.5.4 Windows installer. ~keep
  $required = [version]'5.5.3'
  $current = Get-TesseractVersion -Executable $Executable
  if ($null -ne $current -and $current -ge $required) {
    Write-Host "Verified Tesseract $current"
    return
  }
  $url = 'https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe'
  $expected = 'bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4'
  Invoke-WebRequest -Uri $url -OutFile $Installer -ErrorAction Stop
  if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'Tesseract installer checksum mismatch'
  }
  $process = Start-Process -FilePath $Installer -ArgumentList '/S' -Wait -PassThru
  if ($process.ExitCode -ne 0) { throw "Tesseract installer failed with exit $($process.ExitCode)" }
  $current = Get-TesseractVersion -Executable $Executable
  if ($null -eq $current -or $current -lt $required) {
    throw "Tesseract version $current is below required $required after installation"
  }
  Write-Host "Verified Tesseract $current"
}
