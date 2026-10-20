#!/usr/bin/env bash
set -Eeuo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
XRAYLARCH_WEB_TEST_MODE=1 source "$repo_root/scripts/deploy-xraylarch-web.sh"
fail_test() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
release="$test_root/build"
mkdir -p "$release/backend/.venv/bin" "$release/deploy"
printf '%s\n' 'fastapi==0.116.1' 'xlwt==1.3.0' 'xlrd==2.0.2' > "$release/backend/requirements.txt"
printf '%s\n' 'fastapi==0.116.1' > "$release/deploy/python-release-constraints.txt"
run_clean() {
  printf '%s\n' "$PWD" > "$test_root/cwd"
  printf '%s\n' "$@" > "$test_root/args"
  if [[ "$*" == *'pip install'* ]]; then
    local previous='' argument
    for argument in "$@"; do
      [[ "$previous" != --requirement ]] || printf '%s\n' "$argument" > "$test_root/installed-requirements"
      previous="$argument"
    done
  fi
  return "${command_status:-0}"
}
declare -F install_backend_requirements >/dev/null || fail_test 'backend requirement install helper is missing'
install_backend_requirements "$release" || fail_test 'backend dependency installation must succeed'
[[ "$(cat "$test_root/cwd")" == "$release/backend" ]] || fail_test 'requirements must resolve from backend cwd'
[[ "$(cat "$test_root/installed-requirements")" == requirements.txt ]] || fail_test 'install the web dependencies declared in backend/requirements.txt'
grep -Fx -- '--constraint' "$test_root/args" >/dev/null || fail_test 'constraints argument missing'
grep -Fx -- "$release/deploy/python-release-constraints.txt" "$test_root/args" >/dev/null || fail_test 'wrong constraints file'
command_status=7
if install_backend_requirements "$release"; then fail_test 'dependency installation failure must propagate'; fi
command_status=0
assert_backend_application_import "$release" || fail_test 'app import must succeed'
[[ "$(cat "$test_root/cwd")" == "$release/backend" ]] || fail_test 'app import must use backend cwd'
grep -Fx 'from xraylarch_web.main import app' "$test_root/args" >/dev/null || fail_test 'smoke must import complete application'
command_status=1
if assert_backend_application_import "$release"; then fail_test 'broken app import must fail'; fi
command_status=0

# Exercise the actual Node expression while keeping the deployment host and
# conda environment out of the test. Include both sides of the major boundary.
(
  CONDA_BIN=/fake/conda
  run_clean() {
    [[ "$#" -eq 8 && "$1" == "$CONDA_BIN" && "$2" == run && "$3" == --no-capture-output &&
       "$4" == -n && "$5" == drxas-node20 && "$6" == node && "$7" == -e ]] \
      || fail_test 'runtime check must use the existing frontend conda environment'
    node -e 'Object.defineProperty(process.versions, "node", { value: process.argv[1] }); eval(process.argv[2])' \
      "$runtime_version" "$8"
  }
  for runtime_version in 18.20.8 20.9.0 20.19.6 21.7.3; do
    if assert_frontend_runtime_supported >"$test_root/runtime-output" 2>&1; then
      fail_test "unsupported Node $runtime_version passed the frontend runtime gate"
    fi
    grep -F 'Node.js 22 or newer for Plotly 4' "$test_root/runtime-output" >/dev/null \
      || fail_test 'runtime failure must explain the required upgrade'
  done
  for runtime_version in 22.0.0 22.14.0 24.0.0; do
    assert_frontend_runtime_supported || fail_test "supported Node $runtime_version failed the frontend runtime gate"
  done
)


# CI and deployment must execute the same complete installer. Every dependency
# gate must fail before the immutable release or frontend can be published.
declare -F install_release_backend >/dev/null || fail_test 'shared release installer is missing'

