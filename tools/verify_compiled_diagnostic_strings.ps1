# Inspect compiled method strings without constructing or running the guard.
$ErrorActionPreference = 'Stop'
$raceAssembly = [Reflection.Assembly]::LoadFrom((Join-Path (Get-Location) 'main\protection\bin\OverlayRaceGuard.exe'))
function Get-RaceMethodStrings([string]$Type,[string]$Method) {
    $raceMethod = $raceAssembly.GetType($Type).GetMethod($Method,[Reflection.BindingFlags]'Public,NonPublic,Instance,Static')
    $raceBytes = $raceMethod.GetMethodBody().GetILAsByteArray()
    for ($raceIndex=0; $raceIndex -lt $raceBytes.Length-4; $raceIndex++) {
        if ($raceBytes[$raceIndex] -ne 0x72) { continue }
        $raceToken = [BitConverter]::ToInt32($raceBytes,$raceIndex+1)
        if (($raceToken -band 0xFF000000) -eq 0x70000000) { $raceMethod.Module.ResolveString($raceToken) }
    }
}
$raceExpected = @{
    'GuardContext/Stop' = @('STOPPED.')
    'GuardContext/Consider' = @('RETURN_FOCUS result=','; Windows may deny the request.')
    'ToastTransaction/Apply' = @('TOASTS policy applied and value verified.')
    'RegistryToastBackend/ProbeWriteAccess' = @('No writable ancestor key was confirmed.')
}
foreach ($raceItem in $raceExpected.GetEnumerator()) {
    $raceNames = $raceItem.Key.Split('/')
    $raceStrings = @(Get-RaceMethodStrings $raceNames[0] $raceNames[1])
    foreach ($raceExpectedText in $raceItem.Value) {
        if ($raceStrings -notcontains $raceExpectedText) { throw ('Compiled diagnostic missing: '+$raceExpectedText) }
        Write-Output ('Compiled diagnostic verified: '+$raceExpectedText)
    }
}
