BeforeAll {
    $script:Script = Join-Path $PSScriptRoot '..' 'scripts' 'windows.ps1'

    # ~keep The script ends by executing the binary it copied ("& $taskExe --version"). A shebang
    # stub satisfies that on POSIX hosts; on Windows only a real PE image would, so the tests that
    # run to completion are skipped there and the Windows runner covers the paths that throw
    # before this line. See the -Skip reasons below.
    function New-ExecutableStub {
        param([string]$Path, [string]$Output)

        # ~keep chmod is a native binary and receives the string verbatim, while PowerShell's
        # own path parameters silently normalise "\" to "/" on POSIX. Passing the unnormalised
        # path made chmod fail against a name that does not exist, leaving a non-executable
        # stub that the script then failed to run -- without failing the assertions above it.
        $posixPath = $Path -replace '\\', '/'
        Set-Content -LiteralPath $posixPath -Value @('#!/bin/sh', "echo '$Output'")
        & chmod +x $posixPath
        if ($LASTEXITCODE -ne 0) { throw "could not make the stub at $posixPath executable" }
    }

    # ~keep CI runs every suite in a single pwsh process, so an environment variable or a global
    # ~keep function left behind here decides what the next file sees. Snapshot on entry, hand
    # ~keep back on exit.
    $script:SavedEnvironment = @{}
    foreach ($name in @('RUNNER_TEMP', 'GITHUB_PATH', 'GITHUB_TOKEN', 'MISE_GITHUB_TOKEN', 'MISE_HTTP_TIMEOUT', 'MISE_LOCKED')) {
        $script:SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
    }
}

