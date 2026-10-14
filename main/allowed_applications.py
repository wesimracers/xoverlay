"""User-selected ordinary-window exceptions and deliberate, non-elevated launches."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess

DEFAULT_ALLOWED = [
    {"label": "Apple Music", "process": "AppleMusic", "path": "", "target": ""},
    {"label": "Notes", "process": "Microsoft.Notes", "path": "", "target": ""},
    {"label": "Notepad", "process": "Notepad", "path": "", "target": ""},
    {"label": "Snipping Tool", "process": "SnippingTool", "path": "", "target": ""},
    {"label": "Windows PowerShell", "process": "powershell", "path": "", "target": "builtin:powershell"},
    {"label": "PowerShell", "process": "pwsh", "path": "", "target": ""},
    {"label": "Console windows (shared host)", "process": "conhost", "path": "", "target": ""},
    {"label": "OpenConsole (shared host)", "process": "OpenConsole", "path": "", "target": ""},
    {"label": "Windows Terminal (shared host)", "process": "WindowsTerminal", "path": "", "target": ""},
]


def normalize(entries):
    result = []
    seen = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        label, process, path, target = (str(entry.get(key, "")).strip() for key in ("label", "process", "path", "target"))
        if not re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", process) and process:
            continue
        if process.lower().endswith(".exe"):
            process = process[:-4]
        if path and (not Path(path).is_absolute() or Path(path).suffix.lower() != ".exe"):
            continue
        if target.startswith("aumid:") and not re.fullmatch(r"[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+", target[6:]):
            continue
        if target and target != "builtin:powershell" and not target.startswith("aumid:") and target != path:
            continue
        if not process and not path:
            continue
        key = (process.lower(), path.lower(), target.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append({"label": label[:160] or process or Path(path).stem, "process": process, "path": path, "target": target})
    return result[:128]


def from_executable(path):
    path = Path(path).resolve()
    return normalize([{"label": path.stem, "process": "", "path": str(path), "target": str(path)}])[0]


def guard_exceptions(entries):
    entries = normalize(entries)
    return ([entry["process"] for entry in entries if entry["process"]],
            [entry["path"] for entry in entries if entry["path"]])


def launch(entry):
    entries = normalize([entry])
    if not entries or not entries[0]["target"]:
        raise ValueError("Select the installed app with Find installed apps, or add its executable first.")
    target = entries[0]["target"]
    if target == "builtin:powershell":
        target = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    elif target.startswith("aumid:"):
        target = "shell:AppsFolder\\" + target[6:]
    elif not Path(target).is_file():
        raise ValueError("The selected executable is no longer available.")
    # The ordinary Windows open verb may require personal approval; never use runas.
    os.startfile(target)


def installed_apps():
    """Read the current user's packaged apps; no activation, install or elevation."""
    script = r"""$ErrorActionPreference='Stop';$packages=@{};foreach($package in Get-AppxPackage){$packages[$package.PackageFamilyName]=$package};$result=@();foreach($app in Get-StartApps){if($app.AppID -notmatch '^([A-Za-z0-9_.-]+)!([A-Za-z0-9_.-]+)$'){continue};$family=$Matches[1];$id=$Matches[2];$package=$packages[$family];if(-not $package){continue};try{$manifest=[xml]([IO.File]::ReadAllText((Join-Path $package.InstallLocation 'AppxManifest.xml')));$definition=@($manifest.Package.Applications.Application)|Where-Object {$_.Id -eq $id};$exe=[string]$definition.Executable;if(-not $exe -or $exe -match '\$'){continue};$path=Join-Path $package.InstallLocation $exe;if(-not(Test-Path -LiteralPath $path)){continue};$result+=@{label=[string]$app.Name;process='';path=$path;target=('aumid:'+ $app.AppID)}}catch{}};ConvertTo-Json -InputObject @($result) -Depth 3 -Compress"""
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);" + script
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    return normalize(json.loads(result.stdout.lstrip("\ufeff")))
