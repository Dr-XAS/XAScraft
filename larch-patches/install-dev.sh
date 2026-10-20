#!/usr/bin/env bash
# Build XAScraft's patched Larch with build.py and install its wheel into a Python environment.
#
#   larch-patches/install-dev.sh [--python PYTHON] [--upstream PATH_OR_URL] [--keep DIR]
#
#   --python    the environment's interpreter (default: backend/.venv/bin/python)
#   --upstream  a local xraylarch clone (only read) or a git URL (default: upstream-url in PIN)
#   --keep      also keep build.py's output (tree, wheel, sdist, IDENTITY) in DIR
#
# The interpreter is also the build backend (build.py --build-python), so it must have
# setuptools, wheel and setuptools-scm at the pins in deploy/python-release-constraints.txt;
# an environment made from that file has them. The wheel's dependencies are installed under
# the same constraints. Any Larch already installed (an editable one included) is replaced.
# Ends by importing larch from outside the repository and checking its version against IDENTITY.
set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
REPO="$(dirname -- "$HERE")"
CONSTRAINTS="$REPO/deploy/python-release-constraints.txt"
PYTHON="$REPO/backend/.venv/bin/python"
UPSTREAM=""
KEEP=""

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) [[ $# -ge 2 ]] || usage; PYTHON="$2"; shift 2 ;;
    --upstream) [[ $# -ge 2 ]] || usage; UPSTREAM="$2"; shift 2 ;;
    --keep) [[ $# -ge 2 ]] || usage; KEEP="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done
[[ -x "$PYTHON" ]] || { echo "install-dev.sh: no interpreter at $PYTHON (create the venv first)" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/xascraft-larch-dev.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
OUT="$WORK/larch"

build_args=(--out "$OUT" --build-python "$PYTHON")
[[ -n "$UPSTREAM" ]] && build_args+=(--upstream "$UPSTREAM")
"$PYTHON" -I "$HERE/build.py" "${build_args[@]}"

wheels=("$OUT"/dist/xraylarch-*.whl)
[[ ${#wheels[@]} -eq 1 && -f "${wheels[0]}" ]] || { echo "install-dev.sh: expected one wheel in $OUT/dist" >&2; exit 1; }
version="$("$PYTHON" -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' "$OUT/IDENTITY")"

"$PYTHON" -m pip uninstall --yes --quiet xraylarch 2>/dev/null || true
"$PYTHON" -m pip install --no-input --quiet --disable-pip-version-check \
  --constraint "$CONSTRAINTS" "${wheels[0]}"

# Import from a neutral directory, so neither the repository nor its larch/ is on sys.path.
( cd "$WORK" && "$PYTHON" -I - "$version" "$REPO" <<'PY'
import sys
from importlib.metadata import version
from pathlib import Path
import larch
expected, repo = sys.argv[1], Path(sys.argv[2]).resolve()
where = Path(larch.__file__).resolve()
problems = []
if larch.__version__ != expected or version("xraylarch") != expected:
    problems.append(f"larch reports {larch.__version__} (metadata {version('xraylarch')}), "
                    f"IDENTITY says {expected}")
if where.is_relative_to(repo) and "site-packages" not in where.parts:
    problems.append(f"larch is imported from the repository: {where}")
if problems:
    sys.exit("install-dev.sh: " + "; ".join(problems))
print(f"install-dev.sh: installed larch {larch.__version__} at {where.parent}")
PY
)

if [[ -n "$KEEP" ]]; then
  mkdir -p -- "$KEEP"
  cp -R "$OUT"/. "$KEEP"/
  echo "install-dev.sh: build output kept in $KEEP"
fi
