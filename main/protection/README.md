# Integrated protection and portable administrative setup

The normal GUI starts a hidden, per-user/session `OverlayRaceGuard.exe`. PID/start-time owner leases allow more than one Manager; the guard exits after the last closes. There is no console or protection UI at boot. All configuration remains under `race_protection` in the user's `overlay.json`.

Config's Manage allowed applications dialog stages process-name presets or exact executable paths, discovers packaged apps without launching them, and offers an explicit Open selected action. Save Config persists both the staged list and selected mode; Cancel discards pending edits. In Allow mode the ordinary guard excludes those windows from hiding, routing and focus recovery. Configuration comparison includes both exception arrays: any change restores previous windows before committing the new configuration; removing an exception resumes eligibility for future popup events. Open selected uses the ordinary Windows open verb and currently saved protection mode, without committing pending changes or automating runas/consent. PowerShell console hosts are explicitly listed because they can host several programs.

The side-by-side Allow and Block all controls are mutually exclusive and always selectable. The existing `block_elevation` setting selects the mode. Block all requests the experimental global new-interactive-elevation gate regardless of the saved list; runtime `AllowedProcessNames` and `AllowedExecutablePaths` are empty in that mode, even while setup is pending or fails. The persisted `allowed_apps` list remains intact and manageable. Allow releases this client's gate request and restores both exception arrays; another active Manager may still hold a global lease. Actual UAC success/failure/recovery remains separate from the selected mode. Defaults allow common user apps and keep the broker available. Selecting an exception never grants administrative permission or changes a Windows UAC policy. Security/consent hard exclusions remain in both modes.

The app checks hashes, registered LocalSystem service paths, startup configuration and current-account authorization before publishing privileged feature leases. Missing, outdated or unregistered helpers trigger one normal personal UAC approval through the embedded, fixed-operation `OverlayProtectionSetup.exe`. Automatic requests wait until supported games close. Cancel/error means no automatic retry storm. Config's Retry renews the personal setup request; Remove first disables privileged leases and asks for normal administrative approval to restore/remove the helpers.

Setup resolves actual Windows known folders and the requesting SID's registered profile. It preserves other previously authorized SIDs, updates the requesting profile, rejects unmanaged/untrusted/reparse-point roots, verifies helper hashes before/after copy, and refuses upgrades with active client leases or pending recovery journals. An upgrade disables only its own service while stopping it, backs up the previous binary, and restores that binary/startup state on failure. The service is removed only after normal restoration; audit files remain.

Protected code is stored under `%ProgramFiles%\OverlayAppFirewall` and `%ProgramFiles%\OverlayElevationGate`; state is under the corresponding `%ProgramData%` folders. SYSTEM/Administrators can write protected code/state. Authorized users receive read/query/start rights and Modify rights only for their own SID lease directory. No account name, machine name, install-folder location or existing service is a prerequisite. The elevation helper has Automatic startup for stale-journal recovery; firewall has Manual startup and starts on demand. Boot recovery never opens the Manager.

| Option | Factory default | Coverage |
|---|---|---|
| Enabled | ON | App-owned ordinary protection and restoration |
| Toasts | ON | Journaled per-user app-toast policy while a supported game is open |
| Focus timeout | ON | Temporary session ForegroundLockTimeout; Windows can reject it |
| Firewall notifications | ON | Journaled Domain/Private/Public NotifyOnListen, without changing rules |
| Route always | ON | Route eligible fresh common alerts without activating them |
| Alert display | Auto | Select an actual upper display; dynamic device IDs |
| Input grace | 2500 ms | Preserve deliberate switching/clicks |
| Global elevation gate | OFF | Experimental, separate unvalidated Appinfo broker operation |

Supported game processes are iRacingSim64DX11, Le Mans Ultimate, acs, acs_x86 and AssettoCorsaEVO. Game-dependent components require a game in the client's session. Launchers and unrelated sessions do not activate them. Routing can operate independently. When a destination disconnects, moved windows return to their original display or a visible primary area.

Security/consent/anti-cheat, games, shell surfaces, OverlayApp, known overlays and pass-through/noactivate windows are excluded. Input hooks forward every event unchanged. External app processes are never killed. Movement does not activate or raise windows. A popup may appear briefly before detection; elevated windows, system-feature notifications and managed policy can reject ordinary protection.

Status reports Windows, Routing, Toasts, Focus, Firewall, UAC and Setup separately. ON is the user's enabled preference; it is not confirmation of every component. Missing prerequisites explicitly degrade ordinary component status, and unconfirmed UAC is reported as not blocked. A confirmed policy value still requires behavioral validation. `Pending` means unresolved restoration, not ordinary active journal ownership.

The gate writes and flushes a recovery journal before any Appinfo mutation. The revised transaction requests a normal stop before changing startup configuration, then stops again to close trigger restart races. A separate SYSTEM watchdog is ready before activation. OFF, last-client expiry, service death and boot recover the original start/running state. Failures latch durably: closing/reopening the Manager or toggling the option does not silently retry; a personally approved setup Retry is needed after Windows recovery. Neither service nor watchdog kills Appinfo's host.

No UAC policy or secure-desktop setting is changed. Existing elevated tokens, services and scheduled tasks are outside the gate. Because stopping Appinfo can affect legitimate app activation as well as elevation, this feature remains experimental and OFF in the factory distribution. [Live acceptance and recovery limits](UAC-FEASIBILITY.md) must be read before testing it.
