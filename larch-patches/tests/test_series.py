"""The patch series applied to the pinned upstream commit reproduces XAScraft's Larch.

The series is applied with plain ``git am`` in a scratch clone (``git clone --shared``
for a local upstream clone, a one-commit fetch otherwise), never in the upstream clone
itself.  Upstream source: ``$XASCRAFT_LARCH_UPSTREAM`` (path or URL), else the URL in
``PIN``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PATCHES_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PATCHES_DIR.parent

# The seven XAScraft commits that changed the Larch copy XAScraft used to vendor, in date
# order. Each team patch comes from one of them and names it in an XAScraft-commit trailer.
TEAM_COMMITS = [
    "e47015166",
    "3ca0a9716",
    "ab60c3776",
    "cc099c125",
    "b334e57f8",
    "8d37ac358",
    "aee4bb5e6",
]

# Every patch after the team patches is temporary: written while tracking upstream, it undoes
# an upstream regression, or keeps an app result that upstream changed on purpose until the
# owner decides (README.md, "Patches"). It comes from no XAScraft commit, so it carries no
# trailer.

COMMITTER = {
    "GIT_COMMITTER_NAME": "XAScraft patch queue",
    "GIT_COMMITTER_EMAIL": "patches@xascraft.invalid",
}


def git(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=full_env, check=True, capture_output=True, text=True
    )
    return result.stdout


def read_pin() -> dict[str, str]:
    pin: dict[str, str] = {}
    for line in (PATCHES_DIR / "PIN").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        pin[key.strip()] = value.strip()
    return pin


def series() -> list[Path]:
    return sorted((PATCHES_DIR / "series").glob("*.patch"))


@pytest.fixture(scope="module")
def patched(tmp_path_factory) -> Path:
    """A scratch clone of upstream at the pin with the series applied by ``git am``."""
    pin = read_pin()
    source = os.environ.get("XASCRAFT_LARCH_UPSTREAM", pin["upstream-url"])
    dest = tmp_path_factory.mktemp("upstream") / "xraylarch"
    if Path(source).is_dir():
        subprocess.run(
            ["git", "clone", "-q", "--shared", "--no-checkout", source, str(dest)], check=True
        )
    else:
        dest.mkdir()
        git("init", "-q", cwd=dest)
        git("fetch", "-q", "--depth", "1", source, pin["upstream-commit"], cwd=dest)
    git("checkout", "-q", "--detach", pin["upstream-commit"], cwd=dest)
    git(
        "am", "-q", "--committer-date-is-author-date",
        *[str(p) for p in series()],
        cwd=dest, env=COMMITTER,
    )
    return dest


def test_pin_names_a_full_upstream_commit():
    pin = read_pin()
    assert len(pin["upstream-commit"]) == 40
    assert pin["upstream-url"] == "https://github.com/xraypy/xraylarch.git"
    # setuptools-scm's version of a commit ends in +g<9-character short sha>.
    assert pin["upstream-version"].endswith(f"+g{pin['upstream-commit'][:9]}")


def test_series_is_numbered_from_0001_and_starts_with_the_team_patches():
    names = [p.name for p in series()]
    assert len(names) >= len(TEAM_COMMITS)
    assert [n[:5] for n in names] == [f"{i:04d}-" for i in range(1, len(names) + 1)]


def applied_commits(cwd: Path) -> list[str]:
    upstream = read_pin()["upstream-commit"]
    applied = git("rev-list", "--reverse", f"{upstream}..HEAD", cwd=cwd).split()
    assert len(applied) == len(series())
    return applied


def temporary_commits(cwd: Path) -> list[str]:
    return applied_commits(cwd)[len(TEAM_COMMITS):]


def test_series_reproduces_the_pinned_larch_tree(patched):
    assert git("rev-parse", "HEAD:larch", cwd=patched).strip() == read_pin()["patched-larch-tree"]


def test_series_reproduces_the_pinned_pyproject(patched):
    assert (
        git("rev-parse", "HEAD:pyproject.toml", cwd=patched).strip()
        == read_pin()["patched-pyproject-blob"]
    )


def test_pin_is_the_reviewed_one():
    """The one place outside PIN that names the pin and what the series gives on it, so that a
    changed pin or patch needs a reviewed edit here too. A re-pin or a patch that changes
    larch/ updates PIN and these values together (README.md, "Maintaining the queue").

    Upstream 247278cef. The seven team patches give larch/ deec1766f137; with the temporary
    patches 0008 (FEFF path parameters) and 0009 (self-absorption E0), the tree below."""
    pin = read_pin()
    assert pin["upstream-commit"] == "247278cefbb16eda04c91f79fc1b43df000fa498"
    assert pin["patched-larch-tree"] == "50051233d1761bc8ecf24553bd4f50b81663c3b2"
    assert pin["patched-pyproject-blob"] == "14ccc10ed6f759cda9059d331e3c9139cfe7a8d2"


# What the series carries (README "Maintaining the queue"), less tests/run_tests.sh, whose
# context is upstream's list and so moves with the pin (checked on its own below).
CARRIED_PATHS = ["larch", "pyproject.toml", "tests/test_xafs_defects.py",
                 "tests/test_xrf_model.py", "tests/test_read_beamlinedata.py"]


def patch_id(sha: str, cwd: Path) -> str:
    """``git patch-id --stable`` of a commit's changes to ``CARRIED_PATHS``: the same for the
    same change at other line numbers, so it survives a re-pin that only moved the context."""
    diff = git("show", "--format=", sha, "--", *CARRIED_PATHS, cwd=cwd)
    result = subprocess.run(["git", "patch-id", "--stable"], cwd=cwd, input=diff,
                            check=True, capture_output=True, text=True)
    return result.stdout.split()[0]


def test_each_applied_commit_makes_the_change_its_xascraft_commit_made(patched):
    """Needs XAScraft's history, which this checkout has.  Whatever the pin, each patch makes
    the same change as the team's commit made to the vendored copy."""
    applied = applied_commits(patched)
    for sha, new in zip(TEAM_COMMITS, applied):
        assert patch_id(new, patched) == patch_id(sha, REPO_ROOT), sha


