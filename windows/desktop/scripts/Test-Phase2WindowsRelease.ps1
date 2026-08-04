# Phase 2 Windows 预编译发布包门禁；必须在原生 Windows runner 上通过。
[CmdletBinding()]
param(
    [string]$ReleaseRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)

    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\\"') + '"'
}

function Read-JsonUtf8 {
    param([Parameter(Mandatory)][string]$Path)

    $encoding = [System.Text.UTF8Encoding]::new($false, $true)
    $json = [System.IO.File]::ReadAllText($Path, $encoding)
    return ($json | ConvertFrom-Json)
}

function Write-JsonUtf8 {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText(
        $Path,
        ($Value | ConvertTo-Json -Depth 30),
        $encoding)
}

function Write-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Value)

    [System.IO.File]::WriteAllText(
        $Path,
        $Value,
        [System.Text.UTF8Encoding]::new($false))
}

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int[]]$ExpectedExitCodes = @(0),
        [int]$TimeoutSeconds = 120
    )

    $argumentLine = ($Arguments | ForEach-Object {
        ConvertTo-NativeArgument -Value $_
    }) -join ' '
    $startInfo                        = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName               = $FilePath
    $startInfo.Arguments              = $argumentLine
    $startInfo.UseShellExecute        = $false
    $startInfo.CreateNoWindow         = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError  = $true

    $process           = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "无法启动进程：$FilePath"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $process.Kill() } catch { }
            try { $process.WaitForExit() } catch { }
            throw "进程自检超时：$FilePath"
        }
        $process.WaitForExit()
        $process.Refresh()
        $stdout   = $stdoutTask.GetAwaiter().GetResult()
        $stderr   = $stderrTask.GetAwaiter().GetResult()
        $exitCode = [int]$process.ExitCode
        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            Write-Host $stdout.TrimEnd()
        }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            Write-Host $stderr.TrimEnd()
        }
        if ($ExpectedExitCodes -notcontains $exitCode) {
            throw "进程退出码不符合预期（实际 $exitCode，预期 $($ExpectedExitCodes -join ',')）：$FilePath"
        }
        return [pscustomobject][ordered]@{
            ExitCode = $exitCode
            StdOut   = $stdout
            StdErr   = $stderr
        }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-ReleaseScript {
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int[]]$ExpectedExitCodes = @(0),
        [int]$TimeoutSeconds = 180
    )

    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $nativeArguments = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $ScriptPath
    ) + $Arguments
    return Invoke-CheckedProcess `
        -FilePath $powershell `
        -Arguments $nativeArguments `
        -ExpectedExitCodes $ExpectedExitCodes `
        -TimeoutSeconds $TimeoutSeconds
}

function Assert-ManifestFiles {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$PayloadRoot
    )

    foreach ($entry in $Manifest.files) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or
            $relative.Contains("..") -or
            [System.IO.Path]::IsPathRooted($relative)) {
            throw "发布清单包含非法相对路径：$relative"
        }
        $path = Join-Path $PayloadRoot ($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "发布文件缺失：$relative"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) {
            throw "发布文件哈希不一致：$relative"
        }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$entry.size_bytes) {
            throw "发布文件大小不一致：$relative"
        }
    }
}

function Assert-PowerShellSyntax {
    param([Parameter(Mandatory)][string]$Path)

    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $Path,
        [ref]$tokens,
        [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) {
        $messages = ($errors | ForEach-Object { $_.Message }) -join ' | '
        throw "PowerShell 语法失败：$Path | $messages"
    }
}

function Copy-PackageRoot {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )

    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    return $Destination
}

function Update-ManifestFileEntry {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$RelativePath
    )

    $path = Join-Path $PackageRoot ("payload\" + ($RelativePath -replace '/', '\'))
    $entry = $Manifest.files | Where-Object {
        [string]$_.path -eq $RelativePath
    } | Select-Object -First 1
    if ($null -eq $entry) {
        throw "夹具清单缺少文件：$RelativePath"
    }
    $entry.sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $entry.size_bytes = (Get-Item -LiteralPath $path).Length
}

