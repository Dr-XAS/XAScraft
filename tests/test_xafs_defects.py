"""Regression tests for three EXAFS defects, each with a known answer."""
from pathlib import Path

import numpy as np
import pytest

from larch import Group
from larch.xafs import (autobk, estimate_noise, feffit, feffit_dataset, feffit_transform,
                        feffpath, path2chi, pre_edge)
from larch.fitting import guess, param, param_group
import larch.xafs.sigma2_models as sigma2_models

FEFF_CU = Path(__file__).parents[1] / 'examples' / 'feffit' / 'Feff_Cu'


@pytest.fixture
def python_debye(monkeypatch):
    """Larch's own Python correlated-Debye model in place of the native library,
    which is not built for every platform. The defect is in which path is read,
    not in the model."""
    def debye(natoms, tk, theta, rnorm, x, y, z, atwt):
        floats = lambda values: [float(value) for value in values]
        return sigma2_models.sigma2_correldebye_py(natoms, tk, theta, float(rnorm), floats(x),
                                                   floats(y), floats(z), floats(atwt))
    monkeypatch.setattr(sigma2_models, 'sigma2_correldebye', debye)


def test_reversing_the_path_list_leaves_every_path_its_own_debye_sigma2(python_debye):
    """lmfit copies the parameters into a new interpreter but kept the sigma2
    procedures bound to the old one, so every path got the last path's sigma2
    and the fitted Debye temperature moved with the path order (348 K forward,
    307 K reversed, true 315 K)."""
    files = [FEFF_CU / 'feff0001.dat', FEFF_CU / 'feff0005.dat']
    temperature, theta_true = 300.0, 315.0
    k = np.linspace(0, 16, 321)
    chi = np.zeros_like(k)
    for name in files:
        path = feffpath(str(name), s02=0.9, e0=0.0)
        path.sigma2 = float(sigma2_models.sigma2_debye(temperature, theta_true, path))
        path2chi(path, k=k)
        chi += path.chi
    transform = feffit_transform(kmin=3, kmax=14, kw=2, dk=1, window='hanning', rmin=1.4, rmax=5.0)
    fitted = []
    for order in ([0, 1], [1, 0]):
        params = param_group(amp=param(0.9, vary=False), e0=param(0.0, vary=False),
                             theta=guess(250.0, min=100, max=600))
        paths = [feffpath(str(files[i]), s02='amp', e0='e0',
                          sigma2=f'sigma2_debye({temperature}, theta)') for i in order]
        dataset = feffit_dataset(data=Group(k=k, chi=chi), pathlist=paths, transform=transform)
        theta = feffit(params, dataset).params['theta'].value
        fitted.append(theta)
        for path in (dataset.paths.values() if isinstance(dataset.paths, dict) else dataset.paths):
            used = path.path_paramvals()['sigma2']
            assert used == pytest.approx(sigma2_models.sigma2_debye(temperature, theta, path), rel=1e-9)
    assert fitted == pytest.approx([theta_true, theta_true], abs=1e-3)


def test_autobk_chi_does_not_depend_on_the_units_of_mu():
    """The endpoint clamps weighed chi in the raw units of mu, so the same
    absorption in other units gave another background: chi(k) changed by 15%
    (k^2-weighted RMS, k 3-10) when mu was multiplied by 100."""
    energy = np.linspace(6339., 7439., 280)
    relative = energy - 6539.
    k = np.sqrt(.2624682917 * np.maximum(relative, 0))
    step = .5 + np.arctan(relative / 1.6) / np.pi
    mu = .2 - 4.5e-5 * relative + step * (1 + .04 * np.sin(4.8 * k) * np.exp(-.01 * k * k) / np.maximum(k, 1))
    chis = []
    for scale in (.01, 1., 100.):
        group = Group(energy=energy, mu=scale * mu)
        pre_edge(group, e0=6539., pre1=-170., pre2=-40., norm1=100., norm2=880., nnorm=2)
        autobk(group, e0=6539., rbkg=1., kweight=2, kmax=14., clamp_lo=1, clamp_hi=1)
        chis.append(group.chi)
        mask = (group.k >= 3) & (group.k <= 10)
    for chi in (chis[0], chis[2]):
        difference = np.linalg.norm(((chi - chis[1]) * group.k**2)[mask])
        assert difference < 1e-9 * np.linalg.norm((chis[1] * group.k**2)[mask])


def test_estimate_noise_uses_the_window_it_is_given():
    """The window was passed under a keyword the transform ignores, so every
    estimate used a Kaiser window; Hanning with dk=0 became an all-zero Kaiser
    window and the estimate failed."""
    k = np.arange(0, 20.001, 0.05)
    chi = np.random.default_rng(1).normal(0, 0.002, k.size)
    estimates = {}
    for window, dk in (('hanning', 2), ('kaiser', 2), ('hanning', 0)):
        group = Group()
        estimate_noise(k, chi, group=group, kmin=3, kmax=14, dk=dk, kweight=2, kwindow=window)
        estimates[window, dk] = group.epsilon_k
    assert np.isfinite(estimates['hanning', 0])
    assert estimates['hanning', 2] != estimates['kaiser', 2]
