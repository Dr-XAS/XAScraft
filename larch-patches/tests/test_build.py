"""``larch-patches/build.py`` builds the patched Larch from the pin and the series.

Every test runs the script as a program, the way the deploy script, the installer and CI
call it.  Upstream: ``$XASCRAFT_LARCH_UPSTREAM`` (a local clone path, which is what local
runs use, or a URL), else the URL in ``PIN``.  The build environment is the interpreter
running the tests (``--build-python``), which must have the pinned setuptools, wheel and
setuptools-scm installed, as an environment made from ``deploy/python-release-constraints.txt``
has.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

PATCHES_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PATCHES_DIR.parent
BUILD = PATCHES_DIR / "build.py"


def read_pin() -> dict[str, str]:
    pin: dict[str, str] = {}
    for line in (PATCHES_DIR / "PIN").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            pin[key.strip()] = value.strip()
    return pin


PIN = read_pin()
UPSTREAM = os.environ.get("XASCRAFT_LARCH_UPSTREAM", PIN["upstream-url"])


def run_build(out: Path, *args: str, script: Path = BUILD) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), "--upstream", UPSTREAM, "--out", str(out),
         "--build-python", sys.executable, *args],
        capture_output=True, text=True,
    )


def build_ok(out: Path, *args: str, script: Path = BUILD) -> Path:
    result = run_build(out, *args, script=script)
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def files_under(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file() or p.is_symlink()
    }


@pytest.fixture(scope="module")
def full(tmp_path_factory) -> Path:
    return build_ok(tmp_path_factory.mktemp("full") / "out")


def test_full_build_gives_the_larch_tree_recorded_in_pin(full):
    """The exported ``larch/`` hashes to the git tree that ``PIN`` records."""
    scratch = full.parent / "tree-check"
    env = {**os.environ, "GIT_DIR": str(scratch), "GIT_WORK_TREE": str(full / "xraylarch-src")}
    subprocess.run(["git", "init", "-q", "--bare", str(scratch)], check=True)
    subprocess.run(["git", "add", "-f", "larch"], env=env, check=True,
                   cwd=full / "xraylarch-src")
    tree = subprocess.run(["git", "write-tree", "--prefix=larch/"], env=env, check=True,
                          capture_output=True, text=True).stdout.strip()
    assert tree == PIN["patched-larch-tree"]


def test_full_build_larch_equals_the_baseline_larch_byte_for_byte(full):
    tag = subprocess.run(["git", "rev-parse", "-q", "--verify", "refactor-baseline^{commit}"],
                         cwd=REPO_ROOT, capture_output=True, text=True)
    if tag.returncode != 0:
        pytest.skip("tag refactor-baseline is not in this clone; the PIN tree test still runs")
    archive = subprocess.run(["git", "archive", "--format=tar", "refactor-baseline", "larch"],
                             cwd=REPO_ROOT, check=True, capture_output=True).stdout
    baseline = full.parent / "baseline"
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(baseline, filter="data")
    assert files_under(full / "xraylarch-src" / "larch") == files_under(baseline / "larch")
