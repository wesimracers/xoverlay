#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
if (Get-Process -Name OverlayRaceGuard -ErrorAction SilentlyContinue) { throw 'Close OverlayApp/protection before removing the helper.' }
$raceService = Get-Service OverlayRaceFirewall -ErrorAction SilentlyContinue
if ($raceService -and $raceService.Status -ne 'Stopped') {
    Stop-Service OverlayRaceFirewall
    $raceService.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40))
}
$raceExe = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'OverlayAppFirewall\OverlayRaceFirewall.exe'
if (Test-Path -LiteralPath $raceExe) {
    $raceRecovery = Start-Process -FilePath $raceExe -ArgumentList '--restore' -WindowStyle Hidden -PassThru -Wait
    if ($raceRecovery.ExitCode -ne 0) { throw 'Restoration pending; helper/journal preserved.' }
}
if (Test-Path -LiteralPath (Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'OverlayAppFirewall\firewall-journal.json')) { throw 'Journal pending; not removed.' }
if (Test-Path -LiteralPath (Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'OverlayAppFirewall\toasts-journal.json')) { throw 'Toast journal pending; not removed.' }
if ($raceService) {
    & (Join-Path ([Environment]::GetFolderPath('System')) 'sc.exe') delete OverlayRaceFirewall
    if ($LASTEXITCODE -ne 0) { throw 'Failed to remove service.' }
}
Write-Output 'Service removed. Files/journals/logs retained for audit; no firewall rule changed.'
