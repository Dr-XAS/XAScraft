#!/usr/bin/env python3
"""Export the canonical React element picker, or verify its downloadable archive."""

from __future__ import annotations

import argparse
from io import BytesIO
import os
from pathlib import Path
import stat
import tempfile
from zipfile import ZIP_STORED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend/components/artefacts/element-picker"
OUTPUT = ROOT / "frontend/public/artefacts/drxas-element-picker.zip"
FILES = (
    "index.ts",
    "elements.ts",
    "element-picker.tsx",
    "element-picker.module.css",
    "element-picker.module.css.d.ts",
    "example.tsx",
    "README.md",
    "LICENSE",
)


def archive_bytes() -> bytes:
    """Stable order, timestamps, permissions, and uncompressed source bytes."""
    missing = [name for name in FILES if not (SOURCE / name).is_file()]
    if missing:
        raise ValueError("Missing artefact source: " + ", ".join(missing))
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name in FILES:
            entry = ZipInfo("drxas-element-picker/" + name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = ZIP_STORED
            archive.writestr(entry, (SOURCE / name).read_bytes())
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Verify the current ZIP without writing files"
    )
    args = parser.parse_args()
    try:
        expected = archive_bytes()
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != expected:
            parser.exit(1, "Element-picker ZIP is missing or stale; run this script without --check.\n")
        print(f"Element-picker ZIP matches all {len(FILES)} source files.")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=OUTPUT.parent, suffix=".zip.tmp", delete=False) as target:
            temporary = Path(target.name)
            target.write(expected)
        temporary.chmod(0o644)
        os.replace(temporary, OUTPUT)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Exported {len(FILES)} files to {OUTPUT.relative_to(ROOT)} ({len(expected):,} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
