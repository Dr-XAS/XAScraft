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

# The seven XAScraft commits that touch Larch, in date order (decisions record,
# notes/01-patch-queue.md section 3).
TEAM_COMMITS = [
    "e47015166",
    "3ca0a9716",
    "ab60c3776",
    "cc099c125",
    "b334e57f8",
    "8d37ac358",
    "aee4bb5e6",
]

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
    assert pin["upstream-commit"].startswith("8d6cd41c2")
    assert pin["upstream-url"] == "https://github.com/xraypy/xraylarch.git"


def test_series_has_one_patch_per_team_commit():
    names = [p.name for p in series()]
    assert [n[:5] for n in names] == [f"{i:04d}-" for i in range(1, 8)]


def test_series_reproduces_the_baseline_larch_tree(patched):
    assert git("rev-parse", "HEAD:larch", cwd=patched).strip() == read_pin()["patched-larch-tree"]


def test_series_reproduces_the_baseline_pyproject(patched):
    assert (
        git("rev-parse", "HEAD:pyproject.toml", cwd=patched).strip()
        == read_pin()["patched-pyproject-blob"]
    )


def test_expected_hashes_in_pin_are_the_baseline_ones():
    """Cross-check PIN against the baseline tag, while this checkout still has it."""
    try:
        larch = git("rev-parse", "refactor-baseline:larch", cwd=REPO_ROOT).strip()
        pyproject = git("rev-parse", "refactor-baseline:pyproject.toml", cwd=REPO_ROOT).strip()
    except subprocess.CalledProcessError:
        pytest.skip("tag refactor-baseline is not in this checkout")
    pin = read_pin()
    assert (pin["patched-larch-tree"], pin["patched-pyproject-blob"]) == (larch, pyproject)
    assert larch == "72b7101ea9da8e7e4801c94a4d17ef289ec1517b"


def test_applied_commits_carry_their_xascraft_sha_in_order(patched):
    upstream = read_pin()["upstream-commit"]
    trailers = git(
        "log", "--reverse", "--format=%(trailers:key=XAScraft-commit,valueonly)",
        f"{upstream}..HEAD", cwd=patched,
    ).split()
    assert [t[:9] for t in trailers] == TEAM_COMMITS
    assert all(len(t) == 40 for t in trailers)


def test_applied_commits_keep_original_author_date_and_message(patched):
    """Needs XAScraft's history, which this checkout has."""
    upstream = read_pin()["upstream-commit"]
    fmt = "%an%x00%ae%x00%at%x00%B"
    applied = git(
        "log", "--reverse", f"--format={fmt}%x01", f"{upstream}..HEAD", cwd=patched
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
