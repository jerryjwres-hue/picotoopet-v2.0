#Requires -Version 5.1
<#
.SYNOPSIS
    PicotooPet P0 #237: Windows OpenSSH READ-ONLY, offline prerequisites.
.DESCRIPTION
    No network, SSH login, process launches except ssh.exe -V, key generation,
    secret/credential reads, filesystem writes or privilege changes.
    Run on the user's Windows machine ONLY with explicit device-check approval.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Emit-Check {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][string] $Value
    )
    Write-Output ('{0}={1}' -f $Name, $Value)
}

Emit-Check 'CHECK_SCHEMA' 'owner_ssh_readonly_preflight.v1'
Emit-Check 'DEVICE_ROLE' 'WINDOWS'
Emit-Check 'DEVICE_ACTIONS' 'READ_ONLY_NO_NETWORK_NO_SUDO'

# Explicit system path; never execute an ssh.exe found through untrusted PATH.
if ([string]::IsNullOrWhiteSpace($env:WINDIR)) {
    Emit-Check 'WIN_SYSTEM_OPENSSH' 'UNVERIFIED_WINDOWS_DIRECTORY'
}
else {
    $sshPath = Join-Path -Path $env:WINDIR -ChildPath 'System32\OpenSSH\ssh.exe'
    if (-not (Test-Path -LiteralPath $sshPath -PathType Leaf)) {
        Emit-Check 'WIN_SYSTEM_OPENSSH' 'MISSING'
    }
    else {
        $sshItem = Get-Item -LiteralPath $sshPath -Force
        if (($sshItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Emit-Check 'WIN_SYSTEM_OPENSSH' 'BLOCKED_REPARSE_POINT'
        }
        else {
            Emit-Check 'WIN_SYSTEM_OPENSSH' 'PRESENT'
            try {
                # -V only prints the version and never attempts an SSH connection.
                $versionOutput = (& $sshPath -V 2>&1 | Out-String).Trim()
                if ($versionOutput -match '^OpenSSH') {
                    Emit-Check 'WIN_SYSTEM_OPENSSH_VERSION' (
                        ($versionOutput -split '[\r\n]')[0] -replace '[^A-Za-z0-9_. -]', '_'
                    )
                }
                else {
                    Emit-Check 'WIN_SYSTEM_OPENSSH_VERSION' 'UNVERIFIED'
                }
            }
            catch {
                Emit-Check 'WIN_SYSTEM_OPENSSH_VERSION' 'UNVERIFIED_EXECUTION_ERROR'
            }
        }
    }
}

# These require an operator-verified Mac fingerprint and separate protected SSH identity.
# Their absence must NOT cause code to generate keys, probe ports or disable auth.
Emit-Check 'WIN_MAC_HOST_FINGERPRINT' 'NOT_CHECKED_NEEDS_MAC_OUT_OF_BAND_CONFIRMATION'
Emit-Check 'WIN_SSH_IDENTITY_PROVISIONING' 'NOT_CHECKED_NO_SECRET_ACCESS'
Emit-Check 'WIN_SSH_AUTHENTICATED_HANDSHAKE' 'NOT_PERFORMED'
Emit-Check 'WIN_OWNER_REVIEW_LIVE_READY' 'BLOCKED'
