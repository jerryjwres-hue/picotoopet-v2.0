[CmdletBinding()]
param([string]$PackageRoot)
if ([string]::IsNullOrWhiteSpace($PackageRoot)) { exit 21 }
if (-not (Test-Path -LiteralPath $PackageRoot)) { exit 22 }
exit 0
