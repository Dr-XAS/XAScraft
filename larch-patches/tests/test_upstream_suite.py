"""``run-upstream-tests.sh --known-failures`` shows the upstream tests that fail without wx.

The upstream example-script tests in the runner's ``KNOWN_FAILURES`` call wx plotting
commands and fail wherever wxPython is missing, on plain upstream too.  The main run leaves
them out; this mode runs just them, names them as known pre-existing failures, and exits
non-zero as soon as the set changes (one of them passes, or fails differently), so the list
never goes stale.  The tests here read that list from the runner, and check that README.md
names the same tests.

Builds the patched tree like ``test_build.py`` (same upstream and build environment) and
runs the suite against the Larch installed in the interpreter running these tests.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_build import build_ok

PATCHES_DIR = Path(__file__).resolve().parents[1]
RUNNER = PATCHES_DIR / "run-upstream-tests.sh"


def runner_list(name: str) -> list[str]:
    """The words of the runner's bash array ``name=( ... )``."""
    runner = RUNNER.read_text()
    start = f"\n{name}=("
    return runner[runner.index(start) + len(start):].split(")", 1)[0].split()


KNOWN = runner_list("KNOWN_FAILURES")


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> Path:
    return build_ok(tmp_path_factory.mktemp("upstream-suite") / "out") / "xraylarch-src"


def known_failures(tree: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(RUNNER), str(tree), "--python", sys.executable,
                           "--known-failures"], capture_output=True, text=True)


def test_the_main_run_leaves_out_exactly_the_known_failures_and_passes(tree):
    result = subprocess.run(["bash", str(RUNNER), str(tree), "--python", sys.executable],
                            capture_output=True, text=True)

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr
    assert f" {len(KNOWN)} deselected" in result.stdout.splitlines()[-1]


def test_the_runner_names_the_files_upstreams_run_tests_sh_names_at_the_pin(tree):
    """The patched tree's tests/run_tests.sh (upstream's list at the pin, plus 0007's
    test_xafs_defects.py), and test_xrf_model.py, which patch 0004 changed.  Files with
    nothing to collect without wx print no progress line, so the runner's own list is read."""
    script = (tree / "tests" / "run_tests.sh").read_text().split()
    named = [word for word in script if word.startswith("test_") and word.endswith(".py")]
    files = runner_list("FILES")

    assert "test_xafs_defects.py" in named
    assert sorted(files) == sorted({*named, "test_xrf_model.py"})


def test_the_known_failures_are_run_and_named_and_do_not_fail_the_step(tree):
    result = known_failures(tree)

    assert result.returncode == 0, result.stdout + result.stderr
    report = result.stdout[result.stdout.index("known pre-existing failures"):]
    assert [name for name in KNOWN if name in report] == KNOWN


def test_a_known_failure_that_starts_passing_fails_the_step(tree, tmp_path):
    # Without its plot commands, test02's script runs without wx.
    changed = tmp_path / "xraylarch-src"
    shutil.copytree(tree, changed)
    script = changed / "examples" / "xafs" / "doc_autobk1.lar"
    script.write_text("".join(line for line in script.read_text().splitlines(keepends=True)
                              if not line.startswith("plot_")))

    result = known_failures(changed)

    assert result.returncode != 0
    assert "test02_autobk" in result.stderr and "now passes" in result.stderr


def readme_known_failures() -> list[str]:
    """The tests README.md names in its "Known pre-existing failures" bullet."""
    readme = (PATCHES_DIR / "README.md").read_text()
    bullet = readme[readme.index("- **Known pre-existing failures.**"):].split("\n- ", 1)[0]
    return re.findall(r"`(test\d+_\w+)`", bullet)


def test_the_readme_names_the_known_failures_the_runner_names():
    """The runner's error message says to update both lists when the known failures change."""
    assert sorted(readme_known_failures()) == sorted(KNOWN)
