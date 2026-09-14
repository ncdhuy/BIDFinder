"""Serve the checked-out apps/web directory for local frontend verification."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class DevelopmentRequestHandler(SimpleHTTPRequestHandler):
    server_version = "BIDFinderLocalWeb/1.0"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()

    web_root = Path(__file__).resolve().parents[1] / "apps" / "web"
    if not web_root.is_dir():
        raise SystemExit(f"frontend directory not found: {web_root}")

    handler = partial(DevelopmentRequestHandler, directory=str(web_root))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {web_root} at http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
