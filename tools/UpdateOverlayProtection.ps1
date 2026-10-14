param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
if(Get-Process -Name OverlayApp,OverlayRaceGuard -ErrorAction SilentlyContinue){throw 'Close all Overlay Managers normally and wait for their guards to exit before replacing the executable.'}
$targetFolder=(Resolve-Path -LiteralPath $Destination).Path
if($targetFolder -eq $PSScriptRoot){throw 'Source and destination must be different directories.'}
$source=Join-Path $PSScriptRoot 'OverlayApp.exe'
if(-not(Test-Path -LiteralPath $source)){throw 'Run this optional update script beside the reviewed OverlayApp.exe.'}
$target=Join-Path $targetFolder 'OverlayApp.exe'
$backup=Join-Path $targetFolder ('backup-portable-'+(Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach($name in 'OverlayApp.exe','overlay.json','database.json','blacklist.json','race_review_state.json'){
 $original=Join-Path $targetFolder $name
 if(Test-Path -LiteralPath $original){Copy-Item -LiteralPath $original -Destination $backup}
}
$temporary=$target+'.new';Copy-Item -LiteralPath $source -Destination $temporary
if((Get-FileHash -LiteralPath $temporary).Hash -ne (Get-FileHash -LiteralPath $source).Hash){throw 'Executable copy verification failed; installed application preserved.'}
if(Test-Path -LiteralPath $target){[IO.File]::Replace($temporary,$target,(Join-Path $backup 'OverlayApp-replaced.exe'))}else{[IO.File]::Move($temporary,$target)}
Write-Output "Overlay executable updated. User settings preserved. Open OverlayApp normally to provision any required helpers. Backup: $backup"
