"""``run-upstream-tests.sh --known-failures`` shows the upstream tests that fail without wx.

Eleven of upstream's example-script tests call wx plotting commands and fail wherever
wxPython is missing, on plain upstream too.  The main run leaves them out; this mode runs
just them, names them as known pre-existing failures, and exits non-zero as soon as the
set changes (one of them passes, or fails differently), so the list never goes stale.

Builds the patched tree like ``test_build.py`` (same upstream and build environment) and
runs the suite against the Larch installed in the interpreter running these tests.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_build import build_ok

RUNNER = Path(__file__).resolve().parents[1] / "run-upstream-tests.sh"
KNOWN = [
    "test02_autobk", "test03_autobk2", "test05_autobk_with_std", "test07_xafsft1",
    "test08_xafsft2", "test09_xafsft3", "test10_xafsft3", "test13_feffit1", "test15_feffit2",
    "test16_feffit3", "test18_feffit_save_fit_stale_paths",
]


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
    runner = RUNNER.read_text()
    files = runner[runner.index("\nFILES=(") + 8:].split(")", 1)[0].split()

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
