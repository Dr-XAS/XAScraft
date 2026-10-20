"""Larch's own fitting examples, run as plain Larch and through the app's HTTP API.

Each example runs twice on the same Larch build: once as the example script
does it (the reference run, written out below with plain Larch calls), and once
through the routes the UI uses. The reference is the rerun, never the numbers
printed in Larch's documentation, which are static text.

The two runs share their data. The reference script reduces the measured
spectrum with plain Larch; the app is then handed that result as a file, the
way a user would import it, so what is compared is the fit, not two background
removals. The scripts' transforms use the app's fixed settings (kstep 0.05,
nfft 2048, Hanning R window), which the app does not let a user change.
"""
from copy import copy
from pathlib import Path
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient
from larch import Group
from larch.fitting import guess, minimize, param, param_group
from larch.io import read_ascii
from larch.math import index_of, interp
from larch.xafs import autobk, feffit, feffit_dataset, feffit_transform, feffpath, pre_edge
from lmfit.models import GaussianModel, LinearModel, StepModel, VoigtModel

from xraylarch_web.config import Settings
from xraylarch_web.main import create_app

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
FEFFIT = EXAMPLES / "feffit"
XAFSDATA = EXAMPLES / "xafsdata"

# xafs_feffit examples: the app and plain Larch run the same feffit on the same
# numbers, so anything beyond rounding is a difference in how the app reads the
# model it was sent.
FEFFIT_RTOL = 1e-9
APP_TRANSFORM = dict(kstep=0.05, nfft=2048, rwindow="hanning")
STATISTICS = ("n_independent", "chi_square", "reduced_chi_square", "r_factor", "aic", "bic", "epsilon_k")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_root=tmp_path))) as client:
        yield client


def import_columns(client, name, x, y, data_type, project=None):
    """Upload two columns as a file and import them as one group, as the UI does.

    The group goes into `project`, or into a new project when none is given.
    """
    if project is None:
        project = client.post("/api/athena/projects")
        assert project.status_code == 200, project.text
        project = project.json()
    content = "# x y\n" + "".join(f"{float(a)!r} {float(b)!r}\n" for a, b in zip(x, y))
    inspected = client.post(f"/api/athena/projects/{project['id']}/inspect",
                            files={"file": (name, content.encode())})
    assert inspected.status_code == 200, inspected.text
    inspected = inspected.json()
    columns = [column["column_id"] for column in inspected["columns"]]
    imported = client.post(f"/api/athena/projects/{project['id']}/import", json={
        "version": project["version"], "upload_id": inspected["upload_id"],
        "energy_column": columns[0], "numerator": [columns[1]], "data_type": data_type})
    assert imported.status_code == 200, imported.text
    project = imported.json()
    return project, project["groups"][-1]


def feff_text(filename, degen=None):
    """A FEFF path file's text, optionally with its degeneracy edited in the header.

    The app has no per-path degeneracy field; a user who wants Larch's
    feffpath(degen=N) edits the `nleg, deg, reff` header line instead.
    """
    text = (FEFFIT / filename).read_text()
    if degen is None:
        return text
    edited, count = re.subn(r"^(\s*\d+\s+)\S+(\s+\S+.*nleg, deg, reff.*)$",
                            lambda match: f"{match[1]}{degen:.3f}{match[2]}", text, flags=re.MULTILINE)
    assert count == 1, filename
    return edited


