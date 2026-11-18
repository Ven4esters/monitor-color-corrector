"""Windows CI: exercise the actual .bat from a different working directory."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def launch(folder, cwd, *, offline=False):
    env = dict(os.environ, SPECTRA_NO_PAUSE="1", QT_QPA_PLATFORM="offscreen")
    if offline:
        env["PIP_NO_INDEX"] = "1"
    process = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(folder / "Start-Spectra.bat"), "--check"],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=420,
    )
    print(process.stdout)
    if process.returncode:
        # Include the final diagnostic in the check result, not just the runner's exit code.
        tail = "\n".join(process.stdout.splitlines()[-14:])
        message = tail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=Start-Spectra.bat ({process.returncode})::{message}")
        raise SystemExit(1)


def main(mode):
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory() as tmp:
        elsewhere = Path(tmp)
        folder = root
        if mode == "standalone":
            folder = elsewhere / "Студия с пробелами"
            folder.mkdir()
            shutil.copy2(root / "Start-Spectra.bat", folder)
        launch(folder, elsewhere)
        stamp = folder / ".venv/spectra-build.txt"
        assert (
            stamp.read_text()
            .strip()
            .startswith("archive-" if mode == "standalone" else "checkout-")
        )
        before = stamp.stat().st_mtime_ns
        launch(folder, elsewhere, offline=True)
        assert stamp.stat().st_mtime_ns == before, "Second launch reinstalled the app"


if __name__ == "__main__":
    main(sys.argv[1])
