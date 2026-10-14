"""Build a separate reviewable release; never stop processes or touch dist."""
import importlib.util
import hashlib
import shutil
import subprocess
import sys
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / (sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else "build-staging-portable")
OUT = STAGE / "release"
CSC = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


def main():
    source = ROOT / "main/protection"
    OUT.mkdir(parents=True, exist_ok=True)
    common = [str(CSC), "/nologo", "/target:winexe", "/platform:x64"]
    def compile_helper(arguments):
        subprocess.run(arguments, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    compile_helper(common + [f"/out:{source / 'bin/OverlayRaceGuard.exe'}",
                   "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:System.Runtime.Serialization.dll",
                   "/r:System.ServiceProcess.dll"] + [str(source / n) for n in
                   ("OverlayRaceGuard.cs", "GuardIntegration.cs", "ElevationGateProtocol.cs", "WindowRouting.cs", "ToastPolicy.cs", "MachineProtocol.cs", "FakeToastBackend.cs")])
    compile_helper(common + [f"/out:{source / 'bin/OverlayElevationGate.exe'}",
                   "/r:System.ServiceProcess.dll", "/r:System.Runtime.Serialization.dll",
                   str(source / "OverlayElevationGate.cs"), str(source / "ElevationGateProtocol.cs")])
    gate_hash = STAGE / "GateHash.txt"
    gate_hash.write_text(hashlib.sha256((source / "bin/OverlayElevationGate.exe").read_bytes()).hexdigest(), encoding="ascii")
    compile_helper(common + [f"/out:{source / 'InstallElevationGate.exe'}",
                   f"/win32manifest:{source / 'Installer.manifest'}",
                   f"/resource:{source / 'InstallElevationGate.ps1'},Install",
                   f"/resource:{gate_hash},GateHash", str(source / "InstallElevationGate.cs")])
    compile_helper(common + [f"/out:{source / 'bin/OverlayRaceFirewall.exe'}",
                   "/r:System.ServiceProcess.dll", "/r:System.Runtime.Serialization.dll",
                   f"/resource:{source / 'FirewallProfiles.ps1'},FirewallProfiles",
                   *[str(source / name) for name in ("OverlayRaceFirewall.cs", "ToastPolicy.cs", "MachineProtocol.cs", "FakeToastBackend.cs")]])
    hash_file = STAGE / "FirewallHash.txt"
    hash_file.write_text(hashlib.sha256((source / "bin/OverlayRaceFirewall.exe").read_bytes()).hexdigest(), encoding="ascii")
    compile_helper(common + [f"/out:{source / 'InstallFirewallHelper.exe'}", "/r:System.Windows.Forms.dll",
                   f"/win32manifest:{source / 'Installer.manifest'}",
                   f"/resource:{source / 'InstallFirewallHelper.ps1'},Install",
                   f"/resource:{source / 'UninstallFirewallHelper.ps1'},Uninstall",
                   f"/resource:{hash_file},FirewallHash", str(source / "InstallFirewallHelper.cs")])
    if "--skip-helper-self-tests" not in sys.argv:
        for name in ("OverlayRaceGuard", "OverlayRaceFirewall", "OverlayElevationGate"):
            subprocess.run([str(source / f"bin/{name}.exe"), "--self-test"],
                           creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    setup = source / "OverlayProtectionSetup.exe"
    compile_helper(common + [f"/out:{setup}", "/r:System.Runtime.Serialization.dll",
                   f"/win32manifest:{source / 'Setup.manifest'}",
                   f"/resource:{source / 'SetupProtection.ps1'},Setup",
                   f"/resource:{source / 'bin/OverlayRaceFirewall.exe'},Firewall",
                   f"/resource:{source / 'bin/OverlayElevationGate.exe'},Elevation",
                   str(source / "OverlayProtectionSetup.cs")])
    manifest = {"schema": 1, "installer": hashlib.sha256(setup.read_bytes()).hexdigest(),
                "firewall": hashlib.sha256((source / "bin/OverlayRaceFirewall.exe").read_bytes()).hexdigest(),
                "elevation": hashlib.sha256((source / "bin/OverlayElevationGate.exe").read_bytes()).hexdigest()}
    (source / "setup-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if "--helpers-only" in sys.argv:
        shutil.copytree(source, OUT / "protection", dirs_exist_ok=True)
        shutil.copy2(ROOT / "tools/UpdateOverlayProtection.ps1", OUT / "UpdateOverlayProtection.ps1")
        shutil.copy2(ROOT / "tools/UpdateElevationGate.ps1", OUT / "UpdateElevationGate.ps1")
        print("Updated, self-tested helpers:", OUT / "protection")
        return
    module_spec = importlib.util.spec_from_file_location("build_config", ROOT / "main/build.py")
    config = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(config)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
               "--name", "OverlayApp", "--hidden-import", "irsdk", "--distpath", str(OUT),
               "--workpath", str(STAGE / "work"), "--specpath", str(STAGE),
               "--add-data", str(source / "bin/OverlayRaceGuard.exe") + ";protection/bin",
               "--add-data", str(source / "bin/config.json") + ";protection/bin", str(ROOT / "main/main.py")]
    command[-1:-1] = ["--add-data", str(setup) + ";protection",
                      "--add-data", str(source / "setup-manifest.json") + ";protection",
                      "--add-data", str(ROOT / "main/factory-overlay.json") + ";."]
    with (STAGE / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(command, cwd=ROOT / "main", env=config._pyinstaller_env(),
                       stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    analysis = (STAGE / "work/OverlayApp/Analysis-00.toc").read_text(encoding="utf-8")
    assert "('icuuc.dll'," not in analysis.lower(), "Unsafe ICU DLL"
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(OUT / "OverlayApp.exe"))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    for name in ("manager", "race_protection", "administrative_setup", "core", "racechat_profile_sync", "relative", "standings", "rpm", "racechat", "sector_timing"):
        code = pyz.extract(name)
        expected = compile((ROOT / f"main/{name}.py").read_text(encoding="utf-8-sig"), code.co_filename, "exec")
        assert code == expected, name
    for name in ("protection/bin/OverlayRaceGuard.exe", "protection/bin/config.json", "protection/OverlayProtectionSetup.exe", "protection/setup-manifest.json"):
        assert archive.extract(name.replace("/", "\\")) == (ROOT / "main" / name).read_bytes(), name
    assert archive.extract("factory-overlay.json") == (ROOT / "main/factory-overlay.json").read_bytes()
    # User settings are only copied to this separate release, never merged over dist.
    if "--include-user-settings" in sys.argv:
        for name in ("overlay.json", "database.json", "blacklist.json", "race_review_state.json"):
            original = ROOT / "dist" / name
            if original.exists() and not (OUT / name).exists():
                shutil.copy2(original, OUT / name)
    shutil.copytree(source, OUT / "protection", dirs_exist_ok=True)
    shutil.copy2(ROOT / "tools/UpdateOverlayProtection.ps1", OUT / "UpdateOverlayProtection.ps1")
    shutil.copy2(ROOT / "tools/UpdateElevationGate.ps1", OUT / "UpdateElevationGate.ps1")
    print("Built and bytecode-verified:", OUT / "OverlayApp.exe")


if __name__ == "__main__":
    main()
