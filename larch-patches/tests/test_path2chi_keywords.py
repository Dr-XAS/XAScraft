"""Regression tests for path parameters given as keywords (temporary patch 0010).

Since upstream ``c18a4ed63`` (2026-10-11), a path parameter given as a keyword is left out of
the values ``_calc_chi`` unpacks, so ``path2chi(path, sigma2=0.005)``,
``path.calc_chi_from_params(params, sigma2=0.005)`` and ``path._calc_chi(e0=-3)`` (upstream's
``examples/feffit/use_ff2chi.lar``) raise ``ValueError: not enough values to unpack (expected
7, got 6)``. Larch at 8d6cd41c2 used the keyword's value in place of the path's own.

The expected chi is that of a path whose own parameter has the keyword's value, through the
same Larch: the two do the same arithmetic on the same numbers, so they agree bit for bit on
any platform, as they do at 8d6cd41c2. The value at k = 5 is Larch's at 8d6cd41c2 (with the
team patches), to 9 digits. No test compares chi with 8d6cd41c2's bit for bit, an accepted
deviation: CI runs these tests on Ubuntu, where the splines and libm may round the last bits
otherwise. Bit-for-bit agreement with 8d6cd41c2 was measured on macOS.

A path parameter that is neither given as a keyword nor in the path's lmfit Parameters raises
``KeyError`` naming it, as at 8d6cd41c2.
"""
import numpy as np
import pytest
from lmfit import Parameters

from larch.fitting import param, param_group
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


def fit_parameters():
    return param_group(amp=param(0.9, vary=True), de0=param(1.0, vary=True),
                       alpha=param(0.004, vary=True), ss=param(0.003, vary=True))


def test_a_path_parameter_given_to_path2chi_replaces_its_expression_in_a_parameter_group():
    """path2chi(path, params=<ParameterGroup>, sigma2=0.005), for a path whose parameters are
    expressions of the group's: sigma2 = 0.005 replaces its expression, and the other path
    parameters are still evaluated from the group."""
    expressions = dict(s02='amp', e0='de0', deltar='alpha*reff')
    path = a_path(sigma2='ss', **expressions)
    path2chi(path, params=fit_parameters(), sigma2=0.005)
    expected = a_path(sigma2=0.005, **expressions)
    path2chi(expected, params=fit_parameters())
    np.testing.assert_array_equal(path.k, expected.k)
    np.testing.assert_array_equal(path.chi, expected.chi)
    assert path.chi[100] == pytest.approx(0.02809605312, rel=1e-9)   # k = 5


# The forms of parameters calc_chi_from_params takes: each has its own branch there.
CALC_CHI_FROM_PARAMS_FORMS = {
    'lmfit Parameters': Parameters,
    'a parameter group': param_group,
}


@pytest.mark.parametrize('form', CALC_CHI_FROM_PARAMS_FORMS)
def test_a_path_parameter_given_to_calc_chi_from_params_replaces_the_paths_own(form):
    """path.calc_chi_from_params(params, sigma2=0.005) calculates chi with sigma2 = 0.005 and
    the path's own values for the other path parameters."""
    path = a_path(s02=0.9, e0=1.0, sigma2=0.003)
    path.calc_chi_from_params(CALC_CHI_FROM_PARAMS_FORMS[form](), sigma2=0.005)
    expected = a_path(s02=0.9, e0=1.0, sigma2=0.005)
    path2chi(expected)
    np.testing.assert_array_equal(path.k, expected.k)
    np.testing.assert_array_equal(path.chi, expected.chi)
    assert path.chi[100] == pytest.approx(0.03606396143, rel=1e-9)   # k = 5


# The e0 values of upstream's examples/feffit/use_ff2chi.lar, and chi at k = 5 for each.
USE_FF2CHI_E0 = {-6: -0.01559334245, -3: 0.006056478860, 0: 0.02732576712, 3: 0.04589595567,
                 6: 0.05946102695}


def test_e0_given_to_calc_chi_gives_the_chi_of_that_e0_as_in_upstreams_use_ff2chi_example():
    """Upstream's examples/feffit/use_ff2chi.lar: path._calc_chi(e0=e0) on one new path, on the
    default k grid, for e0 from -6 to 6 eV. Each gives the chi of a path made with that e0, so
    the path keeps its own e0 between the calls."""
    path = a_path(e0=0, sigma2=0.010)
    for e0, chi_at_5 in USE_FF2CHI_E0.items():
        path._calc_chi(e0=e0)
        expected = a_path(e0=e0, sigma2=0.010)
        expected._calc_chi()
        np.testing.assert_array_equal(path.k, expected.k)
        np.testing.assert_array_equal(path.chi, expected.chi, err_msg=f'e0 = {e0}')
        assert path.chi[100] == pytest.approx(chi_at_5, rel=1e-9), e0   # k = 5


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
