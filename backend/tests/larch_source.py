"""Where a hash manifest's source path lives, and which Larch source changes were reviewed.

The Athena fixture manifests pin Larch sources as ``larch/<module path>``. Larch is not part of
this repository; those names refer to the installed (patched) Larch package.

Each manifest records the sha256 of the Larch files its native oracle ran on. When a Larch bump
changes one of those files, its test fails until someone reads the upstream diff. A change that
leaves the oracle's numbers and the app's copy unchanged goes in ``REVIEWED_LARCH_CHANGES``, once
for every manifest; a change that matters needs a new oracle instead.
"""
import hashlib
from pathlib import Path

import larch

LARCH_PACKAGE = Path(larch.__file__).resolve().parent

# (file, sha256 an oracle was recorded on) -> (sha256 of the installed file, why it is safe).
REVIEWED_LARCH_CHANGES = {
    ("larch/math/utils.py",
     "9f7f776459925b66974205328698ef271be3bda5be3a25d9d38d1f37dbc54467"): (
        "15655e0fdb6b32886cf8efc307aaf015076bb9b490124beb00c8eab22b446061",
        "upstream 98650acff (in 247278cef): remove_dups takes np.diff(work).min(), work.min() "
        "and work.max() instead of the builtin min and max. Same result for every finite "
        "array; only an array with NaN can take another branch, and the app never gives "
        "remove_dups one (test_larch_remove_dups.py). Two other commits touch the file with "
        "an empty net diff."),
    ("larch/xafs/pre_edge.py",
     "0a49d5cfb4b465580cb3ba17079df97e36d40c994d7e4b02cf2b8ec9a437e02d"): (
        "b2a6c033e83e998fa921357e0997548a15b1874253dd42a1fb6d9c5c196825aa",
        "upstream 98650acff (in 247278cef): preedge takes energy.min() and energy.max() "
        "instead of the builtin min and max, the same for finite energies (pre_edge and "
        "preedge remove NaN first). a858690aa, 131718786 and 5ef59f2e1 rewrote energy_align, "
        "which neither the app nor these oracles call."),
    ("larch/xafs/xafsutils.py",
     "d21f079b44a20ad6584427b4b521b03a67983869108f88c54f6da2749db36eed"): (
        "dae14a66d9b1893659353bb9e6fe690857a0d627954417524de731b9aef1b67c",
        "upstream 2c2cdd5cb (in 247278cef): gfmt returns a str argument unchanged; gfmt is "
        "used only in FEFF fit reports. KTOE, ETOK and TINY_ENERGY are unchanged."),
}


def source_path(root: Path, name: str) -> Path:
    if name.startswith('larch/'):
        return LARCH_PACKAGE / name.removeprefix('larch/')
    return root / name


def assert_recorded_sources(root: Path, recorded: dict[str, str]) -> None:
    """Every file of a manifest's ``sha256`` map has the bytes it recorded, or, for a Larch
    file, the bytes of a reviewed change to them."""
    for name, sha in recorded.items():
        actual = hashlib.sha256(source_path(root, name).read_bytes()).hexdigest()
        reviewed = REVIEWED_LARCH_CHANGES.get((name, sha))
        accepted = {sha} if reviewed is None else {sha, reviewed[0]}
        assert actual in accepted, f"{name}: sha256 {actual}, recorded {sha}"
