BeforeAll {
    $script:Sut = Join-Path $PSScriptRoot '../scripts/ensure-tesseract-windows.ps1'
    . $script:Sut
}

Describe 'Tesseract provisioning' {
    BeforeEach {
        Mock Get-TesseractVersion { [version]'5.5.3' }
        Mock Invoke-WebRequest {}
        Mock Get-FileHash { @{ Hash = 'BEE9E3434BD94FD65387D9BE28CD467A41F61B1275383B55B0F59A1331270AE4' } }
        Mock Start-Process { @{ ExitCode = 0 } }
    }

    It 'should reuse a verified current binary without downloading' {
        Ensure-Tesseract -Executable 'fixture.exe' -Installer (Join-Path $TestDrive 'installer.exe')
        Should -Invoke Invoke-WebRequest -Exactly -Times 0
    }

    It 'should upgrade an old binary and verify the installed version' {
        $script:VersionCalls = 0
        Mock Get-TesseractVersion {
            $script:VersionCalls++
            if ($script:VersionCalls -eq 1) { return [version]'5.5.0' }
            return [version]'5.5.3'
        }
        Ensure-Tesseract -Executable 'fixture.exe' -Installer (Join-Path $TestDrive 'installer.exe')
        Should -Invoke Invoke-WebRequest -Exactly -Times 1
        Should -Invoke Start-Process -Exactly -Times 1
        $script:VersionCalls | Should -BeExactly 2
    }

    It 'should reject a corrupt installer before execution' {
        Mock Get-TesseractVersion { [version]'5.5.0' }
        Mock Get-FileHash { @{ Hash = ('0' * 64) } }
        { Ensure-Tesseract -Executable 'fixture.exe' -Installer (Join-Path $TestDrive 'installer.exe') } |
            Should -Throw '*checksum mismatch*'
        Should -Invoke Start-Process -Exactly -Times 0
    }

    It 'should reject an unsuccessful native installer' {
        Mock Get-TesseractVersion { [version]'5.5.0' }
        Mock Start-Process { @{ ExitCode = 1603 } }
        { Ensure-Tesseract -Executable 'fixture.exe' -Installer (Join-Path $TestDrive 'installer.exe') } |
            Should -Throw '*exit 1603*'
    }

    It 'should reject a stale binary after reported installation success' {
        Mock Get-TesseractVersion { [version]'5.5.0' }
        { Ensure-Tesseract -Executable 'fixture.exe' -Installer (Join-Path $TestDrive 'installer.exe') } |
            Should -Throw '*below required 5.5.3*'
    }
}
