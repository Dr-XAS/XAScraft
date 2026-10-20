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
from larch.fitting import guess, param, param_group
from larch.io import read_ascii
from larch.xafs import autobk, feffit, feffit_dataset, feffit_transform, feffpath

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


def import_columns(client, name, x, y, data_type):
    """Upload two columns as a file and import them as one group, as the UI does."""
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
