#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ManifestPath = (Join-Path $PSScriptRoot 'model_manifest.json'),
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference            = 'Stop'
$env:HF_XET_HIGH_PERFORMANCE      = '1'
$env:HF_HUB_DOWNLOAD_TIMEOUT      = '600'
$env:HF_HUB_ETAG_TIMEOUT          = '30'
$env:HF_HUB_DISABLE_UPDATE_CHECK  = '1'

function Ensure-Uv {
    $uv = Get-Command uvx.exe -ErrorAction SilentlyContinue
    if ($null -ne $uv) {
        return $uv.Source
    }

    # uv 仅在正式安装模式缺失时安装；验证模式绝不改变系统环境。
    $installer = Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing
    Invoke-Expression $installer
    $candidate = Join-Path $env:USERPROFILE '.local\bin\uvx.exe'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw 'uvx 安装失败，无法继续模型下载。'
    }
    return $candidate
}

function Get-VerifiedHash {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}


function Invoke-HfDownload {
    param(
        [Parameter(Mandatory = $true)][string]$UvxPath,
        [Parameter(Mandatory = $true)][string]$HfTool,
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$Revision,
        [Parameter(Mandatory = $true)][string]$LocalDirectory,
        [Parameter(Mandatory = $true)][string]$DownloadLog
    )

    $stdoutLog = $DownloadLog + '.stdout.tmp'
    $stderrLog = $DownloadLog + '.stderr.tmp'
    $arguments = @(
        '--from', $HfTool,
        'hf', 'download',
        $Repository,
        $SourcePath,
        '--revision', $Revision,
        '--local-dir', $LocalDirectory
    )

    try {
        # Windows PowerShell 5.1 会把 uvx 的正常 stderr 提示包装成 NativeCommandError。
        # 使用 Start-Process 分离 stdout/stderr，只根据真实进程退出码判断成败。
        $process = Start-Process `
            -FilePath $UvxPath `
            -ArgumentList $arguments `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog

        $logParts = New-Object System.Collections.Generic.List[string]
        if (Test-Path -LiteralPath $stdoutLog -PathType Leaf) {
            $stdoutText = Get-Content -LiteralPath $stdoutLog -Raw -ErrorAction SilentlyContinue
            if (-not [string]::IsNullOrWhiteSpace($stdoutText)) {
                $logParts.Add($stdoutText.TrimEnd())
            }
        }
        if (Test-Path -LiteralPath $stderrLog -PathType Leaf) {
            $stderrText = Get-Content -LiteralPath $stderrLog -Raw -ErrorAction SilentlyContinue
            if (-not [string]::IsNullOrWhiteSpace($stderrText)) {
                $logParts.Add($stderrText.TrimEnd())
            }
        }

        ($logParts -join [Environment]::NewLine) | Set-Content -LiteralPath $DownloadLog -Encoding UTF8
        return [int]$process.ExitCode
    }
    finally {
        Remove-Item -LiteralPath $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue
    }
}

$manifest       = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$modelRoot      = [string]$manifest.model_root
$cacheRoot      = [string]$manifest.cache_root
$QuarantineRoot = [string]$manifest.quarantine_root
$hfCliVersion = if ($manifest.PSObject.Properties.Name -contains 'hf_cli_version') {
    [string]$manifest.hf_cli_version
}
else {
    # 兼容 HOTFIX3 及更早清单；旧字段中的版本值同样对应官方 hf CLI。
    [string]$manifest.huggingface_hub_version
}
$hfTool         = 'hf=={0}' -f $hfCliVersion
$uvx            = $null
$results        = New-Object System.Collections.Generic.List[object]

if (-not $VerifyOnly) {
    # 正式安装才创建目录；VerifyOnly 必须保持模型盘完全只读。
    New-Item -ItemType Directory -Path $modelRoot      -Force | Out-Null
    New-Item -ItemType Directory -Path $cacheRoot      -Force | Out-Null
    New-Item -ItemType Directory -Path $QuarantineRoot -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $cacheRoot 'download-logs') -Force | Out-Null
}

foreach ($model in $manifest.models) {
    $expectedHash         = ([string]$model.sha256).ToLowerInvariant()
    $destinationDirectory = Join-Path $modelRoot ([string]$model.destination)
    $destinationFile      = Join-Path $destinationDirectory ([string]$model.filename)

    if (Test-Path -LiteralPath $destinationFile -PathType Leaf) {
        $existingHash = Get-VerifiedHash -Path $destinationFile
        if ($existingHash -eq $expectedHash) {
            $results.Add([ordered]@{
                File   = [string]$model.filename
                Status = 'already_verified'
                Path   = $destinationFile
                Sha256 = $existingHash
            })
            continue
        }

        if ($VerifyOnly) {
            # 只读验证只报告错误哈希，不隔离、不覆盖、不创建任何目录。
            $results.Add([ordered]@{
                File           = [string]$model.filename
                Status         = 'hash_mismatch'
                Path           = $destinationFile
                ExpectedSha256 = $expectedHash
                ActualSha256   = $existingHash
            })
            continue
        }

        $quarantineName = '{0}.{1}.bad' -f $model.filename, (Get-Date -Format 'yyyyMMdd-HHmmss')
        $quarantineFile = Join-Path $QuarantineRoot $quarantineName
        Move-Item -LiteralPath $destinationFile -Destination $quarantineFile -Force
    }

    if ($VerifyOnly) {
        $results.Add([ordered]@{
            File   = [string]$model.filename
            Status = 'missing'
            Path   = $destinationFile
        })
        continue
    }

    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    if ($null -eq $uvx) {
        $uvx = Ensure-Uv
    }

    # 每个模型使用稳定暂存目录；下载中断时保留 Hub 元数据和分片以便续传。
    $stagingName      = 'staging-' + [IO.Path]::GetFileNameWithoutExtension([string]$model.filename)
    $stagingRoot      = Join-Path $cacheRoot $stagingName
    $downloadComplete = $false
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

    try {
        $downloadLog = Join-Path (Join-Path $cacheRoot 'download-logs') `
            ('{0}-{1}.log' -f [IO.Path]::GetFileNameWithoutExtension([string]$model.filename), (Get-Date -Format 'yyyyMMdd-HHmmss'))

        # 当前 Hugging Face CLI 由独立的 hf 包提供；固定版本并完整保存原生下载器输出。
        $downloadExitCode = Invoke-HfDownload `
            -UvxPath $uvx `
            -HfTool $hfTool `
            -Repository ([string]$model.repository) `
            -SourcePath ([string]$model.source_path) `
            -Revision ([string]$model.revision) `
            -LocalDirectory $stagingRoot `
            -DownloadLog $downloadLog

        if ($downloadExitCode -ne 0) {
            $downloadTail = @(Get-Content -LiteralPath $downloadLog -Tail 30 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            throw ("模型下载失败：{0}`n下载器退出码：{1}`n详情日志：{2}`n{3}" -f `
                [string]$model.filename, $downloadExitCode, $downloadLog, $downloadTail)
        }

        $relativeSource = ([string]$model.source_path).Replace('/', '\')
        $stagedFile     = Join-Path $stagingRoot $relativeSource
        if (-not (Test-Path -LiteralPath $stagedFile -PathType Leaf)) {
            throw "下载完成但未找到暂存文件：$stagedFile"
        }

        $actualHash = Get-VerifiedHash -Path $stagedFile
        if ($actualHash -ne $expectedHash) {
            $badName = '{0}.{1}.hash-mismatch' -f $model.filename, (Get-Date -Format 'yyyyMMdd-HHmmss')
            Move-Item -LiteralPath $stagedFile -Destination (Join-Path $QuarantineRoot $badName) -Force
            Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
            throw "SHA-256 不匹配：$($model.filename)"
        }

        # 暂存目录和正式模型目录都在 E 盘，Move-Item 在同卷内完成原子放置。
        Move-Item -LiteralPath $stagedFile -Destination $destinationFile -Force
        $downloadComplete = $true
        $results.Add([ordered]@{
            File   = [string]$model.filename
            Status = 'installed_verified'
            Path   = $destinationFile
            Sha256 = $actualHash
        })
    }
    finally {
        # 只有完整安装成功才清理暂存目录；失败时保留断点续传资料。
        if ($downloadComplete) {
            Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$results
