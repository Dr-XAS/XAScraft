"""Agreement tests: the backend's copies of Larch logic against Larch itself.

The backend repeats a few of Larch's own computations, to check a request
before handing it to Larch or to split a result Larch only gives whole. Each
test here runs bundled data through the copy and through Larch, and fails if
they part. A copy that disagrees today is marked xfail(strict=True) with the
reason, so a change in either side is noticed.
"""
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient
from larch import Group
from larch.xafs import autobk, pre_edge

from xraylarch_web.config import Settings
from xraylarch_web.main import create_app

RANGES = ("pre1", "pre2", "norm1", "norm2", "nnorm")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with TestClient(create_app(Settings(data_root=tmp_path_factory.mktemp("agreement")))) as client:
        yield client


@pytest.fixture(scope="module")
def bundled_project(client):
    """The bundled copper series, processed by the API with every range left to the app."""
    project = client.post("/api/athena/projects").json()
    response = client.post(f"/api/athena/projects/{project['id']}/command", json={
        "version": project["version"], "action": "example", "group_ids": [], "options": {}})
    assert response.status_code == 200, response.text
    project = response.json()
    assert project["groups"] and all(g["processing_error"] is None for g in project["groups"])
    return project


@pytest.fixture(scope="module")
def bundled_groups(bundled_project):
    return bundled_project["groups"]


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


def _autobk_pre_checks(monkeypatch, group, parameters):
    """The spline size the app checked, and the one Larch then used.

    The app's copy is not reported anywhere: it only decides whether to refuse
    the request. It is read from process_spectrum's frame at the moment the app
    hands the spectrum to Larch's autobk; Larch's own count is read from the
    autobk_details it leaves on the group.
    """
    import sys

    from xraylarch_web import athena_science

    seen = []

    def spy(*args, **kwargs):
        app = sys._getframe(1).f_locals
        autobk(*args, **kwargs)
        details = kwargs["group"].autobk_details
        seen.append(dict(app=(app["nspl"], app["irbkg"]), larch=(details.nspl, details.irbkg)))

    monkeypatch.setattr(athena_science, "autobk", spy)
    athena_science.process_spectrum(group["energy"], group["mu"], parameters)
    assert seen, "process_spectrum did not reach Larch's autobk"
    return seen[0]


AUTOBK_CASES = [
    pytest.param({}, id="defaults"),
    pytest.param(dict(rbkg=1.4, bkg_kmin=0.5, bkg_kmax=12), id="rbkg-and-range"),
    pytest.param(dict(rbkg=0.01), id="rbkg-below-the-r-grid"),
    pytest.param(dict(nknots=12), id="nknots", marks=pytest.mark.xfail(strict=True, reason=(
        "athena_science.py:625 sizes the spline from rbkg alone; Larch's autobk.py:164 "
        "replaces it with nknots when nknots is given, so the residual check uses the wrong count."))),
]


@pytest.mark.parametrize("parameters", AUTOBK_CASES)
def test_autobk_spline_count_is_larchs(monkeypatch, bundled_groups, parameters):
    """Copy: backend/xraylarch_web/athena_science.py:620-630 (rbkg floor, nspl_raw, nspl, irbkg).

    Original: larch/xafs/autobk.py:141-166 (rgrid, rbkg floor, nspl, irbkg,
    nknots, the 5..128 clamp), reported as autobk_details.nspl/irbkg. The app
    refuses a request on its own count before Larch sees it, so the two counts
    must be the same.
    """
    for group in bundled_groups:
        counts = _autobk_pre_checks(monkeypatch, group, parameters)
        assert counts["app"] == counts["larch"], group["label"]


def _fit(client, project, transform, guesses):
    """Fit the bundled 10 K Cu foil with Larch's feffcu01 first-shell path.

    `guesses` names the path parameters left free; the others are Set at the
    example's starting value.
    """
    from xraylarch_web.artemis import copper_example

    example = copper_example()
    group = next(g for g in project["groups"] if g["label"] == "Cu foil · 10 K")
    parameters = [parameter | {"kind": "guess" if parameter["name"] in guesses else "set"}
                  for parameter in example["parameters"]]
    path = {key: value for key, value in example["path"].items() if key != "metadata"}
    return client.post(f"/api/artemis/projects/{project['id']}/groups/{group['id']}/fit?view=summary", json=dict(
        version=project["version"], parameters=parameters, transform=transform,
        paths=[path | {"id": "cu1", "label": "Cu first shell"}]))


# n_idp = 1 + 2 Δk ΔR / π falls between three and four free parameters for each.
FEFFIT_TRANSFORMS = [
    pytest.param(dict(kmin=3, kmax=8, rmin=1.4, rmax=2.2, kweight=[2]), id="r-space"),
    pytest.param(dict(kmin=3.5, kmax=9.5, rmin=1.5, rmax=2.1, kweight=[1, 2, 3], fitspace="k"), id="k-space"),
    pytest.param(dict(kmin=2.6, kmax=10.1, rmin=1.7, rmax=2.25, dk=1, kweight=[0, 3]), id="decimal-ranges"),
]