function Set-PackageVersion {
    param(
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$Version
    )

    $manifestPath = Join-Path $PackageRoot "release-manifest.json"
    $manifest = Read-JsonUtf8 -Path $manifestPath
    $manifest.version = $Version
    Write-JsonUtf8 -Value $manifest -Path $manifestPath
    return $manifest
}

function Set-PackageProductVersion {
    param(
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$ProductVersion
    )

    if ($ProductVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$') {
        throw "夹具产品版本必须是四段数字：$ProductVersion"
    }
    $manifestPath = Join-Path $PackageRoot "release-manifest.json"
    $manifest = Read-JsonUtf8 -Path $manifestPath
    $manifest.product_version = $ProductVersion
    $versionFile = Join-Path $PackageRoot "payload\product-version.txt"
    Write-Utf8NoBom -Path $versionFile -Value "$ProductVersion`n"
    Update-ManifestFileEntry `
        -Manifest $manifest `
        -PackageRoot $PackageRoot `
        -RelativePath "product-version.txt"
    Write-JsonUtf8 -Value $manifest -Path $manifestPath
    return $manifest
}

function Set-FastExitApplication {
    param(
        [Parameter(Mandatory)][string]$PackageRoot,
        [Parameter(Mandatory)][string]$Version
    )

    $manifest = Set-PackageVersion -PackageRoot $PackageRoot -Version $Version
    $fastExit = Join-Path $env:SystemRoot "System32\whoami.exe"
    if (-not (Test-Path -LiteralPath $fastExit -PathType Leaf)) {
        throw "找不到激活失败夹具程序：$fastExit"
    }
    $appPath = Join-Path $PackageRoot "payload\Picotoo Pet AI.exe"
    Copy-Item -LiteralPath $fastExit -Destination $appPath -Force
    Update-ManifestFileEntry `
        -Manifest $manifest `
        -PackageRoot $PackageRoot `
        -RelativePath "Picotoo Pet AI.exe"
    Write-JsonUtf8 -Value $manifest -Path (Join-Path $PackageRoot "release-manifest.json")
}

function Get-LatestReport {
    param(
        [Parameter(Mandatory)][string]$DataRoot,
        [Parameter(Mandatory)][string]$Filter
    )

    $reportsRoot = Join-Path $DataRoot "reports"
    $report = Get-ChildItem -LiteralPath $reportsRoot -Filter $Filter -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $report) {
        throw "未找到夹具报告：$Filter"
    }
    return $report
}

function Copy-ValidatedReport {
    param(
        [Parameter(Mandatory)][string]$DataRoot,
        [Parameter(Mandatory)][string]$Filter,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ExpectedStatus
    )

    $reportFile = Get-LatestReport -DataRoot $DataRoot -Filter $Filter
    $report = Read-JsonUtf8 -Path $reportFile.FullName
    if ([string]$report.status -ne $ExpectedStatus) {
        throw "夹具报告状态错误：$($reportFile.Name) | $($report.status)"
    }
    Copy-Item -LiteralPath $reportFile.FullName -Destination $Destination -Force
    return $report
}

