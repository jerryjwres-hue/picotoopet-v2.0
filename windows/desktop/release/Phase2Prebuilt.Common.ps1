# Phase 2 Windows 预编译包共享兼容逻辑；安装、验证和回滚必须共同使用。

$script:PicotooManagedShortcutPattern = '^Picotoo Pet AI(?: [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)?\.lnk$'
$script:PicotooProductVersionPattern = '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'

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

function Assert-PicotooProductVersion {
    param([Parameter(Mandatory)][string]$ProductVersion)

    $value = $ProductVersion.Trim()
    if ($value -notmatch $script:PicotooProductVersionPattern) {
        throw "产品版本必须是四段数字：$ProductVersion"
    }
    return $value
}

function Get-PicotooManagedShortcutLocations {
    param([string]$DesktopDirectory = "")

    $desktop = Resolve-PicotooDesktopDirectory -DesktopDirectory $DesktopDirectory
    $locations = @(
        [pscustomobject][ordered]@{
            location  = "desktop"
            directory = $desktop
        },
        [pscustomobject][ordered]@{
            location  = "start_menu"
            directory = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
        },
        [pscustomobject][ordered]@{
            location  = "startup"
            directory = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
        }
    )
    foreach ($location in $locations) {
        New-Item -ItemType Directory -Path ([string]$location.directory) -Force | Out-Null
    }
    return $locations
}

function Get-PicotooManagedShortcutName {
    param([Parameter(Mandatory)][string]$ProductVersion)

    $normalized = Assert-PicotooProductVersion -ProductVersion $ProductVersion
    return "Picotoo Pet AI $normalized.lnk"
}

function Get-PicotooShortcutPaths {
    param(
        [Parameter(Mandatory)][string]$ProductVersion,
        [string]$DesktopDirectory = ""
    )

    $name = Get-PicotooManagedShortcutName -ProductVersion $ProductVersion
    $locations = @(Get-PicotooManagedShortcutLocations -DesktopDirectory $DesktopDirectory)
    $paths = [ordered]@{}
    foreach ($location in $locations) {
        $paths[[string]$location.location] = Join-Path ([string]$location.directory) $name
    }
    return [pscustomobject]$paths
}

function Get-PicotooShortcutPathValues {
    param([Parameter(Mandatory)]$ShortcutPaths)

    return @(
        [string]$ShortcutPaths.desktop,
        [string]$ShortcutPaths.start_menu,
        [string]$ShortcutPaths.startup
    )
}

function Get-PicotooManagedShortcutFiles {
    param([string]$DesktopDirectory = "")

    $results = @()
    foreach ($location in @(Get-PicotooManagedShortcutLocations -DesktopDirectory $DesktopDirectory)) {
        $files = @(Get-ChildItem -LiteralPath ([string]$location.directory) -Filter "*.lnk" -File -ErrorAction SilentlyContinue)
        foreach ($file in $files) {
            if ($file.Name -match $script:PicotooManagedShortcutPattern) {
                $results += [pscustomobject][ordered]@{
                    location = [string]$location.location
                    file     = $file
                }
            }
        }
    }
    return $results
}

