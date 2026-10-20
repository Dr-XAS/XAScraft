#!/usr/bin/env bash
# Run upstream xraylarch's own test suite, from a tree build.py wrote, against the installed Larch.
#
#   larch-patches/run-upstream-tests.sh SRC_TREE [--python PYTHON] [--known-failures] [-- PYTEST_ARGS...]
#
#   SRC_TREE          build.py's DIR/xraylarch-src (its tests/ and examples/ are used)
#   --python          the environment that has the patched Larch installed (default: python3)
#   --known-failures  run only KNOWN_FAILURES (below); succeed when exactly those fail
#
# The tests write files next to themselves and into examples/, so they run in a scratch copy
# of SRC_TREE; SRC_TREE is not changed. The file list is upstream's tests/run_tests.sh at the
# pin, plus test_xrf_model.py, which patch 0004 changed but run_tests.sh does not name.
# Plots go to matplotlib's Agg backend; wxPython is not installed (see KNOWN_FAILURES below).
set -Eeuo pipefail

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
[[ $# -ge 1 && "$1" != -* ]] || usage
SRC="$(cd -- "$1" && pwd)"; shift
PYTHON=python3
PYTEST_ARGS=()
KNOWN_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) [[ $# -ge 2 ]] || usage; PYTHON="$2"; shift 2 ;;
    --known-failures) KNOWN_ONLY=1; shift ;;
    --) shift; PYTEST_ARGS=("$@"); break ;;
    *) usage ;;
  esac
done
[[ -d "$SRC/tests" && -d "$SRC/examples" ]] || { echo "run-upstream-tests.sh: $SRC has no tests/ and examples/" >&2; exit 1; }

FILES=(
  test_athena_addgroup.py test_basic_processing.py test_funccalls.py test_importlarch.py
  test_interpreter.py test_jsonutils.py test_larch_interpreter.py test_larchexamples_basic.py
  test_larchexamples_xafs.py test_larchexamples_xray.py test_math_deglitch.py test_math_utils.py
  test_plot_rixsdata_import.py test_read_beamlinedata.py test_read_xafsdata.py
  test_symbol_callbacks.py test_xafs_rebin.py test_xas_data_source.py test_xrf_roi.py
  test_xafs_defects.py test_xrf_model.py
)

# Known pre-existing failures. These example scripts call wx plotting commands (plot_bkg,
# plot_chik, plot_chifit, ...), which Larch defines only when wxPython is installed. Without
# wx each fails ("NameError: 'plot_...' is not defined"), on plain upstream at the pin as
# well, so the failure says nothing about the patches. XAScraft's environments do not
# install wxPython (it is not in the release constraints, and PyPI has no Linux wheels).
# The main run deselects them; --known-failures runs only them and checks that exactly
# these fail, so every CI run shows them and notices when this list goes stale.
KNOWN_FAILURES=(
  test02_autobk test03_autobk2 test05_autobk_with_std test07_xafsft1 test08_xafsft2
  test09_xafsft3 test10_xafsft3 test13_feffit1 test15_feffit2 test16_feffit3
  test18_feffit_save_fit_stale_paths
)
known_ids=()
for name in "${KNOWN_FAILURES[@]}"; do
  known_ids+=("test_larchexamples_xafs.py::TestScripts::$name")
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/xascraft-upstream-tests.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
# The physical path: pytest resolves symlinks (macOS's /var is /private/var), and a
# --rootdir that differs from the resolved path gives test IDs no deselect matches.
WORK="$(cd -- "$WORK" && pwd -P)"
cp -R "$SRC" "$WORK/xraylarch-src"
cd "$WORK/xraylarch-src/tests"

# -I: the scratch tree's larch/ must not shadow the installed build.
"$PYTHON" -I -c 'import larch; print(f"run-upstream-tests.sh: larch {larch.__version__} from {larch.__file__}")'
# Not -I: the tests import utils.py from this directory. --rootdir: test IDs (and so the
# known-failure IDs) are relative to tests/, whatever pytest would infer from the tree.
if [[ "$KNOWN_ONLY" -eq 0 ]]; then
  deselect_args=()
  for id in "${known_ids[@]}"; do deselect_args+=(--deselect "$id"); done
  MPLBACKEND=Agg "$PYTHON" -m pytest -p no:cacheprovider -ra --rootdir "$PWD" "${FILES[@]}" "${deselect_args[@]}" \
    ${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}
  exit
fi

# These are expected to fail, so pytest's exit status is not the result: each test's
# outcome in the JUnit report is.
MPLBACKEND=Agg "$PYTHON" -m pytest -p no:cacheprovider -q -rf --rootdir "$PWD" \
  --junitxml "$WORK/known-failures.xml" "${known_ids[@]}" ${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"} || true
"$PYTHON" -I - "$WORK/known-failures.xml" "${KNOWN_FAILURES[@]}" <<'PY'
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

report, known = Path(sys.argv[1]), sys.argv[2:]
if not report.is_file():
    sys.exit("run-upstream-tests.sh: pytest crashed before it reported the known failures")
outcome = {}
for case in ET.parse(report).iter("testcase"):
    outcome[case.get("name")] = next(
        (kind for kind in ("failure", "error", "skipped") if case.find(kind) is not None), "passed")
problems = [f"{name} now passes" if outcome.get(name) == "passed"
            else f"{name} did not run" if name not in outcome
            else f"{name} ends in {outcome[name]}, not failure"
            for name in known if outcome.get(name) != "failure"]
if problems:
    sys.exit("run-upstream-tests.sh: the known pre-existing failures changed: " + "; ".join(problems)
             + ". Update KNOWN_FAILURES in larch-patches/run-upstream-tests.sh and the list in"
             " larch-patches/README.md.")
print(f"run-upstream-tests.sh: {len(known)} known pre-existing failures, all failing as expected "
      "(they need wxPython, and fail on plain upstream as well):")
for name in known:
    print(f"  test_larchexamples_xafs.py::TestScripts::{name}")
if os.environ.get("GITHUB_ACTIONS") == "true":
    print(f"::warning title=Known pre-existing upstream failures::{len(known)} upstream tests fail "
          "without wxPython, as on plain upstream: " + ", ".join(known))
PY
