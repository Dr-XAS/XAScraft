"""Regression test for temporary patch 0009 (``fluo_corr`` uses the e0 it is given).

Like every temporary patch's test, it lives here only; 0009 changes nothing in upstream's
tests/, and upstream's own tests/test_xafs_fluo.py still passes with the patch.
"""

import numpy as np
from larch.io import read_ascii
from larch.xafs import fluo_corr
from larch.xafs.pre_edge import preedge

from examples_path import examples_dir


def test_fluo_corr_normalizes_around_the_e0_it_is_given():
    """An e0 the caller passes is used, as pre_edge() uses it: norm_corr is mu_corr
    normalized with the caller's options.  fluo_corr dropped it and normalized around
    its own find_e0 instead (here e0 is 7112 eV, the tabulated Fe K edge)."""
    dat = read_ascii(str(examples_dir() / 'xafsdata' / 'fe2o3_rt1.xmu'))
    opts = dict(e0=7112.0, pre1=-100, pre2=-30, norm1=50, norm2=300, nnorm=2)
    fluo_corr(dat.energy, dat.mu, 'Fe2O3', 'Fe', group=dat, **opts)
    expected = preedge(dat.energy, dat.mu_corr, **opts)['norm']
    np.testing.assert_allclose(dat.norm_corr, expected, rtol=0, atol=1e-12)
