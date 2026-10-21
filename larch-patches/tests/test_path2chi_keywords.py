"""Regression tests for path parameters given as keywords to ``path2chi`` (temporary patch 0010).

Since upstream ``c18a4ed63`` (2026-10-11), a path parameter given as a keyword is left out of
the values ``_calc_chi`` unpacks, so ``path2chi(path, sigma2=0.005)`` raises ``ValueError: not
enough values to unpack (expected 7, got 6)``. Larch at 8d6cd41c2 used the keyword's value in
place of the path's own.

The expected chi is that of a path whose own parameter has the keyword's value, through the
same Larch: at 8d6cd41c2 the two are equal bit for bit, on any platform. The value at k = 5 is
Larch's at 8d6cd41c2 (with the team patches), to 9 digits.
"""
import numpy as np
import pytest
from lmfit import Parameters

from larch.fitting import param_group
from larch.xafs import feffpath, path2chi

from examples_path import examples_dir

FEFF0001 = examples_dir() / 'feffit' / 'Feff_Cu' / 'feff0001.dat'

# The forms in which path2chi takes the parameters that path parameters may refer to.
PARAMETER_FORMS = {
    'no parameters': lambda: {},
    'lmfit Parameters': lambda: {'params': Parameters()},
    'a parameter group': lambda: {'paramgroup': param_group()},
}


def a_path(**values):
    return feffpath(str(FEFF0001), **values)


@pytest.mark.parametrize('form', PARAMETER_FORMS)
def test_a_path_parameter_given_to_path2chi_replaces_the_paths_own(form):
    """path2chi(path, sigma2=0.005) calculates chi with sigma2 = 0.005 and the path's own
    values for the other path parameters, whichever form of parameters it is also given."""
    path = a_path(s02=0.9, e0=1.0, sigma2=0.003)
    path2chi(path, sigma2=0.005, **PARAMETER_FORMS[form]())
    expected = a_path(s02=0.9, e0=1.0, sigma2=0.005)
    path2chi(expected)
    np.testing.assert_array_equal(path.k, expected.k)
    np.testing.assert_array_equal(path.chi, expected.chi)
    assert path.chi[100] == pytest.approx(0.03606396143, rel=1e-9)   # k = 5
