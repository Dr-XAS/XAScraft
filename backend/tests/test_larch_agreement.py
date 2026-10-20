"""Agreement tests: the backend's copies of Larch logic against Larch itself.

The backend repeats a few of Larch's own computations, to check a request
before handing it to Larch or to split a result Larch only gives whole. Each
test here runs bundled data through the copy and through Larch, and fails if
they part. A copy that disagrees today is marked xfail(strict=True) with the
reason, so a change in either side is noticed.
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from larch import Group
from larch.xafs import pre_edge

from xraylarch_web.config import Settings
from xraylarch_web.main import create_app

RANGES = ("pre1", "pre2", "norm1", "norm2", "nnorm")


@pytest.fixture(scope="module")
def bundled_groups(tmp_path_factory):
    """The bundled copper series, processed by the API with every range left to the app."""
    with TestClient(create_app(Settings(data_root=tmp_path_factory.mktemp("agreement")))) as client:
        project = client.post("/api/athena/projects").json()
        response = client.post(f"/api/athena/projects/{project['id']}/command", json={
            "version": project["version"], "action": "example", "group_ids": [], "options": {}})
        assert response.status_code == 200, response.text
        groups = response.json()["groups"]
    assert groups and all(g["processing_error"] is None for g in groups)
    return groups


def test_pre_edge_default_ranges_are_larchs(bundled_groups):
    """Copy: backend/xraylarch_web/athena_science.py:233-264 (_normalization_ranges).

    Original: larch/xafs/pre_edge.py preedge(), the pre1/pre2/norm1/norm2/nnorm
    defaults. With every range left unset, the ranges the API reports must be
    the ones Larch's pre_edge chooses for the same spectrum and e0.
    """
    for group in bundled_groups:
        assert all(group["parameters"][key] is None for key in RANGES)
        effective = group["result"]["effective"]
        native = Group()
        pre_edge(np.asarray(group["energy"]), np.asarray(group["mu"]), group=native, e0=effective["e0"])
        larch_ranges = {key: getattr(native.pre_edge_details, key) for key in RANGES}
        assert {key: effective[key] for key in RANGES} == pytest.approx(larch_ranges), group["label"]
