param([string]$PackageRoot,[string]$UserSid,[string]$FirewallHash,[string]$ElevationHash,[switch]$Firewall,[switch]$Elevation,[switch]$Remove)
$ErrorActionPreference='Stop'
if($UserSid -notmatch '^S-1-(5-21|12-1)-[0-9-]+$'){throw 'An ordinary Windows account SID is required.'}
$profile=Get-CimInstance Win32_UserProfile | Where-Object { $_.SID -eq $UserSid -and -not $_.Special }
if(-not $profile -or -not (Test-Path -LiteralPath $profile.LocalPath)){throw 'The requesting Windows profile is unavailable.'}
$sc=Join-Path ([Environment]::GetFolderPath('System')) 'sc.exe'
$profiles=@([pscustomobject]@{Name=$UserSid;SID=$UserSid;Profile=$profile.LocalPath})
function Safe-Directory([string]$Path){
 if(Test-Path -LiteralPath $Path){if((Get-Item -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'A helper directory is a reparse point; setup refused.'}}
 else{New-Item -ItemType Directory -Path $Path | Out-Null}
}
function Trusted-Existing([string]$Path){
 if(-not(Test-Path -LiteralPath $Path)){return}
 $acl=Get-Acl -LiteralPath $Path
 if($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin 'S-1-5-18','S-1-5-32-544'){throw 'An existing helper folder has an untrusted owner; preserved for review.'}
 $write=[Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
 foreach($rule in $acl.Access){if($rule.AccessControlType -eq 'Allow' -and ($rule.FileSystemRights -band $write) -and $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin 'S-1-5-18','S-1-5-32-544'){throw 'An existing helper folder allows untrusted writes; setup refused.'}}
}
function Protect-Directory([string]$Path,[string[]]$Sids,[string]$WritableSid=''){
 Safe-Directory $Path
 $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
 foreach($sid in $Sids){if(-not $WritableSid -or $WritableSid -eq $sid){$rights=if($sid -eq $WritableSid){'Modify'}else{'ReadAndExecute'};$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),$rights,'ContainerInherit,ObjectInherit','None','Allow'))}}
 Set-Acl -LiteralPath $Path -AclObject $acl
}
function Write-Atomic([string]$Path,$Value){
 $temporary=$Path+'.new';[IO.File]::WriteAllText($temporary,(ConvertTo-Json -InputObject $Value -Depth 8),[Text.UTF8Encoding]::new($false))
 if(Test-Path -LiteralPath $Path){[IO.File]::Replace($temporary,$Path,[NullString]::Value)}else{[IO.File]::Move($temporary,$Path)}
}
function Has-Clients([string]$State,[bool]$ElevationMode){
 $leases=Join-Path $State 'leases';if(-not(Test-Path -LiteralPath $leases)){return $false}
 foreach($file in Get-ChildItem -LiteralPath $leases -Filter '*.json' -Recurse){
  if($file.Length -gt 2048 -or (Get-Date).ToUniversalTime().Subtract($file.LastWriteTimeUtc).TotalSeconds -gt 5){continue}
  try{$lease=Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json;if($lease.Enabled -and ($ElevationMode -or $lease.FirewallEnabled -or $lease.ToastEnabled)){$process=Get-Process -Id $lease.Pid -ErrorAction Stop;if($process.ProcessName -eq 'OverlayRaceGuard' -and $process.StartTime.ToUniversalTime().Ticks -eq $lease.Start){return $true}}}catch{}
 }
 return $false
}
function Install-Component([string]$Name,[string]$Folder,[string]$Hash,[string]$Metadata,[string]$Startup){
 $code=Join-Path ([Environment]::GetFolderPath('ProgramFiles')) $Folder
 $state=Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) $Folder
 $exe=Join-Path $code ($Name+'.exe');$source=Join-Path $PackageRoot ($Name+'.exe')
 $service=Get-CimInstance Win32_Service -Filter "Name='$Name'"
 if($service -and ($service.StartName -ne 'LocalSystem' -or $service.PathName -ne ('"'+$exe+'"'))){throw 'Unexpected helper service identity; setup refused.'}
 if(-not $service -and ((Test-Path -LiteralPath $code) -or (Test-Path -LiteralPath $state))){
  if(-not(Test-Path -LiteralPath (Join-Path $state 'managed-setup.json'))){throw 'Unmanaged helper folders already exist; preserved for review.'}
 }
 Trusted-Existing $code;Trusted-Existing $state
 $entries=@();$metadataPath=Join-Path $state $Metadata
 if(Test-Path -LiteralPath $metadataPath){$decoded=Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json;$entries=@($decoded)}
 if($Metadata -eq 'authorized-profiles.json'){
  $entries=@($entries | Where-Object {$_.SID -ne $UserSid})+@($profiles)
  $sids=@($entries | ForEach-Object SID)
 }else{$entries=@($entries | ForEach-Object { [string]$_ });if($entries -notcontains $UserSid){$entries+=$UserSid};$sids=@($entries)}
 foreach($sid in $sids){if($sid -notmatch '^S-1-(5-21|12-1)-[0-9-]+$'){throw 'Invalid existing authorized account; metadata preserved.'}}
 if(-not $Remove -and (Get-FileHash -LiteralPath $source).Hash -ne $Hash){throw 'Embedded package helper hash mismatch.'}
 if($service -and (Has-Clients $state ($Name -eq 'OverlayElevationGate'))){throw 'Another Overlay Manager still uses this helper. Close that Manager normally, then retry setup.'}
 $oldStartup=if($service){$service.StartMode}else{$Startup};$backup=$null;$stopped=$false
 try{
  if($service){
   Set-Service -Name $Name -StartupType Disabled
   Stop-Service -Name $Name
   (Get-Service -Name $Name).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40));$stopped=$true
   $deadline=[DateTime]::UtcNow.AddSeconds(20)
   do{Start-Sleep -Milliseconds 100;$running=@(Get-Process -Name $Name -ErrorAction SilentlyContinue)}while($running.Count -and [DateTime]::UtcNow -lt $deadline)
   if($running.Count){throw 'Recovery helper has not exited normally; binary preserved.'}
  }
  foreach($journal in @('journal.json','firewall-journal.json','toasts-journal.json')){
   if(Test-Path -LiteralPath (Join-Path $state $journal)){throw 'Restoration is still pending; helper and journals preserved.'}
  }
  if($Remove){if($service){& $sc delete $Name | Out-Null;if($LASTEXITCODE -ne 0){throw 'Helper removal failed.'}};return}
  Protect-Directory $code $sids;Protect-Directory $state $sids
  Write-Atomic (Join-Path $state 'managed-setup.json') @{Schema=1;Service=$Name;Hash=$Hash.ToLowerInvariant();Complete=$false}
  if(Test-Path -LiteralPath $exe){$backup=$exe+'.backup-'+(Get-Date -Format yyyyMMdd-HHmmss);Copy-Item -LiteralPath $exe -Destination $backup}
  Copy-Item -LiteralPath $source -Destination $exe
  if((Get-FileHash -LiteralPath $exe).Hash -ne $Hash){throw 'Protected helper copy verification failed.'}
  $leases=Join-Path $state 'leases';Protect-Directory $leases $sids
  foreach($sid in $sids){Protect-Directory (Join-Path $leases $sid) $sids $sid}
  Write-Atomic $metadataPath @($entries)
  if(-not $service){New-Service -Name $Name -BinaryPathName ('"'+$exe+'"') -StartupType $Startup -DisplayName ('OverlayApp - '+$Name) | Out-Null}
  $users=($sids | ForEach-Object {'(A;;CCLCRP;;;'+$_+')'}) -join ''
  & $sc sdset $Name ('D:(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)'+$users) | Out-Null
  if($LASTEXITCODE -ne 0){throw 'Helper query/start permissions could not be configured.'}
  & $sc failure $Name reset= 86400 actions= restart/1000/restart/5000/restart/10000 | Out-Null
  if($LASTEXITCODE -ne 0){throw 'Service failure recovery could not be configured.'}
  & $sc failureflag $Name 1 | Out-Null
  if($LASTEXITCODE -ne 0){throw 'Service failure recovery flag could not be configured.'}
  Set-Service -Name $Name -StartupType $Startup
  if($Name -eq 'OverlayElevationGate' -and (Test-Path -LiteralPath (Join-Path $state 'recovery.flag'))){Remove-Item -LiteralPath (Join-Path $state 'recovery.flag')}
  Start-Service -Name $Name
  Write-Atomic (Join-Path $state 'managed-setup.json') @{Schema=1;Service=$Name;Hash=$Hash.ToLowerInvariant();Complete=$true}
 }catch{
  if($backup -and (Test-Path -LiteralPath $backup)){Copy-Item -LiteralPath $backup -Destination $exe}
  if($service){$restoreMode=if($oldStartup -eq 'Auto'){'Automatic'}elseif($oldStartup -eq 'Manual'){'Manual'}else{'Disabled'};Set-Service -Name $Name -StartupType $restoreMode;if($restoreMode -ne 'Disabled'){Start-Service -Name $Name -ErrorAction SilentlyContinue}}
  throw
 }
}
# Retire the global broker when Allow mode requests only the ordinary helpers.
# Stop only our service; its normal shutdown must finish restoration first.
function Retire-GlobalBroker {
 if(-not (Get-CimInstance Win32_Service -Filter "Name='OverlayElevationGate'")){return}
 $previousRemove=$script:Remove;$script:Remove=$true
 try{
  Install-Component 'OverlayElevationGate' 'OverlayElevationGate' $ElevationHash 'authorized-sids.json' 'Automatic'
  Write-Atomic (Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'OverlayElevationGate/managed-setup.json') @{Schema=1;Service='OverlayElevationGate';Hash=$ElevationHash.ToLowerInvariant();Complete=$false;Retired=$true}
 }finally{$script:Remove=$previousRemove}
}
if($Firewall -and -not $Elevation -and -not $Remove){Retire-GlobalBroker}
if($Firewall){Install-Component 'OverlayRaceFirewall' 'OverlayAppFirewall' $FirewallHash 'authorized-profiles.json' 'Manual'}
if($Elevation){Install-Component 'OverlayElevationGate' 'OverlayElevationGate' $ElevationHash 'authorized-sids.json' 'Automatic'}
Write-Output 'Administrative helpers configured for the requesting account. No UAC policy, firewall rule, game, OBS or NoPing configuration was changed. Runtime protection and restoration are verified separately.'
