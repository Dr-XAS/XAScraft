"""Explicit source snapshots and the XAScraft-only release channel."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from . import PROTOCOL
from .common import REPOSITORY, RELEASE_PREFIX, SOURCE_ASSET, get_url, write_json

ROOT_FILES = {"README.md", "LICENSE", "NOTICE"}
SOURCE_DIRS = ("backend/xraylarch_web", "frontend", "examples", "installers/local")
# A checkout carries the Larch patch queue; a snapshot carries what it builds: the patched
# Larch wheel and its IDENTITY (pin, patches, version), in LARCH_DIR.
BUILD_SCRIPT = "larch-patches/build.py"
LARCH_DIR = "patched-larch"
EXTRA_FILES = {"backend/requirements.txt", "deploy/python-release-constraints.txt",
               "docs/local-installation.md", "Install.command", "Install Windows.cmd"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", ".pytest_cache",
             "test-results", "playwright-report", "build", "dist"}


def source_git(source: Path, *args: str) -> str | None:
    """An archive nested inside another checkout does not belong to that Git tree."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        top = subprocess.check_output(["git", "-C", str(source), "rev-parse", "--show-toplevel"],
                                      env=env, stderr=subprocess.DEVNULL).decode().strip()
        if Path(top).resolve() != source.resolve():
            return None
        return subprocess.check_output(["git", "-C", str(source), *args],
                                       env=env, stderr=subprocess.DEVNULL).decode()
    except (OSError, subprocess.CalledProcessError):
        return None


def allowed_source(name: str) -> bool:
    path = PurePosixPath(name)
    if any(p in SKIP_DIRS or p.startswith(".next") or p.startswith(".env") for p in path.parts):
        return False
    if path.suffix in {".pyc", ".pyo", ".tsbuildinfo"} or path.name in {".DS_Store", "next-env.d.ts"}:
        return False
    return name in ROOT_FILES | EXTRA_FILES or any(name.startswith(d + "/") for d in SOURCE_DIRS)


def source_files(source: Path) -> list[Path]:
    candidates = []
    files = source_git(source, "ls-files", "-z")
    tracked = set(files.split("\0")) if files is not None else None
    # Restrict examples to tracked distribution data when installing a working tree.
    for folder in SOURCE_DIRS:
        start = source / folder
        if not start.is_dir():
            raise RuntimeError(f"Incomplete source distribution: missing {folder}")
        for directory, subdirs, files in os.walk(start, followlinks=False):
            subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS and not d.startswith((".next", ".env"))
                          and not (Path(directory) / d).is_symlink()]
            for name in files:
                path = Path(directory) / name
                relative = path.relative_to(source).as_posix()
                if folder == "examples" and tracked is not None and relative not in tracked:
                    continue
                if allowed_source(relative):
                    if path.is_symlink():
                        raise RuntimeError(f"Source symlinks are not supported: {relative}")
                    candidates.append(path)
    candidates.extend(source / name for name in ROOT_FILES | EXTRA_FILES if (source / name).is_file())
    return sorted(set(candidates), key=lambda p: p.relative_to(source).as_posix())


