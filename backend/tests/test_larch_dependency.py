"""The backend runs on XAScraft's patched Larch build, not on Larch code in this repository.

The patched build is upstream xraylarch at the pin in ``larch-patches/PIN`` plus the patches
in ``larch-patches/series/``; ``larch-patches/build.py`` builds it and names its version.
"""
import ast
from importlib.metadata import distributions
from importlib.util import find_spec, module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import re
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

from xraylarch_web.config import Settings
from xraylarch_web.main import create_app

REPO = Path(__file__).resolve().parents[2]
PATCHES = REPO / "larch-patches"


def patches_module(name: str):
    """``larch-patches/<name>.py``, loaded under a name of its own."""
    spec = spec_from_file_location(f"larch_patches_{name}", PATCHES / f"{name}.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_build_version() -> str:
    """The version ``build.py`` gives a build of the current pin and series (IDENTITY's
    ``version``)."""
    return patches_module("build").expected_version(PATCHES)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path: Path) -> dict[str, str]:
    """``name==version`` lines of a requirements file, by canonical name."""
    found = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, _, version = line.partition("==")
            found[canonical(name)] = version.strip()
    return found


def direct_imports() -> set[str]:
    """Third-party modules ``xraylarch_web`` imports by absolute name."""
    package = REPO / "backend" / "xraylarch_web"
    own = {"xraylarch_web"} | {path.stem for path in package.glob("*.py")}
    found = set()
    for source in package.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                found.add(node.module)
    return {name for name in found
            if name.partition(".")[0] not in sys.stdlib_module_names | own}


def owners() -> dict[Path, str]:
    """Installed files, mapped to the distribution that ships them."""
    return {Path(dist.locate_file(file)).resolve(): canonical(dist.metadata["Name"])
            for dist in distributions() for file in dist.files or ()
            if file.suffix == ".py"}


def test_requirements_declare_every_direct_import_at_the_baseline_pin_and_no_larch():
    requirements = REPO / "backend" / "requirements.txt"
    lines = [line.split("#", 1)[0].strip() for line in requirements.read_text().splitlines()]
    declared = pins(requirements)
    # Larch comes from the patched build (larch-patches/install-dev.sh), never from this
    # repository and never from PyPI.
    assert not [line for line in lines if line.startswith(("-e", ".", "/"))]
    assert "xraylarch" not in declared
    assert len(declared) == len([line for line in lines if line])

    # Exact pins, equal to the release constraints wherever those pin the package too
    # (xlwt and xlrd are pinned only here).
    baseline = pins(REPO / "deploy" / "python-release-constraints.txt")
    assert {name: baseline.get(name, version) for name, version in declared.items()} == declared

    # The optional engines are declared in requirements-engines.txt and may be absent.
    optional = set(pins(REPO / "backend" / "requirements-engines.txt"))
    shipped_by = owners()
    needed = {}
    for module in sorted(direct_imports()):
        top = module.partition(".")[0]
        if top == "larch" or canonical(top) in optional:
            continue
        origin = Path(find_spec(module).origin).resolve()
        needed.setdefault(shipped_by.get(origin, f"? {origin}"), []).append(module)
    assert {name: modules for name, modules in needed.items() if name not in declared} == {}


def test_larch_is_the_installed_patched_build_not_the_repository_copy():
    # The check install-dev.sh and the deploy script make: version, distribution, site-packages.
    _, problems = patches_module("installed").check(patched_build_version())
    assert problems == []


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_root=tmp_path))) as client:
        yield client


def test_processed_groups_report_the_patched_build_version_as_their_larch_version(
        client, xas_arrays):
    project = client.post("/api/athena/projects").json()
    energy, mu = xas_arrays
    text = StringIO()
    np.savetxt(text, np.column_stack((energy, mu)), header="energy mu")
    inspected = client.post(f"/api/athena/projects/{project['id']}/inspect",
                            files={"file": ("cu.dat", text.getvalue().encode())}).json()
    columns = {column["name"]: column["column_id"] for column in inspected["columns"]}
    imported = client.post(f"/api/athena/projects/{project['id']}/import", json={
        "version": project["version"], "upload_id": inspected["upload_id"],
        "energy_column": columns["energy"], "numerator": [columns["mu"]], "mode": "mu"})
    assert imported.status_code == 200, imported.text

    [group] = imported.json()["groups"]
    assert group["result"]["larch_version"] == patched_build_version()
