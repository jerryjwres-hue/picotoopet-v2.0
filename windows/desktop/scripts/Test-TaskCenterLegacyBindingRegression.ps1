# 在真实 WPF 页面中临时恢复历史绑定，证明旧代码会抛出只读属性 InvalidOperationException。
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$desktopRoot  = Split-Path -Parent $PSScriptRoot
$xamlPath     = Join-Path $desktopRoot "src\PicotooPet.Desktop\Views\Pages\TaskCenterPage.xaml"
$smokeProject = Join-Path $desktopRoot "tests\PicotooPet.Desktop.Core.SmokeTests\PicotooPet.Desktop.Core.SmokeTests.csproj"
$dotnet       = (Get-Command "dotnet.exe" -ErrorAction Stop).Source
$original     = [System.IO.File]::ReadAllBytes($xamlPath)
$originalHash = (Get-FileHash -LiteralPath $xamlPath -Algorithm SHA256).Hash
$encoding     = [System.Text.UTF8Encoding]::new($false, $true)

try {
    $fixedXaml = $encoding.GetString($original)
    $legacyXaml = $fixedXaml.Replace(
        'Text="{Binding Priority, Mode=OneWay}"',
        'Text="{Binding Priority}"').Replace(
        'Text="{Binding TimeoutSeconds, Mode=OneWay}"',
        'Text="{Binding TimeoutSeconds}"')
    if ($legacyXaml -eq $fixedXaml) {
        throw "未找到两处已修复的 Task Center Run.Text 绑定。"
    }
    if ($legacyXaml.Contains('Text="{Binding Priority, Mode=OneWay}"') -or
        $legacyXaml.Contains('Text="{Binding TimeoutSeconds, Mode=OneWay}"')) {
        throw "历史绑定变异不完整。"
    }

    [System.IO.File]::WriteAllText(
        $xamlPath,
        $legacyXaml,
        [System.Text.UTF8Encoding]::new($false))

    & $dotnet build $smokeProject `
        --configuration Release `
        --nologo `
        -p:ContinuousIntegrationBuild=true
    if ($LASTEXITCODE -ne 0) {
        throw "历史绑定 WPF smoke 构建失败，退出码 $LASTEXITCODE。"
    }

    $output = & $dotnet run `
        --project $smokeProject `
        --configuration Release `
        --no-build `
        -- `
        --expect-task-center-legacy-binding-failure 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "历史绑定异常见证失败，退出码 $exitCode。"
    }
    if (($output -join "`n") -notmatch "PHASE23_TASK_CENTER_LEGACY_BINDING_RED=PASS") {
        throw "历史绑定异常见证没有输出 PASS 标记。"
    }
}
finally {
    [System.IO.File]::WriteAllBytes($xamlPath, $original)
}

$restoredHash = (Get-FileHash -LiteralPath $xamlPath -Algorithm SHA256).Hash
if ($restoredHash -ne $originalHash) {
    throw "TaskCenterPage.xaml 在异常见证后未恢复原始内容。"
}

& $dotnet clean $smokeProject --configuration Release --nologo | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "历史绑定异常见证后的清理失败，退出码 $LASTEXITCODE。"
}

Write-Host "PHASE23_TASK_CENTER_LEGACY_BINDING_RED=PASS"