# Larch comes from XAScraft's patched build (larch-patches/build.py), never from
# the release checkout. Each run records its run_clean calls, one stage per line.
larch_release="$test_root/larch-release"
mkdir -p "$larch_release/backend/.venv/bin" "$larch_release/deploy" "$larch_release/larch-patches"
printf '%s\n' 'fastapi==0.116.1' > "$larch_release/backend/requirements.txt"
: > "$larch_release/deploy/python-release-constraints.txt"
run_larch_install() (
  # $1: stage to fail (or none); the environment selects the Larch source.
  local failure="$1"
  calls="$test_root/larch-calls"
  : > "$calls"
  run_clean() {
    local stage=''
    case "$*" in
      *'pip install --requirement '*'/deploy/python-release-constraints.txt '*) stage=constraints ;;
      *'pip install --no-deps --no-build-isolation --upgrade setuptools=='*) stage=build_tools ;;
      *'pip wheel '*) stage=checkout_wheel ;;
      *'larch-patches/build.py '*)
        stage=larch_build
        local previous='' argument
        for argument in "$@"; do
          if [[ "$previous" == --out ]]; then
            [[ ! -e "$argument" ]] || fail_test 'build.py output directory must be fresh'
            mkdir -p "$argument/dist"
            : > "$argument/dist/xraylarch-2026.3.1.post35+g8d6cd41c2.xascraft.test-py3-none-any.whl"
            printf '%s\n' "$argument" > "$test_root/larch-out"
          fi
          previous="$argument"
        done
        ;;
      *'pip install --constraint '*'xraylarch-'*'.whl') stage=larch_install ;;
      *'pip install --requirement requirements.txt '*) stage=backend ;;
      *'import larch, xraylarch_web'*) stage=import ;;
      *'from xraylarch_web.main import app'*) stage=app ;;
      *'patched-larch-tree'*) stage=larch_check ;;
      *'pip check'*) stage=check ;;
      *'pip freeze'*) stage=freeze ;;
      *) stage="unexpected: $*" ;;
    esac
    local call="$*"
    printf '%s\t%s\n' "$stage" "${call//$'\n'/ }" >> "$calls"
    [[ "$stage" != "$failure" ]] || return 7
  }
  install_release_backend "$larch_release"
)
larch_stages() { cut -f1 "$test_root/larch-calls" | paste -sd ' ' -; }
larch_call() { grep "^$1"$'\t' "$test_root/larch-calls" | cut -f2-; }

unset XASCRAFT_LARCH_UPSTREAM XASCRAFT_LARCH_WHEEL
run_larch_install none || fail_test 'release backend install with a Larch build must succeed'
[[ "$(larch_stages)" == 'constraints build_tools larch_build larch_install backend import app larch_check check freeze' ]] \
  || fail_test "unexpected release install stages: $(larch_stages)"
larch_out=$(cat "$test_root/larch-out")
build_call=$(larch_call larch_build)
[[ "$build_call" == "$larch_release/backend/.venv/bin/python -I $larch_release/larch-patches/build.py --out $larch_out --build-python $larch_release/backend/.venv/bin/python" ]] \
  || fail_test "build.py must build with the release interpreter and fetch the pin itself: $build_call"
[[ "$(larch_call larch_install)" == "$larch_release/backend/.venv/bin/python -m pip install --constraint $larch_release/deploy/python-release-constraints.txt $larch_out/dist/xraylarch-2026.3.1.post35+g8d6cd41c2.xascraft.test-py3-none-any.whl" ]] \
  || fail_test "the built wheel must be installed under the release constraints: $(larch_call larch_install)"
[[ ! -e "$larch_out" ]] || fail_test 'build.py output must be removed after installation'

# An operator may point build.py at a local upstream clone or mirror.
XASCRAFT_LARCH_UPSTREAM="$test_root/xraylarch clone" run_larch_install none \
  || fail_test 'release backend install from a local upstream must succeed'
[[ "$(larch_call larch_build)" == *"--build-python $larch_release/backend/.venv/bin/python --upstream $test_root/xraylarch clone" ]] \
  || fail_test "XASCRAFT_LARCH_UPSTREAM must reach build.py: $(larch_call larch_build)"

