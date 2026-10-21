"""Regression tests for upstream FEFF path behavior that changed after 8d6cd41c2.

Upstream ``c18a4ed63`` (2026-10-11) broke each of these; patch 0008 restores them.
Each test has a known answer from Larch at 8d6cd41c2.
"""
import shutil

import pytest
from lmfit import Parameters

from larch.xafs import feffpath, path2chi

from examples_path import FEFF_CU


def test_paths_with_identical_feff_content_keep_their_own_parameters(tmp_path):
    """Two files with the same FEFF content (a split shell, or one file added twice)
    got the same parameter names, so the second path's sigma2 overwrote the first's."""
    first, second = tmp_path / 'feff0001.dat', tmp_path / 'feff0002.dat'
    for name in (first, second):
        shutil.copyfile(FEFF_CU / 'feff0001.dat', name)
    params = Parameters()
    paths = [feffpath(str(first), sigma2=0.003, s02=0.9),
             feffpath(str(second), sigma2=0.008, s02=0.9)]
    for path in paths:
        path.create_path_params(params=params)
    assert [path.path_paramvals()['sigma2'] for path in paths] == [0.003, 0.008]


def test_path2chi_with_lmfit_parameters_calculates_chi():
    """Given lmfit Parameters, path2chi set up the path parameters but never
    calculated chi, so path.chi stayed unset."""
    path = feffpath(str(FEFF_CU / 'feff0001.dat'), sigma2=0.004, s02=0.9, e0=1.0)
    path2chi(path, params=Parameters())
    assert len(path.k) == len(path.chi) == 401
    assert path.chi[100] == pytest.approx(0.0372203, abs=1e-7)   # k = 5, Larch at 8d6cd41c2


def test_a_kmax_beyond_the_feff_grid_is_clamped_to_it():
    """Without an explicit k, chi was calculated up to a given kmax even past the
    last k of the Feff.dat grid (20 here), where FEFF has no data."""
    path = feffpath(str(FEFF_CU / 'feff0001.dat'), sigma2=0.004, s02=0.9)
    path2chi(path, kmax=25)
    assert len(path.k) == 401
    assert path.k[-1] == pytest.approx(20.0)
