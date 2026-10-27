BeforeAll {
    $path = Join-Path $PSScriptRoot '../scripts/install-windows.ps1'
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors.Count -ne 0) { throw 'Windows installer did not parse' }
    $functions = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in @('Retry-Command', 'Assert-LibheifVersion')
    }, $true))
    if ($functions.Count -ne 2) { throw 'Expected both actual dependency validation functions' }
    foreach ($function in $functions) { . ([scriptblock]::Create($function.Extent.Text)) }
}

Describe 'Windows native dependency retries' {
    It 'should not report a native nonzero exit as successful' {
        Retry-Command { & (Join-Path $PSHOME 'pwsh') -NoProfile -Command 'exit 7' } -MaxAttempts 1 |
            Should -BeFalse
    }

    It 'should not let native stdout hide a failed exit status' {
        Retry-Command {
            & (Join-Path $PSHOME 'pwsh') -NoProfile -Command 'Write-Output "native diagnostic"; exit 7'
        } -MaxAttempts 1 | Should -BeFalse
    }

    It 'should accept an actual successful native command' {
        Retry-Command { & (Join-Path $PSHOME 'pwsh') -NoProfile -Command 'exit 0' } -MaxAttempts 1 |
            Should -BeTrue
    }
}

Describe 'Installed Windows libheif validation' {
    It 'should accept exactly one current base port alongside feature rows' {
        { Assert-LibheifVersion -Packages @(
            'libheif:x64-windows-static-md 1.23.7#1 HEIF decoder',
            'libheif[hevc]:x64-windows-static-md HEVC encoder'
        ) } | Should -Not -Throw
    }

    It 'should reject a cache containing an old installed base port' {
        { Assert-LibheifVersion -Packages @('libheif:x64-windows-static-md 1.23.0 HEIF decoder') } |
            Should -Throw '*exactly one installed libheif 1.23.7*'
    }

    It 'should reject an empty query and feature-only output' {
        { Assert-LibheifVersion -Packages @() } | Should -Throw '*exactly one*'
        { Assert-LibheifVersion -Packages @('libheif[hevc]:x64-windows-static-md HEVC encoder') } |
            Should -Throw '*exactly one*'
    }
}
