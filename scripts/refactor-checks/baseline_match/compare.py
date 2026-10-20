"""Compare two baseline-match capture folders exactly.

    python compare.py <first capture dir> <second capture dir>

Prints every differing path, one per line, and exits 1 if there is any.
Nothing is tolerated: a float differs if its repr differs, and 1 differs from 1.0.
"""
import json
import sys
from pathlib import Path

_SHOWN = 200


def _show(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= _SHOWN else text[:_SHOWN] + "…"


def _same_scalar(a, b):
    return type(a) is type(b) and (repr(a) == repr(b) if isinstance(a, float) else a == b)


def _walk(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            child = f"{path}.{key}"
            if key not in b:
                out.append(f"{child}: only in first")
            elif key not in a:
                out.append(f"{child}: only in second")
            else:
                _walk(a[key], b[key], child, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for index, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, f"{path}[{index}]", out)
    elif not _same_scalar(a, b):
        out.append(f"{path}: {_show(a)} != {_show(b)}")


def compare_documents(a, b):
    """Every path at which two JSON documents differ."""
    out = []
    _walk(a, b, "$", out)
    return out


def compare_dirs(first, second):
    """Every difference between two capture folders, as `scenario: path: detail` lines."""
    first, second = Path(first), Path(second)
    names = {p.stem for p in first.glob("*.json")} | {p.stem for p in second.glob("*.json")}
    out = []
    for name in sorted(names):
        a, b = first / f"{name}.json", second / f"{name}.json"
        if not b.exists():
            out.append(f"{name}: only in first")
        elif not a.exists():
            out.append(f"{name}: only in second")
        else:
            out.extend(f"{name}: {line}" for line in
                       compare_documents(json.loads(a.read_text()), json.loads(b.read_text())))
    return out


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    differences = compare_dirs(*args)
    for line in differences:
        print(line)
    scenarios = len({line.split(":", 1)[0] for line in differences})
    print(f"{len(differences)} differences in {scenarios} scenarios" if differences else "identical",
          file=sys.stderr)
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
