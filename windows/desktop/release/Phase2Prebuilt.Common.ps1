# Phase 2 Windows 预编译包共享兼容逻辑；安装、验证和回滚必须共同使用。

function Get-Sha256Hex {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "SHA-256 文件不存在：$Path"
    }

    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha256.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes)).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Get-FileHash {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [ValidateSet("SHA256")][string]$Algorithm = "SHA256"
    )

    # 某些最小化 Windows PowerShell 5.1 进程不会自动导入 Microsoft.PowerShell.Utility；
    # 为发布包提供所需的 SHA-256 子集，避免用户安装依赖可选 Cmdlet 自动加载。
    return [pscustomobject][ordered]@{
        Algorithm = $Algorithm
        Hash      = Get-Sha256Hex -Path $LiteralPath
        Path      = [System.IO.Path]::GetFullPath($LiteralPath)
    }
}

function Resolve-PicotooDesktopDirectory {
    param([string]$DesktopDirectory = "")

    $resolved = $DesktopDirectory
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        $resolved = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::DesktopDirectory)
    }
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        throw "Windows 未返回当前用户 DesktopDirectory。"
    }

    $resolved = [System.IO.Path]::GetFullPath($resolved)
    New-Item -ItemType Directory -Path $resolved -Force | Out-Null
    return $resolved
}

function Get-PicotooShortcutPaths {
    param([string]$DesktopDirectory = "")

    $desktop = Resolve-PicotooDesktopDirectory -DesktopDirectory $DesktopDirectory
    return [pscustomobject][ordered]@{
        desktop    = Join-Path $desktop "Picotoo Pet AI.lnk"
        start_menu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Picotoo Pet AI.lnk"
        startup    = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Picotoo Pet AI.lnk"
    }
}

function Get-PicotooShortcutPathValues {
    param([Parameter(Mandatory)]$ShortcutPaths)

    return @(
        [string]$ShortcutPaths.desktop,
        [string]$ShortcutPaths.start_menu,
        [string]$ShortcutPaths.startup
    )
}

function Set-PicotooShortcuts {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [string]$DesktopDirectory = ""
    )

    $expectedExecutable = [System.IO.Path]::GetFullPath($Executable)
    if (-not (Test-Path -LiteralPath $expectedExecutable -PathType Leaf)) {
        throw "快捷方式目标不存在：$expectedExecutable"
    }

    $paths = Get-PicotooShortcutPaths -DesktopDirectory $DesktopDirectory
    $shell = New-Object -ComObject WScript.Shell
    try {
        foreach ($shortcutPath in Get-PicotooShortcutPathValues -ShortcutPaths $paths) {
            $shortcutDirectory = Split-Path -Parent $shortcutPath
            New-Item -ItemType Directory -Path $shortcutDirectory -Force | Out-Null
            $shortcut = $shell.CreateShortcut($shortcutPath)
            $shortcut.TargetPath       = $expectedExecutable
            $shortcut.WorkingDirectory = Split-Path -Parent $expectedExecutable
            $shortcut.IconLocation     = "$expectedExecutable,0"
            $shortcut.Description      = "Picotoo Pet V2 双机 AI 控制面板"
            $shortcut.Save()
        }
    }
    finally {
        if ($null -ne $shell -and [System.Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }

    return $paths
}

function Assert-PicotooShortcuts {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [string]$DesktopDirectory = ""
    )

    $expectedExecutable = [System.IO.Path]::GetFullPath($Executable)
    $paths = Get-PicotooShortcutPaths -DesktopDirectory $DesktopDirectory
    $shell = New-Object -ComObject WScript.Shell
    try {
        foreach ($shortcutPath in Get-PicotooShortcutPathValues -ShortcutPaths $paths) {
            if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
                throw "快捷方式缺失：$shortcutPath"
            }
            $shortcut = $shell.CreateShortcut($shortcutPath)
            if ([string]::IsNullOrWhiteSpace([string]$shortcut.TargetPath)) {
                throw "快捷方式目标为空：$shortcutPath"
            }
            $actualExecutable = [System.IO.Path]::GetFullPath([string]$shortcut.TargetPath)
            if (-not $actualExecutable.Equals(
                    $expectedExecutable,
                    [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "快捷方式目标不一致：$shortcutPath | $actualExecutable"
            }
        }
    }
    finally {
        if ($null -ne $shell -and [System.Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }

    return [pscustomobject][ordered]@{
        shortcuts_verified = $true
        shortcut_paths     = $paths
        target             = $expectedExecutable
    }
}

function Remove-PicotooShortcuts {
    param([string]$DesktopDirectory = "")

    $paths = Get-PicotooShortcutPaths -DesktopDirectory $DesktopDirectory
    foreach ($shortcutPath in Get-PicotooShortcutPathValues -ShortcutPaths $paths) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
    }
    return $paths
}
