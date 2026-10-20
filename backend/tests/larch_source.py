"""Where a hash manifest's source path lives.

The Athena fixture manifests pin Larch sources as ``larch/<module path>``. Larch is not part of
this repository; those names refer to the installed (patched) Larch package.
"""
from pathlib import Path

import larch

LARCH_PACKAGE = Path(larch.__file__).resolve().parent


def source_path(root: Path, name: str) -> Path:
    if name.startswith('larch/'):
        return LARCH_PACKAGE / name.removeprefix('larch/')
    return root / name
