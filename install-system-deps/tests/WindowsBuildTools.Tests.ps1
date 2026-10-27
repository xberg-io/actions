BeforeAll {
    . (Join-Path $PSScriptRoot "../scripts/ensure-build-tools-windows.ps1")
}
Describe 'Windows build tool runtime selection' {
    It 'accepts exactly the selected runtime' {
        Test-BuildToolVersion -Executable (Join-Path $PSHOME 'pwsh') -Arguments @('-NoProfile', '-Command', 'Write-Output "clang version 23.1.3"') -Version '23.1.3' | Should -BeTrue
    }
    It 'rejects stale cached versions' {
        Test-BuildToolVersion -Executable (Join-Path $PSHOME 'pwsh') -Arguments @('-NoProfile', '-Command', 'Write-Output "clang version 22.1.8"') -Version '23.1.3' | Should -BeFalse
    }
    It 'rejects a successful-looking version with native failure' {
        Test-BuildToolVersion -Executable (Join-Path $PSHOME 'pwsh') -Arguments @('-NoProfile', '-Command', 'Write-Output "cmake version 4.4.4"; exit 7') -Version '4.4.4' | Should -BeFalse
    }
    It 'rejects absent executables and empty output' {
        Test-BuildToolVersion -Executable 'missing-xberg-build-tool' -Version '4.4.4' | Should -BeFalse
        Test-BuildToolVersion -Executable (Join-Path $PSHOME 'pwsh') -Arguments @('-NoProfile', '-Command', 'exit 0') -Version '4.4.4' | Should -BeFalse
    }
}
