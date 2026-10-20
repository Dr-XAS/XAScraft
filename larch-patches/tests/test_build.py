"""``larch-patches/build.py`` builds the patched Larch from the pin and the series.

Every test runs the script as a program, the way the deploy script, the installer and CI
call it.  Upstream: ``$XASCRAFT_LARCH_UPSTREAM`` (a local clone path, which is what local
runs use, or a URL), else the URL in ``PIN``.  The build environment is the interpreter
running the tests (``--build-python``), which must have the pinned setuptools, wheel and
setuptools-scm installed, as an environment made from ``deploy/python-release-constraints.txt``
has.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

PATCHES_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PATCHES_DIR.parent
BUILD = PATCHES_DIR / "build.py"


def read_pin() -> dict[str, str]:
    pin: dict[str, str] = {}
    for line in (PATCHES_DIR / "PIN").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            pin[key.strip()] = value.strip()
    return pin


PIN = read_pin()
UPSTREAM = os.environ.get("XASCRAFT_LARCH_UPSTREAM", PIN["upstream-url"])


def run_build(out: Path, *args: str, script: Path = BUILD) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), "--upstream", UPSTREAM, "--out", str(out),
         "--build-python", sys.executable, *args],
        capture_output=True, text=True,
    )


def build_ok(out: Path, *args: str, script: Path = BUILD) -> Path:
    result = run_build(out, *args, script=script)
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def files_under(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file() or p.is_symlink()
    }


@pytest.fixture(scope="module")
def full(tmp_path_factory) -> Path:
    return build_ok(tmp_path_factory.mktemp("full") / "out")


def larch_tree_of(out: Path, scratch: Path) -> str:
    """The git tree hash of the exported ``larch/`` folder, computed from the files."""
    env = {**os.environ, "GIT_DIR": str(scratch), "GIT_WORK_TREE": str(out / "xraylarch-src")}
    subprocess.run(["git", "init", "-q", "--bare", str(scratch)], check=True)
    subprocess.run(["git", "add", "-f", "larch"], env=env, check=True,
                   cwd=out / "xraylarch-src")
    return subprocess.run(["git", "write-tree", "--prefix=larch/"], env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_full_build_gives_the_larch_tree_recorded_in_pin(full, tmp_path):
    """The exported ``larch/`` hashes to the git tree that ``PIN`` records."""
    assert larch_tree_of(full, tmp_path / "git") == PIN["patched-larch-tree"]


def test_full_build_larch_equals_the_baseline_larch_byte_for_byte(full):
    tag = subprocess.run(["git", "rev-parse", "-q", "--verify", "refactor-baseline^{commit}"],
                         cwd=REPO_ROOT, capture_output=True, text=True)
    if tag.returncode != 0:
        pytest.skip("tag refactor-baseline is not in this clone; the PIN tree test still runs")
    archive = subprocess.run(["git", "archive", "--format=tar", "refactor-baseline", "larch"],
                             cwd=REPO_ROOT, check=True, capture_output=True).stdout
    baseline = full.parent / "baseline"
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(baseline, filter="data")
    assert files_under(full / "xraylarch-src" / "larch") == files_under(baseline / "larch")


# The XAScraft commit each patch came from (README.md, "Patches"; notes/01 section 3).
XASCRAFT_COMMITS = {
    "0001": "e47015166",
    "0002": "3ca0a9716",
    "0003": "ab60c3776",
    "0004": "cc099c125",
    "0005": "b334e57f8",
    "0006": "8d37ac358",
    "0007": "aee4bb5e6",
}


def series_id(patch_dir: Path, skip: tuple[str, ...] = ()) -> str:
    """The patch-set id as the ticket defines it: sha256 of the patch files' bytes in order."""
    files = sorted((patch_dir / "series").glob("*.patch"))
    data = b"".join(p.read_bytes() for p in files if p.name[:4] not in skip)
    return hashlib.sha256(data).hexdigest()[:12]


def identity(out: Path) -> dict:
    return json.loads((out / "IDENTITY").read_text())


