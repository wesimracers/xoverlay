# XOverlay repository scope

Destination: https://github.com/wesimracers/xoverlay (existing public repository).
The product remains OverlayApp. Current application source is in `main/`; the Windows executable is in `releases/windows-x64/`. Files excluded from publication remain in their original local locations.

## Audited reduction

The first local import contained 2,689 files and 296,136,746 bytes. It included 2,149 files from other overlay projects under `source/`, 380 historical version files and 39 research artifacts. These 2,568 files are not required to run or build the current application. Their Git histories, assets and snapshots are retained locally and excluded from the publication ancestry.

This publication contains **119 files**: 67 current application/helper source and configuration files; 26 tests and fixtures; 9 current build, packaging, setup and verification utilities; 8 bundled-component license texts; 4 Windows distribution files; and 5 root documentation/configuration/license files. This reduces the file count by 95.6%.

## Dependency evidence

- `main/main.py` starts the Manager. Current Python modules and test imports resolve from `main/` and the pinned packages in `main/requirements.txt`.
- `main/build.py` calls `tools/build_protection_release.py`. That builder compiles the protection sources under `main/protection/`, then freezes the Python application with its factory configuration and exact helper resources. It does not read `source/`, `versions/` or historical research.
- `pyirsdk` is installed from `main/requirements.txt`; the old `source/pyirsdk` checkout is not a runtime/build dependency. Test data required by current country/RPM tests is retained in `tests/fixtures/`.
- Static inspection verifies 39 source modules against the distributed executable and verifies its embedded installer/helper hashes. The executable includes Python 3.12, QtCore, QtWidgets, QtMultimedia, guard, setup and factory resources. No GUI or administrative setup was launched for this audit.
- Third-party runtime license texts are retained in `licenses/`. Other external overlay projects are not used by the distributed application and are omitted.

## Other removed excess

`outputs/` contains old machine installation notes. Eight historical or workstation-specific tools, two generated test screenshots, the obsolete PyInstaller spec, a personal setup-status report and a one-off profile-encoding repair utility are omitted. The active builder constructs its own PyInstaller command and does not use that old spec. Current build/packaging code excludes the one-off repair utility. Historical regression notes referenced in comments remain available in the preserved local research archive; they are not executed or required by the tests.

All 26 current test/fixture files and the 9 retained development utilities remain available to develop and validate the product. Historical tool files excluded: `SYNC_IRACING_VOICEMEETER_27_27B.ps1`, `audit_relative_captures.py`, `build_racechat_release.py`, `build_release.py`, `freeze_protection_release.py`, `replay_overlay_checks.py`, `verify_protection_language.py`, `verify_protection_ui.py`.

Personal settings, credentials, DPAPI stores, real `.env` files, telemetry captures, runtime databases/logs, installed dependencies, caches and obsolete generated releases are excluded. The current factory configuration is retained.

## History and publication

The existing remote LICENSE and initial commit are preserved. A clean publication commit is based on remote commit `b2e6c99c8480c444d9fbd4e288dcf91795bb18af`; the broad local import `0b2ea2dab84ac76e960d44ad014ea0fdcd45ba7d` is retained locally and is not an ancestor of the reduced publication. No force-push or deletion of original working files is required.

The prepared tree is not proof of a completed upload. The initial connector attempt on 2026-10-14 returned HTTP 403. A later authenticated check reported write access and successfully stored the current Weather module as a Git blob. Publication is complete only after the main branch and all distribution contents are independently verified.
