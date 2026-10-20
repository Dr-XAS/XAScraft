from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import uuid

from .common import (NODE_HASHES, NODE_VERSION, available_port, exclusive_lock,
                     prepare_root, python_in, read_json, require_free_port, run, runtime_env, write_json)
from .services import ServicePair, science_smoke
from .source import download, extract_zip, larch_wheel, latest_release, snapshot


def ensure_node(root: Path) -> Path:
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "win"}.get(platform.system())
    arch = {"x86_64": "x64", "AMD64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine())
    key = f"{system}-{arch}"
    if key not in NODE_HASHES:
        raise RuntimeError(f"Local edition does not yet support {key}. Bundled FEFF requires x86-64 on Linux/Windows.")
    name = f"node-v{NODE_VERSION}-{key}"
    parent = root / "runtime" / name
    node = parent / ("node.exe" if system == "win" else "bin/node")
    if node.is_file():
        return node
    with tempfile.TemporaryDirectory(dir=root / "cache", prefix="node-") as temp:
        temp = Path(temp)
        extension = "zip" if system == "win" else "tar.gz"
        archive = temp / (name + "." + extension)
        print(f"Downloading private Node.js {NODE_VERSION} ({key})…", flush=True)
        download(f"https://nodejs.org/dist/v{NODE_VERSION}/{archive.name}", archive, NODE_HASHES[key])
        if system == "win":
            extract_zip(archive, temp / "unpacked")
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(temp / "unpacked", filter="data")
        os.replace(temp / "unpacked" / name, parent)
    return node


def build_release(root: Path, release: Path, metadata: dict, uv: Path):
    node = ensure_node(root)
    metadata["node"] = str(node)
    source = release / "source"
    scratch = release / "verification-data"
    env = runtime_env(root, source, metadata, scratch)
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    env.update({"UV_CACHE_DIR": str(root / "cache/uv"), "UV_NO_CONFIG": "1"})
    log_path = root / "logs/install.log"
    print(f"Installing dependencies and building XAScraft. Details: {log_path}", flush=True)
    _, larch = larch_wheel(source)
    py = python_in(release / ".venv")
    with log_path.open("ab") as log:
        run([uv, "venv", "--python", sys.executable, release / ".venv"], env=env, log=log)
        constraints = source / "deploy/python-release-constraints.txt"
        run([uv, "pip", "install", "--python", py, "--constraint", constraints,
             "--build-constraint", constraints, "--requirement", source / "backend/requirements.txt", larch],
            cwd=source / "backend", env=env, log=log)
        run([uv, "pip", "check", "--python", py], env=env, log=log)
        import subprocess
        # Its own check, not larch-patches/installed.py: the installer runs from a snapshot
        # zip that carries the wheel and IDENTITY but not larch-patches/. The version to
        # expect is the snapshot's (from IDENTITY), and uv installed into a fresh venv.
        installed = subprocess.check_output(
            [str(py), "-I", "-c", "from importlib.metadata import version; print(version('xraylarch'))"],
            cwd=release, env=env, text=True).strip()
        if installed != metadata["larch_version"]:
            raise RuntimeError(f"Installed Larch {installed} is not the snapshot's Larch {metadata['larch_version']}.")
        frozen = subprocess.check_output([str(uv), "pip", "freeze", "--python", str(py)], env=env)
        (release / "python-packages.txt").write_bytes(frozen)
        npm = node.parent / ("node_modules/npm/bin/npm-cli.js" if os.name == "nt" else "../lib/node_modules/npm/bin/npm-cli.js")
        # Build dependencies are needed even though installed services run in production.
        run([node, npm, "ci", "--include=dev", "--no-audit", "--no-fund"],
            cwd=source / "frontend", env=env, log=log)
        run([node, npm, "run", "build"], cwd=source / "frontend", env=env, log=log)
    metadata.update(python=sys.version.split()[0], controller_python=sys.executable,
                    node_version=NODE_VERSION, ready=False)
    write_json(release / "release.json", metadata)
    ports = {"backend": available_port(18006), "frontend": available_port(13004)}
    pair = ServicePair(root, release, ports, data=scratch, log_prefix="verify")
    print("Checking the installed web app, bundled spectra and native FEFF…", flush=True)
    try:
        pair.start()
        metadata["verification"] = science_smoke(pair)
    finally:
        pair.stop()
        shutil.rmtree(scratch, ignore_errors=True)
    metadata["ready"] = True
    write_json(release / "release.json", metadata)


def activate(root: Path, release: Path) -> dict:
    """Commit point: candidate already verified; data backup precedes any switch."""
    metadata = read_json(release / "release.json", {})
    if not metadata.get("ready"):
        raise RuntimeError("Cannot activate an unverified release.")
    previous = read_json(root / "current.json")
    backup = None
    if previous:
        for port in previous["ports"].values():
            require_free_port(port)
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        backup = root / "backups" / name
        # Services are stopped and operation.lock excludes a concurrent start/install.
        shutil.copytree(root / "data", backup / "data")
        write_json(backup / "current.json", previous)
    current = {
        "release": release.name,
        "previous_release": previous["release"] if previous else None,
        "backup": str(backup) if backup else None,
        "ports": previous["ports"] if previous else {
            "frontend": available_port(3004), "backend": available_port(8006),
        },
    }
    write_json(root / "current.json", current)
    return current


def install_source(root: Path, source: Path, uv: Path, *, make_shortcuts=True) -> dict:
    prepare_root(root)
    # All versions share this lock with the supervisor's start/stop operations.
    with exclusive_lock(root / "run/operation.lock"):
        from .manager import manager_status
        status = manager_status(root)
        if status and (status.get("active") or status.get("running")):
            raise RuntimeError("Stop XAScraft in the Manager before installing an update.")
        current = read_json(root / "current.json")
        if current:
            # Also catches surviving services after an abruptly killed supervisor.
            # Never back up live data or terminate an unknown listener.
            for port in current["ports"].values():
                require_free_port(port)
        release = root / "releases" / uuid.uuid4().hex
        release.mkdir()
        try:
            metadata = snapshot(source, release / "source")
            build_release(root, release, metadata, uv)
            # Make the stable entry point before activation; it reads current.json at launch.
            from .shortcuts import write_dispatcher, create_shortcuts
            write_dispatcher(root)
            if make_shortcuts:
                create_shortcuts(root, release)
            current = activate(root, release)
            return {**current, "label": metadata["label"]}
        except BaseException:
            # Retain logs, leave active version/data untouched, reclaim failed build only.
            active = read_json(root / "current.json", {})
            if active.get("release") != release.name:
                shutil.rmtree(release, ignore_errors=True)
            raise


def install_update(root: Path, uv: Path, expected_tag: str) -> dict:
    latest = latest_release()
    if not latest or latest["tag"] != expected_tag:
        raise RuntimeError("The release changed since the update check. Check for updates again.")
    with tempfile.TemporaryDirectory(dir=root / "cache", prefix="update-") as temp:
        temp = Path(temp)
        archive = temp / "source.zip"
        download(latest["url"], archive, latest["sha256"])
        extract_zip(archive, temp / "source")
        metadata = read_json(temp / "source/xascraft-release.json", {})
        if metadata.get("label") != latest["tag"]:
            raise RuntimeError("Release metadata does not match the selected version.")
        return install_source(root, temp / "source", uv)
