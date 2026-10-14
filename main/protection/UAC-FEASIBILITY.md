# Elevation gate: actual acceptance and recovery limits

The global Appinfo gate is a candidate, not proven administrative protection. **Factory default: OFF.** No live activation has confirmed Disabled/Stopped and no successfully active gate has passed OFF, close, crash or reboot restoration tests.

During the 2026-10-11 session, the older service repeatedly attempted activation and received Windows error 1061 when stopping Appinfo. Its configuration rollback restored Manual and reported Running with no remaining journal. Later the user reported that Apple Music, Screenshot and other applications could not open, showing the same service-control error. SCM logs show repeated Manual→Disabled→Manual pairs around those attempts, including between failed app-launch attempts. This establishes temporal association with the old gate; it does not establish the internal Windows failure mechanism or successful functional recovery.

The experimental preference and current user/session runtime flag were disabled for recovery. No new activation is authorized until app launching works again. A normal recovery approval request did not produce a consent window and was cancelled. The prepared `OverlayWindowsRecovery.exe` performs only a normal stop/disable of our own gate and normal Appinfo restart, preserving original Manual configuration. It performs no forced svchost termination, broad app repair, policy reset, logoff or reboot. Executing it from a personally opened administrative Task Manager task is the remaining recovery route if normal UAC cannot operate. Service status alone must not be presented as proof that application launching works.

The new source stops Appinfo before changing startup configuration and uses bounded retry for 1061. An independent watchdog and flushed journals cover partial operations. Failure latches now remain across option toggles/Manager restarts and require personally approved setup after recovery. These changes pass isolated simulations but have not repaired or proved this Windows installation. The new complete GUI candidate is staged separately; it has not replaced the live executable.

## Independent evidence

The earlier ordinary-popup live test routed a harmless MessageBox to the upper display by 231 ms while every foreground sample remained the iRacing process. It demonstrated routing with retained focus, allowing a brief initial visible appearance. The earlier protection OFF/ON test restored/reapplied ordinary firewall/toast components. Those observations do not prove zero-frame suppression, restoration after actual focus theft, Appinfo suppression or another user's login behavior.

Current test reports accompany the release. Python/Qt tests run offscreen with mocked controllers and temporary data. Service transaction suites use fake backends, and setup transaction tests replace SCM/ACL effects. Embedded resources, requireAdministrator manifest, hashes and frozen Python bytecode are inspected without launching the installer. These are build/logic checks, not Windows service acceptance.

## Remaining controlled acceptance

1. Recover Appinfo and personally confirm that previously failing applications launch. Verify no new gate-induced SCM configuration changes occur. Do not test the gate before this succeeds.
2. Through the normal app workflow, personally approve the reviewed setup installer on a clean/current Windows profile. Verify protected ACLs, service identity/hash, current SID metadata, repeat-open without approval, cancellation/retry and a second independently configured user.
3. Outside a game, explicitly enable the experimental gate only in a controlled test window. Record actual Appinfo state and actual refusal of a new elevation. Test UAC coverage separately from ordinary protection.
4. Verify exact original Appinfo configuration plus actual application activation after OFF, last Manager close, guard/service failure and restart/boot recovery. Preserve journals/logs on every failure; never clear a pending journal to force success.

Normal [UAC policy settings](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/user-account-control/settings-and-configuration) provide automatic denial for standard users. They do not supply the requested administrator-wide behavior without changing the account/security model. [Windows error 1061](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--1000-1299-) means the service cannot accept control messages at that time. [ControlService](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-controlservice) explains service control/transition errors. This candidate never automates consent or weakens secure desktop to obtain elevation.
