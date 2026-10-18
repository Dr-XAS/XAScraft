"""Independent AUTOBK and FT limits retain measured chi and native zero padding."""
from copy import deepcopy
from io import StringIO

import numpy as np
import pytest
from larch import Group
from larch.xafs import xftf

from xraylarch_web.athena import AthenaStore, Command, ImportRequest, _native_processing_limits
from xraylarch_web.athena_context import measurement_uncertainty
from xraylarch_web.athena_plot_transform import PlotTransformOptions, plot_transform
from xraylarch_web.athena_science import ScientificError, process_spectrum
from xraylarch_web.athena_special_plot import SpecialPlotOptions, special_plot
from xraylarch_web.config import Settings


@pytest.fixture
def long_spectrum():
    energy = np.linspace(8750, 10150, 2801)
    k = np.sqrt(np.maximum(energy - 8980, 0) / 3.80998212)
    edge = 1 / (1 + np.exp(-(energy - 8980) / 2.5))
    chi = .035 * np.sin(4.2 * k + .3) * np.exp(-.17 * k)
    mu = .18 + .000018 * (energy - energy[0]) + .85 * edge * (1 + chi)
    return energy, mu


def test_background15_ft15_3_matches_direct_larch_without_extending_chi(long_spectrum):
    reference = process_spectrum(*long_spectrum, {'e0':8980, 'bkg_kmax':15, 'kmax':14})
    result = process_spectrum(*long_spectrum, {'e0':8980, 'bkg_kmax':15, 'kmax':15.3})
    a, e = result['arrays'], result['effective']
    assert e['bkg_kmax'] == e['available_kmax'] == a['k'][-1] == 15
    assert e['kmax'] == 15.3 < e['measured_kmax']
    for key in ('energy', 'mu', 'bkg', 'k', 'chi'):
        np.testing.assert_array_equal(a[key], reference['arrays'][key])
    direct = Group()
    xftf(np.asarray(a['k']), np.asarray(a['chi']), group=direct,
         kmin=3, kmax=15.3, kweight=2, dk=1, window='hanning')
    for key in ('kwin', 'r', 'chir_re', 'chir_im', 'chir_mag'):
        np.testing.assert_allclose(a[key], getattr(direct, key), rtol=1e-12, atol=1e-12)
    assert any('zero-padded' in note for note in result['warnings'])
    assert not np.allclose(a['chir_mag'], reference['arrays']['chir_mag'])


def test_native_limits_do_not_replace_ft_with_background_limit(long_spectrum):
    parameters = {'e0':8980, 'energy_shift':0, 'bkg_kmax':15, 'kmax':15.3}
    before = deepcopy(parameters)
    _native_processing_limits(parameters, long_spectrum[0], 'mu', {'native':{}})
    assert parameters == before


@pytest.mark.parametrize('bounds', [
    {'kmax':18},  # Beyond original measured energy support.
    {'kmin':15.05, 'kmax':15.3},  # No extracted samples in the window.
    {'kmin':14.96, 'kmax':15.3},  # Only one extracted sample in the window.
])
def test_extension_retains_measured_coverage_and_overlap_checks(long_spectrum, bounds):
    with pytest.raises(ScientificError, match='available k|three measured k points'):
        process_spectrum(*long_spectrum, {'e0':8980, 'bkg_kmax':15, **bounds})


def imported_project(tmp_path, spectrum):
    store = AthenaStore(Settings(data_root=tmp_path))
    project = store.create()
    content = StringIO()
    np.savetxt(content, np.column_stack(spectrum), header='energy mu', fmt='%.17g')
    info = store.inspect(project['id'], content.getvalue().encode(), 'synthetic.dat')
    ids = {c['name']:c['column_id'] for c in info['columns']}
    project = store.import_data(project['id'], ImportRequest(version=0,
        upload_id=info['upload_id'], energy_column=ids['energy'], numerator=[ids['mu']]))
    gid = project['groups'][0]['id']
    for options in ({'bkg_kmax':17, 'kmax':15.3}, {'bkg_kmax':15}):
        project = store.command(project['id'], Command(version=project['version'],
            action='parameters', group_ids=[gid], options=options))
    return store, project


@pytest.mark.parametrize('format', ['json', 'prj'])
def test_change_only_background_preserves_ft_and_survives_project_reopen(tmp_path, long_spectrum, format):
    store, project = imported_project(tmp_path, long_spectrum)
    group = project['groups'][0]
    assert group['processing_error'] is None
    assert group['parameters']['kmax'] == group['result']['effective']['kmax'] == 15.3
    assert group['parameters']['bkg_kmax'] == group['result']['effective']['bkg_kmax'] == 15
    assert store.load(project['id']) == project
    payload = store.export_project(project['id'], format)
    target = store.create()
    reopened = store.restore(target['id'], 0, payload, 'spectrum.'+format)['groups'][0]
    assert reopened['processing_error'] is None
    assert reopened['parameters']['kmax'] == reopened['result']['effective']['kmax'] == 15.3
    assert reopened['parameters']['bkg_kmax'] == 15
    np.testing.assert_array_equal(reopened['result']['arrays']['chi'], group['result']['arrays']['chi'])
    np.testing.assert_array_equal(reopened['result']['arrays']['chir_mag'], group['result']['arrays']['chir_mag'])


@pytest.mark.parametrize('legacy_cache', [False, True])
def test_viewer_weight_and_special_plot_keep_independent_ft_without_mutation(tmp_path, long_spectrum, legacy_cache):
    store, project = imported_project(tmp_path, long_spectrum)
    group = project['groups'][0]
    if legacy_cache:
        group['result']['effective'].pop('measured_kmax')
    before = deepcopy(group)
    view = plot_transform(group, PlotTransformOptions(version=project['version'], kweight=3))
    assert view['effective']['kmax'] == 15.3
    assert view['arrays']['k'][-1] == 15
    direct = process_spectrum(*long_spectrum, {**group['parameters'], 'kweight':3})
    np.testing.assert_array_equal(view['arrays']['chir_mag'], direct['arrays']['chir_mag'])
    special = special_plot([group], SpecialPlotOptions(version=project['version'], view='quad',
        group_ids=[group['id']], kweight=3))
    rpanel = next(panel for panel in special['panels'] if panel['id']=='R')
    np.testing.assert_array_equal(rpanel['curves'][0]['y'], direct['arrays']['chir_mag'])
    assert any('zero-padded' in note for note in special['notes'])
    cached = special_plot([group], SpecialPlotOptions(version=project['version'], view='quad',
        group_ids=[group['id']], kweight=2))
    assert any('zero-padded' in note for note in cached['notes'])
    assert group == before


def test_legacy_viewer_support_uses_already_shifted_cached_energy(tmp_path, long_spectrum):
    _, project = imported_project(tmp_path, long_spectrum)
    group = project['groups'][0]
    group['parameters'].update(e0=8985, energy_shift=5, kmax=14)
    group['result'] = process_spectrum(*long_spectrum, group['parameters'])
    measured = group['result']['effective'].pop('measured_kmax')
    before = deepcopy(group)
    view = plot_transform(group, PlotTransformOptions(version=project['version'], kweight=2, kmax=15.3))
    assert view['effective']['kmax'] == 15.3
    assert view['effective']['measured_kmax'] == measured
    assert group == before


def test_zero_padding_does_not_increase_independent_point_count(tmp_path, long_spectrum):
    _, project = imported_project(tmp_path, long_spectrum)
    report = measurement_uncertainty(project['groups'][0])
    assert report['nidp'] == pytest.approx(2 * (15 - 3) * (3 - 1) / np.pi)