function Assert-PointerVersions {
    param(
        [Parameter(Mandatory)][string]$DataRoot,
        [Parameter(Mandatory)][string]$CurrentVersion,
        [Parameter(Mandatory)][string]$PreviousVersion,
        [string]$CurrentProductVersion = "",
        [string]$PreviousProductVersion = ""
    )

    $current = Read-JsonUtf8 -Path (Join-Path $DataRoot "current_version.json")
    $previous = Read-JsonUtf8 -Path (Join-Path $DataRoot "previous_version.json")
    if ([string]$current.version -ne $CurrentVersion) {
        throw "current_version.json 版本错误：$($current.version)"
    }
    if ([string]$previous.version -ne $PreviousVersion) {
        throw "previous_version.json 版本错误：$($previous.version)"
    }
    if (-not [string]::IsNullOrWhiteSpace($CurrentProductVersion) -and
        [string]$current.product_version -ne $CurrentProductVersion) {
        throw "current_version.json 产品版本错误：$($current.product_version)"
    }
    if (-not [string]::IsNullOrWhiteSpace($PreviousProductVersion) -and
        [string]$previous.product_version -ne $PreviousProductVersion) {
        throw "previous_version.json 产品版本错误：$($previous.product_version)"
    }
    if (-not ($current.PSObject.Properties.Name -contains "shortcut_state") -or
        -not ($previous.PSObject.Properties.Name -contains "shortcut_state")) {
        throw "版本指针缺少 shortcut_state。"
    }
    return [pscustomobject][ordered]@{
        current  = $current
        previous = $previous
    }
}

function Convert-ShortcutSnapshotToJson {
    param([Parameter(Mandatory)]$ShortcutState)

    return (@($ShortcutState | Sort-Object location, name) |
        ConvertTo-Json -Depth 20 -Compress)
}

function Assert-ShortcutSnapshotEqual {
    param(
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)]$Actual
    )

    $expectedJson = Convert-ShortcutSnapshotToJson -ShortcutState $Expected
    $actualJson = Convert-ShortcutSnapshotToJson -ShortcutState $Actual
    if ($expectedJson -ne $actualJson) {
        throw "快捷方式快照不一致。expected=$expectedJson actual=$actualJson"
    }
}

function Assert-VersionedShortcutNames {
    param(
        [Parameter(Mandatory)]$ShortcutState,
        [Parameter(Mandatory)][string]$ProductVersion
    )

    $expectedName = "Picotoo Pet AI $ProductVersion.lnk"
    $entries = @($ShortcutState)
    if ($entries.Count -ne 3) {
        throw "版本快捷方式数量不是 3：$($entries.Count)"
    }
    foreach ($entry in $entries) {
        if ([string]$entry.name -ne $expectedName) {
            throw "快捷方式名称错误：$($entry.name)"
        }
    }
}

