# Mock NetSecurity entirely; never import/call the real module.
$ErrorActionPreference = 'Stop'
$raceFixture = Join-Path ([IO.Path]::GetTempPath()) ('overlay-firewall-tests-'+[guid]::NewGuid())
New-Item -ItemType Directory -Path (Join-Path $raceFixture 'OverlayAppFirewall') | Out-Null
$raceScriptPath = Join-Path (Get-Location) 'main\protection\FirewallProfiles.ps1'
$raceContent = [IO.File]::ReadAllText($raceScriptPath).Replace("([Environment]::GetFolderPath('CommonApplicationData'))",("'"+$raceFixture.Replace("'","''")+"'"))
$raceOperation = [scriptblock]::Create($raceContent)
$script:checks = 0
function Assert-Race($Condition,$Name) { if (-not $Condition) { throw "FALHA: $Name" }; $script:checks++ }
function Reset-Race($Values) {
    $script:localProfiles = @{}
    $script:activeProfiles = @{}
    $script:writes = 0
    $script:failRestore = ''
    $script:denyPolicy = $false
    $script:journalBeforeWrite = $true
    for ($raceIndex=0;$raceIndex -lt 3;$raceIndex++) {
        $raceName = @('Domain','Private','Public')[$raceIndex]
        $script:localProfiles[$raceName]=$Values[$raceIndex]
        $script:activeProfiles[$raceName]=$Values[$raceIndex]
    }
}
function Get-NetFirewallProfile($PolicyStore,$Name) {
    $raceMap = if ($PolicyStore -eq 'PersistentStore') { $script:localProfiles } else { $script:activeProfiles }
    $raceNames = if ($Name) { @($Name) } else { @('Domain','Private','Public') }
    foreach ($raceName in $raceNames) { [pscustomobject]@{Name=$raceName;NotifyOnListen=$raceMap[$raceName]} }
}
function Set-NetFirewallProfile($PolicyStore,$Name,$NotifyOnListen) {
    if ($PolicyStore -ne 'PersistentStore') { throw 'Apenas PersistentStore permitido.' }
    if (-not (Test-Path -LiteralPath (Join-Path $raceFixture 'OverlayAppFirewall\firewall-journal.json'))) { $script:journalBeforeWrite=$false }
    foreach ($raceName in @($Name)) {
        if ($script:failRestore -eq $raceName -and [string]$NotifyOnListen -ne 'False') { throw 'falha simulada' }
        $script:localProfiles[$raceName]=[string]$NotifyOnListen
        if (-not $script:denyPolicy) { $script:activeProfiles[$raceName]=[string]$NotifyOnListen }
        $script:writes++
    }
}
try {
    Reset-Race @('True','NotConfigured','False')
    & $raceOperation -Mode Apply
    Assert-Race $script:journalBeforeWrite 'Snapshot duravel antes de qualquer alteracao'
    Assert-Race ($script:writes -eq 3) 'Somente propriedade solicitada nos tres perfis'
    & $raceOperation -Mode Restore
    Assert-Race ($script:localProfiles.Domain -eq 'True') 'Domain exato'
    Assert-Race ($script:localProfiles.Private -eq 'NotConfigured') 'NotConfigured exato'
    Assert-Race ($script:localProfiles.Public -eq 'False') 'False original exato'
    Assert-Race (-not (Test-Path -LiteralPath (Join-Path $raceFixture 'OverlayAppFirewall\firewall-journal.json'))) 'Journal removido somente apos restauracao'
    Reset-Race @('True','True','True')
    $script:denyPolicy=$true
    $raceRejected=$false
    try { & $raceOperation -Mode Apply } catch { $raceRejected=$true }
    Assert-Race $raceRejected 'Politica efetiva rejeitada reporta falha'
    $script:denyPolicy=$false
    & $raceOperation -Mode Restore
    Assert-Race ($script:localProfiles.Private -eq 'True') 'Reverte aplicacao parcial/rejeitada'
    Reset-Race @('True','True','True')
    & $raceOperation -Mode Apply
    $script:failRestore='Private'
    $raceRejected=$false
    try { & $raceOperation -Mode Restore } catch { $raceRejected=$true }
    Assert-Race $raceRejected 'Falha de restauracao nao e ocultada'
    $racePending = Get-Content -LiteralPath (Join-Path $raceFixture 'OverlayAppFirewall\firewall-journal.json') -Raw | ConvertFrom-Json
    Assert-Race ($racePending.Count -eq 2) 'Journal preserva perfis pendentes sem repetir concluido'
    $script:failRestore=''
    & $raceOperation -Mode Restore
    Assert-Race ($script:localProfiles.Public -eq 'True') 'Retry restaura restantes'
    Reset-Race @('NotConfigured','True','True')
    & $raceOperation -Mode Apply
    $script:localProfiles.Domain='True'
    & $raceOperation -Mode Restore
    Assert-Race ($script:localProfiles.Domain -eq 'True') 'Mudanca administrativa externa preservada'
    Write-Output "$script:checks testes simulados de firewall passaram; nenhuma API real de firewall chamada."
} finally {
    # This fixture was created here; verify it is still inside Temp before removal.
    $raceResolved = [IO.Path]::GetFullPath($raceFixture)
    if ($raceResolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $raceResolved -Recurse -Force
    }
}
