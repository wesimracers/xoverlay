"""Inspect release bytes without launching the application or privileged installer."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import os
import pefile
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
stage = ROOT / (sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else "build-staging-portable")
release = stage / "release"
source = ROOT / "main"
archive = CArchiveReader(str(release / "OverlayApp.exe"))
pyz = archive.open_embedded_archive("PYZ.pyz")
checked = []
for path in source.glob("*.py"):
    if path.stem in pyz.toc:
        actual = pyz.extract(path.stem)
        expected = compile(path.read_text(encoding="utf-8-sig"), actual.co_filename, "exec")
        assert actual == expected, path.name
        checked.append(path.name)
assert len(checked) >= 35, checked
assert not any(name.lower().endswith(("overlay.json", "database.json", "secrets.dpapi")) and name != "factory-overlay.json" for name in archive.toc)
manifest = json.loads((release / "protection/setup-manifest.json").read_text())
installer = release / "protection/OverlayProtectionSetup.exe"
for key, file in (("installer", installer), ("firewall", release / "protection/bin/OverlayRaceFirewall.exe"), ("elevation", release / "protection/bin/OverlayElevationGate.exe")):
    assert hashlib.sha256(file.read_bytes()).hexdigest() == manifest[key], key
    assert file.read_bytes() == (source / file.relative_to(release)).read_bytes(), key
pe = pefile.PE(str(installer))
assert pe.FILE_HEADER.Machine == 0x8664
manifests = []
for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
    if entry.id == 24:
        for resource in entry.directory.entries:
            for language in resource.directory.entries:
                data = language.data.struct
                manifests.append(pe.get_data(data.OffsetToData, data.Size))
assert any(b'level="requireAdministrator"' in data and b'uiAccess="false"' in data for data in manifests)
# A direct, ordinary console inspector avoids shell command parsing entirely.
inspector = stage / "InspectSetupResources.exe"
csc = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
subprocess.run([str(csc), "/nologo", "/target:exe", "/platform:x64", "/out:" + str(inspector), str(ROOT / "tools/InspectSetupResources.cs")], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
result = subprocess.run([str(inspector), str(installer)], capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
resources = dict(line.strip().split(":", 1) for line in result.stdout.splitlines() if ":" in line)
assert resources["Firewall"] == manifest["firewall"]
assert resources["Elevation"] == manifest["elevation"]
assert resources["Setup"] == hashlib.sha256((source / "protection/SetupProtection.ps1").read_bytes()).hexdigest()
report = {"python_modules_verified": checked, "installer_require_administrator": True, "embedded_resources": resources, "helper_manifest": manifest,
          "application_sha256": hashlib.sha256((release / "OverlayApp.exe").read_bytes()).hexdigest(), "application_or_setup_launched": False}
(stage / "artifact-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(f"Verified {len(checked)} frozen source modules, x64 administrative manifest and exact embedded helper/setup resources; no application/setup launched.")
