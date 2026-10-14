"""Package verified portable artifacts and an explicit, private-data-free source set."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
stage = ROOT / (sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else "build-staging-portable")
package = stage / "package/Overlay-portable"
package.mkdir(parents=True, exist_ok=True)
release = stage / "release"
for name in ("OverlayApp.exe", "UpdateOverlayProtection.ps1", "UpdateElevationGate.ps1"):
    shutil.copy2(release / name, package / name)
shutil.copytree(release / "protection", package / "protection", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("RepairProfileEncoding.cs"))
shutil.copy2(ROOT / "README.md", package / "README.md")
if (stage / "VALIDATION.md").exists():
    shutil.copy2(stage / "VALIDATION.md", package / "VALIDATION.md")
qa = package / "qa"; qa.mkdir(exist_ok=True)
for name in ("python-tests.txt", "setup-tests.txt", "firewall-profile-tests.txt", "artifact-verification.json", "build.log"):
    shutil.copy2(stage / name, qa / name)
if (stage / "clean-source-tests.txt").exists():
    shutil.copy2(stage / "clean-source-tests.txt", qa / "clean-source-tests.txt")
clean = stage / "source-qa/build-staging-clean"
if (clean / "artifact-verification.json").exists():
    shutil.copy2(clean / "artifact-verification.json", qa / "clean-source-artifact-verification.json")
    shutil.copy2(clean / "build.log", qa / "clean-source-build.log")
shutil.copytree(stage / "qa", qa, dirs_exist_ok=True)
for name in ("testes.txt", "gate-tests.txt", "firewall-tests.txt"):
    shutil.copy2(release / "protection/bin" / name, qa / name)
source_files = [ROOT / "README.md", ROOT / ".gitignore", ROOT / "main/AGENTS.md", ROOT / "main/requirements.txt", ROOT / "main/factory-overlay.json"]
source_files += sorted((ROOT / "main").glob("*.py"))
source_files += [path for path in sorted((ROOT / "main/protection").glob("*")) if path.suffix.lower() in (".cs", ".ps1", ".manifest", ".md") and path.name != "RepairProfileEncoding.cs"]
source_files += [ROOT / "main/protection/bin/config.json"]
source_files += sorted((ROOT / "tests").glob("*.py")) + sorted((ROOT / "tests").glob("*.ps1"))
source_files += sorted((ROOT / "tests/fixtures").glob("*.json"))
source_files += [ROOT / "tools/racechat_setup_browser.py"]
source_files += [ROOT / "tools" / name for name in ("build_protection_release.py", "verify_portable_release.py", "InspectSetupResources.cs", "verify_elevation_gate_ui.py", "package_portable_release.py", "UpdateOverlayProtection.ps1", "UpdateElevationGate.ps1")]
source_files = sorted(set(source_files))
source_zip = package / "Overlay-source.zip"
with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
    for file in source_files:
        archive.write(file, file.relative_to(ROOT).as_posix())
    assert all(Path(name).name not in ("overlay.json", "database.json", "secrets.dpapi", "settings.json") for name in archive.namelist())
report = {
    "source_files": {file.relative_to(ROOT).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in source_files},
    "portable_files": {file.relative_to(package).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(package.rglob("*")) if file.is_file() and file.name != "SHA256.json"},
}
(package / "SHA256.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
with zipfile.ZipFile(stage / "package/Overlay-portable.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(package.rglob("*")):
        if file.is_file():
            archive.write(file, "Overlay-portable/" + file.relative_to(package).as_posix())
print("Packaged complete GUI and", len(source_files), "source files without personal settings:", package)
