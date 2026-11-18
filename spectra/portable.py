"""Build the downloadable, dependency-free Python 3.12 zipapp without shipping user state."""

import argparse
from functools import lru_cache
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

FILENAME = "Spectra-Studio.pyz"
# An explicit manifest, not an archive of the working directory or the user's home.
CONTENTS = (
    "__init__.py",
    "__main__.py",
    "color.py",
    "studio.py",
    "server.py",
    "portable.py",
    "backends/__init__.py",
    "backends/base.py",
    "backends/backlight.py",
    "backends/ddc_linux.py",
    "backends/ddc_windows.py",
    "backends/demo.py",
    "backends/edid.py",
    "backends/linux.py",
    "backends/windows.py",
    "web/index.html",
    "web/studio.css",
    "web/studio.js",
    "web/assets/alpine-lake.jpg",
    "web/assets/brand.svg",
    "web/assets/icons.svg",
    "web/assets/monitor-aqua.svg",
    "web/assets/monitor-violet.svg",
    "web/assets/fonts/OFL.txt",
    "web/assets/fonts/manrope-cyrillic-wght-normal.woff2",
    "web/assets/fonts/manrope-latin-wght-normal.woff2",
)


@lru_cache(maxsize=1)
def archive_bytes() -> bytes:
    package = files("spectra")
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "__main__.py",
            "import sys\nif sys.version_info < (3, 12):\n"
            '    raise SystemExit("Spectra Studio requires Python 3.12 or later.")\n'
            "from spectra.__main__ import main\nmain()\n",
        )
        for entry in CONTENTS:
            archive.writestr("spectra/" + entry, package.joinpath(*entry.split("/")).read_bytes())
    return stream.getvalue()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Собрать переносимое приложение Spectra Studio")
    parser.add_argument("output", type=Path, nargs="?", default=Path(FILENAME))
    path = parser.parse_args().output
    path.write_bytes(archive_bytes())
    print(path.resolve())
