"""Regression tests for path parameters given as keywords to ``path2chi`` (temporary patch 0010).

Since upstream ``c18a4ed63`` (2026-10-11), a path parameter given as a keyword is left out of
the values ``_calc_chi`` unpacks, so ``path2chi(path, sigma2=0.005)`` raises ``ValueError: not
enough values to unpack (expected 7, got 6)``. Larch at 8d6cd41c2 used the keyword's value in
place of the path's own.

The expected chi is that of a path whose own parameter has the keyword's value, through the
same Larch: the two do the same arithmetic on the same numbers, so they agree bit for bit on
any platform, as they do at 8d6cd41c2. The value at k = 5 is Larch's at 8d6cd41c2 (with the
team patches), to 9 digits.

A path parameter that is neither given as a keyword nor in the path's lmfit Parameters raises
``KeyError`` naming it, as at 8d6cd41c2.
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


def test_every_path_parameter_can_be_given_to_path2chi_on_a_k_grid():
    """All seven path parameters as keywords, on an explicit k grid: the chi of a path whose
    own parameters have these values. With every one given, none reached the values
    _calc_chi unpacks ('expected 7, got 0')."""
    values = dict(s02=0.81, e0=2.5, deltar=0.012, sigma2=0.0052, third=1.0e-4, fourth=2.0e-5,
                  ei=0.3)
    k = np.arange(241) * 0.05
    path = a_path(s02=0.9, e0=1.0, sigma2=0.003)
    path2chi(path, k=k, **values)
    expected = a_path(**values)
    path2chi(expected, k=k)
    np.testing.assert_array_equal(path.k, k)
    np.testing.assert_array_equal(path.chi, expected.chi)
    assert path.chi[100] == pytest.approx(0.03443451930, rel=1e-9)   # k = 5


# The calls that read a path's parameter values from its lmfit Parameters as they are.
READ_PATH_PARAMETERS = {
    'path_paramvals()': lambda path: path.path_paramvals(),
    '_calc_chi(k=k)': lambda path: path._calc_chi(k=np.arange(241) * 0.05),
}


@pytest.mark.parametrize('call', READ_PATH_PARAMETERS)
def test_a_path_parameter_neither_given_nor_in_the_lmfit_parameters_raises_key_error(call):
    """A path parameter missing from the path's lmfit Parameters, and not given as a keyword,
    raises KeyError naming it. At the pin, upstream's check that it is there leaves it out
    ('expected 7, got 6'); that check kept with keywords used again would give None."""
    path = a_path(s02=0.9, e0=1.0, sigma2=0.003)
    path2chi(path)
    missing = path.pathpar_name('ei')
    del path.params[missing]
    with pytest.raises(KeyError) as raised:
        READ_PATH_PARAMETERS[call](path)
    assert raised.value.args == (missing,)
