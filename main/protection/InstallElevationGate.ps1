param([string]$ExpectedHelperHash, [switch]$Uninstall, [switch]$AllowLiveProvisioning)
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$gateGames = 'iRacingSim64DX11','Le Mans Ultimate','acs','acs_x86','AssettoCorsaEVO'
if ($Uninstall -or -not $AllowLiveProvisioning) {
    if (Get-Process -Name $gateGames -ErrorAction SilentlyContinue) { throw 'Close all games before provisioning the global elevation gate.' }
    if (Get-Process -Name OverlayApp,OverlayRaceGuard -ErrorAction SilentlyContinue) { throw 'Close all Overlay Managers and guards before provisioning the elevation gate.' }
}
# Explicit live provisioning only installs the inactive recovery service. Appinfo is untouched.
$gateInstall = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'OverlayElevationGate'
$gateState = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'OverlayElevationGate'
$gateSc = Join-Path ([Environment]::GetFolderPath('System')) 'sc.exe'
if ($Uninstall) {
    $gateService = Get-CimInstance Win32_Service -Filter "Name='OverlayElevationGate'"
    if (-not $gateService) { throw 'Elevation gate service is not installed.' }
    $gateExpectedPath = '"' + (Join-Path $gateInstall 'OverlayElevationGate.exe') + '"'
    if ($gateService.PathName -ne $gateExpectedPath -or $gateService.StartName -ne 'LocalSystem') { throw 'Unexpected service configuration; removal refused.' }
    # Recovery runs with the installed SYSTEM service, never through a new Appinfo elevation.
    Start-Service OverlayElevationGate
    $gateDeadline = [DateTime]::UtcNow.AddSeconds(20)
    while ((Test-Path -LiteralPath (Join-Path $gateState 'journal.json')) -and [DateTime]::UtcNow -lt $gateDeadline) { Start-Sleep -Milliseconds 250 }
    if (Test-Path -LiteralPath (Join-Path $gateState 'journal.json')) { throw 'Appinfo recovery is pending; service and recovery files retained.' }
    Stop-Service OverlayElevationGate
    & $gateSc delete OverlayElevationGate | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Service removal failed; files retained.' }
    Write-Output 'Elevation gate service removed. Code and audit files retained for review.'
    return
}
if (Get-Service OverlayElevationGate -ErrorAction SilentlyContinue) { throw 'Service already exists; review and remove the previous installation first.' }
if ((Test-Path -LiteralPath $gateInstall) -or (Test-Path -LiteralPath $gateState)) { throw 'Installation/state directory already exists; no existing code or journal will be overwritten.' }
$gateSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$gateUsers = @(Get-LocalUser | Where-Object { $_.SID.Value -eq $gateSid -and $_.Enabled })
if ($gateUsers.Count -ne 1) { throw 'The current local Windows account was not confirmed. Use integrated setup for other profile types.' }
function Set-GateDirectoryAcl([string]$Path, [string]$WritableSid = '') {
    $gateAcl = [Security.AccessControl.DirectorySecurity]::new()
    $gateAcl.SetAccessRuleProtection($true,$false)
    $gateAcl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach ($gateSid in 'S-1-5-18','S-1-5-32-544') {
        $gateAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($gateSid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    foreach ($gateSid in $gateUsers.SID.Value) {
        if (-not $WritableSid -or $WritableSid -eq $gateSid) {
            $gateRights = if ($WritableSid -eq $gateSid) { 'Modify' } else { 'ReadAndExecute' }
            $gateAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($gateSid),$gateRights,'ContainerInherit,ObjectInherit','None','Allow'))
        }
    }
    Set-Acl -LiteralPath $Path -AclObject $gateAcl
}
New-Item -ItemType Directory -Path $gateInstall,$gateState | Out-Null
Set-GateDirectoryAcl $gateInstall
Set-GateDirectoryAcl $gateState
$gateSource = Join-Path $PSScriptRoot 'bin\OverlayElevationGate.exe'
$gateExe = Join-Path $gateInstall 'OverlayElevationGate.exe'
if (-not $ExpectedHelperHash -or (Get-FileHash -LiteralPath $gateSource -Algorithm SHA256).Hash -ne $ExpectedHelperHash) { throw 'Package helper hash was not confirmed.' }
Copy-Item -LiteralPath $gateSource -Destination $gateExe
if ((Get-FileHash -LiteralPath $gateExe -Algorithm SHA256).Hash -ne $ExpectedHelperHash) { throw 'Protected helper hash was not confirmed.' }
$gateLeases = Join-Path $gateState 'leases'
New-Item -ItemType Directory -Path $gateLeases | Out-Null
Set-GateDirectoryAcl $gateLeases
foreach ($gateUser in $gateUsers) {
    $gateLease = Join-Path $gateLeases $gateUser.SID.Value
    New-Item -ItemType Directory -Path $gateLease | Out-Null
    Set-GateDirectoryAcl $gateLease $gateUser.SID.Value
}
[IO.File]::WriteAllText((Join-Path $gateState 'authorized-sids.json'),(ConvertTo-Json -InputObject @($gateUsers.SID.Value)),[Text.UTF8Encoding]::new($false))
New-Service -Name OverlayElevationGate -BinaryPathName ('"'+$gateExe+'"') -StartupType Automatic -DisplayName 'OverlayApp - recoverable global elevation gate' | Out-Null
$gatePermissions = ($gateUsers | ForEach-Object { '(A;;CCLCRP;;;'+$_.SID.Value+')' }) -join ''
$gateSddl = 'D:(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)'+$gatePermissions
& $gateSc sdset OverlayElevationGate $gateSddl | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Service start/query permissions were not confirmed.' }
& $gateSc failure OverlayElevationGate reset= 86400 actions= restart/1000/restart/5000/restart/10000 | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Independent service restart recovery was not configured.' }
& $gateSc failureflag OverlayElevationGate 1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Service failure recovery flag was not configured.' }
Write-Output 'Experimental gate provisioned for the current local account; Appinfo has not been modified. The recovery service starts automatically at boot. Runtime coverage remains unvalidated.'