def app_feffit(client, project, group, parameters, paths, transform):
    """POST the fit the Artemis page sends, with each FEFF file's text."""
    body = dict(version=project["version"], parameters=parameters, transform=transform,
                paths=[dict(path, content=path.get("content") or feff_text(path["filename"]))
                       for path in paths])
    reply = client.post(f"/api/artemis/projects/{project['id']}/groups/{group['id']}/fit", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def chi_data(group):
    """The chi(k) a script's autobk made, alone: the data the app is given."""
    return Group(k=group.k, chi=group.chi)


def assert_same_feffit(app, reference, dataset, names):
    """Parameters, uncertainties, correlations and statistics agree to FEFFIT_RTOL."""
    assert app["success"] is True
    rows = {row["name"]: row for row in app["parameters"]}
    assert set(rows) == set(names)
    for name in names:
        expected = reference.params[name]
        np.testing.assert_allclose(rows[name]["value"], expected.value, rtol=FEFFIT_RTOL, atol=0,
                                   err_msg=f"{name} value")
        if expected.stderr is None:
            assert rows[name]["stderr"] is None, name
        else:
            np.testing.assert_allclose(rows[name]["stderr"], expected.stderr, rtol=FEFFIT_RTOL, atol=0,
                                       err_msg=f"{name} stderr")
    correlations = {(row["left"], row["right"]): row["value"] for row in app["correlations"]}
    expected_correlations = {tuple(sorted((name, other))): value
                             for name in names for other, value in (reference.params[name].correl or {}).items()
                             if other in names}
    assert set(correlations) == set(expected_correlations)
    for pair, value in expected_correlations.items():
        np.testing.assert_allclose(correlations[pair], value, rtol=FEFFIT_RTOL, atol=0, err_msg=f"correlation {pair}")
    statistics = app["statistics"]
    assert statistics["n_varys"] == reference.nvarys
    assert statistics["n_data"] == reference.ndata
    assert statistics["errorbars"] == reference.errorbars
    epsilon_k = dataset.epsilon_k
    expected_statistics = dict(n_independent=reference.n_independent, chi_square=reference.chi_square,
                               reduced_chi_square=reference.chi2_reduced, r_factor=reference.rfactor,
                               aic=reference.aic, bic=reference.bic,
                               epsilon_k=np.mean(epsilon_k[0] if isinstance(epsilon_k, (list, tuple)) else epsilon_k))
    for key in STATISTICS:
        np.testing.assert_allclose(statistics[key], expected_statistics[key], rtol=FEFFIT_RTOL, atol=0, err_msg=key)




def guesses(**values):
    """Larch param(value, vary=True) / guess(value), as the app's Guess rows."""
    return [dict(name=name, kind="guess", value=value) for name, value in values.items()]


# --- feffit Ex1: Cu first shell (examples/feffit/doc_feffit1.py) -------------------------

def cu_metal_chi(rbkg):
    data = read_ascii(str(XAFSDATA / "cu_metal_rt.xdi"))
    autobk(data.energy, data.mutrans, group=data, rbkg=rbkg, kw=2)
    return data


def run_ex1(client, reference_data):
    """doc_feffit1.py on `reference_data`, then the same fit through the app."""
    cu_data = cu_metal_chi(rbkg=1.0)
    pars = param_group(amp=param(1.0, vary=True), del_e0=param(0.0, vary=True),
                       sig2=param(0.0, vary=True), del_r=guess(0.0, vary=True))
    path1 = feffpath(str(FEFFIT / "feffcu01.dat"), s02="amp", e0="del_e0", sigma2="sig2", deltar="del_r")
    trans = feffit_transform(kmin=3, kmax=17, kw=2, dk=4, window="kaiser", rmin=1.4, rmax=3.0, **APP_TRANSFORM)
    dset = feffit_dataset(data=reference_data(cu_data), pathlist=[path1], transform=trans)
    reference = feffit(pars, dset)

    project, group = import_columns(client, "cu_metal_rt.chi", cu_data.k, cu_data.chi, "chi")
    app = app_feffit(client, project, group, parameters=guesses(amp=1.0, del_e0=0.0, sig2=0.0, del_r=0.0),
                     paths=[dict(id="path1", filename="feffcu01.dat", s02="amp", e0="del_e0",
                                 sigma2="sig2", deltar="del_r")],
                     transform=dict(fitspace="r", kmin=3, kmax=17, kweight=[2], dk=4, window="kaiser",
                                    rmin=1.4, rmax=3.0))
    return app, reference, dset


def test_feffit_ex1_cu_first_shell_matches_plain_larch(client):
    app, reference, dset = run_ex1(client, chi_data)
    assert_same_feffit(app, reference, dset, ["amp", "del_e0", "sig2", "del_r"])


@pytest.mark.xfail(strict=True, reason=(
    "Genuine difference, kept visible: the script passes autobk's whole group to feffit_dataset, and "
    "feffit adds autobk's chi(k) uncertainty (delta_chi, from autobk_details.covar) to its high-R noise "
    "estimate. The app fits chi(k) alone, so its noise is the high-R estimate only. Measured on Ex1: "
    "epsilon_k 1.5953e-4 (app) vs 3.1429e-4 mean (script); chi-square 848.50 vs 437.22; reduced "
    "chi-square 75.353 vs 38.829; AIC 69.319 vs 59.201; BIC 72.220 vs 62.102. R-factor agrees to 3e-16. "
    "Values agree to 5.0e-10 and uncertainties to 1.13e-9 relative (del_r), just outside 1e-9."))
def test_feffit_ex1_literal_script_adds_autobk_uncertainty_the_app_does_not(client):
    app, reference, dset = run_ex1(client, lambda autobk_group: autobk_group)
    assert_same_feffit(app, reference, dset, ["amp", "del_e0", "sig2", "del_r"])


# --- feffit Ex2: Cu, three paths (examples/feffit/doc_feffit2.py) ------------------------
# The app has no third-cumulant field, so both sides drop path1's third='c3_1' and
# the c3_1 parameter with it.

def test_feffit_ex2_cu_three_paths_without_third_cumulant_matches_plain_larch(client):
    cu_data = read_ascii(str(XAFSDATA / "cu_metal_rt.xdi"))
    cu_data.mu = cu_data.mutrans
    autobk(cu_data, rbkg=1.1, kw=2)
    pars = param_group(amp=param(1, vary=True), del_e0=param(3, vary=True),
                       sig2_1=param(.002, vary=True), sig2_2=param(.002, vary=True),
                       sig2_3=param(.002, vary=True), alpha=param(0, vary=True))
    paths = [feffpath(str(FEFFIT / f"feff000{index}.dat"), s02="amp", e0="del_e0",
                      sigma2=f"sig2_{index}", deltar="alpha*reff") for index in (1, 2, 3)]
    trans = feffit_transform(kmin=3, kmax=17, kw=2, dk=4, window="kaiser", rmin=1.4, rmax=3.5, **APP_TRANSFORM)
    dset = feffit_dataset(data=chi_data(cu_data), pathlist=paths, transform=trans)
    reference = feffit(pars, dset)

    project, group = import_columns(client, "cu_metal_rt.chi", cu_data.k, cu_data.chi, "chi")
    app = app_feffit(client, project, group,
                     parameters=guesses(amp=1, del_e0=3, sig2_1=.002, sig2_2=.002, sig2_3=.002, alpha=0),
                     paths=[dict(id=f"path{index}", filename=f"feff000{index}.dat", s02="amp", e0="del_e0",
                                 sigma2=f"sig2_{index}", deltar="alpha*reff") for index in (1, 2, 3)],
                     transform=dict(fitspace="r", kmin=3, kmax=17, kweight=[2], dk=4, window="kaiser",
                                    rmin=1.4, rmax=3.5))

    assert_same_feffit(app, reference, dset, ["amp", "del_e0", "sig2_1", "sig2_2", "sig2_3", "alpha"])


# --- feffit Ex4: FeO coordination numbers (examples/feffit/doc_feffit4.py) ---------------
# The script sets degen=1 on each path and fits N through s02='s02*n1'. The app has no
# per-path degeneracy field, so its FEFF files carry degeneracy 1 in their headers.
# (The other workaround, s02='s02*n1/degen' on the file's degeneracy, is the same model
# but rounds differently: it moved the de0-n1 correlation by 6.0e-9 relative.)

FEO_NAMES = ["n1", "n2", "s02", "de0", "sig2_1", "delr_1", "sig2_2", "delr_2"]
FEO_PATHS = [dict(id="feo", filename="feff_feo01.dat", content=feff_text("feff_feo01.dat", degen=1),
                  s02="s02*n1", e0="de0", sigma2="sig2_1", deltar="delr_1"),
             dict(id="fefe", filename="feff_feo02.dat", content=feff_text("feff_feo02.dat", degen=1),
                  s02="s02*n2", e0="de0", sigma2="sig2_2", deltar="delr_2")]


def feo_ex4_reference():
    """doc_feffit4.py up to its fit, on the chi(k) its autobk made."""
    feo_dat = read_ascii(str(XAFSDATA / "feo_xafs.dat"), labels="energy mu")
    autobk(feo_dat, kweight=2, rbkg=1.05, clamp_hi=300)
    pars = Group(n1=param(6, vary=True), n2=param(12, vary=True), s02=param(0.700, vary=False),
                 de0=guess(0.1), sig2_1=param(0.002, vary=True), delr_1=guess(0.),
                 sig2_2=param(0.002, vary=True), delr_2=guess(0.))
    path_feo = feffpath(str(FEFFIT / "feff_feo01.dat"), degen=1, s02="s02*n1", e0="de0",
                        sigma2="sig2_1", deltar="delr_1")
    path_fefe = feffpath(str(FEFFIT / "feff_feo02.dat"), degen=1, s02="s02*n2", e0="de0",
                         sigma2="sig2_2", deltar="delr_2")
    trans = feffit_transform(kmin=2.0, kmax=13.5, kweight=3, dk=3, window="kaiser",
                             rmin=1.0, rmax=3.2, fitspace="r", **APP_TRANSFORM)
    dset = feffit_dataset(data=chi_data(feo_dat), pathlist=[path_feo, path_fefe], transform=trans)
    out = feffit(pars, dset)
    return feo_dat, pars, dset, out


def feo_parameters(values):
    return [dict(name=name, kind="set" if name == "s02" else "guess", value=values[name]) for name in FEO_NAMES]


def test_feffit_ex4_feo_coordination_numbers_matches_plain_larch(client):
    feo_dat, _, dset, reference = feo_ex4_reference()

    project, group = import_columns(client, "feo_xafs.chi", feo_dat.k, feo_dat.chi, "chi")
    app = app_feffit(client, project, group,
                     parameters=feo_parameters(dict(n1=6, n2=12, s02=0.7, de0=0.1, sig2_1=0.002, delr_1=0.,
                                                    sig2_2=0.002, delr_2=0.)),
                     paths=FEO_PATHS,
                     transform=dict(fitspace="r", kmin=2.0, kmax=13.5, kweight=[3], dk=3, window="kaiser",
                                    rmin=1.0, rmax=3.2))

    assert_same_feffit(app, reference, dset, FEO_NAMES)


# --- feffit Ex5: FeO in other fitting spaces (examples/feffit/doc_feffit5.py) ------------
# The script saves Ex4's fit as its R-space result, so R space is the Ex4 test above. The
# app fits only in k and R, so the q- and wavelet-space fits are skipped by design. The
# script runs its k-space fit after the q-space one, on copy(pars) and the same dataset.
# feffit does not write fitted values back into pars, so skipping the q fit leaves the
# k fit's starting point unchanged: the script's own initial values, which the app is sent.

def test_feffit_ex5_feo_in_k_space_matches_plain_larch(client):
    feo_dat, pars, dset, _ = feo_ex4_reference()
    pars3 = copy(pars)
    dset.transform.kweight = 2
    dset.transform.fitspace = "k"
    starting = {name: float(getattr(pars3, name).value) for name in FEO_NAMES}
    reference = feffit(pars3, dset)

    project, group = import_columns(client, "feo_xafs.chi", feo_dat.k, feo_dat.chi, "chi")
    app = app_feffit(client, project, group, parameters=feo_parameters(starting), paths=FEO_PATHS,
                     transform=dict(fitspace="k", kmin=2.0, kmax=13.5, kweight=[2], dk=3, window="kaiser",
                                    rmin=1.0, rmax=3.2))

    assert_same_feffit(app, reference, dset, FEO_NAMES)


# --- feffit Ex6: ZnSe, one fit per scatterer (examples/feffit/doc_feffit6.py) ------------
# The script sets degen=4.0 on every path; the app's files carry it in their headers.
# Its phase-corrected transform and plots are drawing only and are left out.

ZNSE_SCATTERERS = ("Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb")


def znse_chi():
    dat = read_ascii(str(XAFSDATA / "znse_zn_xafs.001"), labels="energy dwelltime i0 i1")
    dat.mu = -np.log(dat.i1 / dat.i0)
    autobk(dat, e0=9665.0, rbkg=1.21, kweight=2)
    return dat


@pytest.mark.parametrize("scatterer", ZNSE_SCATTERERS)
def test_feffit_ex6_znse_one_scatterer_matches_plain_larch(client, scatterer):
    znse_data = znse_chi()
    filename = f"Feff_ZnSe/feff_zn{scatterer.lower()}.dat"
    path = feffpath(str(FEFFIT / filename), degen=4.0, s02="amp", e0="del_e0", sigma2="sig2", deltar="del_r")
    trans = feffit_transform(rmin=1.5, rmax=3.0, kmin=3, kmax=13, kw=2, dk=4, window="kaiser", **APP_TRANSFORM)
    dset = feffit_dataset(data=chi_data(znse_data), paths={scatterer: path}, transform=trans)
    pars = Group(amp=guess(1.0), del_e0=guess(0.1, min=-20, max=20),
                 sig2=param(0.006, vary=True, min=0), del_r=guess(0.))
    reference = feffit(pars, dset)

    project, group = import_columns(client, "znse_zn_xafs.chi", znse_data.k, znse_data.chi, "chi")
    app = app_feffit(client, project, group,
                     parameters=[dict(name="amp", kind="guess", value=1.0),
                                 dict(name="del_e0", kind="guess", value=0.1, min=-20, max=20),
                                 dict(name="sig2", kind="guess", value=0.006, min=0),
                                 dict(name="del_r", kind="guess", value=0.)],
                     paths=[dict(id=scatterer, filename=filename.split("/")[-1],
                                 content=feff_text(filename, degen=4.0),
                                 s02="amp", e0="del_e0", sigma2="sig2", deltar="del_r")],
                     transform=dict(fitspace="r", kmin=3, kmax=13, kweight=[2], dk=4, window="kaiser",
                                    rmin=1.5, rmax=3.0))

    assert_same_feffit(app, reference, dset, ["amp", "del_e0", "sig2", "del_r"])


# --- fitting_examples Ex2: Fe pre-edge peaks (examples/fitting/doc_example2{a,b,c}.lar) --
# The scripts model the window as peaks + off + erf_amp*erf(erf_wid*(e - erf_cen)). The
# app's peak model is lmfit peaks + a linear background + lmfit's erf StepModel, with its
# own bounds, so both sides use the app's model. The scripts' erf is that step exactly:
# amplitude 2*erf_amp, sigma 1/erf_wid, and the offset off - erf_amp in the intercept.
# The app adds the free slope. Tolerances are the fast engine's precedent: two
# optimizers on one model agree within 1% of each parameter's uncertainty.

VALUE_SIGMA = 0.01
STDERR_RTOL = 0.01
REDCHI_RTOL = 1e-6

FE_PEAKS = {
    # example: (peak kind, [(amp, cen, wid), ...] as the script's params start them)
    "2a": ("gaussian", [(0.25, 7113.25, 0.6), (0.25, 7116.0, 1.2)]),
    "2b": ("gaussian", [(0.25, 7113.25, 0.6), (0.25, 7116.0, 1.2), (0.5, 7122.0, 1.2)]),
    "2c": ("voigt", [(0.25, 7113.25, 0.6), (0.25, 7116.0, 1.2), (0.5, 7122.0, 1.2)]),
}
FE_ERF = dict(off=0.50, erf_amp=0.50, erf_wid=0.50, erf_cen=7123.5)


def fe_pre_edge_window():
    """The scripts' data: plain pre_edge, then norm from just above index_of(7105) to index_of(7125)."""
    dat = read_ascii(str(EXAMPLES / "fitting" / "doc_example2.dat"), labels="energy xmu i0")
    pre_edge(dat.energy, dat.xmu, group=dat)
    i1, i2 = index_of(dat.energy, 7105), index_of(dat.energy, 7125)
    return dat, dat.energy[i1 + 1:i2 + 1], dat.norm[i1 + 1:i2 + 1]


def app_model_reference_fit(e, y, kind, peaks, step):
    """The app's documented peak model, written as a plain lmfit script."""
    span = float(e[-1] - e[0])
    min_width = max(float(np.min(np.diff(e))) / 10, span * 1e-9)
    model = LinearModel(prefix="background_")
    params = model.make_params(slope=0.0, intercept=FE_ERF["off"] - FE_ERF["erf_amp"])
    step_model = StepModel(form="erf", prefix="step_")
    params.update(step_model.make_params(**step))
    params["step_center"].set(min=float(e[0] - span), max=float(e[-1] + span))
    params["step_sigma"].set(min=min_width, max=span)
    params["step_amplitude"].set(min=0)
    model = model + step_model
    for index, (amplitude, center, sigma) in enumerate(peaks, start=1):
        prefix = f"peak_{index}_"
        peak = {"gaussian": GaussianModel, "voigt": VoigtModel}[kind](prefix=prefix)
        params.update(peak.make_params(center=center, sigma=sigma, amplitude=amplitude))
        params[prefix + "center"].set(min=float(e[0]), max=float(e[-1]))
        params[prefix + "sigma"].set(min=min_width, max=span)
        params[prefix + "amplitude"].set(min=0)
        model = model + peak
    return model.fit(y, params, x=e, method="leastsq", max_nfev=2000)


FE_2B_DOES_NOT_CONVERGE = pytest.mark.xfail(strict=True, reason=(
    "Genuine limitation, kept visible: Example 2b (three Gaussians) does not converge in the app's model. "
    "The script holds cen3 in [7120, 7124] and erf_cen in [7121, 7124]; the app has no per-parameter "
    "bounds, and with its own (centres anywhere in the 7105.07-7124.95 eV window, step centre one window "
    "width either side) plus the free slope, peak_3_center runs to the window edge (7124.9502) and the "
    "step narrows to sigma 0.0906 eV. The plain lmfit reference of the app's model stops at max_nfev=2000 "
    "(and 5000) with 'Tolerance seems to be too small. Could not estimate error-bars.', redchi 1.1844e-4; "
    "the app refuses the same request with HTTP 400 'Peak fit did not converge within max_nfev=2000' "
    "and the same lmfit message. So the two sides agree, but neither reproduces the example."))


@pytest.mark.parametrize("example", [pytest.param(example, marks=FE_2B_DOES_NOT_CONVERGE if example == "2b" else ())
                                     for example in sorted(FE_PEAKS)])
def test_fitting_ex2_fe_pre_edge_peaks_match_plain_larch(client, example):
    kind, peaks = FE_PEAKS[example]
    step = dict(amplitude=2 * FE_ERF["erf_amp"], center=FE_ERF["erf_cen"], sigma=1 / FE_ERF["erf_wid"])
    dat, e, y = fe_pre_edge_window()
    reference = app_model_reference_fit(e, y, kind, peaks, step)
    assert reference.success

    project, group = import_columns(client, "doc_example2.nor", dat.energy, dat.norm, "norm")
    reply = client.post(f"/api/athena/projects/{project['id']}/analyze", json={
        "version": project["version"], "action": "peaks", "group_ids": [group["id"]], "options": {
            "array": "norm", "xmin": float(e[0]), "xmax": float(e[-1]),
            "peaks": [dict(kind=kind, amplitude=amplitude, center=center, sigma=sigma)
                      for amplitude, center, sigma in peaks],
            "background": dict(slope=0.0, intercept=FE_ERF["off"] - FE_ERF["erf_amp"],
                               step=dict(step, form="erf", vary=True))}})
    assert reply.status_code == 200, reply.text
    app = reply.json()["result"]

    np.testing.assert_array_equal(app["x"], e)
    np.testing.assert_array_equal(app["observed"], y)
    assert app["details"]["nvarys"] == reference.nvarys
    assert set(app["parameters"]) == set(reference.params)
    for name, expected in reference.params.items():
        row = app["parameters"][name]
        if expected.stderr is None:
            assert row["stderr"] is None, name
            assert row["value"] == pytest.approx(expected.value, rel=1e-12, abs=0), name
            continue
        off_by = abs(row["value"] - expected.value) / expected.stderr
        assert off_by <= VALUE_SIGMA, f"{name}: {off_by:.3g} sigma ({row['value']!r} vs {expected.value!r})"
        np.testing.assert_allclose(row["stderr"], expected.stderr, rtol=STDERR_RTOL, err_msg=f"{name} stderr")
    np.testing.assert_allclose(app["redchi"], reference.redchi, rtol=REDCHI_RTOL)


# --- fitting_examples Ex3: Au linear combination (examples/fitting/doc_example3/*.lar) ---
# The scripts fit weights in [0, 1] with the last one tied to 1 minus the others, which is
# the app's LCF with sum_to_one and nonnegative. The scripts divide the residual by
# eps=0.001; Larch's minimize scales the covariance by reduced chi-square, so that changes
# chi-square (by 1/eps**2) and nothing else. The app solves the same least squares
# directly. fit1 is s1+s2 from 0.5; fit3's eleven models include fit2's five.

AU = EXAMPLES / "fitting" / "doc_example3"
AU_EPS = 0.001
AU_MODELS = {
    # name: (standards fitted freely, the standard tied to 1 - the others, start value)
    "fit1": ((1,), 2, 0.5),
    "fit3-s1s2": ((1,), 2, 0.4),
    "fit3-s1s2s3": ((1, 2), 3, 0.4),
    "fit3-s1s2s4": ((1, 2), 4, 0.4),
    "fit3-s1s2s5": ((1, 2), 5, 0.4),
    "fit3-s1s2s6": ((1, 2), 6, 0.4),
    "fit3-s1s2s3s4": ((1, 2, 3), 4, 0.4),
    "fit3-s1s2s3s5": ((1, 2, 3), 5, 0.4),
    "fit3-s1s2s3s6": ((1, 2, 3), 6, 0.4),
    "fit3-s1s2s4s5": ((1, 2, 4), 5, 0.4),
    "fit3-s1s2s5s6": ((1, 2, 5), 6, 0.3),
    "fit3-s1s2s4s6": ((1, 2, 4), 6, 0.4),
}


def au_read_data():
    """ReadData.lar: the unknown between index_of(11870) and index_of(12030), standards on its grid."""
    d1 = read_ascii(str(AU / "unknown.dat"))
    standards = {index: read_ascii(str(AU / f"s{index}.dat")) for index in range(1, 7)}
    i1, i2 = index_of(d1.energy, 11870), index_of(d1.energy, 12030)
    data = Group(energy=d1.energy[i1:i2 + 1], mu=d1.munorm[i1:i2 + 1])
    for index, standard in standards.items():
        setattr(data, f"s{index}", interp(standard.energy, standard.munorm, data.energy))
    data.eps = AU_EPS
    return d1, standards, data


def au_resid(pars, data):
    model = sum(getattr(pars, f"amp{index}") * getattr(data, f"s{index}") for index in range(1, 7))
    return (data.mu - model) / data.eps


AU_S6_ON_ITS_BOUND = pytest.mark.xfail(strict=True, reason=(
    "Genuine difference, kept visible: in fit3's s1+s2+s5+s6 model the constrained optimum puts s6 on "
    "its zero bound. The app finds it (weights 0.278665, 0.532070, 0.189264, 1.1e-17; s6 held at zero "
    "with no error, the same fit as s1+s2+s5; chi-square 5.07829e-3, reduced 3.21411e-5). The script's "
    "lmfit fit, with amp6 = 1 - amp1 - amp2 - amp5 as a bounded expression, stops after 150 evaluations "
    "at a worse point: 0.276955 +/- 0.016713, 0.532733 +/- 0.003270, 0.190310 +/- 0.012601, "
    "1.26e-6 +/- 0.004146; chi-square 5.07954e-3, reduced 3.23537e-5. amp1 differs by 0.102 of its "
    "uncertainty, beyond the 0.01 allowed."))


@pytest.mark.parametrize("model", [pytest.param(model, marks=AU_S6_ON_ITS_BOUND if model == "fit3-s1s2s5s6" else ())
                                   for model in AU_MODELS])
def test_fitting_ex3_au_linear_combination_matches_plain_larch(client, model):
    free, tied, start = AU_MODELS[model]
    d1, standards, data = au_read_data()
    pars = param_group(**{f"amp{index}": param(start if index in free + (tied,) else 0.0, min=0, max=1)
                          for index in range(1, 7)})
    for index in free:
        getattr(pars, f"amp{index}").vary = True
    getattr(pars, f"amp{tied}").expr = "1 - " + " - ".join(f"amp{index}" for index in free)
    reference = minimize(au_resid, pars, args=(data,)).fit_details
    assert reference.success

    used = sorted(free + (tied,))
    project, target = import_columns(client, "unknown.dat", d1.energy, d1.munorm, "norm")
    group_ids = [target["id"]]
    for index in used:
        project, group = import_columns(client, f"s{index}.dat", standards[index].energy,
                                        standards[index].munorm, "norm", project=project)
        group_ids.append(group["id"])
    reply = client.post(f"/api/athena/projects/{project['id']}/analyze", json={
        "version": project["version"], "action": "lcf", "group_ids": group_ids, "options": {
            "array": "norm", "xmin": float(data.energy[0]), "xmax": float(data.energy[-1]),
            "sum_to_one": True, "nonnegative": True}})
    assert reply.status_code == 200, reply.text
    app = reply.json()["result"]

    np.testing.assert_array_equal(app["x"], data.energy)
    for weight, stderr, index in zip(app["weights"], app["weight_stderr"], used):
        expected = reference.params[f"amp{index}"]
        off_by = abs(weight - expected.value) / expected.stderr
        assert off_by <= VALUE_SIGMA, f"amp{index}: {off_by:.3g} sigma ({weight!r} vs {expected.value!r})"
        np.testing.assert_allclose(stderr, expected.stderr, rtol=STDERR_RTOL, err_msg=f"amp{index} stderr")
    np.testing.assert_allclose(app["reduced_chisqr"], reference.redchi * AU_EPS ** 2, rtol=REDCHI_RTOL)
