"""Docs and comments name only paths that exist and describe the patched-Larch setup.

The repository used to hold the whole upstream xraylarch tree and installed it in
editable mode.  That tree, its packaging files and its CI are gone; Larch now comes from
``larch-patches/`` (see larch-patches/README.md).  These checks catch docs, comments and
other text that still send a reader to the deleted paths or to the old install, or that
place Larch in this checkout.  Links are checked in the Markdown docs; the phrases in
every tracked text file.

Dated records (``docs/agent-runs/``, ``docs/superpowers/``, ``docs/qa/``, ``reports/``)
describe the tree as it was when they were written, so they are not checked.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RECORDS = ("docs/agent-runs/", "docs/superpowers/", "docs/qa/", "reports/", "examples/",
           "larch-patches/series/")
# The patch queue is about upstream's tree, so it names upstream's files (tests/run_tests.sh,
# pyproject.toml, MANIFEST.in) on purpose.
PATCH_QUEUE = "larch-patches/"
# The guards spell out the phrases they forbid.
GUARDS = {"tests/ci/test_docs.py", "tests/ci/test_workflows.py"}


def tracked_text_files() -> list[str]:
    """Every tracked text file, less the dated records, examples/ and the patch series.
    A file with a NUL byte counts as binary."""
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True,
                             capture_output=True, text=True).stdout.split("\0")
    return sorted(name for name in tracked
                  if name and not name.startswith(RECORDS) and (REPO / name).is_file()
                  and b"\0" not in (REPO / name).read_bytes())


TEXT_FILES = tracked_text_files()
DOCS = [name for name in TEXT_FILES if name.endswith(".md")]
CHECKED = [name for name in TEXT_FILES if name not in GUARDS]


def lines(name: str):
    for number, line in enumerate((REPO / name).read_text(encoding="utf-8").splitlines(), 1):
        yield number, line


def test_there_are_docs():
    assert {"README.md", "AGENTS.md", "docs/local-installation.md",
            "larch-patches/README.md"} <= set(DOCS)


def test_the_phrase_checks_read_code_and_scripts_too():
    assert {"backend/xraylarch_web/athena_science.py", "scripts/deploy-xraylarch-web.sh",
            "frontend/tests/e2e/screens/workbench.screens.ts", "NOTICE"} <= set(CHECKED)


LINK = re.compile(r"\]\(([^)\s]+)\)")


@pytest.mark.parametrize("name", DOCS)
def test_relative_links_resolve(name):
    broken = []
    for number, line in lines(name):
        for target in LINK.findall(line):
            path = target.split("#", 1)[0]
            if path and not re.match(r"[a-z][a-z0-9+.-]*:", path):
                if not ((REPO / name).parent / path).exists():
                    broken.append(f"{name}:{number}: {target}")
    assert not broken


# Deleted with the upstream tree.  Named as files, in code spans, links or URLs.
DELETED = re.compile(
    r"(?<![\w.-])(?:dylibs/|CHANGELOG\.md|INSTALL\b(?!\.)|publish_docs\.sh"
    r"|setup\.py|MANIFEST\.in|\.gitmodules|installers/GetLarch|installers/conda_constructor"
    r"|installers/README|test-ubuntu\.yml|test-windows\.yml)"
    r"|`(?:doc|history)/|`pyproject\.toml`"
)
# The old editable install of the repository's own Larch, and advice that only made
# sense while the root larch/ folder existed.
OLD_INSTALL = re.compile(
    r"-e \.\.|pip install -e|editable (?:mode|install)\b|PYTHONPATH=\.\.|root `larch/`"
    r"|`larch/` folder|repository's Larch|repository's `larch/`|this clone's Larch",
    re.IGNORECASE,
)
TEST_FILE = re.compile(r"(?<![\w./-])tests/(test_\w+\.py|run_tests\w*\.sh)")
# A link to the file in upstream at a fixed commit is how a doc names a deleted file.
UPSTREAM_AT_COMMIT = re.compile(r"\[[^\]]*\]\(https://github\.com/xraypy/xraylarch/blob/[0-9a-f]{40}/[^)]*\)")


@pytest.mark.parametrize("name", [name for name in CHECKED if not name.startswith(PATCH_QUEUE)])
def test_no_doc_names_the_deleted_upstream_tree(name):
    found = []
    for number, line in lines(name):
        line = UPSTREAM_AT_COMMIT.sub("", line)
        found += [f"{name}:{number}: {match.group()}" for match in DELETED.finditer(line)]
        # Upstream's root tests/ files are gone; the app's tests live elsewhere.
        for match in TEST_FILE.finditer(line):
            homes = ("tests", "backend/tests", "frontend/tests", "larch-patches/tests")
            if not any((REPO / home / match.group(1)).exists() for home in homes):
                found.append(f"{name}:{number}: {match.group()}")
    assert not found


@pytest.mark.parametrize("name", CHECKED)
def test_no_doc_describes_the_old_editable_install(name):
    found = [f"{name}:{number}: {line.strip()}" for number, line in lines(name)
             if OLD_INSTALL.search(line)]
    assert not found


# Between two words of a phrase: spaces or a line break, also one inside a #, // or * comment.
GAP = r"[\s#/*]+"
# "This checkout" was the repository with Larch inside it ("built on this checkout of
# the `xraylarch` library", "this checkout's `larch/xafs/autobk.py`").  Larch is now an
# installed build; the phrase may still name the repository itself.  The words may wrap.
THIS_CHECKOUTS_LARCH = re.compile(
    rf"this{GAP}checkout(?:'s)?{GAP}(?:of{GAP}(?:the{GAP})?)?`?(?:xraylarch|larch)\b", re.IGNORECASE)
# Nothing here is "this checkout's" ("this checkout's ETOK" was Larch's), and no Python file
# is "checked-out" ("the checked-out `feffit.py`" was Larch's).  The words may wrap.
STALE_LARCH = re.compile(
    rf"this{GAP}checkout['’]s|checked-out{GAP}\[?`?[\w./-]+\.py\b", re.IGNORECASE)
# In these, "this checkout" is the repository itself.
CHECKOUT_MEANS_THE_REPOSITORY = {"CLAUDE.md", "docs/athena-verification.md",
                                 "larch-patches/tests/test_series.py"}


def matches(name: str, pattern: re.Pattern) -> list[str]:
    """Each match in the whole text, as ``name:line: words``, so a match may wrap."""
    text = (REPO / name).read_text(encoding="utf-8")
    return [f"{name}:{text.count(chr(10), 0, match.start()) + 1}: {' '.join(match.group().split())}"
            for match in pattern.finditer(text)]


@pytest.mark.parametrize("name", CHECKED)
def test_no_doc_places_larch_in_this_checkout(name):
    assert not matches(name, THIS_CHECKOUTS_LARCH)


@pytest.mark.parametrize("name", [name for name in CHECKED if name not in CHECKOUT_MEANS_THE_REPOSITORY])
def test_no_doc_calls_larch_this_checkouts_or_checked_out(name):
    assert not matches(name, STALE_LARCH)


# Outside the queue, a patch is named by its ledger title in larch-patches/README.md, never by
# its number: retiring a patch renumbers the later ones, so a number would quietly point at
# another patch.  The per-patch report is keyed by patch number, so it is queue tooling too.
QUEUE_TOOLING = (PATCH_QUEUE, "scripts/refactor-checks/")
PATCH = re.compile(r"\bpatch", re.IGNORECASE)
PATCH_NUMBER = re.compile(r"(?<![\w.])0\d{3}(?!\w)")
# A patch file name may stand, such as the made-up one in a build error ("0003-x.patch").
PATCH_FILE = re.compile(r"\b\d{4}-[\w.-]+\.patch\b")


@pytest.mark.parametrize("name", [name for name in CHECKED if not name.startswith(QUEUE_TOOLING)])
def test_no_doc_names_a_patch_by_number(name):
    found = [f"{name}:{number}: {line.strip()}" for number, line in lines(name)
             if PATCH.search(line) and PATCH_NUMBER.search(PATCH_FILE.sub("", line))]
    assert not found