def test_identity_names_the_pin_the_patch_set_and_the_version(full):
    ident = identity(full)
    patch_set = series_id(PATCHES_DIR)
    assert ident["pin"] == PIN["upstream-commit"] == "8d6cd41c2b2a19260dbc80519c3c95211331d4fc"
    assert ident["upstream_version"] == "2026.3.1.post35+g8d6cd41c2"
    assert ident["patch_set_id"] == patch_set
    assert ident["version"] == f"2026.3.1.post35+g8d6cd41c2.xascraft.{patch_set}"
    assert ident["excluded"] == []
    assert ident["pure_upstream"] is False
    assert [p["number"] for p in ident["patches"]] == list(XASCRAFT_COMMITS)
    for entry in ident["patches"]:
        assert entry["xascraft_commit"].startswith(XASCRAFT_COMMITS[entry["number"]])
        assert len(entry["xascraft_commit"]) == 40
        assert (PATCHES_DIR / "series" / entry["file"]).is_file()
    assert ident["larch_tree"] == PIN["patched-larch-tree"]


def the_wheel(out: Path) -> Path:
    wheels = sorted((out / "dist").glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def installed_versions(wheel: Path, target: Path) -> list[str]:
    """Install the wheel (no dependencies) into ``target`` and ask it for its version
    the two ways the app and Python can: package metadata and ``larch.__version__``."""
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps",
                    "--target", str(target), str(wheel)], check=True)
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import importlib.metadata as md, larch;"
        "assert larch.__file__.startswith(sys.argv[1]), larch.__file__;"
        "print(md.version('xraylarch')); print(larch.__version__)"
    )
    # Run outside the repository, so its root larch/ folder cannot shadow the install.
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(target)], cwd=target,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


def test_installed_wheel_reports_the_version(full, tmp_path):
    version = f"2026.3.1.post35+g8d6cd41c2.xascraft.{series_id(PATCHES_DIR)}"
    wheel = the_wheel(full)
    assert wheel.name == f"xraylarch-{version}-py3-none-any.whl"
    assert installed_versions(wheel, tmp_path / "site") == [version, version]


def test_wheel_carries_the_whole_patched_larch_tree(full):
    """Built without git, the wheel still ships every file under larch/ (MANIFEST.in), plus
    the generated _version.py and nothing else."""
    import zipfile

    with zipfile.ZipFile(the_wheel(full)) as whl:
        in_wheel = {n: whl.read(n) for n in whl.namelist()
                    if n.startswith("larch/") and not n.endswith("/")}
    version_py = in_wheel.pop("larch/_version.py").decode()
    assert f"__version__ = version = '{identity(full)['version']}'" in version_py
    source = {f"larch/{k}": v for k, v in files_under(full / "xraylarch-src" / "larch").items()}
    assert in_wheel.keys() == source.keys()
    assert in_wheel == source


def test_dist_has_a_matching_sdist(full):
    sdists = sorted((full / "dist").glob("*.tar.gz"))
    assert [s.name for s in sdists] == [f"xraylarch-{identity(full)['version']}.tar.gz"]


def test_two_builds_are_identical(full, tmp_path):
    """Same inputs, same outputs: tree, IDENTITY, wheel and sdist, byte for byte."""
    again = build_ok(tmp_path / "again")
    assert files_under(again / "xraylarch-src") == files_under(full / "xraylarch-src")
    assert (again / "IDENTITY").read_bytes() == (full / "IDENTITY").read_bytes()
    assert files_under(again / "dist") == files_under(full / "dist")


