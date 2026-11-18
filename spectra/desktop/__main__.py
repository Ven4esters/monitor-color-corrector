"""Entry point for the native app; --check is a hardware-free installation check."""

import argparse
import sys
from contextlib import nullcontext
from tempfile import TemporaryDirectory

from .. import __version__
from ..studio import Studio, state_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spectra Studio — настольная версия на PySide6")
    parser.add_argument(
        "--demo", action="store_true", help="виртуальные дисплеи без обращения к оборудованию"
    )
    parser.add_argument(
        "--check", action="store_true", help="проверить запуск Qt с временными демоданными и выйти"
    )
    parser.add_argument("--version", action="version", version=f"Spectra Studio {__version__}")
    args = parser.parse_args(argv)
    try:
        from PySide6.QtCore import QLibraryInfo, QLocale, QLockFile, QTimer, QTranslator
        from PySide6.QtWidgets import QApplication, QMessageBox

        from .ui import theme
        from .window import Window
    except ImportError as exc:
        parser.exit(
            1,
            f'Не удалось загрузить PySide6: {exc}\nЗапустите Start-Spectra.bat или установите настольную версию: python -m pip install ".[desktop]"\n',
        )
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Spectra Studio")
    app.setOrganizationName("Spectra")
    app.setApplicationVersion(__version__)
    QLocale.setDefault(QLocale(QLocale.Language.Russian))
    translation = QTranslator(app)
    if translation.load("qtbase_ru", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translation)
    theme(app)
    with TemporaryDirectory() if args.check else nullcontext(None) as temp:
        lock = None
        if not args.check:
            try:
                folder = state_dir()
                folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(None, "Spectra Studio", f"Нет доступа к папке состояния: {exc}")
                return 1
            lock = QLockFile(str(folder / "desktop.lock"))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                QMessageBox.warning(
                    None,
                    "Spectra Studio",
                    "Не удалось открыть журнал для работы. Проверьте права и закройте другой экземпляр Spectra Studio.",
                )
                return 1
        try:
            window = Window(lambda: Studio(demo=args.demo or args.check, directory=temp))
            app.aboutToQuit.connect(window.stop_worker)
            passed = []
            if args.check:

                def done(action, ok):
                    passed.append(ok and bool(window.state and window.state["demo"]))
                    QTimer.singleShot(0, window.close)

                window.operationFinished.connect(done)
            window.show()
            result = app.exec()
            if args.check:
                if not passed or not passed[0]:
                    return 1
                print("Spectra Studio: Qt и демонстрационные дисплеи готовы.")
            return result
        finally:
            if lock is not None:
                lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
