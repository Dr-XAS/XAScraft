from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hmac
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

from .common import exclusive_lock, prepare_root, read_json, write_json
from .services import ServicePair, request_json


def manager_status(root: Path):
    saved = read_json(root / "run/manager.json")
    if not saved:
        return None
    try:
        return request_json(f"http://127.0.0.1:{saved['port']}/api/status", token=saved["token"], timeout=2)
    except (OSError, ValueError):
        return None


def manager_request(root: Path, action: str, **options):
    saved = read_json(root / "run/manager.json")
    if not saved:
        raise RuntimeError("XAScraft Manager is not running.")
    return request_json(f"http://127.0.0.1:{saved['port']}/api/action", {"action": action, **options}, token=saved["token"])


def ensure_manager(root: Path):
    status = manager_status(root)
    if status and status["restart_required"]:
        if status.get("active") or status["busy"]:
            raise RuntimeError("Stop XAScraft before restarting its updated Manager.")
        manager_request(root, "quit")
        deadline = time.monotonic() + 15
        while manager_status(root) and time.monotonic() < deadline:
            time.sleep(0.2)
        status = None
    if status:
        return
    # A racing second launcher is harmless: serve() takes a lifetime kernel lock.
    entry = Path(__file__).resolve().parents[1] / "run.py"
    kwargs = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    with (root / "logs/manager.log").open("ab") as log:
        subprocess.Popen([sys.executable, str(entry), "--root", str(root), "serve"],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if manager_status(root):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Manager did not start. See {root / 'logs/manager.log'}")


def open_manager(root: Path):
    saved = read_json(root / "run/manager.json")
    webbrowser.open(f"http://127.0.0.1:{saved['port']}/{saved['token']}/")


class Manager:
    def __init__(self, root):
        self.root = root
        self.loaded_release = read_json(root / "current.json")["release"]
        self.pair = None
        self.busy = ""
        self.error = ""
        self.message = ""
        self.latest = None
        self.gate = threading.Lock()
        self.worker = None
        self.server = None

    def status(self):
        from .source import newer_release
        current = read_json(self.root / "current.json")
        metadata = read_json(self.root / "releases" / current["release"] / "release.json")
        return {"running": bool(self.pair and self.pair.healthy()),
                "active": bool(self.pair and self.pair.active()), "busy": self.busy,
                "error": self.error, "message": self.message, "latest": self.latest,
                "update_available": bool(self.latest and newer_release(metadata["label"], self.latest["tag"])),
                "label": metadata["label"], "release": current["release"],
                "restart_required": current["release"] != self.loaded_release,
                "url": f"http://127.0.0.1:{current['ports']['frontend']}",
                "data": str(self.root / "data"), "backup": current.get("backup"),
                "logs": str(self.root / "logs")}

    def dispatch(self, action, options):
        if action not in {"start", "stop", "check", "update", "quit"}:
            raise ValueError("Unknown manager action.")
        if not self.gate.acquire(blocking=False):
            raise RuntimeError("Another operation is in progress.")
        self.busy, self.error = action, ""
        self.worker = threading.Thread(target=self._work, args=(action, options), daemon=True)
        self.worker.start()

    def _work(self, action, options):
        try:
            if action == "check":
                from .source import latest_release
                self.latest = latest_release()
                self.message = ("Available: " + self.latest["tag"] if self.latest
                                else "No packaged XAScraft release is published yet. Source installation remains available.")
            elif action == "update":
                if self.pair:
                    raise RuntimeError("Stop XAScraft before updating. Save your work first.")
                if not self.latest or options.get("tag") != self.latest["tag"]:
                    raise RuntimeError("Check for updates and select the displayed release first.")
                if not self.status()["update_available"]:
                    raise RuntimeError("This is not a newer release. Automatic downgrades are disabled.")
                from .install import install_update
                uv = self.root / ("runtime/uv/uv.exe" if os.name == "nt" else "runtime/uv/uv")
                install_update(self.root, uv, self.latest["tag"])
                self.message = "Update verified and installed. Quit this Manager and reopen XAScraft. Your data was backed up."
            else:
                with exclusive_lock(self.root / "run/operation.lock"):
                    if action == "start":
                        if self.status()["restart_required"]:
                            raise RuntimeError("Quit this Manager and reopen XAScraft to load the new version.")
                        if self.pair and self.pair.healthy():
                            return
                        if self.pair:
                            self.pair.stop()
                        current = read_json(self.root / "current.json")
                        release = self.root / "releases" / current["release"]
                        self.pair = ServicePair(self.root, release, current["ports"])
                        self.pair.start()
                        self.message = "XAScraft is running on this computer."
                    else:
                        if self.pair:
                            self.pair.stop()
                            self.pair = None
                        self.message = "XAScraft is stopped."
                        if action == "quit":
                            self.server.shutdown()
        except Exception as exc:
            self.error = str(exc)
            if self.pair and not self.pair.healthy():
                self.pair.stop()
                self.pair = None
        finally:
            self.busy = ""
            self.gate.release()


def handler_for(manager, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # URLs contain a private capability; do not log them.

        def _path(self):
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected_host:
                return None
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + expected_host:
                return None
            path = urllib.parse.urlsplit(self.path).path
            bearer = self.headers.get("Authorization", "")
            if hmac.compare_digest(bearer, "Bearer " + token):
                return path
            if path.startswith("/" + token + "/"):
                return "/" + path[len(token) + 2:]
            return None

        def _send(self, status, body, content_type="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self._path()
            if path == "/":
                page = Path(__file__).with_name("manager.html").read_text(encoding="utf-8")
                self._send(200, page, "text/html")
            elif path == "/api/status":
                self._send(200, manager.status())
            elif path == "/api/logs":
                logs = {}
                for name in ("install.log", "app-backend.log", "app-frontend.log", "verify-backend.log", "verify-frontend.log"):
                    file = manager.root / "logs" / name
                    if file.exists():
                        with file.open("rb") as stream:
                            stream.seek(max(0, file.stat().st_size - 16000))
                            logs[name] = stream.read().decode("utf-8", errors="replace")
                self._send(200, logs)
            else:
                self._send(403, {"error": "Open XAScraft Manager using its installed shortcut."})

        def do_POST(self):
            if self._path() != "/api/action":
                self._send(403, {"error": "Request denied."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4096:
                    raise ValueError("Invalid request size.")
                data = json.loads(self.rfile.read(length))
                manager.dispatch(data["action"], data)
                self._send(202, {"accepted": True})
            except (KeyError, ValueError, TypeError, RuntimeError) as exc:
                self._send(409, {"error": str(exc)})
    return Handler


def serve(root: Path):
    prepare_root(root)
    with exclusive_lock(root / "run/manager.lock"):
        manager = Manager(root)
        token = secrets.token_urlsafe(32)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(manager, token))
        server.daemon_threads = True
        manager.server = server
        write_json(root / "run/manager.json", {"port": server.server_port, "token": token})
        def terminate(_signum, _frame):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)
        try:
            server.serve_forever(poll_interval=0.25)
        finally:
            # Do not abandon an install halfway through activation on normal shutdown.
            if manager.worker:
                manager.worker.join()
            if manager.pair:
                manager.pair.stop()
            server.server_close()
            (root / "run/manager.json").unlink(missing_ok=True)
