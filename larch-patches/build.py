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
import gzip
import hashlib
import io
import json
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
    archive = git("archive", "--format=tar", "HEAD", cwd=repo, text=False)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")


def xascraft_commit(patch: Path) -> str | None:
    """The ``XAScraft-commit:`` trailer of a patch file, if it has one."""
    for line in patch.read_text(errors="replace").splitlines():
        if line.startswith("XAScraft-commit:"):
            return line.partition(":")[2].strip()
        if line.startswith("---"):
            break
    return None


def patch_set_id(patches: list[Path]) -> str:
    """First 12 hex of sha256 over the patch files' bytes, in order (``cat | sha256sum``)."""
    digest = hashlib.sha256()
    for patch in patches:
        digest.update(patch.read_bytes())
    return digest.hexdigest()[:12]


def make_identity(pin: dict[str, str], patches: list[Path], larch_tree: str) -> dict:
    set_id = patch_set_id(patches)
    return {
        "pin": pin["upstream-commit"],
        "upstream_version": pin["upstream-version"],
        "patch_set_id": set_id,
        "version": f"{pin['upstream-version']}.xascraft.{set_id}",
        "pure_upstream": False,
        "patches": [
            {"number": p.name[:4], "file": p.name, "xascraft_commit": xascraft_commit(p)}
            for p in patches
        ],
        "excluded": [],
        "larch_tree": larch_tree,
    }


def build_requirements() -> list[str]:
    """The build backend's pins, taken from the release constraints (the deploy pins)."""
    constraints = HERE.parent / "deploy" / "python-release-constraints.txt"
    if not constraints.is_file():
        raise BuildError(f"{constraints} not found; pass --build-python")
    wanted = {"setuptools", "wheel", "setuptools-scm"}
    pins = [line.strip() for line in constraints.read_text().splitlines()
            if line.partition("==")[0].strip().lower() in wanted]
    if len(pins) != len(wanted):
        raise BuildError(f"{constraints} does not pin all of {sorted(wanted)}")
    return [*pins, "--constraint", str(constraints)]


def build_environment(work: Path) -> str:
    """A fresh venv with the pinned build backend (needs PyPI or a pip cache)."""
    env_dir = work / "build-env"
    run([sys.executable, "-m", "venv", str(env_dir)], "creating the build venv")
    python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    run([python, "-m", "pip", "install", "-q", "--disable-pip-version-check",
         *build_requirements()], "installing the build backend")
    return python


def run(cmd: list[str], what: str, **kwargs) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise BuildError(f"{what} failed:\n{(result.stdout + result.stderr).strip()}")
    return result.stdout


# Runs in the build environment: PEP 517 hooks, the way `python -m build` calls them.
HOOK = """\
import sys
import setuptools.build_meta as backend
hook = backend.build_sdist if sys.argv[1] == "sdist" else backend.build_wheel
print(hook(sys.argv[2]))
"""


def build_dists(src: Path, work: Path, dist: Path, python: str, version: str,
                epoch: str) -> None:
    """Build the sdist and the wheel, each from its own fresh copy of ``src``."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("SETUPTOOLS_SCM_") and k not in ("PYTHONPATH",)}
    env.update({
        # The tree has no .git; this is the only version setuptools-scm may use.
        "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_XRAYLARCH": version,
        # Fixed timestamps in the archives: the patched commit's time.
        "SOURCE_DATE_EPOCH": epoch,
        # Never let setuptools-scm's file finder see a repository around the temp dir.
        "GIT_CEILING_DIRECTORIES": str(work),
    })
    dist.mkdir()
    for kind in ("sdist", "wheel"):
        copy = work / f"build-{kind}"
        shutil.copytree(src, copy, symlinks=True)
        name = run([python, "-I", "-c", HOOK, kind, str(dist)], f"building the {kind}",
                   cwd=copy, env=env).strip().splitlines()[-1]
        built = name.split("-")[1] if kind == "wheel" else name.removesuffix(".tar.gz").removeprefix("xraylarch-")
        if built != version:
            raise BuildError(f"the {kind} {name} has version {built!r}, not {version!r} "
                             "(setuptools normalised it)")
        if kind == "sdist":
            normalise_sdist(dist / name, int(epoch))


def normalise_sdist(path: Path, epoch: int) -> None:
    """Make the sdist reproducible, which setuptools does not: the files it generates
    (PKG-INFO, egg-info, _version.py) get the build time, the tar records the builder's
    uid and gid, and the gzip header records the time of compression."""
    with tarfile.open(path, "r:gz") as src:
        members = [(m, src.extractfile(m).read() if m.isfile() else None)
                   for m in src.getmembers()]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as dst:
        for member, data in sorted(members, key=lambda item: item[0].name):
            member.mtime = min(int(member.mtime), epoch)
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.pax_headers = {}
            dst.addfile(member, io.BytesIO(data) if data is not None else None)
    with open(path, "wb") as raw, gzip.GzipFile(
            filename=path.name.removesuffix(".gz"), mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(buffer.getvalue())


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
        ident = make_identity(pin, patches, git("rev-parse", "HEAD:larch", cwd=repo).strip())
        stage = work / "out"
        stage.mkdir()
        export_tree(repo, stage / "xraylarch-src")
        python = args.build_python or build_environment(work)
        build_dists(stage / "xraylarch-src", work, stage / "dist", python, ident["version"],
                    git("log", "-1", "--format=%ct", cwd=repo).strip())
        (stage / "IDENTITY").write_text(json.dumps(ident, indent=2) + "\n")
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
