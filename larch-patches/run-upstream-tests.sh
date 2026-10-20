#!/usr/bin/env bash
# Run upstream xraylarch's own test suite, from a tree build.py wrote, against the installed Larch.
#
#   larch-patches/run-upstream-tests.sh SRC_TREE [--python PYTHON] [-- PYTEST_ARGS...]
#
#   SRC_TREE    build.py's DIR/xraylarch-src (its tests/ and examples/ are used)
#   --python    the environment that has the patched Larch installed (default: python3)
#
# The tests write files next to themselves and into examples/, so they run in a scratch copy
# of SRC_TREE; SRC_TREE is not changed. The file list is upstream's tests/run_tests.sh at the
# pin, plus test_xrf_model.py, which patch 0004 changed but run_tests.sh does not name.
# Plots go to matplotlib's Agg backend; wxPython is not installed (see DESELECT below).
set -Eeuo pipefail

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
[[ $# -ge 1 && "$1" != -* ]] || usage
SRC="$(cd -- "$1" && pwd)"; shift
PYTHON=python3
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) [[ $# -ge 2 ]] || usage; PYTHON="$2"; shift 2 ;;
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
  test_symbol_callbacks.py test_xas_data_source.py test_xrf_roi.py test_xafs_defects.py
  test_xrf_model.py
)

# These example scripts call wx plotting commands (plot_bkg, plot_chik, plot_chifit, ...),
# which Larch defines only when wxPython is installed. Without wx each fails with
# "NameError: 'plot_...' is not defined", on plain upstream at the pin as well, so the failure
# says nothing about the patches. XAScraft's environments do not install wxPython (it is not in
# the release constraints, and PyPI has no Linux wheels for it).
DESELECT=(
  test02_autobk test03_autobk2 test05_autobk_with_std test07_xafsft1 test08_xafsft2
  test09_xafsft3 test10_xafsft3 test13_feffit1 test15_feffit2 test16_feffit3
  test18_feffit_save_fit_stale_paths
)
deselect_args=()
for name in "${DESELECT[@]}"; do
  deselect_args+=(--deselect "test_larchexamples_xafs.py::TestScripts::$name")
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/xascraft-upstream-tests.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
cp -R "$SRC" "$WORK/xraylarch-src"
cd "$WORK/xraylarch-src/tests"

# -I: the scratch tree's larch/ must not shadow the installed build.
"$PYTHON" -I -c 'import larch; print(f"run-upstream-tests.sh: larch {larch.__version__} from {larch.__file__}")'
# Not -I: the tests import utils.py from this directory. --rootdir: test IDs (and so the
# --deselect IDs) are relative to tests/, whatever pytest would infer from the tree.
MPLBACKEND=Agg "$PYTHON" -m pytest -p no:cacheprovider -ra --rootdir "$PWD" "${FILES[@]}" "${deselect_args[@]}" \
  ${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}