function Set-CorruptDesktopShortcut {
    param(
        [Parameter(Mandatory)][string]$DesktopDirectory,
        [Parameter(Mandatory)][string]$ProductVersion
    )

    $path = Join-Path $DesktopDirectory "Picotoo Pet AI $ProductVersion.lnk"
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($path)
        $shortcut.TargetPath = Join-Path $env:SystemRoot "System32\notepad.exe"
        $shortcut.Arguments = "/fixture-corrupt"
        $shortcut.WorkingDirectory = $env:SystemRoot
        $shortcut.Description = "fixture-corrupt"
        $shortcut.Save()
    }
    finally {
        if ($null -ne $shell -and [System.Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }
}

function Invoke-LifecycleFixture {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$DesktopDirectory,
        [Parameter(Mandatory)][string]$SourcePackageRoot,
        [Parameter(Mandatory)][string]$FixtureRoot,
        [Parameter(Mandatory)][string]$EvidenceRoot
    )

    $fixturePath = Join-Path $FixtureRoot $Name
    $dataRoot    = Join-Path $fixturePath "data"
    $appData     = Join-Path $fixturePath "AppData\Roaming"
    $localData   = Join-Path $fixturePath "AppData\Local"
    New-Item -ItemType Directory -Path $dataRoot, $appData, $localData, $DesktopDirectory -Force | Out-Null

    $originalAppData      = $env:APPDATA
    $originalLocalAppData = $env:LOCALAPPDATA
    try {
        $env:APPDATA      = $appData
        $env:LOCALAPPDATA = $localData

        $packageA = Copy-PackageRoot `
            -Source $SourcePackageRoot `
            -Destination (Join-Path $fixturePath "package-a")
        $packageB = Copy-PackageRoot `
            -Source $SourcePackageRoot `
            -Destination (Join-Path $fixturePath "package-b")
        $packageFailure = Copy-PackageRoot `
            -Source $SourcePackageRoot `
            -Destination (Join-Path $fixturePath "package-activation-failure")

        $versionA = "fixture-$Name-a"
        $versionB = "fixture-$Name-b"
        $versionFailure = "fixture-$Name-activation-failure"
        $productVersionA = "2.3.5.9"
        $productVersionB = "2.3.6.1"
        [void](Set-PackageVersion -PackageRoot $packageA -Version $versionA)
        [void](Set-PackageProductVersion -PackageRoot $packageA -ProductVersion $productVersionA)
        [void](Set-PackageVersion -PackageRoot $packageB -Version $versionB)
        [void](Set-PackageProductVersion -PackageRoot $packageB -ProductVersion $productVersionB)
        [void](Set-PackageProductVersion -PackageRoot $packageFailure -ProductVersion $productVersionB)
        Set-FastExitApplication -PackageRoot $packageFailure -Version $versionFailure

        $installerA       = Join-Path $packageA "Install-Phase2Prebuilt.ps1"
        $installerB       = Join-Path $packageB "Install-Phase2Prebuilt.ps1"
        $installerFailure = Join-Path $packageFailure "Install-Phase2Prebuilt.ps1"
        $verifierB        = Join-Path $packageB "Verify-Phase2Prebuilt.ps1"
        $rollbackB        = Join-Path $packageB "Rollback-Phase2Prebuilt.ps1"
        $commonB          = Join-Path $packageB "Phase2Prebuilt.Common.ps1"
        . $commonB

        [void](Invoke-ReleaseScript -ScriptPath $installerA -Arguments @(
            "-PackageRoot", $packageA,
            "-DataRoot", $dataRoot,
            "-DesktopDirectory", $DesktopDirectory,
            "-ActivationSelfTest",
            "-SuppressReportOpen"
        ))
        $installA = Copy-ValidatedReport `
            -DataRoot $dataRoot `
            -Filter "phase2-prebuilt-install-*.json" `
            -Destination (Join-Path $EvidenceRoot "$Name-install-a.json") `
            -ExpectedStatus "pass"
        Assert-VersionedShortcutNames `
            -ShortcutState $installA.shortcut_state `
            -ProductVersion $productVersionA
        $snapshotA = @(Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory)
        Assert-ShortcutSnapshotEqual -Expected $installA.shortcut_state -Actual $snapshotA

        [void](Invoke-ReleaseScript -ScriptPath $installerB -Arguments @(
            "-PackageRoot", $packageB,
            "-DataRoot", $dataRoot,
            "-DesktopDirectory", $DesktopDirectory,
            "-ActivationSelfTest",
            "-SuppressReportOpen"
        ))
        $installB = Copy-ValidatedReport `
            -DataRoot $dataRoot `
            -Filter "phase2-prebuilt-install-*.json" `
            -Destination (Join-Path $EvidenceRoot "$Name-install-b.json") `
            -ExpectedStatus "pass"
        Assert-VersionedShortcutNames `
            -ShortcutState $installB.shortcut_state `
            -ProductVersion $productVersionB
        $snapshotB = @(Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory)
        Assert-ShortcutSnapshotEqual -Expected $installB.shortcut_state -Actual $snapshotB
        if (Test-Path -LiteralPath (Join-Path $DesktopDirectory "Picotoo Pet AI 2.3.5.9.lnk")) {
            throw "升级后仍保留旧版本快捷方式。"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $DesktopDirectory "Picotoo Pet AI 2.3.6.1.lnk"))) {
            throw "升级后缺少当前版本快捷方式。"
        }
        [void](Assert-PointerVersions `
            -DataRoot $dataRoot `
            -CurrentVersion $versionB `
            -PreviousVersion $versionA `
            -CurrentProductVersion $productVersionB `
            -PreviousProductVersion $productVersionA)

        [void](Invoke-ReleaseScript -ScriptPath $verifierB -Arguments @(
            "-DataRoot", $dataRoot,
            "-DesktopDirectory", $DesktopDirectory,
            "-OfflinePackageOnly",
            "-SuppressReportOpen"
        ))
        $verification = Copy-ValidatedReport `
            -DataRoot $dataRoot `
            -Filter "phase2-windows-verification.json" `
            -Destination (Join-Path $EvidenceRoot "$Name-verify-b.json") `
            -ExpectedStatus "pass"
        if ([string]$verification.product_version -ne $productVersionB -or
            -not [bool]$verification.release_validation.shortcuts_verified) {
            throw "VERIFY 没有验证产品版本和三处快捷方式。"
        }

        Set-CorruptDesktopShortcut `
            -DesktopDirectory $DesktopDirectory `
            -ProductVersion $productVersionB
        [void](Invoke-ReleaseScript -ScriptPath $rollbackB -Arguments @(
            "-DataRoot", $dataRoot,
            "-DesktopDirectory", $DesktopDirectory,
            "-ActivationSelfTest",
            "-SuppressReportOpen"
        ))
        $rollback = Copy-ValidatedReport `
            -DataRoot $dataRoot `
            -Filter "phase2-rollback-*.json" `
            -Destination (Join-Path $EvidenceRoot "$Name-rollback-a.json") `
            -ExpectedStatus "pass"
        if (-not [bool]$rollback.shortcuts_verified -or
            [string]$rollback.restored_product_version -ne $productVersionA) {
            throw "ROLLBACK 没有恢复产品版本和快捷方式。"
        }
        $pointers = Assert-PointerVersions `
            -DataRoot $dataRoot `
            -CurrentVersion $versionA `
            -PreviousVersion $versionB `
            -CurrentProductVersion $productVersionA `
            -PreviousProductVersion $productVersionB
        $restoredA = @(Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory)
        Assert-ShortcutSnapshotEqual -Expected $snapshotA -Actual $restoredA
        [void](Assert-PicotooShortcuts `
            -Executable ([string]$pointers.current.executable) `
            -ProductVersion $productVersionA `
            -DesktopDirectory $DesktopDirectory `
            -RequireNoLegacy)

        $beforeFailure = @(Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory)
        [void](Invoke-ReleaseScript `
            -ScriptPath $installerFailure `
            -Arguments @(
                "-PackageRoot", $packageFailure,
                "-DataRoot", $dataRoot,
                "-DesktopDirectory", $DesktopDirectory,
                "-ActivationSelfTest",
                "-SuppressReportOpen"
            ) `
            -ExpectedExitCodes @(1))
        $failureReport = Copy-ValidatedReport `
            -DataRoot $dataRoot `
            -Filter "phase2-prebuilt-install-*.json" `
            -Destination (Join-Path $EvidenceRoot "$Name-activation-failure-recovery.json") `
            -ExpectedStatus "fail"
        if ($null -eq $failureReport.recovery_shortcuts -or
            [string]$failureReport.recovery_shortcuts.restore_mode -ne "pre-activation-snapshot") {
            throw "激活失败后没有按快照恢复快捷方式。"
        }
        $afterFailure = @(Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory)
        Assert-ShortcutSnapshotEqual -Expected $beforeFailure -Actual $afterFailure
        $restoredPointers = Assert-PointerVersions `
            -DataRoot $dataRoot `
            -CurrentVersion $versionA `
            -PreviousVersion $versionB `
            -CurrentProductVersion $productVersionA `
            -PreviousProductVersion $productVersionB
        [void](Assert-PicotooShortcuts `
            -Executable ([string]$restoredPointers.current.executable) `
            -ProductVersion $productVersionA `
            -DesktopDirectory $DesktopDirectory `
            -RequireNoLegacy)

        Write-Host "PHASE2_WINDOWS_LIFECYCLE_FIXTURE=PASS | $Name"
    }
    finally {
        $env:APPDATA      = $originalAppData
        $env:LOCALAPPDATA = $originalLocalAppData
    }
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    $ReleaseRoot = Join-Path $desktopRoot "artifacts\release"
}
$ReleaseRoot = [System.IO.Path]::GetFullPath($ReleaseRoot)
$zip = Get-ChildItem -LiteralPath $ReleaseRoot -Filter "PicotooPet-Phase2-Windows-Prebuilt-*.zip" -File |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if ($null -eq $zip) {
    throw "未找到 Phase 2 Windows 预编译 ZIP。"
}

