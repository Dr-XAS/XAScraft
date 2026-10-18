"""A longer FT window must not count zero padding as extra extracted samples."""

import numpy as np
import pytest
from larch import Group
from larch.xafs import xftf

from xraylarch_web.athena_import_policy import initialize_import
from xraylarch_web.athena_science import (
    AthenaParameters, ScientificError, _fft_capacity, process_spectrum,
)


@pytest.fixture
def long_spectrum():
    energy = np.linspace(8750., 10150., 2801)
    k = np.sqrt(np.maximum(energy - 8980., 0) / 3.80998212)
    edge = 1 / (1 + np.exp(-(energy - 8980.) / 2.5))
    chi = .035 * np.sin(4.2 * k + .3) * np.exp(-.17 * k)
    mu = .18 + .000018 * (energy - energy[0]) + .85 * edge * (1 + chi)
    return energy, mu


def test_window_beyond_fft_half_grid_retains_native_larch_result(long_spectrum):
    parameters = dict(e0=8980., bkg_kmax=15., kmax=15.3, nfft=512, kstep=.059)
    result = process_spectrum(*long_spectrum, parameters)
    arrays = result['arrays']
    assert len(arrays['k']) == len(arrays['q']) == len(arrays['chiq_re']) == 255
    assert arrays['k'][-1] == pytest.approx(14.986)
    assert result['effective']['kmax'] == 15.3
    reference = process_spectrum(*long_spectrum, {**parameters, 'kmax':15.})
    np.testing.assert_array_equal(arrays['chi'], reference['arrays']['chi'])
    direct = Group()
    xftf(np.asarray(arrays['k']), np.asarray(arrays['chi']), group=direct,
         kmin=3, kmax=15.3, kweight=2, dk=1, window='hanning', nfft=512, kstep=.059)
    for name in ('kwin', 'r', 'chir_re', 'chir_im', 'chir_mag'):
        np.testing.assert_allclose(arrays[name], getattr(direct, name), rtol=1e-12, atol=1e-12)
    assert any('zero-padded' in warning for warning in result['warnings'])


def test_enforced_import_preserves_valid_independent_window_and_grid(long_spectrum):
    imported = initialize_import(*long_spectrum, policy={'element':'Cu', 'edge':'K'},
        parameters={'bkg_kmax':15., 'kmax':15.3, 'nfft':512, 'kstep':.059}, exafs=True)
    parameters = imported['parameters']
    assert parameters['bkg_kmax'] == 15.
    assert parameters['kmax'] == 15.3
    result = process_spectrum(*long_spectrum, parameters)
    assert result['effective']['kmax'] == 15.3
    assert len(result['arrays']['k']) == 255


def test_actual_extracted_grid_beyond_half_fft_is_still_rejected(long_spectrum):
    with pytest.raises(ScientificError, match='k grid exceeds nfft/2'):
        process_spectrum(*long_spectrum,
                         {'e0':8980., 'bkg_kmax':15.2, 'kmax':15.3, 'nfft':512, 'kstep':.059})


@pytest.mark.parametrize('taper', [{'dk':20.}, {'dk':1., 'dk2':20.}])
def test_oversized_temporary_window_is_rejected_even_when_chi_fits(taper):
    parameters = AthenaParameters(nfft=65536, kstep=.001, kmax=50., **taper)
    # Only 10001 chi samples fit comfortably in nfft/2. The requested window
    # plus its taper needs 70001 temporary samples and must fail independently.
    with pytest.raises(ScientificError, match='transform window creates an oversized grid'):
        _fft_capacity(10., parameters, window_kmax=50.)


def test_large_window_within_temporary_limit_does_not_consume_fft_capacity():
    parameters = AthenaParameters(nfft=65536, kstep=.001, kmax=50., dk=1., dk2=2.)
    _fft_capacity(10., parameters, window_kmax=50.)
