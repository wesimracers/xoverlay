# Overlay

OverlayApp 1.2 portable release in `wesimracers/xoverlay`. See [repository contents and exclusions](REPOSITORY.md) for the source layout, upstream references and publication scope.

Windows x64 iRacing overlays with Relative, Standings, Sectors, Info, Weather, Fuel, RPM, Input Trace, Tyres, Alerts, Heart Rate, Garage Cover, Wind, RaceChat and Pop-up Protection. The Manager has 15 rows with Config and ON/OFF controls; it adapts to shorter displays without requiring vertical scrolling.

Weather/Hub displays Rubber in at most seven characters. Wet retains Yes/No; track condition (Dry, Mostly Dry and wet states) appears in its own column with a divider and no quotation marks. Existing layouts split the previous combined column space where possible, preserving custom widths and settings.

Extract the release anywhere and open `OverlayApp.exe` normally. A fresh installation creates its settings under `%LOCALAPPDATA%\OverlayApp\Settings`, using the embedded factory layout. Existing `overlay.json` beside an older executable continues to be used and is preserved by the optional update script. Fresh windows are clamped to the available primary display. There are no packaged personal settings, telemetry captures, OAuth clients or tokens. Python/Qt are bundled; Windows PowerShell and .NET are the existing Windows components, not separate user installation steps.

In Pop-up Protection Config, choose one of the side-by-side **Allow** or **Block all** modes. **Manage allowed applications** stays available in both modes and manages apps whose windows should stay visible and keep focus in Allow mode. Defaults include Apple Music, Notes, Notepad, Snipping Tool, PowerShell and shared console hosts. **Add executable** grants an exact-path window exception; **Find installed apps** lets you choose a packaged app such as Apple Music. Save the list, then Save Config to persist and apply changes; Cancel Config discards pending mode/list edits. **Open selected** uses ordinary Windows activation and the currently saved protection mode. It never autoapproves elevation or commits pending Config edits. Applying a changed exception list restores previous window placements before reloading the guard. Shared console-host exceptions cover every console hosted by that process; remove those entries if that scope is unwanted.

Ordinary protection can remain ON while allowed apps open. Both modes remain selectable with any saved list. **Block all** requests experimental blocking of new interactive elevations globally; it does not stop every application, existing elevated process, service or scheduled task. It suspends every saved per-app window exception at runtime and requests the elevation helper regardless of list contents. The saved `allowed_apps` list is preserved across mode changes, reopenings and restarts; `block_elevation` remains the persisted mode key. **Allow** releases this Manager's global blocking request and restores the saved exceptions. Actual UAC status is reported separately from the selected mode; setup readiness alone does not confirm blocking, and another Manager can retain an active global lease. Ordinary Windows consent/security surfaces remain excluded from window manipulation. Administrative setup uses normal shutdown when retiring an existing global broker service for firewall/toast-only setup and refuses removal while restoration or another Manager's active lease remains pending. This does not repair an already unresponsive Windows broker.

Pop-up Protection checks whether its requested administrative helpers match this release, include the actual account SID, and have the expected service identity. Missing/outdated helpers are provisioned through the embedded `OverlayProtectionSetup.exe`, after one personal Windows administrative approval. Automatic setup waits until supported games close. Explicit **Retry administrative setup** can request approval while a game is open; use it at a convenient pause. Cancelling does not cause repeated prompts. Protection Config also provides **Remove administrative helpers**. Ordinary protection continues with explicit degraded component status until prerequisites are confirmed. Installation is part of the app workflow; standalone scripts are optional recovery/update conveniences.

Saving **Block all** while protection is enabled explicitly requests any missing/outdated/retired elevation helper through that in-app Windows approval workflow, including during a game. No external command or list removal is needed. Cancelling or failing setup keeps the requested mode/list saved and leaves actual global blocking unconfirmed. Save Config again to retry missing setup, or use Retry administrative setup for a durable recovery latch. An already pending setup completes before a newly requested component is provisioned; repeated status polling sends no duplicate requests. Provisioning preserves previously authorized account SIDs and profiles. Successful installation only permits the guard's global request; the UAC runtime status still has to confirm the broker's actual result.

The experimental global elevation option is **OFF by default and has not passed live acceptance**. Windows rejected earlier activation with error 1061, and users subsequently reported application-launch failures. Restoring the start type and observing Running did not prove recovery of the broker. Do not enable this option until Windows functionality and controlled gate recovery are validated. See [protection details](main/protection/README.md) and [actual acceptance limits](main/protection/UAC-FEASIBILITY.md).

RaceChat, heart-rate integrations and external providers require the user's own credentials/URLs and network access. Credentials remain in each user's DPAPI-protected local store. Existing opt-in synchronization between two Windows accounts is supported using their actual registered profiles; its startup hook uses this same executable. A fresh package creates no synchronization task or account pairing. Game/OBS/NoPing settings are not installed or modified.

## Windows executable

Download [OverlayApp.exe](https://github.com/wesimracers/xoverlay/raw/refs/heads/main/releases/windows-x64/OverlayApp.exe). The 48 MB file includes Python 3.12, Qt and the required helper resources. [Checksums and static verification](releases/windows-x64/) accompany it. See [third-party notices](THIRD_PARTY_NOTICES.md) for bundled components.

## Build from source

Use Windows x64 with Python 3.12, .NET Framework 4.8's x64 C# compiler, and Windows PowerShell 5.1. Windows 10/11 provide the service/ACL APIs; the toast and firewall helpers require the Windows firewall/registry components and permissions. Managed enterprise policy may reject changes. The release bundles Python, Qt and Python dependencies; end users do not need Python or a compiler.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r main\requirements.txt
.venv\Scripts\python.exe tools\build_protection_release.py --stage build-staging-portable
```

The build compiles helpers, embeds their exact bytes in the administrative installer, runs isolated helper tests, builds the full one-file GUI, and compares frozen Python bytecode/resources with source. Output is `build-staging-portable\release`. It never stops or replaces an installed app. `main\build.py` calls the same isolated builder. `--include-user-settings` is an explicit private-copy option; omit it for distribution.

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
Invoke-Expression ([IO.File]::ReadAllText('tests\test_portable_setup.ps1'))
Invoke-Expression ([IO.File]::ReadAllText('tests\test_firewall_profiles.ps1'))
.venv\Scripts\python.exe tools\verify_elevation_gate_ui.py --stage build-staging-portable
.venv\Scripts\python.exe tools\verify_portable_release.py --stage build-staging-portable
```

These suites use temporary data, mocked services/policies and offscreen Qt. They do not approve UAC, manipulate the desktop or prove live elevation blocking. Source and release hashes are supplied for review; timestamps/compiler environments may affect binary hashes. Review licensing of existing code and bundled dependencies before public release; no new license is implied by this package.