function Get-PicotooManagedShortcutSnapshot {
    param([string]$DesktopDirectory = "")

    $shell = New-Object -ComObject WScript.Shell
    $entries = @()
    try {
        foreach ($managed in @(Get-PicotooManagedShortcutFiles -DesktopDirectory $DesktopDirectory)) {
            $file = $managed.file
            $shortcut = $shell.CreateShortcut($file.FullName)
            $entries += [pscustomobject][ordered]@{
                location          = [string]$managed.location
                name              = [string]$file.Name
                path              = [string]$file.FullName
                target_path       = [string]$shortcut.TargetPath
                arguments         = [string]$shortcut.Arguments
                working_directory = [string]$shortcut.WorkingDirectory
                icon_location     = [string]$shortcut.IconLocation
                description       = [string]$shortcut.Description
            }
        }
    }
    finally {
        if ($null -ne $shell -and [System.Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }
    return @($entries | Sort-Object location, name)
}

function Remove-PicotooManagedShortcuts {
    param([string]$DesktopDirectory = "")

    $removed = @()
    foreach ($managed in @(Get-PicotooManagedShortcutFiles -DesktopDirectory $DesktopDirectory)) {
        $removed += [string]$managed.file.FullName
        Remove-Item -LiteralPath ([string]$managed.file.FullName) -Force
    }
    return @($removed)
}

function Restore-PicotooManagedShortcutSnapshot {
    param(
        [Parameter(Mandatory)]$ShortcutState,
        [string]$DesktopDirectory = ""
    )

    $locations = @{}
    foreach ($location in @(Get-PicotooManagedShortcutLocations -DesktopDirectory $DesktopDirectory)) {
        $locations[[string]$location.location] = [string]$location.directory
    }

    [void](Remove-PicotooManagedShortcuts -DesktopDirectory $DesktopDirectory)
    $shell = New-Object -ComObject WScript.Shell
    try {
        foreach ($entry in @($ShortcutState)) {
            $locationName = [string]$entry.location
            $name = [string]$entry.name
            if (-not $locations.ContainsKey($locationName)) {
                throw "快捷方式快照包含未知位置：$locationName"
            }
            if ($name -notmatch $script:PicotooManagedShortcutPattern) {
                throw "快捷方式快照包含非受管名称：$name"
            }
            $targetPath = [string]$entry.target_path
            if ([string]::IsNullOrWhiteSpace($targetPath) -or
                -not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
                throw "快捷方式快照目标不存在：$targetPath"
            }
            $path = Join-Path $locations[$locationName] $name
            $shortcut = $shell.CreateShortcut($path)
            $shortcut.TargetPath       = [System.IO.Path]::GetFullPath($targetPath)
            $shortcut.Arguments        = [string]$entry.arguments
            $shortcut.WorkingDirectory = [string]$entry.working_directory
            $shortcut.IconLocation     = [string]$entry.icon_location
            $shortcut.Description      = [string]$entry.description
            $shortcut.Save()
        }
    }
    finally {
        if ($null -ne $shell -and [System.Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }

    return @(Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory)
}

function Set-PicotooShortcuts {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$ProductVersion,
        [string]$DesktopDirectory = ""
    )

    $expectedExecutable = [System.IO.Path]::GetFullPath($Executable)
    if (-not (Test-Path -LiteralPath $expectedExecutable -PathType Leaf)) {
        throw "快捷方式目标不存在：$expectedExecutable"
    }

    $normalizedVersion = Assert-PicotooProductVersion -ProductVersion $ProductVersion
    $shortcutName = "Picotoo Pet AI $ProductVersion.lnk"
    if ($shortcutName -ne (Get-PicotooManagedShortcutName -ProductVersion $normalizedVersion)) {
        throw "快捷方式名称版本未规范化：$shortcutName"
    }
    [void](Remove-PicotooManagedShortcuts -DesktopDirectory $DesktopDirectory)
    $paths = Get-PicotooShortcutPaths `
        -ProductVersion $normalizedVersion `
        -DesktopDirectory $DesktopDirectory
    $shell = New-Object -ComObject WScript.Shell
    try {
        foreach ($shortcutPath in Get-PicotooShortcutPathValues -ShortcutPaths $paths) {
            $shortcutDirectory = Split-Path -Parent $shortcutPath
            New-Item -ItemType Directory -Path $shortcutDirectory -Force | Out-Null
            $shortcut = $shell.CreateShortcut($shortcutPath)
            $shortcut.TargetPath       = $expectedExecutable
            $shortcut.Arguments        = ""
            $shortcut.WorkingDirectory = Split-Path -Parent $expectedExecutable
            $shortcut.IconLocation     = "$expectedExecutable,0"
            $shortcut.Description      = "Picotoo Pet AI $normalizedVersion 双机 AI 控制面板"
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
        [Parameter(Mandatory)][string]$ProductVersion,
        [string]$DesktopDirectory = "",
        [switch]$RequireNoLegacy
    )

    $expectedExecutable = [System.IO.Path]::GetFullPath($Executable)
    $normalizedVersion = Assert-PicotooProductVersion -ProductVersion $ProductVersion
    $expectedName = Get-PicotooManagedShortcutName -ProductVersion $normalizedVersion
    $paths = Get-PicotooShortcutPaths `
        -ProductVersion $normalizedVersion `
        -DesktopDirectory $DesktopDirectory
    $shell = New-Object -ComObject WScript.Shell
    $counts = [ordered]@{}
    try {
        foreach ($location in @(Get-PicotooManagedShortcutLocations -DesktopDirectory $DesktopDirectory)) {
            $managed = @(Get-ChildItem -LiteralPath ([string]$location.directory) -Filter "*.lnk" -File -ErrorAction SilentlyContinue | Where-Object {
                $_.Name -match $script:PicotooManagedShortcutPattern
            })
            $expectedPath = Join-Path ([string]$location.directory) $expectedName
            if (-not (Test-Path -LiteralPath $expectedPath -PathType Leaf)) {
                throw "快捷方式缺失：$expectedPath"
            }
            if ($RequireNoLegacy -and ($managed.Count -ne 1 -or $managed[0].Name -ne $expectedName)) {
                throw "受管快捷方式不是唯一当前版本：$($location.location) | $($managed.Name -join ', ')"
            }
            $shortcut = $shell.CreateShortcut($expectedPath)
            if ([string]::IsNullOrWhiteSpace([string]$shortcut.TargetPath)) {
                throw "快捷方式目标为空：$expectedPath"
            }
            $actualExecutable = [System.IO.Path]::GetFullPath([string]$shortcut.TargetPath)
            if (-not $actualExecutable.Equals(
                    $expectedExecutable,
                    [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "快捷方式目标不一致：$expectedPath | $actualExecutable"
            }
            $counts[[string]$location.location] = $managed.Count
        }
    }
    finally {
        if ($null -ne $shell -and [System.Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }

    return [pscustomobject][ordered]@{
        shortcuts_verified = $true
        product_version    = $normalizedVersion
        shortcut_paths     = $paths
        managed_counts     = [pscustomobject]$counts
        target             = $expectedExecutable
        shortcut_state     = @(Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory)
    }
}

function Remove-PicotooShortcuts {
    param([string]$DesktopDirectory = "")

    return @(Remove-PicotooManagedShortcuts -DesktopDirectory $DesktopDirectory)
}
