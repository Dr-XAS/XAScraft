"""The backend runs on XAScraft's patched Larch build, not on Larch code in this repository.

The patched build is upstream xraylarch at the pin in ``larch-patches/PIN`` plus the patches
in ``larch-patches/series/``; ``larch-patches/build.py`` builds it and names its version.
"""
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from xraylarch_web.config import Settings
from xraylarch_web.main import create_app

REPO = Path(__file__).resolve().parents[2]
PATCHES = REPO / "larch-patches"


def patched_build_version() -> str:
    """The version ``build.py`` gives a build of the current pin and series (IDENTITY's
    ``version``)."""
    spec = spec_from_file_location("larch_patches_build", PATCHES / "build.py")
    build = module_from_spec(spec)
    spec.loader.exec_module(build)
    pin = build.read_pin(PATCHES / "PIN")
    series = sorted((PATCHES / "series").glob("*.patch"))
    return build.make_identity(pin, series, series, False, pin["patched-larch-tree"])["version"]


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
