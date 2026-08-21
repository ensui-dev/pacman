#!/usr/bin/env python3
"""Entry point: ``python3 pac-man.py config.json`` boots the whole game.

Validates the argument and the config, then launches Reflex app (which reads
the resolved config path from ``$PACMAN_CONFIG``) and opens the browser. The
server runs in this process group, so the in-app Exit button (a SIGTERM to the
group) tears the whole thing down, this launcher included cleanly.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser

from game.config import load_config

HOST, PORT = "localhost", 3000
ROOT = os.path.dirname(os.path.abspath(__file__))


def _fail(message: str) -> None:
    """Print a clear error and exit non-zero (no traceback)."""
    print(f"pac-man: {message}", file=sys.stderr)
    sys.exit(1)


def _wait_for_port(host: str, port: int, timeout: float) -> bool:
    """Return True once something is listening on host:port within timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            sock.settimeout(1.0)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.5)
    return False


def main() -> None:
    """Validate input, launch the app, open the browser, wait for shutdown."""
    args = sys.argv[1:]
    if len(args) != 1:
        _fail("usage: python3 pac-man.py <config.json>")

    path = args[0]
    if not os.path.isfile(path):
        _fail(f"config file not found: {path}")
    try:
        load_config(path)               # fail fast with a clear message
    except Exception as exc:          # parser raises ParserError on bad config
        _fail(f"invalid config: {exc}")

    os.environ["PACMAN_CONFIG"] = os.path.abspath(path)

    reflex = os.path.join(os.path.dirname(sys.executable), "reflex")
    if not os.path.exists(reflex):
        _fail(
            "reflex is not installed in this environment, run `make install`"
        )

    print(f"pac-man: starting (config: {path}) …", flush=True)
    # No new session/group: the server stays in our group so the in-app Exit
    # button's group-SIGTERM brings this launcher down too.
    proc = subprocess.Popen([reflex, "run"], cwd=ROOT)

    try:
        if _wait_for_port(HOST, PORT, timeout=180):
            url = f"http://{HOST}:{PORT}"
            print(f"pac-man: opening {url}", flush=True)
            try:
                webbrowser.open(url)
            except Exception:
                print(f"pac-man: open {url} in your browser", flush=True)
        else:
            print("pac-man: the server did not start in time", file=sys.stderr)
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    print("pac-man: stopped.", flush=True)


if __name__ == "__main__":
    main()