def test_temporary_patches_change_only_larch_and_carry_no_xascraft_commit(patched):
    """A temporary patch changes larch/ only; its regression tests live in larch-patches/tests,
    not in upstream's tests/."""
    for sha in temporary_commits(patched):
        changed = git("show", "--format=", "--name-only", sha, cwd=patched).split()
        assert changed and all(name.startswith("larch/") for name in changed), changed
        trailer = git("log", "-1", "--format=%(trailers:key=XAScraft-commit,valueonly)", sha,
                      cwd=patched)
        assert trailer.strip() == "", sha


def test_run_tests_sh_is_upstreams_plus_the_team_regression_file(patched):
    """0007 keeps the team's change to upstream's test list, on upstream's current file."""
    upstream = read_pin()["upstream-commit"]
    before = git("show", f"{upstream}:tests/run_tests.sh", cwd=patched).split()
    after = git("show", "HEAD:tests/run_tests.sh", cwd=patched).split()
    assert after == before + ["test_xafs_defects.py"]


def test_applied_commits_carry_their_xascraft_sha_in_order(patched):
    upstream = read_pin()["upstream-commit"]
    team_tip = applied_commits(patched)[len(TEAM_COMMITS) - 1]
    trailers = git(
        "log", "--reverse", "--format=%(trailers:key=XAScraft-commit,valueonly)",
        f"{upstream}..{team_tip}", cwd=patched,
    ).split()
    assert [t[:9] for t in trailers] == TEAM_COMMITS
    assert all(len(t) == 40 for t in trailers)


def test_applied_commits_keep_original_author_date_and_message(patched):
    """Needs XAScraft's history, which this checkout has."""
    upstream = read_pin()["upstream-commit"]
    team_tip = applied_commits(patched)[len(TEAM_COMMITS) - 1]
    fmt = "%an%x00%ae%x00%at%x00%B"
    applied = git(
        "log", "--reverse", f"--format={fmt}%x01", f"{upstream}..{team_tip}", cwd=patched
    ).split("\x01")[:-1]
    assert len(applied) == len(TEAM_COMMITS)
    for sha, got in zip(TEAM_COMMITS, applied):
        original = git("log", "-1", f"--format={fmt}", sha, cwd=REPO_ROOT)
        full_sha = git("rev-parse", sha, cwd=REPO_ROOT).strip()
        an, ae, at, body = got.lstrip("\n").split("\x00")
        oan, oae, oat, obody = original.split("\x00")
        assert (an, ae, at) == (oan, oae, oat), sha
        # The message is the original one plus the trailer (git am may drop a
        # trailing blank line of an empty body).
        trailer = f"XAScraft-commit: {full_sha}"
        assert body.rstrip().endswith(trailer), sha
        assert body.rstrip().removesuffix(trailer).rstrip() == obody.rstrip(), sha
