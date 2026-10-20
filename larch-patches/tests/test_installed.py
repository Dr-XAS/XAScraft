"""``larch-patches/installed.py`` says whether the Larch an interpreter imports is the
patched build, the one check install-dev.sh, the deploy script and the backend test share.

Runs the script as a program against the interpreter running the tests, which must have
the current patched build installed (``install-dev.sh``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PATCHES_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PATCHES_DIR / "installed.py"


def expected_version() -> str:
    code = "import sys; sys.path.insert(0, sys.argv[1]); import build; print(build.expected_version())"
    return subprocess.run([sys.executable, "-I", "-c", code, str(PATCHES_DIR)], check=True,
                          capture_output=True, text=True).stdout.strip()


def check(*args: str, cwd: Path, pythonpath: Path | None = None) -> subprocess.CompletedProcess:
    if pythonpath is None:
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True,
                              text=True, cwd=cwd)
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          cwd=cwd, env={**os.environ, "PYTHONPATH": str(pythonpath)})


def test_the_installed_patched_build_passes_and_is_named(tmp_path):
    result = check(cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert expected_version() in result.stdout and "site-packages" in result.stdout


def test_another_version_than_the_build_of_this_queue_fails_naming_both(tmp_path):
    result = check("--version", "2000.1.0", cwd=tmp_path)

    assert result.returncode == 1
    assert "2000.1.0" in result.stderr and expected_version() in result.stderr


def test_a_larch_imported_from_a_source_tree_fails_even_with_the_right_version(tmp_path):
    # A larch/ package of the right version ahead of site-packages on sys.path: what the
    # old in-repository Larch looked like.
    tree = tmp_path / "tree"
    (tree / "larch").mkdir(parents=True)
    (tree / "larch" / "__init__.py").write_text(f"__version__ = {expected_version()!r}\n")

    result = check(cwd=tmp_path, pythonpath=tree)

    assert result.returncode == 1
    assert "site-packages" in result.stderr and str(tree / "larch") in result.stderr
