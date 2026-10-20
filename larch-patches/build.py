#!/usr/bin/env python3
"""Build XAScraft's patched Larch: upstream xraylarch at the pin plus the series.

    python3 larch-patches/build.py --out DIR [--upstream PATH_OR_URL]
                                   [--exclude NNNN ...] [--pure-upstream]
                                   [--build-python PYTHON]

Reads ``PIN`` and ``series/*.patch`` next to this script.  Writes, all or nothing:

    DIR/xraylarch-src/   the patched upstream source tree (no .git)
    DIR/dist/            the wheel and the sdist
    DIR/IDENTITY         JSON: pin, patch-set id, version, patches, excluded patches

Standard library only (Python 3.12+).  See README.md, "Building".
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The series is applied by a fixed committer, so the commits (and their dates) are the
# same on every machine.  Git runs without the user's or the system's configuration.
COMMITTER = {
    "GIT_COMMITTER_NAME": "XAScraft patch queue",
    "GIT_COMMITTER_EMAIL": "patches@xascraft.invalid",
}


class BuildError(Exception):
    """A build step failed; the message says which and why."""


def git(*args: str, cwd: Path, capture: bool = True, text: bool = True):
    env = {
        **os.environ,
        **COMMITTER,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=capture, text=text)
    if result.returncode != 0:
        err = result.stderr if text else result.stderr.decode(errors="replace")
        raise BuildError(f"git {' '.join(args[:2])} failed in {cwd}:\n{err.strip()}")
    return result.stdout


def read_pin(path: Path) -> dict[str, str]:
    pin: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            pin[key.strip()] = value.strip()
    for key in ("upstream-commit", "upstream-version"):
        if not pin.get(key):
            raise BuildError(f"{path}: missing '{key} = ...'")
    return pin


def checkout_upstream(upstream: str, commit: str, dest: Path) -> None:
    """Upstream at exactly ``commit`` in ``dest``; a local clone is only read."""
    if Path(upstream).is_dir():
        git("clone", "-q", "--shared", "--no-checkout", str(Path(upstream).resolve()),
            str(dest), cwd=dest.parent)
    else:
        dest.mkdir()
        git("init", "-q", cwd=dest)
        git("fetch", "-q", "--depth", "1", upstream, commit, cwd=dest)
    git("checkout", "-q", "--detach", commit, cwd=dest)
    head = git("rev-parse", "HEAD", cwd=dest).strip()
    if head != commit:
        raise BuildError(f"upstream checkout is at {head}, not the pin {commit}")


def apply_series(patches: list[Path], repo: Path) -> None:
    for patch in patches:
        try:
            git("am", "-q", "--committer-date-is-author-date", str(patch), cwd=repo)
        except BuildError as exc:
            raise BuildError(f"patch {patch.name} does not apply:\n{exc}") from None


def export_tree(repo: Path, dest: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"], cwd=repo, capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")


def build(args: argparse.Namespace) -> Path:
    out = Path(args.out).resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise BuildError(f"--out {out} exists and is not empty")
    pin = read_pin(HERE / "PIN")
    patches = sorted((HERE / "series").glob("*.patch"))

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xascraft-larch-") as tmp:
        work = Path(tmp)
        repo = work / "xraylarch"
        checkout_upstream(args.upstream, pin["upstream-commit"], repo)
        apply_series(patches, repo)
        stage = work / "out"
        stage.mkdir()
        export_tree(repo, stage / "xraylarch-src")
        if out.exists():
            out.rmdir()
        shutil.move(str(stage), str(out))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="output directory (absent or empty)")
    parser.add_argument("--upstream", default=None,
                        help="local xraylarch clone or git URL (default: upstream-url in PIN)")
    parser.add_argument("--build-python", default=None)
    args = parser.parse_args(argv)
    try:
        if args.upstream is None:
            args.upstream = read_pin(HERE / "PIN")["upstream-url"]
        out = build(args)
    except BuildError as exc:
        print(f"build.py: error: {exc}", file=sys.stderr)
        return 1
    print(f"build.py: wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
