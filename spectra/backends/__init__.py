import sys

from .base import DisplayError


def native_backend():
    if sys.platform == "win32":
        from .windows import WindowsBackend

        return WindowsBackend()
    if sys.platform.startswith("linux"):
        from .linux import LinuxBackend

        return LinuxBackend()
    raise DisplayError(
        "Аппаратное управление доступно в Windows и в Linux с X11. Здесь доступен деморежим."
    )
