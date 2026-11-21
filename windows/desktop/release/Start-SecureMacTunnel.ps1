# PicotooPet｜使用系统自带 OpenSSH 建立 Windows->Mac 私有加密通道。
# 仅准备控制通道；不接触设备 Token、Owner、Worker HMAC、GPU、模型或素材。
[CmdletBinding()]
param(
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-PicotooSshHost {
    param([string]$Value)

    # 只允许单个 IPv4/DNS 目标；拒绝 Shell 元字符、选项、URL、空白及跳板指令。
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value.Length -gt 253 -or
        $Value -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]*$' -or
        $Value.Contains('..')) {
        return $false
    }
    foreach ($label in ($Value -split '\.')) {
        if ($label.Length -eq 0 -or $label.Length -gt 63 -or $label.StartsWith('-') -or
            $label.EndsWith('-')) {
            return $false
        }
    }
    return $true
}

function Test-PicotooSshUser {
    param([string]$Value)

    # SSH 登录名严格限制，禁止 user@host、密码、换行和参数注入。
    return (-not [string]::IsNullOrWhiteSpace($Value) -and
        $Value.Length -le 64 -and $Value -match '^[A-Za-z_][A-Za-z0-9_.-]*$')
}

function New-PicotooSshArguments {
    param(
        [string]$MacHost,
        [string]$MacUser,
        [int]$MacPort,
        [int]$SshPort = 22
    )

    if (-not (Test-PicotooSshHost $MacHost) -or -not (Test-PicotooSshUser $MacUser) -or
        $MacPort -lt 1 -or $MacPort -gt 65535 -or
        $SshPort -lt 1 -or $SshPort -gt 65535) {
        throw "INVALID_SSH_TUNNEL_CONFIG"
    }

    # 无密码/新主机自动信任；严格使用现有 known_hosts 和 SSH 公钥身份。
    # -L 的两端都指向 127.0.0.1，拒绝将 Mac Core 开放给 Windows 局域网。
    return @(
        "-N", "-T",
        "-o", "BatchMode=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=7",
        "-o", "ServerAliveInterval=20",
        "-o", "ServerAliveCountMax=3",
        "-L", ("127.0.0.1:18766:127.0.0.1:{0}" -f $MacPort),
        "-p", [string]$SshPort,
        ("{0}@{1}" -f $MacUser, $MacHost)
    )
}

if ($SelfTest) {
    # 可在 Windows CI/PowerShell 5.1 直接验证，不启动 ssh、不下载、不连网。
    $a = New-PicotooSshArguments -MacHost "mac.example.test" -MacUser "mac_owner" -MacPort 8766
    # 直接校验 SSH 参数数组，避免 PowerShell 正则转义误报安全策略失败。
    foreach ($required in @(
        "StrictHostKeyChecking=yes", "BatchMode=yes",
        "PasswordAuthentication=no", "ExitOnForwardFailure=yes",
        "127.0.0.1:18766:127.0.0.1:8766"
    )) {
        if ($a -notcontains $required) { throw "SSH_TUNNEL_POLICY_TEST_FAILED" }
    }
    if ($a -contains "StrictHostKeyChecking=no") {
        throw "SSH_TUNNEL_POLICY_TEST_FAILED"
    }
    foreach ($bad in @("-ssh", "user@evil", "host/path", "host;echo", "a..b", "mac host")) {
        if (Test-PicotooSshHost $bad) { throw "SSH_TUNNEL_HOST_INJECTION_ALLOWED" }
    }
    if (Test-PicotooSshUser "owner@evil") { throw "SSH_TUNNEL_USER_INJECTION_ALLOWED" }
    Write-Host "SECURE_MAC_TUNNEL_SELFTEST=PASS_NO_NETWORK_NO_GPU"
    exit 0
}

# 首次只收集无秘密的 Mac 用户名、地址和 Core 端口；之后复用本地设置。
$dataRoot = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
$configFile = Join-Path $dataRoot "secure-mac-tunnel.json"
if (Test-Path -LiteralPath $configFile) {
    $config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
    $macHost = [string]$config.mac_host
    $macUser = [string]$config.mac_user
    $macPort = [int]$config.mac_port
    $sshPort = [int]$config.ssh_port
} else {
    $macHost = (Read-Host "Mac 的局域网 IP 或可信主机名").Trim()
    $macUser = (Read-Host "Mac 的系统用户名（非设备令牌）").Trim()
    $portText = (Read-Host "Mac Core 端口 [默认 8766]").Trim()
    $macPort = if ($portText) { [int]$portText } else { 8766 }
    $sshPort = 22
}
$argsList = New-PicotooSshArguments -MacHost $macHost -MacUser $macUser -MacPort $macPort -SshPort $sshPort

# 只使用 Windows 系统自带的 SSH 客户端，防止 PATH 中同名程序劫持。
$sshExe = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
if (-not (Test-Path -LiteralPath $sshExe -PathType Leaf)) {
    throw "未安装 Windows OpenSSH Client；请先在 Windows 可选功能中启用。"
}

# 本地端口如已被占用，拒绝把设备 Token 发给未知本地进程。
$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback, 18766)
try {
    $listener.Start()
} catch {
    throw "127.0.0.1:18766 已被占用，无法证明它是可信 SSH 隧道；拒绝接管。"
} finally {
    $listener.Stop()
}

# 不使用 cmd.exe / shell 插值；所有变量均经严格白名单验证。
$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName        = $sshExe
$info.Arguments       = $argsList -join " "
$info.UseShellExecute = $false
$info.CreateNoWindow  = $true
$process = [System.Diagnostics.Process]::Start($info)
if ($null -eq $process) { throw "OpenSSH 启动失败。" }

try {
    $ready = $false
    for ($index = 0; $index -lt 36; $index++) {
        if ($process.HasExited) { break }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:18766/api/v1/health" `
                -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            # 不能只凭任意 200/非空 status 就称已连到真实 2.3 Mac Core。
            # 在传入设备令牌之前，只读取公开的 loopback health 三项。
            $health = $response.Content | ConvertFrom-Json
            if ([int]$response.StatusCode -eq 200 -and
                [string]$health.status -eq 'ok' -and
                [string]$health.database -eq 'ok' -and
                [string]$health.version -match '^2\\.3\\.') {
                $ready = $true
                break
            }
        } catch {
            # SSH 握手未完成时重试；绝不回退到明文局域网 HTTP。
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) {
        throw "隧道未连通 Mac Core。请核查 Mac 的 Remote Login、SSH 公钥、known_hosts 与 Core 端口。"
    }

    # 只在成功看到隧道后的 Mac Health 时保存无秘密配置；不记录 SSH 密钥。
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    $public = [ordered]@{
        mac_host = $macHost
        mac_user = $macUser
        mac_port = $macPort
        ssh_port = $sshPort
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText(
        $configFile, $public, [System.Text.UTF8Encoding]::new($false))
    Write-Host "SECURE_MAC_TUNNEL=READY"
    Write-Host "Windows Studio 的 Mac Core 地址填写：http://127.0.0.1:18766"
    Write-Host "请保持已验证的 OpenSSH 后台进程运行；不自动授予 GPU。"
} catch {
    if (-not $process.HasExited) {
        try { $process.Kill() } catch { }
    }
    throw
} finally {
    $process.Dispose()
}
