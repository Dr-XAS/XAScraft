from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import os
import secrets
import socket
import subprocess
import sys
import urllib.request

REPOSITORY = "Dr-XAS/XAScraft"
RELEASE_PREFIX = "xascraft-v"
SOURCE_ASSET = "xascraft-source.zip"
PYTHON_VERSION = "3.12.14"
NODE_VERSION = "24.21.0"
NODE_HASHES = {
    "darwin-arm64": "bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057",
    "darwin-x64": "1462cb3b3046b815cf8ea436d3da450ec1a9f11dac7e5a46b0ada5305d7e8097",
    "linux-x64": "6e1db87ef58b8819e5d5402eff1536491b18edd8eb7bee5ef7897876e88dc5ff",
    "win-x64": "158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541",
}


def default_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/XAScraft"
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "XAScraft"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "XAScraft"


def prepare_root(root: Path) -> None:
    for part in ("", "releases", "runtime", "run", "logs", "data", "backups", "cache"):
        directory = root / part
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            directory.chmod(0o700)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as out:
            if os.name != "nt":
                os.fchmod(out.fileno(), 0o600)
            json.dump(data, out, indent=2, ensure_ascii=True, allow_nan=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def exclusive_lock(path: Path):
    """A kernel-owned nonblocking lock; crashes never leave an unrecoverable lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another XAScraft operation is already running.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def python_in(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def runtime_env(root: Path, source: Path, metadata: dict, data: Path | None = None) -> dict:
    """Never inherit a developer's .env, hosted integration flags, or Python paths."""
    keep = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "COMSPEC",
            "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LOCALAPPDATA", "APPDATA",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
            "https_proxy", "http_proxy", "no_proxy")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    data = data or root / "data"
    env.update({
        "PYTHONPATH": str(source / "backend"), "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1", "XRAYLARCH_DATA_ROOT": str(data),
        "LARCHDIR": str(data / "larch"), "MPLCONFIGDIR": str(data / "matplotlib"),
        "XRAYLARCH_XRF_WORKERS": "2", "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1", "NEXT_TELEMETRY_DISABLED": "1",
        "NEXT_PUBLIC_APP_BASE_PATH": "", "NODE_ENV": "production",
        "XRAYLARCH_GIT_REVISION": metadata.get("revision") or "unknown",
        "APP_BUILD_SHA": metadata.get("revision") or metadata["content_sha256"],
        "APP_BUILD_DATE": metadata["created_at"],
        "APP_BUILD_COUNT": metadata["content_sha256"][:8],
    })
    return env


def run(args, *, cwd=None, env=None, log=None) -> None:
    args = [str(arg) for arg in args]
    print(f"Running: {Path(args[0]).name} {' '.join(args[1:5])}", flush=True)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    subprocess.run(args, cwd=cwd, env=env, stdout=log, stderr=log,
                   check=True, stdin=subprocess.DEVNULL, **options)


def get_url(url: str, *, timeout=30):
    # Only used for public distribution metadata and loopback manager requests.
    request = urllib.request.Request(url, headers={"User-Agent": "XAScraft-local/1"})
    return urllib.request.urlopen(request, timeout=timeout)


def available_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as sock:
            if os.name != "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No loopback port is available.")


def require_free_port(port: int) -> None:
    with socket.socket() as sock:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"Port {port} is in use. Stop the other application and retry. "
                               "XAScraft keeps its address stable so saved browser projects remain accessible.") from exc