def build_patched_larch(source: Path, destination: Path) -> None:
    """Run the checkout's build script and keep its wheel and IDENTITY. Needs git and the
    network, unless XASCRAFT_LARCH_UPSTREAM names a local xraylarch clone."""
    print("Building the patched Larch (larch-patches/build.py)…", flush=True)
    with tempfile.TemporaryDirectory(prefix="xascraft-larch-") as temp:
        out = Path(temp) / "larch"
        command = [sys.executable, "-I", str(source / BUILD_SCRIPT), "--out", str(out)]
        if os.environ.get("XASCRAFT_LARCH_UPSTREAM"):
            command += ["--upstream", os.environ["XASCRAFT_LARCH_UPSTREAM"]]
        result = subprocess.run(command, cwd=temp, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            raise RuntimeError("Building the patched Larch failed:\n"
                               + (result.stdout + result.stderr).strip())
        destination.mkdir(parents=True)
        shutil.copy2(out / "IDENTITY", destination / "IDENTITY")
        for wheel in (out / "dist").glob("xraylarch-*.whl"):
            shutil.copy2(wheel, destination / wheel.name)


def larch_wheel(root: Path) -> tuple[str, Path]:
    """The patched Larch version (from IDENTITY) and the one wheel built with it."""
    folder = root / LARCH_DIR
    try:
        version = json.loads((folder / "IDENTITY").read_text())["version"]
    except (OSError, ValueError, KeyError):
        raise RuntimeError(f"Incomplete source distribution: missing {LARCH_DIR}/IDENTITY") from None
    wheel = folder / f"xraylarch-{version}-py3-none-any.whl"
    if sorted(folder.glob("*.whl")) != [wheel]:
        raise RuntimeError(f"Incomplete source distribution: {LARCH_DIR} must hold one wheel, Larch {version}")
    return version, wheel


def snapshot(source: Path, destination: Path, *, label: str | None = None) -> dict:
    source = source.resolve()
    original = source / "xascraft-release.json"
    prior = json.loads(original.read_text()) if original.exists() else None
    if prior is not None and prior.get("protocol") != PROTOCOL:
        raise RuntimeError(f"This source uses installer protocol {prior.get('protocol')}; "
                           f"this installer needs protocol {PROTOCOL}. Download a current release.")
    files = source_files(source)
    if prior is not None:
        # A packaged snapshot already holds the built Larch; it is never rebuilt.
        larch = source / LARCH_DIR
        if not larch.is_dir():
            raise RuntimeError(f"Incomplete source distribution: missing {LARCH_DIR}")
        files += sorted(path for path in larch.iterdir() if path.is_file() and not path.is_symlink())
    elif not (source / BUILD_SCRIPT).is_file():
        raise RuntimeError(f"Incomplete source distribution: missing {BUILD_SCRIPT}")
    destination.mkdir(parents=True, exist_ok=False)
    for path in files:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if prior is None:
        build_patched_larch(source, destination / LARCH_DIR)
    larch_version, _ = larch_wheel(destination)
    # Hash the copies, so metadata identifies installed bytes even during local edits.
    digest = hashlib.sha256()
    for path in sorted((p for p in destination.rglob("*") if p.is_file()),
                       key=lambda p: p.relative_to(destination).as_posix()):
        name = path.relative_to(destination).as_posix()
        digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    if prior is not None:
        if prior.get("content_sha256") != digest.hexdigest() or prior.get("larch_version") != larch_version:
            raise RuntimeError("Source manifest does not match its files.")
        return prior
    revision = (source_git(source, "rev-parse", "HEAD") or "").strip()
    return {
        "protocol": PROTOCOL, "repository": REPOSITORY,
        "label": label or f"local-{digest.hexdigest()[:12]}",
        "revision": revision, "content_sha256": digest.hexdigest(),
        # The patch queue's identity, so app-only changes keep the same Larch version.
        "larch_version": larch_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_zip(archive: Path, destination: Path, *, max_bytes=2_000_000_000) -> None:
    """Extract source/Node archives without traversal, links, or zip bombs."""
    with zipfile.ZipFile(archive) as bundle:
        total = 0
        seen = set()
        for entry in bundle.infolist():
            name = entry.filename
            path = PurePosixPath(name)
            total += entry.file_size
            if ("\\" in name or ":" in name or path.is_absolute() or ".." in path.parts
                    or any(p.endswith((".", " ")) for p in path.parts)
                    or stat.S_ISLNK(entry.external_attr >> 16) or total > max_bytes
                    or name.lower() in seen):
                raise RuntimeError("Unsafe or oversized distribution archive.")
            seen.add(name.lower())
        for entry in bundle.infolist():
            target = destination / entry.filename
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as inp, target.open("xb") as out:
                    shutil.copyfileobj(inp, out)
                if entry.external_attr >> 16 & 0o111:
                    target.chmod(0o755)


def download(url: str, target: Path, expected: str, *, max_bytes=2_000_000_000) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("A SHA-256 distribution digest is required.")
    digest = hashlib.sha256()
    count = 0
    try:
        with get_url(url, timeout=60) as inp, target.open("xb") as out:
            while chunk := inp.read(1024 * 1024):
                count += len(chunk)
                if count > max_bytes:
                    raise RuntimeError("Distribution download is too large.")
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("Distribution checksum verification failed.")
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def latest_release() -> dict | None:
    with get_url(f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100") as response:
        releases = json.load(response)
    candidates = []
    for release in releases:
        match = re.fullmatch(re.escape(RELEASE_PREFIX) + r"(\d+)\.(\d+)\.(\d+)", release.get("tag_name", ""))
        if not match or release.get("draft") or release.get("prerelease"):
            continue
        for asset in release.get("assets", []):
            digest = asset.get("digest") or ""
            url = asset.get("browser_download_url", "")
            prefix = f"https://github.com/{REPOSITORY}/releases/download/{release['tag_name']}/"
            if asset["name"] == SOURCE_ASSET and url == prefix + SOURCE_ASSET and re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                candidates.append((tuple(map(int, match.groups())), {
                    "tag": release["tag_name"], "url": url, "sha256": digest[7:],
                    "notes_url": f"https://github.com/{REPOSITORY}/releases/tag/{release['tag_name']}",
                }))
    return max(candidates, key=lambda entry: entry[0])[1] if candidates else None


def newer_release(current_label: str, tag: str) -> bool:
    pattern = re.escape(RELEASE_PREFIX) + r"(\d+)\.(\d+)\.(\d+)"
    current = re.fullmatch(pattern, current_label)
    candidate = re.fullmatch(pattern, tag)
    return bool(candidate and (not current or tuple(map(int, candidate.groups())) > tuple(map(int, current.groups()))))


def package_source(source: Path, output: Path, tag: str) -> None:
    import tempfile
    if not re.fullmatch(re.escape(RELEASE_PREFIX) + r"\d+\.\d+\.\d+", tag):
        raise RuntimeError("Release tags must look like xascraft-v0.1.0.")
    with tempfile.TemporaryDirectory(prefix="xascraft-package-") as temp:
        staged = Path(temp) / "source"
        metadata = snapshot(source, staged, label=tag)
        write_json(staged / "xascraft-release.json", metadata)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staged.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staged))
    output.with_suffix(output.suffix + ".sha256").write_text(
        hashlib.sha256(output.read_bytes()).hexdigest() + "  " + output.name + "\n")
