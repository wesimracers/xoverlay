"""Build into an isolated stage without touching any installed application."""
import os
from pathlib import Path
import subprocess
import sys


def _pyinstaller_env():
    env = os.environ.copy()
    if os.name == "nt":
        python_dir = os.path.dirname(sys.executable)
        windows_dir = env.get("SystemRoot", r"C:\Windows")
        paths = [python_dir, os.path.join(python_dir, "Scripts"),
                 os.path.join(windows_dir, "System32"), windows_dir,
                 os.path.join(windows_dir, "System32", "Wbem")]
        env["PATH"] = os.pathsep.join(path for path in paths if os.path.isdir(path))
    return env


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "tools/build_protection_release.py"),
                    "--stage", "build-staging-portable", *sys.argv[1:]], cwd=root, check=True)