def test_a_url_gives_the_same_build_as_a_local_clone(full, tmp_path):
    """The one-commit fetch path (a file:// URL to the same clone stands in for GitHub)."""
    url = Path(UPSTREAM).resolve().as_uri() if Path(UPSTREAM).is_dir() else UPSTREAM
    result = subprocess.run(
        [sys.executable, str(BUILD), "--upstream", url, "--out", str(tmp_path / "out"),
         "--build-python", sys.executable], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out" / "IDENTITY").read_bytes() == (full / "IDENTITY").read_bytes()
    assert files_under(tmp_path / "out" / "dist") == files_under(full / "dist")


def copy_of_the_queue(dest: Path) -> Path:
    """A copy of build.py, PIN and series/ to change without touching the real queue."""
    import shutil

    dest.mkdir()
    shutil.copy2(BUILD, dest / "build.py")
    shutil.copy2(PATCHES_DIR / "PIN", dest / "PIN")
    shutil.copytree(PATCHES_DIR / "series", dest / "series")
    return dest


def test_changing_a_patch_changes_the_id(full, tmp_path):
    """A message-only change: same Larch tree, different bytes, so a different id."""
    queue = copy_of_the_queue(tmp_path / "queue")
    patch = next((queue / "series").glob("0007-*.patch"))
    patch.write_bytes(patch.read_bytes().replace(b"\nXAScraft-commit:",
                                                 b"\nReworded: yes\nXAScraft-commit:", 1))
    out = build_ok(tmp_path / "out", script=queue / "build.py")
    changed = identity(out)
    assert changed["patch_set_id"] == series_id(queue)
    assert changed["patch_set_id"] != identity(full)["patch_set_id"]
    assert changed["version"] == f"{PIN['upstream-version']}.xascraft.{series_id(queue)}"
    assert changed["larch_tree"] == identity(full)["larch_tree"]


def test_a_full_build_whose_larch_tree_differs_from_pin_stops(tmp_path):
    """If the series gives another larch/ tree than PIN records, the build is refused, so
    an unreviewed tree never ships under the queue's name."""
    queue = copy_of_the_queue(tmp_path / "queue")
    pin = (queue / "PIN").read_text()
    (queue / "PIN").write_text(pin.replace(PIN["patched-larch-tree"], "0" * 40))
    out = tmp_path / "out"
    result = run_build(out, script=queue / "build.py")
    assert result.returncode != 0
    assert "patched-larch-tree" in result.stderr
    assert not out.exists()


def test_a_corrupted_patch_stops_the_build_and_writes_nothing(tmp_path):
    queue = copy_of_the_queue(tmp_path / "queue")
    patch = next((queue / "series").glob("0003-*.patch"))
    text = patch.read_text()
    # Damage a context line of the first hunk, so git am cannot place it.
    hunk = text.index("\n@@ ")
    line_start = text.index("\n ", hunk + 1) + 2
    patch.write_text(text[:line_start] + "corrupted " + text[line_start:])
    out = tmp_path / "out"
    result = run_build(out, script=queue / "build.py")
    assert result.returncode != 0
    assert "0003-" in result.stderr and "does not apply" in result.stderr
    assert not out.exists()


# git rev-parse 8d6cd41c2b2a19260dbc80519c3c95211331d4fc:larch in the upstream clone.
UPSTREAM_LARCH_TREE = "244732f073d99905e9414fc12379b58de769c220"


@pytest.fixture(scope="module")
def pure(tmp_path_factory) -> Path:
    return build_ok(tmp_path_factory.mktemp("pure") / "out", "--pure-upstream")


def test_pure_upstream_build_is_upstream_at_the_pin(pure, tmp_path):
    ident = identity(pure)
    assert larch_tree_of(pure, tmp_path / "git") == ident["larch_tree"] == UPSTREAM_LARCH_TREE
    assert ident["pure_upstream"] is True
    assert ident["patch_set_id"] is None
    assert ident["patches"] == []
    assert ident["excluded"] == list(XASCRAFT_COMMITS)
    assert ident["version"] == "2026.3.1.post35+g8d6cd41c2"
    assert installed_versions(the_wheel(pure), tmp_path / "site") == [ident["version"]] * 2


def test_exclude_leaves_one_patch_out_and_says_so(full, pure, tmp_path):
    out = build_ok(tmp_path / "out", "--exclude", "0001")
    ident = identity(out)
    patch_set = series_id(PATCHES_DIR, skip=("0001",))
    assert ident["patch_set_id"] == patch_set != identity(full)["patch_set_id"]
    assert ident["version"] == f"2026.3.1.post35+g8d6cd41c2.xascraft.{patch_set}.without0001"
    assert ident["excluded"] == ["0001"]
    assert [p["number"] for p in ident["patches"]] == list(XASCRAFT_COMMITS)[1:]
    assert the_wheel(out).name == f"xraylarch-{ident['version']}-py3-none-any.whl"
    # 0001 changes only larch/io/csvfiles.py: that file is upstream's, the rest is patched.
    larch = files_under(out / "xraylarch-src" / "larch")
    csv = "io/csvfiles.py"
    assert larch[csv] == files_under(pure / "xraylarch-src" / "larch")[csv]
    assert larch[csv] != files_under(full / "xraylarch-src" / "larch")[csv]
    assert {k: v for k, v in larch.items() if k != csv} == {
        k: v for k, v in files_under(full / "xraylarch-src" / "larch").items() if k != csv}


@pytest.mark.parametrize("args, message", [
    (["--exclude", "0099"], "no patch 0099"),
    (["--pure-upstream", "--exclude", "0001"], "not allowed with"),
])
def test_bad_selections_are_refused(tmp_path, args, message):
    result = run_build(tmp_path / "out", *args)
    assert result.returncode != 0
    assert message in result.stderr
    assert not (tmp_path / "out").exists()