# Mounted builds must receive their public path at build time. Health qualification
# must bind the backend response to the exact immutable release and contract.
build_source=$(declare -f build_release)
[[ "$build_source" == *'NEXT_PUBLIC_APP_BASE_PATH'* ]] || fail_test 'frontend build must receive the mounted base path'
health_source=$(declare -f backend_health_ok)
[[ "$health_source" == *'git_revision'* ]] || fail_test 'backend health must verify the exact release revision'
[[ "$health_source" == *'integration_contract_version'* ]] || fail_test 'backend health must verify integration contract version 2'

for failure in constraints larch_build larch_install backend app larch_check check freeze collection runtime frontend_runtime; do
(
  XRAYLARCH_WEB_TEST_MODE=1 source "$repo_root/scripts/deploy-xraylarch-web.sh"
  RELEASES_ROOT="$test_root/build-releases-$failure"
  REQUESTED_SHA=0123456789abcdef0123456789abcdef01234567
  CONDA_BIN=/fake/conda
  CANDIDATE_DATA="$test_root/candidate-$failure"
  mkdir -p "$RELEASES_ROOT" "$CANDIDATE_DATA"
  events="$test_root/build-events-$failure"
  run_clean() {
    local stage=''
    case "$*" in
      'git init --quiet '*)
        local target="${@: -1}"
        mkdir -p "$target/backend/.venv/bin" "$target/frontend" "$target/deploy"
        printf '%s\n' 'xlwt==1.3.0' > "$target/backend/requirements.txt"
        : > "$target/deploy/python-release-constraints.txt"
        ;;
      *'rev-parse '*) printf '%s\n' "$REQUESTED_SHA" ;;
      *'git '*describe*) printf '1.0.0\n' ;;
      *'pip install --requirement '*'/deploy/python-release-constraints.txt '*) stage=constraints ;;
      *'pip wheel '*) fail_test 'the release checkout must not be built as Larch' ;;
      *'larch-patches/build.py '*)
        stage=larch_build
        mkdir -p ../.release-larch/dist
        : > ../.release-larch/dist/xraylarch-test.whl
        ;;
      *'pip install --constraint '*'xraylarch-test.whl') stage=larch_install ;;
      *'pip install --requirement requirements.txt '*) stage=backend ;;
      *'from xraylarch_web.main import app'*) stage=app ;;
      *'patched-larch-tree'*) stage=larch_check ;;
      *'pip check'*) stage=check ;;
      *'pip freeze'*) stage=freeze ;;
      *'pytest '*--collect-only*) stage=collection ;;
      *'pytest '*) stage=runtime ;;
      *'node -e '*) stage=frontend_runtime ;;
      *'npm '*) fail_test 'frontend install/build must not run after a dependency or runtime failure' ;;
    esac
    if [[ -n "$stage" ]]; then
      echo "$stage" >> "$events"
      [[ "$stage" != "$failure" ]] || return 7
    fi
  }
  if build_release; then fail_test "build must fail on $failure failure"; fi
  [[ "$(tail -n 1 "$events")" == "$failure" ]] || fail_test "build continued after $failure failure"
  [[ ! -e "$RELEASES_ROOT/$REQUESTED_SHA" ]] || fail_test "$failure failure published immutable release"
)
done
(
  XRAYLARCH_WEB_TEST_MODE=1 source "$repo_root/scripts/deploy-xraylarch-web.sh"
  RELEASES_ROOT="$test_root/helper-call"
  REQUESTED_SHA=0123456789abcdef0123456789abcdef01234567
  CONDA_BIN=/fake/conda
  mkdir -p "$RELEASES_ROOT"
  run_clean() {
    case "$*" in
      *'rev-parse '*) printf '%s\n' "$REQUESTED_SHA" ;;
      *'git '*describe*) printf '1.0.0\n' ;;
    esac
  }
  install_release_backend() { echo shared > "$test_root/shared-called"; return 7; }
  if build_release; then fail_test 'build ignored shared installer failure'; fi
  [[ "$(cat "$test_root/shared-called")" == shared ]] || fail_test 'production must call shared installer'
  [[ ! -e "$RELEASES_ROOT/$REQUESTED_SHA" ]] || fail_test 'shared installer failure published release'
)

