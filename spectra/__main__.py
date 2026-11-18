import argparse
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from importlib.resources import as_file, files

from .backends.base import DisplayError
from .server import handler_for
from .studio import Studio


def main():
    parser = argparse.ArgumentParser(description="Spectra Studio — локальная калибровка мониторов")
    parser.add_argument(
        "--demo", action="store_true", help="виртуальные дисплеи без доступа к оборудованию"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="адрес сервера (для оборудования — только loopback)"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-browser", action="store_true", help="не открывать браузер автоматически"
    )
    args = parser.parse_args()
    local = args.host in ("127.0.0.1", "localhost")
    if not local and not args.demo:
        parser.error(
            "Для внешней сети укажите --demo. Управление реальными мониторами разрешено только локально."
        )
    if not 0 <= args.port <= 65535:
        parser.error("Порт должен быть числом от 0 до 65535.")
    # Python 3.12 supports as_file() for entire resource directories. This lets
    # the same server run from source, an installed wheel, or a single .pyz.
    with as_file(files("spectra").joinpath("web")) as web_root:
        try:
            studio = Studio(demo=args.demo)
            handler = handler_for(studio, local_only=local, web_root=web_root)
            server = ThreadingHTTPServer((args.host, args.port), handler)
        except (DisplayError, OSError) as exc:
            parser.exit(1, f"Spectra: {exc}\n")
        with server:
            url = f"http://{args.host}:{server.server_port}"
            print(
                f"Spectra Studio: {url} ({'деморежим' if studio.demo else 'локальные дисплеи'})",
                flush=True,
            )
            if not args.no_browser:
                threading.Timer(0.25, webbrowser.open, args=(url,)).start()
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
