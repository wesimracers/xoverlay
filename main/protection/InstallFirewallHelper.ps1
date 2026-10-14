param([switch]$PermitRunningGame, [string]$ExpectedHelperHash)
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$raceGames = 'iRacingSim64DX11','Le Mans Ultimate','acs','acs_x86','AssettoCorsaEVO'
if (-not $PermitRunningGame -and (Get-Process -Name $raceGames -ErrorAction SilentlyContinue)) { throw 'Game running: installation requires explicit PermitRunningGame authorization.' }
if (Get-Service -Name OverlayRaceFirewall -ErrorAction SilentlyContinue) { throw 'Service already installed. Review/remove the previous installation before updating.' }
$raceInstall = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'OverlayAppFirewall'
$raceState = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'OverlayAppFirewall'
if ((Test-Path -LiteralPath $raceInstall) -or (Test-Path -LiteralPath $raceState)) { throw 'Directory already exists: review before installing; no code will run from that directory.' }
$raceSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$raceUsers = @(Get-LocalUser | Where-Object { $_.SID.Value -eq $raceSid -and $_.Enabled })
if ($raceUsers.Count -ne 1) { throw 'The current local Windows account was not confirmed. Use integrated setup for other profile types.' }
$raceProfiles = foreach ($raceUser in $raceUsers) {
    $raceProfile = Get-CimInstance Win32_UserProfile | Where-Object { $_.SID -eq $raceUser.SID.Value }
    if (-not $raceProfile.LocalPath -or -not (Test-Path -LiteralPath $raceProfile.LocalPath)) { throw "Profile not found: $($raceUser.Name)" }
    [pscustomobject]@{ Name=$raceUser.Name; SID=$raceUser.SID.Value; Profile=$raceProfile.LocalPath }
}
function Set-RaceDirectoryAcl([string]$Path, [string]$UserSid = '') {
    $raceAcl = [Security.AccessControl.DirectorySecurity]::new()
    $raceAcl.SetAccessRuleProtection($true,$false)
    $raceAcl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach ($raceSid in 'S-1-5-18','S-1-5-32-544') {
        $raceAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($raceSid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    foreach ($raceSid in $raceUsers.SID.Value) {
        $raceRights = if ($UserSid -eq $raceSid) { 'Modify' } else { 'ReadAndExecute' }
        if (-not $UserSid -or $UserSid -eq $raceSid) {
            $raceAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($raceSid),$raceRights,'ContainerInherit,ObjectInherit','None','Allow'))
        }
    }
    Set-Acl -LiteralPath $Path -AclObject $raceAcl
}
New-Item -ItemType Directory -Path $raceInstall,$raceState | Out-Null
Set-RaceDirectoryAcl $raceInstall
Set-RaceDirectoryAcl $raceState
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'bin\OverlayRaceFirewall.exe'),(Join-Path $PSScriptRoot 'FirewallProfiles.ps1') -Destination $raceInstall
if (-not $ExpectedHelperHash -or (Get-FileHash -LiteralPath (Join-Path $raceInstall 'OverlayRaceFirewall.exe') -Algorithm SHA256).Hash -ne $ExpectedHelperHash) {
    throw 'Protected helper hash not confirmed; service will not be registered.'
}
$raceLeases = Join-Path $raceState 'leases'
New-Item -ItemType Directory -Path $raceLeases | Out-Null
Set-RaceDirectoryAcl $raceLeases
foreach ($raceUser in $raceUsers) {
    $raceLease = Join-Path $raceLeases $raceUser.SID.Value
    New-Item -ItemType Directory -Path $raceLease | Out-Null
    Set-RaceDirectoryAcl $raceLease $raceUser.SID.Value
}
[IO.File]::WriteAllText((Join-Path $raceState 'authorized-profiles.json'),($raceProfiles | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
$raceExe = Join-Path $raceInstall 'OverlayRaceFirewall.exe'
New-Service -Name OverlayRaceFirewall -BinaryPathName ('"'+$raceExe+'"') -StartupType Manual -DisplayName 'OverlayApp - temporary race notifications' | Out-Null
$raceUserPermissions = ($raceUsers | ForEach-Object { '(A;;LCRP;;;'+$_.SID.Value+')' }) -join ''
$raceSddl = 'D:(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)'+$raceUserPermissions
& (Join-Path ([Environment]::GetFolderPath('System')) 'sc.exe') sdset OverlayRaceFirewall $raceSddl
if ($LASTEXITCODE -ne 0) { throw 'Failed to configure service start permission.' }
Write-Output 'Installed in Manual mode; OverlayApp starts the helper. No login/boot task or firewall setting was changed.'
$raceProfiles | Format-Table
