#!/usr/bin/env python3
"""Cross-platform standalone desktop launcher for DeckGen Studio."""
import argparse
import os
import socket
import sys
import threading
import time
import webbrowser

_ROOT = os.path.dirname(os.path.abspath(__file__))
_GUI = os.path.join(_ROOT, "gui")
if _GUI not in sys.path:
    sys.path.insert(0, _GUI)

import uvicorn
from config import HOST, PORT


def _find_open_port(host: str, start_port: int, max_tries: int = 20) -> int:
    for offset in range(max_tries):
        port = start_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    return start_port


def _open_browser_when_ready(url: str) -> None:
    time.sleep(0.9)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch DeckGen Studio")
    parser.add_argument("--host", default=HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=PORT, help="Preferred port (default: 8766)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    port = _find_open_port(args.host, args.port)
    url = f"http://{args.host}:{port}/"
    print(f"DeckGen Studio listening on {url}")

    if not args.no_browser:
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    uvicorn.run("app:app", host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
