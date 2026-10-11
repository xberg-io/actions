BeforeAll {
    $script:Script = Join-Path $PSScriptRoot '..' 'scripts' 'deinherit-workspace.ps1'

    function New-Manifest {
        param([string[]]$Crate, [string[]]$Workspace)

        $root = Join-Path ([System.IO.Path]::GetTempPath()) "deinherit-$(New-Guid)"
        New-Item -ItemType Directory -Path $root -Force | Out-Null
        $cratePath = Join-Path $root 'Cargo.toml'
        $workspacePath = Join-Path $root 'workspace-Cargo.toml'
        Set-Content -LiteralPath $cratePath -Value $Crate
        Set-Content -LiteralPath $workspacePath -Value $Workspace
        [pscustomobject]@{ Root = $root; Crate = $cratePath; Workspace = $workspacePath }
    }

    $script:DefaultWorkspace = @(
        '[workspace.package]'
        'version = "1.4.0"'
        'edition = "2021"'
        'license = "MIT"'
        'readme = "README.md"'
        'license-file = "LICENSE"'
        ''
        '[workspace.dependencies]'
        'serde = { version = "1", features = ["derive"] }'
        'anyhow = "1.0.86"'
    )
}

Describe 'deinherit-workspace.ps1' {
    AfterEach {
        if ($script:Fixture) {
            Remove-Item -Recurse -Force $script:Fixture.Root -ErrorAction SilentlyContinue
            $script:Fixture = $null
        }
    }

    It 'should_replace_dotted_package_inheritance_with_concrete_workspace_values' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            'name = "xberg-php"'
            'version.workspace = true'
            'edition.workspace = true'
            'license.workspace = true'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            'name = "xberg-php"'
            'version = "1.4.0"'
            'edition = "2021"'
            'license = "MIT"'
        )
    }

    It 'should_replace_inline_table_inheritance_with_concrete_workspace_values' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            'version = { workspace = true }'
            'edition = {workspace = true,}'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            'version = "1.4.0"'
            'edition = "2021"'
        )
    }

    It 'should_preserve_multiline_workspace_package_values' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            'name = "xberg-php"'
            'authors.workspace = true'
        ) -Workspace @(
            '[workspace.package]'
            'authors = ['
            '  "One Maintainer <one@example.com>",'
            '  "Two Maintainers <two@example.com>",'
            ']'
        )

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            'name = "xberg-php"'
            'authors = ['
            '  "One Maintainer <one@example.com>",'
            '  "Two Maintainers <two@example.com>",'
            ']'
        )
    }

    It 'should_drop_bare_workspace_inheritance_that_has_no_key_to_resolve' {
        $script:Fixture = New-Manifest -Crate @(
            '[lints]'
            'workspace = true'
            ''
            '[package]'
            'name = "xberg-php"'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[lints]'
            ''
            '[package]'
            'name = "xberg-php"'
        )
    }

    It 'should_resolve_dependency_inheritance_from_workspace_dependencies_table' {
        $script:Fixture = New-Manifest -Crate @(
            '[dependencies]'
            'serde.workspace = true'
            'anyhow = { workspace = true }'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[dependencies]'
            'serde = { version = "1", features = ["derive"] }'
            'anyhow = "1.0.86"'
        )
    }

    It 'should_resolve_dependency_inheritance_in_dev_and_build_and_target_tables' {
        $script:Fixture = New-Manifest -Crate @(
            '[dev-dependencies]'
            'anyhow.workspace = true'
            '[build-dependencies]'
            'anyhow.workspace = true'
            "[target.'cfg(windows)'.dependencies]"
            'serde.workspace = true'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[dev-dependencies]'
            'anyhow = "1.0.86"'
            '[build-dependencies]'
            'anyhow = "1.0.86"'
            "[target.'cfg(windows)'.dependencies]"
            'serde = { version = "1", features = ["derive"] }'
        )
    }

    It 'should_throw_when_inherited_dependency_is_absent_from_workspace_dependencies' {
        $script:Fixture = New-Manifest -Crate @(
            '[dependencies]'
            'tokio.workspace = true'
        ) -Workspace $script:DefaultWorkspace

        $thrown = { & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace } |
            Should -Throw -PassThru

        $thrown.Exception.Message | Should -BeExactly "Dependency 'tokio' inherits from the workspace but [workspace.dependencies] in $($script:Fixture.Workspace) has no entry for it"
    }

    It 'should_throw_for_an_unsupported_spelling_of_workspace_inheritance' {
        $script:Fixture = New-Manifest -Crate @(
            '[dependencies]'
            'serde = { workspace = true, features = ["derive"] }'
        ) -Workspace $script:DefaultWorkspace

        $thrown = { & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace } |
            Should -Throw -PassThru

        $thrown.Exception.Message | Should -BeExactly "Cannot de-inherit 'serde = { workspace = true, features = [`"derive`"] }' in $($script:Fixture.Crate): unsupported workspace inheritance form"
    }

    It 'should_copy_comments_verbatim_even_when_they_mention_workspace_inheritance' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            '# version.workspace = true is what alef emits here'
            '   # workspace = true'
            'name = "xberg-php"'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            '# version.workspace = true is what alef emits here'
            '   # workspace = true'
            'name = "xberg-php"'
        )
    }

    It 'should_drop_inherited_readme_and_license_file_instead_of_resolving_them_to_workspace_paths' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            'readme.workspace = true'
            'license-file.workspace = true'
            'version.workspace = true'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            'version = "1.4.0"'
        )
    }

    It 'should_drop_inherited_package_key_that_workspace_package_does_not_define' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            'name = "xberg-php"'
            'rust-version.workspace = true'
        ) -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            'name = "xberg-php"'
        )
    }

    It 'should_leave_a_manifest_without_inheritance_completely_unchanged' {
        $original = @(
            '[package]'
            'name = "xberg-php"'
            'version = "0.1.0"'
            ''
            '[lib]'
            'crate-type = ["cdylib"]'
            ''
            '[dependencies]'
            'serde = "1"'
        )
        $script:Fixture = New-Manifest -Crate $original -Workspace $script:DefaultWorkspace

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly $original
    }

    It 'should_ignore_workspace_package_values_when_the_workspace_manifest_is_missing' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            'name = "xberg-php"'
            'version.workspace = true'
        ) -Workspace $script:DefaultWorkspace
        $absent = Join-Path $script:Fixture.Root 'no-such-Cargo.toml'

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $absent

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            'name = "xberg-php"'
        )
    }

    It 'should_read_workspace_values_only_from_the_workspace_package_table' {
        $script:Fixture = New-Manifest -Crate @(
            '[package]'
            'version.workspace = true'
        ) -Workspace @(
            '[package]'
            'version = "9.9.9"'
            ''
            '[workspace.package]'
            'version = "1.4.0"'
        )

        & $script:Script -CrateManifest $script:Fixture.Crate -WorkspaceManifest $script:Fixture.Workspace

        Get-Content -LiteralPath $script:Fixture.Crate | Should -BeExactly @(
            '[package]'
            'version = "1.4.0"'
        )
    }
}
