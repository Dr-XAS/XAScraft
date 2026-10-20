"""The current docs name only paths that exist and describe the patched-Larch setup.

The repository used to hold the whole upstream xraylarch tree and installed it in
editable mode.  That tree, its packaging files and its CI are gone; Larch now comes from
``larch-patches/`` (see larch-patches/README.md).  These checks catch docs that still send
a reader to the deleted paths or to the old install.

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
# This file is about upstream's tree, so it names upstream's files (tests/run_tests.sh,
# pyproject.toml) on purpose.
UPSTREAM_TREE_DOCS = {"larch-patches/README.md"}


def current_docs() -> list[str]:
    tracked = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=REPO, check=True,
                             capture_output=True, text=True).stdout.split("\0")
    return sorted(name for name in tracked if name and not name.startswith(RECORDS))


DOCS = current_docs()


def lines(name: str):
    for number, line in enumerate((REPO / name).read_text(encoding="utf-8").splitlines(), 1):
        yield number, line


def test_there_are_docs():
    assert {"README.md", "AGENTS.md", "docs/local-installation.md",
            "larch-patches/README.md"} <= set(DOCS)


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


@pytest.mark.parametrize("name", DOCS)
def test_no_doc_names_the_deleted_upstream_tree(name):
    found = []
    for number, line in lines(name):
        line = UPSTREAM_AT_COMMIT.sub("", line)
        for match in DELETED.finditer(line):
            if not (name in UPSTREAM_TREE_DOCS and match.group() == "`pyproject.toml`"):
                found.append(f"{name}:{number}: {match.group()}")
        if name not in UPSTREAM_TREE_DOCS:
            # Upstream's root tests/ files are gone; the app's tests live elsewhere.
            for match in TEST_FILE.finditer(line):
                homes = ("tests", "backend/tests", "frontend/tests", "larch-patches/tests")
                if not any((REPO / home / match.group(1)).exists() for home in homes):
                    found.append(f"{name}:{number}: {match.group()}")
    assert not found


@pytest.mark.parametrize("name", DOCS)
def test_no_doc_describes_the_old_editable_install(name):
    found = [f"{name}:{number}: {line.strip()}" for number, line in lines(name)
             if OLD_INSTALL.search(line)]
    assert not found


# "This checkout" was the repository with Larch inside it ("built on this checkout of
# the `xraylarch` library", "this checkout's `larch/xafs/autobk.py`").  Larch is now an
# installed build; the phrase may still name the repository itself.  The words may wrap.
THIS_CHECKOUTS_LARCH = re.compile(
    r"this\s+checkout(?:'s)?\s+(?:of\s+(?:the\s+)?)?`?(?:xraylarch|larch)\b", re.IGNORECASE)


@pytest.mark.parametrize("name", DOCS)
def test_no_doc_places_larch_in_this_checkout(name):
    text = (REPO / name).read_text(encoding="utf-8")
    found = [f"{name}:{text.count(chr(10), 0, match.start()) + 1}: {' '.join(match.group().split())}"
             for match in THIS_CHECKOUTS_LARCH.finditer(text)]
    assert not found