Describe 'install-task windows.ps1' {
    BeforeEach {
        $script:Root = Join-Path ([System.IO.Path]::GetTempPath()) "install-task-$(New-Guid)"
        New-Item -ItemType Directory -Path $script:Root -Force | Out-Null
        $script:BinDir = Join-Path $script:Root 'bin'
        New-Item -ItemType Directory -Path $script:BinDir -Force | Out-Null
        $script:GithubPath = Join-Path $script:Root 'github-path'
        Set-Content -LiteralPath $script:GithubPath -Value @()

        $env:RUNNER_TEMP = $script:Root
        $env:GITHUB_PATH = $script:GithubPath
        $env:GITHUB_TOKEN = $null
        $env:MISE_GITHUB_TOKEN = $null
        $env:MISE_HTTP_TIMEOUT = $null
        $env:MISE_LOCKED = $null

        # ~keep "$taskBinDir\task.exe" is string concatenation, not Join-Path, so the literal
        # backslash survives on POSIX and names a single file. The tests build the same string
        # rather than assuming a nested directory.
        $script:TaskExe = "$script:BinDir\task.exe"

        Mock Start-Sleep { }

        # ~keep The script calls `mise` by name; a global function wins over any native binary,
        # so CI hosts without mise run the same paths. Each call is recorded with the working
        # directory and the settings mise would see. `which` points at a file that only the tests
        # running to completion create, so every other test stops at the copy. MiseFail fails the
        # named subcommand, only its first MiseFailTimes calls when that is set.
        $global:MiseCalls = [System.Collections.Generic.List[pscustomobject]]::new()
        $global:MiseLatest = '3.54.0'
        $global:MiseFail = ''
        $global:MiseFailTimes = 0
        $global:MiseFailCount = 0
        $global:MiseBinary = Join-Path $script:Root 'mise-task'
        function global:mise {
            $global:MiseCalls.Add([pscustomobject]@{
                    Args     = $args -join ' '
                    Location = (Get-Location).Path
                    Token    = $env:MISE_GITHUB_TOKEN
                    Locked   = $env:MISE_LOCKED
                    Timeout  = $env:MISE_HTTP_TIMEOUT
                })
            if ($args[0] -eq $global:MiseFail) {
                $global:MiseFailCount++
                if ($global:MiseFailTimes -eq 0 -or $global:MiseFailCount -le $global:MiseFailTimes) {
                    $global:LASTEXITCODE = 1
                    return
                }
            }
            $global:LASTEXITCODE = 0
            switch ($args[0]) {
                'latest' { $global:MiseLatest }
                'which' { $global:MiseBinary }
            }
        }
    }

    AfterEach {
        Remove-Item -Recurse -Force $script:Root -ErrorAction SilentlyContinue
        Remove-Item -Path Function:\mise -ErrorAction SilentlyContinue
        $env:GITHUB_TOKEN = $null
        $env:MISE_GITHUB_TOKEN = $null
        $env:MISE_HTTP_TIMEOUT = $null
        $env:MISE_LOCKED = $null
    }

    It 'should_strip_a_leading_v_before_installing_the_pinned_version' {
        { & $script:Script 'v3.51.1' $script:BinDir } | Should -Throw

        $global:MiseCalls.Args | Should -Contain 'install task@3.51.1'
        $global:MiseCalls.Args | Should -Contain 'which task --tool task@3.51.1'
        $global:MiseCalls.Args | Should -Not -Contain 'latest task'
    }

    It 'should_install_a_bare_pinned_version_unchanged' {
        { & $script:Script '3.51.1' $script:BinDir } | Should -Throw

        $global:MiseCalls.Args | Should -Contain 'install task@3.51.1'
    }

    It 'should_resolve_latest_through_mise_and_install_that_exact_version' {
        $global:MiseLatest = '3.55.0'

        { & $script:Script 'latest' $script:BinDir } | Should -Throw

        $global:MiseCalls.Args[0] | Should -BeExactly 'latest task'
        $global:MiseCalls.Args | Should -Contain 'install task@3.55.0'
    }

    It 'should_treat_an_empty_version_as_latest' {
        { & $script:Script '' $script:BinDir } | Should -Throw

        $global:MiseCalls.Args | Should -Contain 'latest task'
        $global:MiseCalls.Args | Should -Contain 'install task@3.54.0'
    }

    It 'should_throw_when_mise_cannot_resolve_latest' {
        $global:MiseFail = 'latest'

        $thrown = { & $script:Script 'latest' $script:BinDir } | Should -Throw -PassThru

        $thrown.Exception.Message | Should -BeExactly "'mise latest task' failed after 6 attempts"
        @($global:MiseCalls | Where-Object Args -EQ 'latest task').Count | Should -Be 6
        $global:MiseCalls.Args | Should -Not -Contain 'install task@3.54.0'
    }

    It 'should_retry_mise_install_six_times_with_backoff_then_throw_without_touching_github_path' {
        $global:MiseFail = 'install'

        $thrown = { & $script:Script '3.54.0' $script:BinDir } | Should -Throw -PassThru

        $thrown.Exception.Message | Should -BeExactly "'mise install task@3.54.0' failed after 6 attempts"
        @($global:MiseCalls | Where-Object Args -EQ 'install task@3.54.0').Count | Should -Be 6
        Should -Invoke Start-Sleep -Times 1 -Exactly -ParameterFilter { $Seconds -eq 5 }
        Should -Invoke Start-Sleep -Times 1 -Exactly -ParameterFilter { $Seconds -eq 10 }
        Should -Invoke Start-Sleep -Times 1 -Exactly -ParameterFilter { $Seconds -eq 20 }
        Should -Invoke Start-Sleep -Times 1 -Exactly -ParameterFilter { $Seconds -eq 40 }
        Should -Invoke Start-Sleep -Times 1 -Exactly -ParameterFilter { $Seconds -eq 80 }
        Should -Invoke Start-Sleep -Times 5 -Exactly
        Get-Content -LiteralPath $script:GithubPath | Should -BeNullOrEmpty
    }

    It 'should_stop_retrying_once_a_mise_call_succeeds' {
        $global:MiseFail = 'install'
        $global:MiseFailTimes = 2

        { & $script:Script '3.54.0' $script:BinDir } | Should -Throw

        @($global:MiseCalls | Where-Object Args -EQ 'install task@3.54.0').Count | Should -Be 3
        $global:MiseCalls.Args | Should -Contain 'which task --tool task@3.54.0'
        Should -Invoke Start-Sleep -Times 2 -Exactly
    }

    It 'should_install_unlocked_with_a_5m_http_timeout_by_default' {
        $env:MISE_LOCKED = '1'

        { & $script:Script '3.54.0' $script:BinDir } | Should -Throw

        $global:MiseCalls.Locked | Sort-Object -Unique | Should -BeExactly 'false'
        $global:MiseCalls.Timeout | Sort-Object -Unique | Should -BeExactly '5m'
    }

    It 'should_keep_an_http_timeout_the_caller_set' {
        $env:MISE_HTTP_TIMEOUT = '90s'

        { & $script:Script '3.54.0' $script:BinDir } | Should -Throw

        $global:MiseCalls.Timeout | Sort-Object -Unique | Should -BeExactly '90s'
    }

    It 'should_run_mise_from_runner_temp_with_the_github_token_and_restore_the_location' {
        $env:GITHUB_TOKEN = 'secret-token'
        $before = (Get-Location).Path

        { & $script:Script '3.54.0' $script:BinDir } | Should -Throw

        $global:MiseCalls.Count | Should -Be 2
        $global:MiseCalls | ForEach-Object { $_.Location | Should -BeExactly (Get-Item $script:Root).FullName }
        $global:MiseCalls.Token | Sort-Object -Unique | Should -BeExactly 'secret-token'
        (Get-Location).Path | Should -BeExactly $before
    }

    It 'should_default_the_install_directory_to_task_bin_under_runner_temp' {
        $global:MiseFail = 'which'
        $expected = Join-Path $env:RUNNER_TEMP 'task-bin'

        { & $script:Script '3.54.0' '' } | Should -Throw

        Test-Path -LiteralPath $expected -PathType Container | Should -BeTrue
    }

    It 'should_resolve_a_relative_install_directory_against_the_caller_location' {
        $work = Join-Path $script:Root 'work'
        New-Item -ItemType Directory -Path $work -Force | Out-Null
        New-ExecutableStub -Path $global:MiseBinary -Output 'Task version: v3.54.0'
        $expected = (Resolve-Path -LiteralPath $work).Path
        Push-Location $work
        try {
            & $script:Script '3.54.0' 'rel-bin' | Out-Null
        } finally {
            Pop-Location
        }

        Get-Content -LiteralPath $script:GithubPath | Should -BeExactly (Join-Path $expected 'rel-bin')
        Test-Path -LiteralPath "$(Join-Path $expected 'rel-bin')\task.exe" | Should -BeTrue
    } -Skip:($IsWindows)

    It 'should_copy_the_binary_report_its_version_and_append_the_bin_directory_to_github_path' {
        New-ExecutableStub -Path $global:MiseBinary -Output 'Task version: v3.54.0'

        # ~keep 6>&1 merges the information stream: the script announces the version with
        # Write-Host, which the call operator does not place on the success stream.
        $output = @(& $script:Script '3.54.0' $script:BinDir 6>&1 | ForEach-Object { $_.ToString() })

        $output | Should -Contain 'Installing Task v3.54.0'
        $output[-1] | Should -BeExactly 'Task version: v3.54.0'
        Get-Content -LiteralPath $script:GithubPath | Should -BeExactly $script:BinDir
    } -Skip:($IsWindows)

    It 'should_overwrite_a_task_binary_left_by_an_earlier_install' {
        New-ExecutableStub -Path $global:MiseBinary -Output 'Task version: v3.54.0'
        New-ExecutableStub -Path $script:TaskExe -Output 'Task version: v3.0.0'

        $output = @(& $script:Script '3.54.0' $script:BinDir 6>&1 | ForEach-Object { $_.ToString() })

        $output[-1] | Should -BeExactly 'Task version: v3.54.0'
    } -Skip:($IsWindows)

    AfterAll {
        foreach ($entry in $script:SavedEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value)
        }
        Remove-Variable -Scope Global -Name MiseCalls, MiseLatest, MiseFail, MiseFailTimes, MiseFailCount, MiseBinary `
            -ErrorAction SilentlyContinue
    }
}
