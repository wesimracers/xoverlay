param([Parameter(Mandatory=$true)][string]$Destination)
# Compatibility entry point; helper provisioning now belongs to OverlayApp.
& (Join-Path $PSScriptRoot 'UpdateOverlayProtection.ps1') -Destination $Destination