$tempRoot     = Join-Path $env:TEMP "picotoo-release-test-$([Guid]::NewGuid().ToString('N'))"
$expandRoot   = Join-Path $tempRoot "expanded"
$fixtureRoot  = Join-Path $tempRoot "fixtures"
$evidenceRoot = Join-Path $ReleaseRoot "fixture-evidence"
New-Item -ItemType Directory -Path $expandRoot, $fixtureRoot -Force | Out-Null
if (Test-Path -LiteralPath $evidenceRoot) {
    Remove-Item -LiteralPath $evidenceRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null

try {
    Expand-Archive -LiteralPath $zip.FullName -DestinationPath $expandRoot -Force
    $topFiles = @(Get-ChildItem -LiteralPath $expandRoot -File)
    $topDirectories = @(Get-ChildItem -LiteralPath $expandRoot -Directory)
    if ($topFiles.Count -ne 0 -or $topDirectories.Count -ne 1) {
        throw "ZIP 必须只包含一个顶层目录。"
    }
    $packageRoot = $topDirectories[0].FullName
    $manifestPath = Join-Path $packageRoot "release-manifest.json"
    $payloadRoot  = Join-Path $packageRoot "payload"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "ZIP 顶层目录缺少 release-manifest.json。"
    }
    $manifest = Read-JsonUtf8 -Path $manifestPath
    if ([string]$manifest.release_type -ne "prebuilt") {
        throw "发布类型不是 prebuilt。"
    }
    if ([string]$manifest.target -ne "win-x64") {
        throw "发布目标不是 win-x64。"
    }
    if ([string]$manifest.product_version -ne "2.3.6.1") {
        throw "正式包 product_version 不是 2.3.6.1。"
    }
    if ($zip.Name -notlike "*-$($manifest.product_version)-*") {
        throw "正式 ZIP 名称没有产品版本。"
    }
    if (-not [bool]$manifest.native_ci_verified) {
        throw "发布清单没有 native_ci_verified=true。"
    }
    if (-not [bool]$manifest.user_install_allowed) {
        throw "发布清单没有 user_install_allowed=true。"
    }
    Assert-ManifestFiles -Manifest $manifest -PayloadRoot $payloadRoot

    $installer = Join-Path $packageRoot "Install-Phase2Prebuilt.ps1"
    $verifier  = Join-Path $packageRoot "Verify-Phase2Prebuilt.ps1"
    $rollback  = Join-Path $packageRoot "Rollback-Phase2Prebuilt.ps1"
    $common    = Join-Path $packageRoot "Phase2Prebuilt.Common.ps1"
    foreach ($script in @($installer, $verifier, $rollback, $common)) {
        Assert-PowerShellSyntax -Path $script
    }

    foreach ($vbsName in @(
        "INSTALL_PHASE2_WINDOWS.vbs",
        "VERIFY_PHASE2_WINDOWS.vbs",
        "ROLLBACK_PHASE2_WINDOWS.vbs")) {
        $vbsPath = Join-Path $packageRoot $vbsName
        $vbsBytes = [System.IO.File]::ReadAllBytes($vbsPath)
        if ($vbsBytes.Length -ge 3 -and
            $vbsBytes[0] -eq 0xEF -and
            $vbsBytes[1] -eq 0xBB -and
            $vbsBytes[2] -eq 0xBF) {
            throw "$vbsName 含 UTF-8 BOM。"
        }
    }

    $preflightRoot    = Join-Path $fixtureRoot "preflight"
    $preflightData    = Join-Path $preflightRoot "data"
    $preflightDesktop = Join-Path $preflightRoot "Desktop"
    $preflightAppData = Join-Path $preflightRoot "AppData\Roaming"
    $originalAppData  = $env:APPDATA
    try {
        $env:APPDATA = $preflightAppData
        [void](Invoke-ReleaseScript -ScriptPath $installer -Arguments @(
            "-PackageRoot", $packageRoot,
            "-DataRoot", $preflightData,
            "-DesktopDirectory", $preflightDesktop,
            "-PreflightOnly",
            "-SuppressReportOpen"
        ))
    }
    finally {
        $env:APPDATA = $originalAppData
    }
    [void](Copy-ValidatedReport `
        -DataRoot $preflightData `
        -Filter "phase2-prebuilt-install-*.json" `
        -Destination (Join-Path $evidenceRoot "preflight-install.json") `
        -ExpectedStatus "pass")

    $appExecutable  = Join-Path $payloadRoot "Picotoo Pet AI.exe"
    $diagExecutable = Join-Path $payloadRoot "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    $selfTestPath   = Join-Path $tempRoot "desktop-self-test.json"
    [void](Invoke-CheckedProcess -FilePath $appExecutable -Arguments @(
        "--self-test", "--self-test-output", $selfTestPath
    ) -TimeoutSeconds 60)
    [void](Invoke-CheckedProcess -FilePath $diagExecutable -Arguments @(
        "--self-test"
    ) -TimeoutSeconds 30)
    if (-not (Test-Path -LiteralPath $selfTestPath -PathType Leaf)) {
        throw "桌面自检报告缺失。"
    }
    $selfTest = Read-JsonUtf8 -Path $selfTestPath
    if ([string]$selfTest.status -ne "pass" -or
        [string]$selfTest.product_version -ne "2.3.6.1") {
        throw "桌面自检报告产品版本不是 pass/2.3.6.1。"
    }

    $normalDesktop = Join-Path $fixtureRoot "normal\User\Desktop"
    $redirectedDesktop = Join-Path $fixtureRoot "redirected-OneDrive\User\OneDrive\桌面"
    Invoke-LifecycleFixture `
        -Name "normal" `
        -DesktopDirectory $normalDesktop `
        -SourcePackageRoot $packageRoot `
        -FixtureRoot $fixtureRoot `
        -EvidenceRoot $evidenceRoot
    Invoke-LifecycleFixture `
        -Name "redirected-OneDrive" `
        -DesktopDirectory $redirectedDesktop `
        -SourcePackageRoot $packageRoot `
        -FixtureRoot $fixtureRoot `
        -EvidenceRoot $evidenceRoot

    $evidenceFiles = @(Get-ChildItem -LiteralPath $evidenceRoot -Filter "*.json" -File)
    if ($evidenceFiles.Count -lt 11) {
        throw "生命周期证据数量不足：$($evidenceFiles.Count)"
    }

    Write-Host "PHASE2_WINDOWS_RELEASE_TEST=PASS"
    Write-Host "PHASE23_TASK_CENTER_PACKAGE_TEST=PASS"
    Write-Host "PHASE23_PRODUCT_VERSION_PACKAGE_TEST=PASS"
    Write-Host "PHASE2_WINDOWS_INSTALL_VERIFY_ROLLBACK=PASS"
    Write-Host "PRODUCT_VERSION=$($manifest.product_version)"
    Write-Host "PACKAGE=$($zip.FullName)"
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
