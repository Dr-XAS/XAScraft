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


def _example_project(client):
    """A new project holding the bundled copper series, for a test that changes it."""
    project = client.post("/api/athena/projects").json()
    response = client.post(f"/api/athena/projects/{project['id']}/command", json={
        "version": project["version"], "action": "example", "group_ids": [], "options": {}})
    assert response.status_code == 200, response.text
    return response.json()


def test_pre_edge_default_ranges_are_larchs(bundled_groups):
    """Copy: backend/xraylarch_web/athena_science.py, _normalization_ranges.

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


TOO_FEW_RESIDUALS = "AUTOBK has too few residuals for its spline"


def _larch_spline(group, settings):
    """The spline size Larch's autobk uses for this spectrum and these settings: its own
    autobk_details.nspl and irbkg. nclamp adds residuals, not knots, so a large one lets
    every case fit without changing the count."""
    effective = group["result"]["effective"]
    native = Group()
    kmax = settings["bkg_kmax"] if settings["bkg_kmax"] is not None else effective["available_kmax"]
    autobk(np.asarray(group["energy"]), np.asarray(group["mu"]), group=native, ek0=effective["e0"],
           edge_step=effective["edge_step"], rbkg=settings["rbkg"], nknots=settings["nknots"] or None,
           kmin=settings["bkg_kmin"], kmax=kmax, kstep=settings["kstep"], nfft=settings["nfft"],
           nclamp=64, calc_uncertainties=False)
    return native.autobk_details.nspl, native.autobk_details.irbkg


def _autobk_outcome(client, project, group_id, options):
    """("refused" | "processed", project) for a parameter change through the API, or the
    reply itself when it is neither (e.g. Larch's own failure, reported as a 400 too)."""
    response = client.post(f"/api/athena/projects/{project['id']}/command", json={
        "version": project["version"], "action": "parameters", "group_ids": [group_id],
        "options": options})
    if response.status_code == 400 and TOO_FEW_RESIDUALS in response.text:
        return "refused", project
    if response.status_code == 200:
        project = response.json()
        [group] = [g for g in project["groups"] if g["id"] == group_id]
        if group["processing_error"] is None:
            return "processed", project
    return f"HTTP {response.status_code}: {response.text[:300]}", project


AUTOBK_CASES = [
    pytest.param({}, id="defaults"),
    pytest.param(dict(rbkg=1.4, bkg_kmin=0.5, bkg_kmax=12), id="rbkg-and-range"),
    pytest.param(dict(rbkg=0.01), id="rbkg-below-the-r-grid"),
    pytest.param(dict(rbkg=0.01, nknots=12), id="nknots", marks=pytest.mark.xfail(strict=True, reason=(
        "process_spectrum (athena_science.py) sizes the spline from rbkg alone; Larch's autobk() "
        "uses nknots when it is given, so the residual check counts too few knots and hands Larch "
        "a spline it has too few residuals for."))),
]


@pytest.mark.parametrize("parameters", AUTOBK_CASES)
def test_autobk_spline_count_is_larchs(client, parameters):
    """Copy: backend/xraylarch_web/athena_science.py, process_spectrum's AUTOBK checks
    (the rbkg floor, nspl_raw, nspl, irbkg: "too few residuals for its spline").

    Original: larch/xafs/autobk.py autobk() (rgrid, the rbkg floor, nspl, irbkg, nknots,
    the 5..128 clamp), reported as autobk_details.nspl/irbkg. The app refuses a request on
    its own count before Larch sees it, when 2·irbkg + 2·nclamp ≤ nspl.

    The app's count shows in the API only as that refusal, so the test asks the API, at
    the nclamp values where Larch's own count changes the answer (0, the largest nclamp it
    leaves too few residuals for, and one more), and compares the API's answer with the one
    Larch's count gives. Where Larch's count leaves enough residuals even at nclamp 0 (the
    first two cases: irbkg is several times nspl), the API can only show that the app does
    not refuse.
    """
    project = _example_project(client)
    for group in list(project["groups"]):
        settings = {**group["parameters"], **parameters}
        nspl, irbkg = _larch_spline(group, settings)
        boundary = (nspl - 2 * irbkg) // 2  # the largest nclamp Larch's count refuses
        for nclamp in sorted({0, boundary, boundary + 1} & set(range(101))):
            expected = "refused" if 2 * irbkg + 2 * nclamp <= nspl else "processed"
            outcome, project = _autobk_outcome(client, project, group["id"],
                                               {**parameters, "nclamp": nclamp})
            assert outcome == expected, (group["label"], nclamp, (nspl, irbkg))


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
    """Copy: backend/xraylarch_web/artemis.py, _parameters (n_independent, the too-many-guesses refusal).

    Original: larch/xafs/feffit.py FeffitDataSet.prepare_fit n_idp, which a
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
    """Copy: backend/xraylarch_web/athena_xrf_xas.py, element_columns and detected.

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
    """Copy: backend/xraylarch_web/athena_xrf_xas.py, scatter_column.

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


# ----------------------------------------------------------------------------
# Private or undocumented Larch API the backend relies on. Each test names the
# site and checks that the symbol is there and answers the call the backend
# makes, so a Larch upgrade that moves or reshapes it fails here, by name.


@pytest.fixture(scope="module")
def copper_path():
    from larch.xafs import feffpath

    from xraylarch_web import artemis

    return feffpath(str(artemis._EXAMPLE), s02=0.9, e0=3, deltar=0.01, sigma2=0.008)


@pytest.fixture
def copper_dataset(copper_path):
    """A one-path Larch feffit dataset on synthetic Cu chi(k), kweight as the backend passes it."""
    from larch.fitting import param, param_group
    from larch.xafs import feffit_dataset, feffit_transform, feffpath, ff2chi

    from xraylarch_web import artemis

    data = Group()
    ff2chi([copper_path], group=data, k=np.arange(301) * 0.05)
    data.chi = data.chi + np.random.default_rng(7).normal(0, 5e-5, data.k.size)
    params = param_group(amp=param(0.9, vary=True), de0=param(3.0, vary=True))
    path = feffpath(str(artemis._EXAMPLE), s02="amp", e0="de0", deltar=0.01, sigma2=0.008)
    transform = feffit_transform(kmin=3, kmax=12, kweight=2, dk=1, rmin=1.4, rmax=3, fitspace="r",
                                 kstep=0.05, nfft=2048, rwindow="hanning")
    return feffit_dataset(data=data, paths=[path], transform=transform), params


def test_private_finde0_takes_an_explicit_step(bundled_groups):
    """Site 1: backend/xraylarch_web/athena_science.py imports larch.xafs.pre_edge._finde0;
    _edge calls it as _finde0(x, y, estep=..., use_smooth=...)[0] for 50-99 point scans."""
    import inspect

    from larch.xafs.pre_edge import _finde0

    assert {"estep", "use_smooth"} <= set(inspect.signature(_finde0).parameters)
    group = next(g for g in bundled_groups if g["label"] == "Cu foil · 10 K")
    energy, mu = np.asarray(group["energy"]), np.asarray(group["mu"])
    e0 = float(_finde0(energy, mu, estep=0.5, use_smooth=True)[0])
    assert e0 == pytest.approx(group["result"]["effective"]["e0"], abs=5)


def test_private_feffdat_carries_the_arrays_and_geometry_read_from_it(copper_path):
    """Sites 2, 5, 6, 7: path._feffdat read in backend/xraylarch_web/artemis.py _read_path,
    artemis_disorder.py evaluate_disorder (geom, rnorman) and artemis_fast.py _path_arrays;
    artemis_export.py export_larix sets its filename."""
    native = copper_path._feffdat
    arrays = [native.k, native.real_phc, native.mag_feff, native.pha_feff, native.red_fact, native.lam, native.rep]
    assert len({np.asarray(a).size for a in arrays}) == 1 and np.asarray(native.k).size >= 8
    assert native.reff == pytest.approx(2.5478, abs=1e-3)
    assert native.degen == 12 and native.nleg == 2 and len(native.geom) == native.nleg
    assert all(len(atom) >= 4 for atom in native.geom)
    assert float(native.rnorman) > 0
    native.filename = "artemis/feff0000.dat"
    assert native.filename == "artemis/feff0000.dat"


def test_private_calc_chi_takes_resolved_path_values(copper_path):
    """Site 3: backend/xraylarch_web/artemis.py preview_paths sets s02, e0, deltar, sigma2 on
    the path, calls path.create_path_params(params=Parameters()) and path._calc_chi(k=k).
    Upstream drops keyword values to _calc_chi since c18a4ed63 ('expected 7, got 3'), and
    XAScraft's build restores them with temporary patch 0010; this call passes none, so it
    works on both."""
    from xraylarch_web.artemis import _path_chi

    k = np.arange(241) * 0.05
    _path_chi(copper_path, k, dict(s02=0.9, e0=3.0, deltar=0.01, sigma2=0.008))
    assert np.asarray(copper_path.chi).shape == k.shape
    assert np.isfinite(copper_path.chi).all() and np.ptp(copper_path.chi) > 0


def _path_params_before_c18a4ed63(self, **kws):
    """FeffPathGroup.__path_params as upstream 8d6cd41c2 has it (and XAScraft's build, with
    temporary patch 0010): a keyword value given to _calc_chi overrides the path parameter,
    which is read only when none is given."""
    from larch.xafs.feffdat import PATH_PARS

    self.store_feffdat()
    if self.params is None:
        self.create_path_params()
    out = []
    for pname in PATH_PARS:
        val = kws.get(pname, None)
        if val is None:
            val = self.params[self.pathpar_name(pname)]._getval()
        out.append(val)
    return out


def _path_params_since_c18a4ed63(self, **kws):
    """FeffPathGroup.__path_params as upstream c18a4ed63 has it (and upstream's main since): a
    value goes in only when no keyword gives it and the path parameter is in the path's lmfit
    Parameters, so a keyword value is dropped."""
    from larch.xafs.feffdat import PATH_PARS

    self.store_feffdat()
    if self.params is None:
        self.create_path_params()
    out = []
    for pname in PATH_PARS:
        val = kws.get(pname, None)
        if val is None:
            parname = self.pathpar_name(pname)
            if parname in self.params:
                val = self.params[parname]._getval()
                out.append(val)
    return out


def test_path_chi_gives_the_keyword_calls_chi_with_path_params_before_and_after_c18a4ed63(
        monkeypatch):
    """artemis._path_chi replaced the backend's call path._calc_chi(k=k, **values), whose
    keyword values upstream c18a4ed63 drops (XAScraft's build restores them with temporary
    patch 0010). With stand-ins of FeffPathGroup.__path_params as before and after c18a4ed63,
    whatever Larch is installed, and on the installed Larch: _path_chi gives, bit for bit, the
    chi the keyword call gives before c18a4ed63. After it, the keyword call fails."""
    from larch.xafs import feffpath
    from larch.xafs.feffdat import FeffPathGroup

    from xraylarch_web import artemis

    k = np.arange(241) * 0.05
    values = dict(s02=0.9, e0=3.0, deltar=0.01, sigma2=0.008)

    def chi(compute):
        path = feffpath(str(artemis._EXAMPLE), s02=0.7, e0=-1.0, deltar=-0.02, sigma2=0.003)
        compute(path)
        return np.array(path.chi, dtype=float)

    def adapter(path):
        artemis._path_chi(path, k, values)

    def keyword_call(path):
        path._calc_chi(k=k, **values)

    installed = chi(adapter)
    with monkeypatch.context() as patch:
        patch.setattr(FeffPathGroup, "_FeffPathGroup__path_params", _path_params_before_c18a4ed63)
        earlier_call = chi(keyword_call)
        earlier_adapter = chi(adapter)
        own_values = chi(lambda path: path._calc_chi(k=k))
        patch.setattr(FeffPathGroup, "_FeffPathGroup__path_params", _path_params_since_c18a4ed63)
        later_adapter = chi(adapter)
        with pytest.raises(ValueError, match=r"expected 7, got 3"):
            chi(keyword_call)

    assert not np.array_equal(earlier_call, own_values)  # the values given do count
    np.testing.assert_array_equal(earlier_adapter, earlier_call)
    np.testing.assert_array_equal(later_adapter, earlier_call)
    np.testing.assert_array_equal(installed, earlier_call)


def test_private_xafsft_fills_a_group_with_chi_r(copper_path):
    """Site 4: backend/xraylarch_web/artemis.py preview_paths calls
    transform._xafsft(chi, group=, rmax_out=10), per path and for the sum."""
    from larch.xafs import feffit_transform

    from xraylarch_web.artemis import _path_chi

    k = np.arange(241) * 0.05
    _path_chi(copper_path, k, dict(s02=0.9, e0=3.0, deltar=0.01, sigma2=0.008))
    transform = feffit_transform(kmin=3, kmax=12, kweight=2, dk=1, rmin=1.4, rmax=3,
                                 kstep=0.05, nfft=2048, rwindow="hanning")
    out = Group()
    transform._xafsft(np.asarray(copper_path.chi, dtype=float), group=out, rmax_out=10)
    assert out.r[-1] == pytest.approx(10, abs=0.05)
    assert np.asarray(out.chir).shape == np.asarray(out.r).shape == np.asarray(out.chir_mag).shape
    # The first shell, 2.55 Å less the phase shift, is where |chi(R)| peaks.
    assert 1.8 < out.r[np.argmax(out.chir_mag)] < 2.6


def test_internal_sigma2_models_used_for_disorder(copper_path):
    """Site 5: backend/xraylarch_web/artemis_disorder.py imports EINS_FACTOR and
    sigma2_correldebye_py from larch.xafs.sigma2_models; its _einstein copies Larch's Einstein formula."""
    import inspect

    from larch.xafs.sigma2_models import EINS_FACTOR, sigma2_correldebye_py, sigma2_eins

    from xraylarch_web.artemis_disorder import evaluate_disorder

    assert isinstance(EINS_FACTOR, float) and EINS_FACTOR > 0
    assert list(inspect.signature(sigma2_correldebye_py).parameters) == [
        "natoms", "tk", "theta", "rnorm", "x", "y", "z", "atwt"]
    assert 0.002 < evaluate_disorder("debye", 300.0, 315.0, copper_path) < 0.02
    # The copied Einstein formula is Larch's sigma2_eins.
    assert evaluate_disorder("eins", 300.0, 230.0, copper_path) == pytest.approx(
        sigma2_eins(300.0, 230.0, copper_path), rel=1e-12)


def test_private_session_symbols_survive_save_session(tmp_path, copper_path):
    """Site 6: backend/xraylarch_web/artemis_export.py export_larix calls save_session(fname,
    symbols=[..., '_feffcache', '_feffpaths'], histbuff=[], _larch=<object with .symtable>),
    storing paths through the app's FeffPathGroup adapter."""
    from types import SimpleNamespace

    from larch.io import read_session, save_session

    from xraylarch_web.artemis_export import FeffPathGroup

    stored = {"cu1": FeffPathGroup(copper_path)}
    data = Group(groupname="g1", filename="cu.dat", k=np.arange(5) * 0.5)
    symbols = Group(_sys=Group(core_groups=["_sys"], config=Group()), _xasgroups={"cu.dat": "g1"},
                    _feffcache={"paths": stored, "runs": {}}, _feffpaths=stored, g1=data)
    output = tmp_path / "model.larix"
    save_session(str(output), symbols=["g1", "_feffcache", "_feffpaths"], histbuff=[],
                 _larch=SimpleNamespace(symtable=symbols))
    restored = read_session(str(output)).symbols
    assert {"g1", "_feffcache", "_feffpaths"} <= set(restored)
    assert set(restored["_feffpaths"]) == {"cu1"}
    # The app's adapter picks Larch's stateful path decoder: FEFF arrays come back without disk access.
    assert restored["_feffpaths"]["cu1"]._feffdat.reff == pytest.approx(copper_path._feffdat.reff)


def test_private_dataset_chi_and_residual(copper_dataset):
    """Sites 7, 8: backend/xraylarch_web/artemis_fast.py build_residual_spec reads dataset._chi,
    and fast_fit_group calls dataset._residual(params) for the engine parity check."""
    dataset, params = copper_dataset
    dataset.prepare_fit(params)
    assert np.asarray(dataset._chi).shape == np.asarray(dataset.model.k).shape
    residual = dataset._residual(params)
    assert residual.ndim == 1 and residual.size > 0 and np.isfinite(residual).all()


def test_one_element_kweight_list_collapses_the_noise_estimate(copper_dataset):
    """Site 11: backend/xraylarch_web/artemis.py fit_inputs (also artemis_export.py export_larix)
    passes a scalar kweight because this Larch collapses a one-element list's noise estimate
    to a scalar, which its residual then indexes per weight. If Larch stops doing
    so, the workaround can go."""
    dataset, _ = copper_dataset
    dataset.transform.kweight = [2]
    dataset.estimate_noise()
    assert np.ndim(dataset.epsilon_k) == 0
    dataset.transform.kweight = [1, 2]
    dataset.estimate_noise()
    assert np.ndim(dataset.epsilon_k) == 1 and len(dataset.epsilon_k) == 2


def test_xrf_model_internals_read_and_written():
    """Site 9: backend/xraylarch_web/athena_xrf_xas.py (Fitter._build, build_model, detected,
    element_columns, scatter_column) reads and writes XRF_Model internals (efano, use_escape,
    detector.material, escape_energy, escape_scale, atten, count_time, det_sigma, params) and
    calls calc_spectrum with a valuesdict-only params object (_Values)."""
    import inspect

    from larch.xrf.xrf_model import XRF_Model

    from xraylarch_web import athena_xrf_xas as engine

    model = engine.build_model(["Fe"], 8.0, (1.0, 8.0), material="Si", thickness=0.5, det_noise=0.06,
                               peak_step=1e-3, peak_tail=0.05, escape_amp=1.0, det_variance_slope=4e-4)
    assert isinstance(model, XRF_Model)
    assert model.efano == 4e-4 and model.use_escape is True and model.detector.material == "Si"
    assert list(inspect.signature(model.det_sigma).parameters) == ["energy", "noise"]
    assert {"det_noise", "peak_step", "peak_tail", "peak_gamma", "peak_beta", "escape_amp", "amp_fe"} <= set(model.params)
    energy = np.linspace(1.0, 8.0, 201)
    pars = {name: value for name, value in model.params.valuesdict().items() if not name.startswith("amp_")}
    model.calc_spectrum(energy, params=engine._Values(pars))
    assert model.comps == {}  # no element amplitude given: no element drawn
    assert np.asarray(model.atten).shape == energy.shape and model.count_time > 0
    assert model.escape_energy == pytest.approx(1.74, abs=0.05)
    assert np.asarray(model.escape_scale).shape == energy.shape
    model.detector.calc_mu(energy)
    assert np.asarray(model.detector.mu_total).shape == energy.shape


def test_autobk_resid_subtracts_the_standard_before_dividing_by_edge_step():
    """Site 10: backend/xraylarch_web/athena_science.py _standard_arguments scales
    chi_std by edge_step because larch.xafs.autobk._resid subtracts chi_std before
    dividing by edge_step."""
    import importlib
    import inspect

    from scipy.interpolate import splrep

    autobk_module = importlib.import_module("larch.xafs.autobk")
    resid = autobk_module._resid
    assert list(inspect.signature(resid).parameters) == [
        "vcoefs", "ncoef", "kraw", "mu", "chi_std", "knots", "order", "kout",
        "ftwin", "nfft", "irbkg", "nclamp", "clamp_lo", "clamp_hi", "edge_step"]

    kraw = np.linspace(0, 12, 400)
    kout = np.arange(241) * 0.05
    mu = 1 + 0.2 * np.sin(2 * kraw) + 0.01 * kraw
    knots, coefs, order = splrep(np.linspace(0, 12, 9), np.ones(9))
    unscaled_chi = autobk_module.spline_eval(kraw, mu, knots, coefs, order, kout)[1]
    common = dict(ncoef=len(coefs), kraw=kraw, mu=mu, knots=knots, order=order, kout=kout,
                  ftwin=np.ones_like(kout), nfft=2048, irbkg=10, nclamp=0, clamp_lo=0, clamp_hi=0)
    # A standard equal to mu - bkg, in mu's own units, cancels whatever edge_step is;
    # one already divided by edge_step does not.
    assert np.allclose(resid(coefs, chi_std=unscaled_chi, edge_step=2.0, **common), 0, atol=1e-12)
    assert not np.allclose(resid(coefs, chi_std=unscaled_chi / 2.0, edge_step=2.0, **common), 0, atol=1e-6)
