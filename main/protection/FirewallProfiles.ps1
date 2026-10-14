param([Parameter(Mandatory=$true)][ValidateSet('Apply','Restore')][string]$Mode)
$ErrorActionPreference = 'Stop'
$raceRoot = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'OverlayAppFirewall'
$raceJournalPath = Join-Path $raceRoot 'firewall-journal.json'

function Save-RaceJournal($raceSnapshot) {
    $raceBytes = [Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject @($raceSnapshot) -Depth 4))
    $raceTemp = $raceJournalPath + '.tmp'
    $raceStream = [IO.FileStream]::new($raceTemp,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $raceStream.Write($raceBytes,0,$raceBytes.Length); $raceStream.Flush($true) } finally { $raceStream.Dispose() }
    if ([IO.File]::Exists($raceJournalPath)) {
        $raceBackup = $raceJournalPath + '.bak'
        [IO.File]::Replace($raceTemp,$raceJournalPath,$raceBackup)
        [IO.File]::Delete($raceBackup)
    }
    else { [IO.File]::Move($raceTemp,$raceJournalPath) }
}

if ($Mode -eq 'Apply') {
    if (Test-Path -LiteralPath $raceJournalPath) { throw 'Previous restoration pending.' }
    $raceSnapshot = @(Get-NetFirewallProfile -PolicyStore PersistentStore | ForEach-Object {
        [pscustomobject]@{ Name=[string]$_.Name; NotifyOnListen=[string]$_.NotifyOnListen }
    })
    if ($raceSnapshot.Count -ne 3 -or @($raceSnapshot.Name | Sort-Object -Unique).Count -ne 3) { throw 'Incomplete firewall snapshot.' }
    Save-RaceJournal $raceSnapshot
    Set-NetFirewallProfile -PolicyStore PersistentStore -Name Domain,Private,Public -NotifyOnListen False
    $raceEffective = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    if ($raceEffective.Count -ne 3 -or @($raceEffective | Where-Object { [string]$_.NotifyOnListen -ne 'False' }).Count) {
        throw 'ActiveStore did not confirm suppression; restoration required.'
    }
} elseif (Test-Path -LiteralPath $raceJournalPath) {
    $racePending = Get-Content -LiteralPath $raceJournalPath -Raw | ConvertFrom-Json
    foreach ($raceProfile in @($racePending)) {
        if ($raceProfile.Name -notin 'Domain','Private','Public' -or $raceProfile.NotifyOnListen -notin 'True','False','NotConfigured') { throw 'Invalid firewall journal.' }
        $raceCurrent = Get-NetFirewallProfile -PolicyStore PersistentStore -Name $raceProfile.Name
        if ([string]$raceCurrent.NotifyOnListen -eq 'False') {
            Set-NetFirewallProfile -PolicyStore PersistentStore -Name $raceProfile.Name -NotifyOnListen $raceProfile.NotifyOnListen
            $raceVerify = Get-NetFirewallProfile -PolicyStore PersistentStore -Name $raceProfile.Name
            if ([string]$raceVerify.NotifyOnListen -ne $raceProfile.NotifyOnListen) { throw "Restoration not confirmed: $($raceProfile.Name)" }
        } elseif ([string]$raceCurrent.NotifyOnListen -ne $raceProfile.NotifyOnListen) {
            # Preserve an external administrator/policy change to this property.
            Add-Content -LiteralPath (Join-Path $raceRoot 'firewall.log') -Value "$(Get-Date -Format o) External change preserved: $($raceProfile.Name)"
        }
        $racePending = @($racePending | Where-Object { $_.Name -ne $raceProfile.Name })
        Save-RaceJournal $racePending
    }
    Remove-Item -LiteralPath $raceJournalPath
}
