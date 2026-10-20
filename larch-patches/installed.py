#!/usr/bin/env python3
"""Check that the Larch this interpreter imports is XAScraft's patched build.

    python -I larch-patches/installed.py [--version VERSION]

The Larch that ``import larch`` gives must report VERSION, as must the installed
``xraylarch`` distribution's metadata; it must be the file that distribution installed;
and it must come from site-packages, not from a source tree.  VERSION defaults to
``build.expected_version()``: the build of this folder's PIN plus the whole series.
Prints the version and where Larch is and exits 0, or names every problem and exits 1.

install-dev.sh, the deploy script (assert_patched_larch) and
backend/tests/test_larch_dependency.py all use this check.  (The per-user installer runs
from a snapshot without larch-patches/, so it compares the metadata version itself; see
installers/local/xascraft_local/install.py.)  Standard library only.
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, distribution
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

HERE = Path(__file__).resolve().parent


def expected_version() -> str:
    """``build.expected_version()`` of this folder; build.py is loaded under its own name."""
    spec = spec_from_file_location("larch_patches_build", HERE / "build.py")
    build = module_from_spec(spec)
    spec.loader.exec_module(build)
    return build.expected_version(HERE)


def check(expected: str) -> tuple[str, list[str]]:
    """Where ``larch`` is imported from, and what is wrong with it as the patched build of
    version ``expected`` (nothing: an empty list)."""
    import larch

    where = Path(larch.__file__).resolve()
    found = []
    try:
        dist = distribution("xraylarch")
    except PackageNotFoundError:
        found.append("no xraylarch distribution is installed")
    else:
        if larch.__version__ != expected or dist.version != expected:
            found.append(f"larch reports {larch.__version__} (metadata {dist.version}), "
                         f"the patched build is {expected}")
        if Path(dist.locate_file("larch/__init__.py")).resolve() != where:
            found.append(f"larch is imported from {where}, not from the xraylarch distribution")
    if "site-packages" not in where.parts:
        found.append(f"larch is not imported from site-packages: {where}")
    return str(where.parent), found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", default=None,
                        help="the version to expect (default: the build of PIN plus the series)")
    args = parser.parse_args(argv)
    expected = args.version or expected_version()
    where, found = check(expected)
    if found:
        print("installed.py: " + "; ".join(found), file=sys.stderr)
        return 1
    print(f"installed.py: patched Larch {expected} at {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
