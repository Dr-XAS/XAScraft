"""The FLUO self-absorption correction gives the numbers of the previous Larch, through the API.

The reference is Larch 2026.3.1.post534+g3461938ac: the Larch XAScraft vendored at commit
3461938ac, which is upstream 8d6cd41c2 with the team's patches. Its preview and saved group for
Cu, Fe3C and Ni from `examples/xafsdata`, imported the way the UI imports a file, are pinned in
`fixtures/athena-self-absorption-fluo-larch-3461938ac.json.gz`, written by
`reference/self_absorption_fluo_reference.py` on that tree. Each spectrum runs twice: with the
E0 the import found, and with E0 set to the tabulated edge energy.

Upstream Larch `d6d27ccca` ("fluo: force recalculation of e0") made `fluo_corr` ignore the E0
it is given and normalize around its own, which moves the normalized corrected curve by up to
3.7% of the edge step on these spectra. Temporary patch 0009 keeps the E0 the app passes until
the owner decides (larch-patches/README.md, ledger "Self-absorption E0").
"""
import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from xraylarch_web.config import Settings
from xraylarch_web.main import create_app

XAFSDATA = Path(__file__).resolve().parents[2] / "examples" / "xafsdata"
FIXTURE = Path(__file__).parent / "fixtures" / "athena-self-absorption-fluo-larch-3461938ac.json.gz"
ATHENA = "/api/athena/projects"

# name: (file, formula, absorber, tabulated K-edge energy in eV)
SPECTRA = {
    "cu": ("cu_metal_rt.xdi", "Cu", "Cu", 8979.0),
    "fe3c": ("fe3c_rt.xdi", "Fe3C", "Fe", 7112.0),
    "ni": ("ni_metal_rt.xdi", "Ni", "Ni", 8333.0),
}
E0_CHOICES = ("imported", "tabulated")
# (spectrum name, E0 choice); the fixture keys each case as "name-choice".
CASES = [(name, e0) for name in SPECTRA for e0 in E0_CHOICES]


def case_key(case):
    return "-".join(case)


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def import_mutrans(client, name):
    """A new project holding the file's `mutrans` column as mu, as the UI's import does."""
    project = ok(client.post(ATHENA))
    inspected = ok(client.post(f"{ATHENA}/{project['id']}/inspect",
                               files={"file": (name, (XAFSDATA / name).read_bytes())}))
    columns = {column["name"]: column["column_id"] for column in inspected["columns"]}
    return ok(client.post(f"{ATHENA}/{project['id']}/import", json={
        "version": project["version"], "upload_id": inspected["upload_id"],
        "energy_column": columns["energy"], "numerator": [columns["mutrans"]], "data_type": "mu"}))


def fluo_outputs(client, case):
    """The panel's preview and the saved group's normalized mu for one case."""
    name, e0_choice = case
    filename, formula, element, tabulated = SPECTRA[name]
    project = import_mutrans(client, filename)
    group = project["groups"][0]
    if e0_choice == "tabulated":
        project = ok(client.post(f"{ATHENA}/{project['id']}/command", json={
            "version": project["version"], "action": "parameters", "group_ids": [group["id"]],
            "options": {"e0": tabulated}}))
    body = {"version": project["version"], "action": "self_absorption", "group_ids": [group["id"]],
            "options": {"formula": formula, "element": element, "edge": "K",
                        "angle_in": 45, "angle_out": 45}}
    row = ok(client.post(f"{ATHENA}/{project['id']}/self-absorption/preview", json=body))["results"][0]
    saved = ok(client.post(f"{ATHENA}/{project['id']}/command", json=body))
    child = saved["groups"][-1]
    assert child["id"] != group["id"]
    return {
        "method": row["details"]["method"],
        "e0": row["normalization"]["e0"],
        "energy": row["energy"],
        "measured": row["measured"],
        "corrected": row["corrected"],
        "saved_norm": child["result"]["arrays"]["norm"],
    }


@pytest.fixture(scope="module")
def recorded():
    return json.loads(gzip.decompress(FIXTURE.read_bytes()))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with TestClient(create_app(Settings(data_root=tmp_path_factory.mktemp("data")))) as client:
        yield client


@pytest.mark.parametrize("case", CASES, ids=case_key)
def test_fluo_correction_gives_the_numbers_of_larch_3461938ac(client, recorded, case):
    expected = recorded["cases"][case_key(case)]
    got = fluo_outputs(client, case)
    assert got["method"] == expected["method"] == "larch.fluo_corr"
    assert got["e0"] == expected["e0"]
    for key in ("energy", "measured", "corrected", "saved_norm"):
        np.testing.assert_array_equal(np.array(got[key]), np.array(expected[key]), err_msg=f"{case} {key}")