@pytest.mark.parametrize("transform", FEFFIT_TRANSFORMS)
def test_feffit_independent_points_are_larchs(client, bundled_project, transform):
    """Copy: backend/xraylarch_web/artemis.py:344-346 (n_independent, the too-many-guesses refusal).

    Original: larch/xafs/feffit.py:464 FeffitDataSet.prepare_fit n_idp, which a
    fit reports as statistics.n_independent. The app refuses a model with as
    many guesses as its own count before Larch runs; with one guess fewer the
    fit runs and reports Larch's. The two counts must agree.
    """
    refused = _fit(client, bundled_project, transform, {"amp", "del_e0", "del_r", "sig2"})
    assert refused.status_code == 400, refused.text
    match = re.search(r"only ([0-9.]+) independent points", refused.text)
    assert match, refused.text
    app_count = float(match.group(1))

    fitted = _fit(client, bundled_project, transform, {"amp", "del_e0", "del_r"})
    assert fitted.status_code == 200, fitted.text
    larch_count = fitted.json()["statistics"]["n_independent"]
    assert 3 < larch_count < 4
    assert app_count == pytest.approx(larch_count, abs=0.005)


XRF_MODELS = [
    pytest.param(dict(symbols=["Mn", "Fe", "Cr"], xray_energy_kev=7.2, energy_window=(3.8, 7.8), material="Ge",
                      split_kbeta=("Mn",)), id="mn-fe-cr-ge-split-kbeta"),
    pytest.param(dict(symbols=["Fe"], xray_energy_kev=8.0, energy_window=(1.0, 8.0), material="Si",
                      escape_amp=1.0), id="fe-si-escape"),
    pytest.param(dict(symbols=["Zn", "Ba"], xray_energy_kev=12.0, energy_window=(0.9, 12.0), material="Si",
                      escape_amp=0.5, peak_gamma=0.03), id="zn-ba-k-and-l-lines"),
]


def _xrf_model(symbols, xray_energy_kev, energy_window, material, escape_amp=0.0, peak_gamma=0.0, split_kbeta=()):
    from xraylarch_web import athena_xrf_xas as engine

    model = engine.build_model(symbols, xray_energy_kev, energy_window, material=material, thickness=1.0,
                               det_noise=0.065, peak_step=1.5e-3, peak_tail=0.06, escape_amp=escape_amp,
                               peak_gamma=peak_gamma)
    energy = np.linspace(*energy_window, 801)
    return model, energy


@pytest.mark.parametrize("case", XRF_MODELS)
def test_xrf_line_columns_sum_to_larchs_element_components(case):
    """Copy: backend/xraylarch_web/athena_xrf_xas.py:874-915 (element_columns) and :849-861 (detected).

    Original: larch/xrf/xrf_model.py XRF_Model.calc_spectrum, the per-element
    loop that fills model.comps. The app splits each element's lines by
    initial level (and a target's K-beta); the columns of one element at unit
    amplitude must add up to Larch's component for that element.
    """
    from xraylarch_web import athena_xrf_xas as engine

    split_kbeta = case.get("split_kbeta", ())
    model, energy = _xrf_model(**case)
    columns = engine.element_columns(model, energy, split_kbeta=split_kbeta)

    for symbol in case["symbols"]:
        model.params[f"amp_{symbol.lower()}"].value = 1.0
    model.calc_spectrum(energy)
    for symbol in case["symbols"]:
        parts = [key for key in columns if key[0] == symbol]
        assert parts, symbol
        summed = np.sum([columns[key] for key in parts], axis=0)
        native = model.comps[symbol]
        assert native.max() > 0
        np.testing.assert_allclose(summed, native, rtol=1e-10, atol=1e-12 * native.max(), err_msg=symbol)
    if case["symbols"] == ["Zn", "Ba"]:
        # The point of the split: one element, two excitation levels.
        assert {key[1] for key in columns if key[0] == "Zn"} >= {"K", "L3"}
    for symbol in split_kbeta:
        assert (symbol, "Kbeta") in columns


@pytest.mark.parametrize("case", XRF_MODELS)
def test_xrf_scatter_column_is_larchs_scatter_component(case):
    """Copy: backend/xraylarch_web/athena_xrf_xas.py:926-934 (scatter_column).

    Original: larch/xrf/xrf_model.py XRF_Model.calc_spectrum, the Rayleigh and
    Compton loop. A unit-amplitude scatter column must be Larch's own scatter
    component for the same centre and shape.
    """
    from xraylarch_web import athena_xrf_xas as engine

    model, energy = _xrf_model(**case)
    shapes = dict(elastic=dict(center=case["xray_energy_kev"] - 0.05, step=0.006, tail=0.35, sigmax=1.1, beta=0.5),
                  compton=dict(center=case["xray_energy_kev"] - 0.4, step=0.006, tail=1.2, sigmax=2.8, beta=0.5))
    for name, shape in shapes.items():
        model.add_scatter_peak(name=name, amplitude=1.0, **shape)
    model.calc_spectrum(energy)
    det_noise = model.params["det_noise"].value
    for name, shape in shapes.items():
        column = engine.scatter_column(model, energy, shape["center"], sigmax=shape["sigmax"], step=shape["step"],
                                       tail=shape["tail"], beta=shape["beta"], det_noise=det_noise)
        native = model.comps[name]
        assert native.max() > 0
        np.testing.assert_allclose(column, native, rtol=1e-10, atol=1e-12 * native.max(), err_msg=name)
