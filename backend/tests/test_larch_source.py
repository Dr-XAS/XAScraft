"""The Athena fixture manifests' Larch source pins: recorded bytes, or a reviewed change."""
import hashlib
from pathlib import Path

import pytest

from tests.larch_source import REVIEWED_LARCH_CHANGES, assert_recorded_sources, source_path

ROOT = Path(__file__).resolve().parents[2]


def sha256(name):
    return hashlib.sha256(source_path(ROOT, name).read_bytes()).hexdigest()


def test_a_file_with_the_recorded_bytes_passes():
    assert_recorded_sources(ROOT, {"larch/xafs/feffdat.py": sha256("larch/xafs/feffdat.py")})


def test_a_file_whose_change_was_reviewed_passes():
    (name, recorded), (installed, _why) = next(iter(REVIEWED_LARCH_CHANGES.items()))
    assert sha256(name) == installed != recorded
    assert_recorded_sources(ROOT, {name: recorded})


def test_a_file_with_other_bytes_fails_and_names_the_file():
    with pytest.raises(AssertionError, match="larch/xafs/feffdat.py"):
        assert_recorded_sources(ROOT, {"larch/xafs/feffdat.py": "0" * 64})


def test_every_reviewed_change_is_the_installed_file():
    """A Larch bump that changes one of these files again fails here, and in the manifests'
    tests, until the new change is reviewed."""
    for (name, _recorded), (installed, why) in REVIEWED_LARCH_CHANGES.items():
        assert sha256(name) == installed, name
        assert why