# Runtime checks may mutate workspace data: use disposable candidate data even
# when the enclosing deployer points at the live database.
for failure in none collection runtime; do
(
  XRAYLARCH_WEB_TEST_MODE=1 source "$repo_root/scripts/deploy-xraylarch-web.sh"
  CANDIDATE_DATA="$test_root/verification-$failure"
  DATA_ROOT="$test_root/live-data"
  mkdir -p "$CANDIDATE_DATA" "$DATA_ROOT"
  printf 'preserve\n' > "$DATA_ROOT/sentinel"
  run_clean() {
    [[ "$DATA_ROOT" == "$CANDIDATE_DATA"/backend-verification.* ]] || fail_test 'verification used live data root'
    [[ -d "$DATA_ROOT" ]] || fail_test 'verification data root must exist'
    printf '%s\n' "$DATA_ROOT" >> "$CANDIDATE_DATA/observed-roots"
    local stage=runtime
    [[ "$*" != *--collect-only* ]] || stage=collection
    [[ "$stage" != "$failure" ]] || return 7
  }
  if verify_release_backend "$test_root/build"; then
    [[ "$failure" == none ]] || fail_test 'verification ignored test failure'
  else
    [[ "$failure" != none ]] || fail_test 'verification failed successful checks'
  fi
  [[ "$DATA_ROOT" == "$test_root/live-data" && "$(cat "$DATA_ROOT/sentinel")" == preserve ]] || fail_test 'verification altered live data'
  while IFS= read -r root; do
    [[ ! -e "$root" ]] || fail_test 'verification data was not cleaned up'
  done < "$CANDIDATE_DATA/observed-roots"
)
done
grep -F 'verify_release_backend "$GITHUB_WORKSPACE"' "$repo_root/.github/workflows/test-web-backend-release.yml" >/dev/null || fail_test 'CI must invoke shared runtime verification'

RELEASES_ROOT="$test_root/releases"
REQUESTED_SHA=0123456789abcdef0123456789abcdef01234567
mkdir -p "$RELEASES_ROOT"
release="$RELEASES_ROOT/$REQUESTED_SHA"
events="$test_root/events"
verify_remote_branch_tip() { echo remote >> "$events"; return "${remote_status:-0}"; }
build_release() { echo build >> "$events"; }
activate_release() { echo activate >> "$events"; }
assert_release_identity() {
  echo identity >> "$events"
  [[ -d "$release" && ! -L "$release" && -f "$release/.xraylarch-release.sha" ]]
}
assert_backend_application_import() { echo smoke >> "$events"; return "${smoke_status:-0}"; }
: > "$events"
perform_deploy || fail_test 'absent release must build'
[[ "$(cat "$events")" == $'remote\nbuild\nactivate' ]] || fail_test 'new release must build after remote verification'
mkdir -p "$release"
printf '%s\n' "$REQUESTED_SHA" > "$release/.xraylarch-release.sha"
: > "$events"
perform_deploy || fail_test 'completed release must be retryable'
[[ "$(cat "$events")" == $'remote\nidentity\nsmoke\nactivate' ]] || fail_test 'retry must validate and smoke existing release without rebuilding'
smoke_status=1
: > "$events"
if perform_deploy; then fail_test 'broken existing application must fail'; fi
! grep -Eq 'build|activate' "$events" || fail_test 'broken existing app must remain untouched'
smoke_status=0
rm "$release/.xraylarch-release.sha"
: > "$events"
if perform_deploy; then fail_test 'incomplete release must fail'; fi
! grep -Eq 'build|activate|smoke' "$events" || fail_test 'incomplete release must remain untouched'
rmdir "$release"
ln -s "$test_root/missing" "$release"
: > "$events"
if perform_deploy; then fail_test 'broken symlink release must fail'; fi
[[ -L "$release" ]] || fail_test 'symlink must not be removed'
! grep -Eq 'build|activate|smoke' "$events" || fail_test 'symlink release must remain untouched'
remote_status=1
: > "$events"
if perform_deploy; then fail_test 'remote mismatch must fail'; fi
[[ "$(cat "$events")" == remote ]] || fail_test 'remote must be verified before release actions'
printf 'release dependency and retry tests passed\n'
