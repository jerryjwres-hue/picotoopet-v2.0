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

function Get-PicotooTunnelShortcutPath {
    # Windows 系统开始菜单入口；绝不加入开机启动项，也不启动 SSH。
    # 固定 ASCII 文件名，兼容英文 Windows PowerShell 5.1 与旧 WScript COM 代码页。
    return Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Picotoo Pet Secure Connect.lnk"
}

function Set-PicotooTunnelShortcut {
    param([string]$VersionRoot = "")

    # 仅引用已验证 manifest SHA 的版本化 payload，不执行 SSH，也不读取证书/密钥。
    $path = Get-PicotooTunnelShortcutPath
    # 保存和核验均使用同一规范绝对路径，避免重复分隔符影响 VBS 参数比较。
    $connection = if ($VersionRoot) { [IO.Path]::GetFullPath((Join-Path $VersionRoot "tools\connection")) } else { "" }
    $launcher = if ($connection) { Join-Path $connection "CONNECT_MAC_SECURE.vbs" } else { "" }
    $bootstrap = if ($connection) { Join-Path $connection "Start-SecureMacTunnel.ps1" } else { "" }

    if (-not $launcher -or -not (Test-Path -LiteralPath $launcher -PathType Leaf) -or
        -not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        return
    }

    New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut                  = $shell.CreateShortcut($path)
        $shortcut.TargetPath       = Join-Path $env:WINDIR "System32\wscript.exe"
        $shortcut.Arguments        = '"' + $launcher + '"'
        $shortcut.WorkingDirectory = $connection
        $shortcut.Description      = "PicotooPet Mac SSH (manual secure connection)"
        $shortcut.Save()
    }
    finally {
        if ($null -ne $shell -and [Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }
}

function Assert-PicotooTunnelShortcut {
    param([Parameter(Mandatory)][string]$VersionRoot)

    # 离线只读比较当前启动器目标；拒绝错误旧版本或指向其他脚本。
    $path = Get-PicotooTunnelShortcutPath
    # 仅规范 Windows 路径拼写；不放宽 VBS 参数或允许额外命令行参数。
    $folder = [IO.Path]::GetFullPath((Join-Path $VersionRoot "tools\connection"))
    $launcher = Join-Path $folder "CONNECT_MAC_SECURE.vbs"
    $script = Join-Path $folder "Start-SecureMacTunnel.ps1"
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script -PathType Leaf) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "P0_VERSIONED_SSH_SHORTCUT_OR_PAYLOAD_MISSING"
    }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($path)
        $expectedExe = [IO.Path]::GetFullPath((Join-Path $env:WINDIR "System32\wscript.exe"))
        $expectedDir = [IO.Path]::GetFullPath($folder)
        $actualExe = [IO.Path]::GetFullPath([string]$shortcut.TargetPath)
        $actualDir = [IO.Path]::GetFullPath([string]$shortcut.WorkingDirectory)
        if (-not $actualExe.Equals($expectedExe, [StringComparison]::OrdinalIgnoreCase) -or
            -not $actualDir.Equals($expectedDir, [StringComparison]::OrdinalIgnoreCase) -or
            [string]$shortcut.Arguments -cne ('"' + $launcher + '"')) {
            # 仅报告各字段是否匹配，不输出可能被篡改的任意命令行内容。
            $exeMatches = $actualExe.Equals($expectedExe, [StringComparison]::OrdinalIgnoreCase)
            $dirMatches = $actualDir.Equals($expectedDir, [StringComparison]::OrdinalIgnoreCase)
            $argMatches = [string]$shortcut.Arguments -ceq ('"' + $launcher + '"')
            throw "P0_VERSIONED_SSH_SHORTCUT_WRONG_TARGET; exe_match=$exeMatches; dir_match=$dirMatches; arg_match=$argMatches"
        }
    }
    finally {
        if ($null -ne $shell -and [Runtime.InteropServices.Marshal]::IsComObject($shell)) {
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
        }
    }
    return $true
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


function Assert-PicotooP0HoldForActivation {
    # 影视预览启动 GUI 之前重检持久 HOLD，避免复制/升级期间被换成 ALLOW。
    # 不触碰核心身份、签名、设备令牌、Comfy 队列或任何 GPU 任务。
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw 'P0_ACTIVATION_HOLD_LOCALAPPDATA_MISSING'
    }
    $gateFile = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\MediaWorker\v1\three-shot-acceptance.json'
    $armedFile = $gateFile + '.armed'
    for ($folder = [IO.DirectoryInfo]::new((Split-Path -Parent $gateFile));
        $null -ne $folder; $folder = $folder.Parent) {
        if ($folder.Exists -and ($folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'P0_ACTIVATION_HOLD_REPARSE_DIRECTORY'
        }
    }
    if (-not (Test-Path -LiteralPath $gateFile -PathType Leaf) -or
        -not (Test-Path -LiteralPath $armedFile -PathType Leaf)) {
        throw 'P0_ACTIVATION_HOLD_FIRST_REQUIRED'
    }
    foreach ($file in @($gateFile, $armedFile)) {
        $attributes = (Get-Item -LiteralPath $file -Force).Attributes
        if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'P0_ACTIVATION_HOLD_REPARSE_FILE'
        }
    }
    try {
        $raw = [IO.File]::ReadAllText($gateFile, [Text.UTF8Encoding]::new($false, $true))
        $state = $raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'P0_ACTIVATION_HOLD_INVALID'
    }
    if ([string]$state.schema_version -cne '1.0' -or
        [string]$state.mode -cne 'hold' -or
        @($state.PSObject.Properties.Name).Count -ne 2 -or
        (Get-Item -LiteralPath $armedFile -Force).Length -lt 1) {
        throw 'P0_ACTIVATION_HOLD_NOT_ARMED'
    }
}
