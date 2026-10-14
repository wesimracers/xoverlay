# Isolated service/ACL transaction doubles. All file writes stay in a unique temp directory.
$ErrorActionPreference='Stop'
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('overlay-setup-tests-'+[guid]::NewGuid())
$programFiles=Join-Path $fixture 'program-files';$programData=Join-Path $fixture 'program-data';$payload=Join-Path $fixture 'payload';$profilePath=Join-Path $fixture 'profile'
foreach($path in @($programFiles,$programData,$payload,$profilePath)){New-Item -ItemType Directory -Path $path | Out-Null}
$script:services=@{};$script:operations=@();$script:checks=0;$script:failCopy=$false;$script:busy=$false
$sidOne='S-1-5-21-999-888-777-1234';$sidTwo='S-1-5-21-999-888-777-5678'
function Get-CimInstance($ClassName,$Filter){if($ClassName -eq 'Win32_UserProfile'){[pscustomobject]@{SID=$script:UserSid;LocalPath=$profilePath;Special=$false}}elseif($ClassName -eq 'Win32_Service'){$name=$Filter.Split("'")[1];$script:services[$name]}else{throw 'Unexpected CIM request.'}}
function Set-Service($Name,$StartupType){$script:operations+=('config:'+$Name+':'+$StartupType);$script:services[$Name].StartMode=$StartupType}
function Stop-Service($Name){$script:operations+=('stop:'+$Name);$script:services[$Name].State='Stopped'}
function Start-Service($Name){$script:operations+=('start:'+$Name);$script:services[$Name].State='Running'}
function Get-Service($Name){$object=$script:services[$Name];$object | Add-Member ScriptMethod WaitForStatus {param($desired,$timeout)if($this.State -ne $desired){throw 'Fake service did not stop.'}} -Force;return $object}
function New-Service($Name,$BinaryPathName,$StartupType,$DisplayName){$script:operations+=('create:'+$Name);$script:services[$Name]=[pscustomobject]@{StartName='LocalSystem';PathName=$BinaryPathName;StartMode=$StartupType;State='Stopped'}}
function Get-Process($Name,$Id){if($Id -and $script:busy){return [pscustomobject]@{ProcessName='OverlayRaceGuard';StartTime=$script:clientStart}};if($Id){throw 'Fake process does not exist.'};return @()}
function Invoke-FakeSC { $script:operations+=('sc:'+($args -join ' '));if($args[0] -eq 'delete'){$script:services.Remove($args[1])};$global:LASTEXITCODE=0 }
function Copy-Item($LiteralPath,$Destination){if($script:failCopy -and $LiteralPath.StartsWith($payload)){$script:failCopy=$false;throw 'Simulated copy failure.'};Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination}
function Assert-Setup($condition,$name){if(-not $condition){throw ('FAILED: '+$name)};$script:checks++}
$content=[IO.File]::ReadAllText((Join-Path (Get-Location) 'main/protection/SetupProtection.ps1'))
$content=$content.Substring(0,$content.LastIndexOf("`nif(`$Firewall)"))
$content=$content.Replace("([Environment]::GetFolderPath('ProgramFiles'))",("'"+$programFiles+"'")).Replace("([Environment]::GetFolderPath('CommonApplicationData'))",("'"+$programData+"'"))
$content=$content.Replace("Join-Path ([Environment]::GetFolderPath('System')) 'sc.exe'","'Invoke-FakeSC'")
try{
 . ([scriptblock]::Create($content)) -PackageRoot $payload -UserSid $sidOne
 # Replace only ACL effects; transaction identity/hash/lease/journal logic stays real.
 function Trusted-Existing($Path){if($script:untrusted){throw 'Simulated untrusted ACL.'}}
 function Protect-Directory($Path,$Sids,$WritableSid){if(-not(Test-Path -LiteralPath $Path)){New-Item -ItemType Directory -Path $Path | Out-Null};$script:operations+=('acl:'+$Path+':'+$WritableSid)}
 $script:UserSid=$sidOne;$script:Remove=$false
 $name='OverlayRaceFirewall';$folder='OverlayAppFirewall';$source=Join-Path $payload ($name+'.exe')
 [IO.File]::WriteAllText($source,'version one');$hash=(Get-FileHash -LiteralPath $source).Hash
 Install-Component $name $folder $hash 'authorized-profiles.json' 'Manual'
 $exe=Join-Path $programFiles ($folder+'/'+$name+'.exe');$state=Join-Path $programData $folder
 Assert-Setup ((Get-FileHash -LiteralPath $exe).Hash -eq $hash) 'fresh install copies verified helper'
 Assert-Setup ($script:services[$name].State -eq 'Running') 'fresh install starts helper'
 Assert-Setup (@(Get-Content -LiteralPath (Join-Path $state 'authorized-profiles.json') -Raw | ConvertFrom-Json)[0].SID -eq $sidOne) 'fresh install uses arbitrary requesting SID'
 $script:UserSid=$sidTwo;$profiles=@([pscustomobject]@{Name=$sidTwo;SID=$sidTwo;Profile=$profilePath})
 [IO.File]::WriteAllText($source,'version two');$hash=(Get-FileHash -LiteralPath $source).Hash
 Install-Component $name $folder $hash 'authorized-profiles.json' 'Manual'
 $decoded=Get-Content -LiteralPath (Join-Path $state 'authorized-profiles.json') -Raw | ConvertFrom-Json;$entries=@($decoded)
 Assert-Setup ($entries.Count -eq 2 -and $entries.SID -contains $sidOne -and $entries.SID -contains $sidTwo) 'upgrade retains previous SID and authorizes current SID'
 Assert-Setup ((Get-FileHash -LiteralPath $exe).Hash -eq $hash) 'upgrade verified new binary'
 $prior=(Get-FileHash -LiteralPath $exe).Hash;$count=$script:operations.Count
 try{Install-Component $name $folder 'incorrect' 'authorized-profiles.json' 'Manual';throw 'Unexpected success'}catch{Assert-Setup ($_.Exception.Message -like '*hash mismatch*') 'wrong hash rejected'}
 Assert-Setup ($script:operations.Count -eq $count -and (Get-FileHash -LiteralPath $exe).Hash -eq $prior) 'hash failure leaves service and binary untouched'
 $script:busy=$true;$script:clientStart=Get-Date
 @{Pid=12345;Start=$script:clientStart.ToUniversalTime().Ticks;Enabled=$true;FirewallEnabled=$true} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $state ('leases/'+$sidOne+'/12345.json'))
 try{Install-Component $name $folder $hash 'authorized-profiles.json' 'Manual';throw 'Unexpected success'}catch{Assert-Setup ($_.Exception.Message -like '*Another Overlay Manager*') 'active client refuses upgrade'}
 Assert-Setup ((Get-FileHash -LiteralPath $exe).Hash -eq $prior) 'active client preserves binary'
 $script:busy=$false;$script:failCopy=$true
 [IO.File]::WriteAllText($source,'version three');$hash=(Get-FileHash -LiteralPath $source).Hash
 try{Install-Component $name $folder $hash 'authorized-profiles.json' 'Manual';throw 'Unexpected success'}catch{Assert-Setup ($_.Exception.Message -like '*Simulated copy failure*') 'partial copy failure propagated'}
 Assert-Setup ((Get-FileHash -LiteralPath $exe).Hash -eq $prior -and $script:services[$name].State -eq 'Running') 'failed upgrade restores old binary and running helper'
 $script:Remove=$true;[IO.File]::WriteAllText((Join-Path $state 'journal.json'),'pending')
 try{Install-Component $name $folder $hash 'authorized-profiles.json' 'Manual';throw 'Unexpected success'}catch{Assert-Setup ($_.Exception.Message -like '*Restoration is still pending*') 'pending journal refuses removal'}
 Assert-Setup ($script:services.ContainsKey($name) -and (Test-Path -LiteralPath $exe)) 'pending recovery preserves service and audit files'
 Remove-Item -LiteralPath (Join-Path $state 'journal.json')
 Install-Component $name $folder $hash 'authorized-profiles.json' 'Manual'
 Assert-Setup (-not $script:services.ContainsKey($name) -and (Test-Path -LiteralPath $exe)) 'uninstall removes service while retaining files'
 $script:Remove=$false
 $gateName='OverlayElevationGate';$gateFolder='OverlayElevationGate'
 $gateSource=Join-Path $payload ($gateName+'.exe');[IO.File]::WriteAllText($gateSource,'isolated gate')
 $script:ElevationHash=(Get-FileHash -LiteralPath $gateSource).Hash
 Install-Component $gateName $gateFolder $script:ElevationHash 'authorized-sids.json' 'Automatic'
 $gateState=Join-Path $programData $gateFolder
 [IO.File]::WriteAllText((Join-Path $gateState 'journal.json'),'pending')
 try{Retire-GlobalBroker;throw 'Unexpected success'}catch{Assert-Setup ($_.Exception.Message -like '*Restoration is still pending*') 'gate retirement preserves pending restoration'}
 Assert-Setup ($script:services.ContainsKey($gateName) -and -not $script:Remove) 'failed gate retirement restores operation mode'
 Remove-Item -LiteralPath (Join-Path $gateState 'journal.json')
 Retire-GlobalBroker
 Assert-Setup (-not $script:services.ContainsKey($gateName) -and -not $script:Remove) 'exceptions retire global broker normally'
 $retired=Get-Content -LiteralPath (Join-Path $gateState 'managed-setup.json') -Raw | ConvertFrom-Json
 Assert-Setup ($retired.Retired -and -not $retired.Complete) 'retired broker cannot claim ready'
 Install-Component $gateName $gateFolder $script:ElevationHash 'authorized-sids.json' 'Automatic'
 Assert-Setup ($script:services.ContainsKey($gateName)) 'retired audit folder allows later verified explicit setup'
 $script:untrusted=$true
 try{Install-Component $name $folder $hash 'authorized-profiles.json' 'Manual';throw 'Unexpected success'}catch{Assert-Setup ($_.Exception.Message -like '*untrusted ACL*') 'untrusted existing path refused'}
 Write-Output "$script:checks isolated setup transaction assertions passed; no real SCM, ACL, UAC or policy calls."
}finally{
 $resolved=[IO.Path]::GetFullPath($fixture);$tempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
 if(-not $resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'Temporary cleanup boundary failed.'}
 Remove-Item -LiteralPath $resolved -Recurse -Force
}
