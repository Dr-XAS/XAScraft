"""One detector upload can atomically create transmission and fluorescence."""
import copy
from io import StringIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from xraylarch_web.athena import AthenaStore, Command, ImportRequest
from xraylarch_web.athena_preferences import AthenaPreferences, ColumnMemory
from xraylarch_web.config import Settings
from xraylarch_web.main import create_app


def staged(tmp_path, xas_arrays, *, reverse=False):
    x, mu = xas_arrays
    values = np.column_stack([x / 1000, np.full(len(x), 10000), 10000 * np.exp(-mu),
                              20000 * mu, 30000 * mu, 10000 * np.exp(-1.75 * mu)])
    buf = StringIO()
    np.savetxt(buf, values[::-1] if reverse else values,
               header='energy i0 it if1 if2 ref', fmt='%.17g')
    store = AthenaStore(Settings(data_root=tmp_path)); project = store.create()
    inspected = store.inspect(project['id'], buf.getvalue().encode(), 'detectors.dat')
    ids = {c['name']: c['column_id'] for c in inspected['columns']}
    req = ImportRequest(version=0, upload_id=inspected['upload_id'], energy_column=ids['energy'],
        units='keV', numerator=[ids['i0']], denominator=ids['it'], mode='transmission',
        additional_fluorescence={'numerator': [ids['if1']], 'denominator': ids['i0']}, sort=reverse)
    return store, project, inspected, req, ids


@pytest.mark.parametrize('dtype', ['mu', 'xanes', 'norm', 'xmudat'])
def test_dual_import_keeps_actual_modes_independent_arithmetic_and_one_undo(tmp_path, xas_arrays, dtype):
    store, p, info, req, ids = staged(tmp_path, xas_arrays, reverse=True)
    req.data_type = dtype
    req.is_reference = True
    req.signal_multiplier = 2
    req.additional_fluorescence.signal_multiplier = -3
    req.additional_fluorescence.invert = True
    before = copy.deepcopy(p)
    preview = store.preview_columns(p['id'], req)
    assert store.load(p['id']) == before
    assert [t['label'] for t in preview['traces']] == ['Transmission · Sample', 'Fluorescence · Sample']
    assert len({t['id'] for t in preview['traces']}) == 2
    imported = store.import_data(p['id'], req)
    assert imported['version'] == p['version'] + 1 and len(imported['undo']) == 1
    assert [g['label'] for g in imported['groups']] == ['detectors.dat · Transmission', 'detectors.dat · Fluorescence']
    for group, trace, mode, factor, numerator, denominator in zip(imported['groups'], preview['traces'],
            ['transmission', 'fluorescence'], [2, 6], [[ids['i0']], [ids['if1']]], [ids['it'], ids['i0']], strict=True):
        np.testing.assert_allclose(group['mu'], factor * xas_arrays[1], atol=1e-14)
        np.testing.assert_allclose(group['energy'], xas_arrays[0], atol=1e-10)
        assert group['mu'] == trace['y']
        mapping = group['source']['mapping']
        assert mapping['mode'] == mode and mapping['numerator'] == numerator and mapping['denominator'] == denominator
        assert mapping['is_reference'] is True
        assert 'additional_fluorescence' not in mapping and group['data_type'] == dtype
    undone = store.command(p['id'], Command(version=imported['version'], action='undo'))
    assert undone['groups'] == []
    redone = store.command(p['id'], Command(version=undone['version'], action='redo'))
    assert redone['groups'] == imported['groups']


@pytest.mark.parametrize('rebin', [None, {'e0': 8980}])
def test_combined_import_saves_three_measurements_and_one_shared_reference(tmp_path, xas_arrays, rebin):
    store, p, info, req, ids = staged(tmp_path, xas_arrays, reverse=True)
    req = ImportRequest.model_validate(req.model_dump() | {
        'reference_numerator': ids['it'], 'reference_denominator': ids['ref'], 'rebin': rebin})
    before = copy.deepcopy(p)
    preview = store.preview_columns(p['id'], req)
    assert store.load(p['id']) == before
    traces = [t for t in preview['traces'] if t.get('stage') == 'rebinned'] if rebin else preview['traces']
    assert len(traces) == 3 and [t['role'] for t in traces] == ['sample', 'sample', 'reference']
    assert len({t['id'] for t in preview['traces']}) == len(preview['traces'])
    if not rebin:
        assert [t['label'] for t in traces] == ['Transmission · Sample', 'Fluorescence · Sample', 'Reference']
        for trace, factor in zip(traces, [1, 2, .75], strict=True):
            np.testing.assert_allclose(trace['y'], factor * xas_arrays[1], atol=1e-14)
    imported = store.import_data(p['id'], req, idempotency_key='three-measurements')
    assert imported['version'] == 1 and len(imported['groups']) == 3 and len(imported['undo']) == 1
    transmission, fluorescence, reference = imported['groups']
    assert [g['label'] for g in imported['groups']] == [
        'detectors.dat · Transmission', 'detectors.dat · Fluorescence', 'detectors.dat · Reference']
    assert transmission['reference_id'] == fluorescence['reference_id'] == reference['id']
    assert reference['reference_id'] is None and not reference['marked']
    for group, trace in zip(imported['groups'], traces, strict=True):
        np.testing.assert_allclose(group['mu'], trace['y'], atol=1e-14)
        np.testing.assert_allclose(group['energy'], trace['x'], atol=1e-10)
    mapping = reference['source']['mapping']
    assert mapping['numerator'] == [ids['it']] and mapping['denominator'] == ids['ref']
    assert mapping['mode'] == 'transmission' and mapping['is_reference'] is True
    assert mapping['reference_numerator'] is mapping['reference_denominator'] is None
    retained = reference['source'].get('rebin_original', reference['source'])
    assert set(retained['column_arrays']) == {ids['energy'], ids['it'], ids['ref']}
    np.testing.assert_allclose(retained['raw_arrays']['i0'], 10000 * np.exp(-xas_arrays[1]))
    np.testing.assert_allclose(retained['raw_arrays']['signal'], 10000 * np.exp(-1.75 * xas_arrays[1]))
    replay = store.import_data(p['id'], req, idempotency_key='three-measurements')
    assert replay['groups'] == imported['groups'] and replay['version'] == imported['version']
    assert replay['last_operation']['idempotent_replay']['group_ids'] == [g['id'] for g in imported['groups']]
    undone = store.command(p['id'], Command(version=imported['version'], action='undo'))
    assert undone['groups'] == []
    redone = store.command(p['id'], Command(version=undone['version'], action='redo'))
    assert redone['groups'] == imported['groups']


def test_individual_fluorescence_rebin_shared_reference_and_preprocessing_match_preview(tmp_path, xas_arrays):
    store, p, info, req, ids = staged(tmp_path, xas_arrays)
    req = ImportRequest.model_validate(req.model_dump() | {
        'additional_fluorescence': {'numerator': [ids['if1'], ids['if2']], 'denominator': [ids['i0']], 'individual_channels': True},
        'reference_numerator': ids['i0'], 'reference_denominator': ids['ref'],
        'preprocessing': {'mark': True}, 'rebin': {'e0': 8980}})
    preview = store.preview_columns(p['id'], req)
    rebinned = [t for t in preview['traces'] if t.get('stage') == 'rebinned']
    assert len(rebinned) == len(preview['rebin_results']) == 4
    assert len({t['id'] for t in preview['traces']}) == len(preview['traces'])
    imported = store.import_data(p['id'], req)
    assert len(imported['groups']) == 4 and imported['version'] == 1
    for group, trace in zip(imported['groups'], rebinned, strict=True):
        np.testing.assert_allclose(group['mu'], trace['y'], atol=1e-14)
        np.testing.assert_allclose(group['energy'], trace['x'], atol=1e-10)
        assert 'rebin_original' in group['source']
    reference = imported['groups'][-1]
    for sample in imported['groups'][:-1]:
        assert sample['reference_id'] == reference['id'] and sample['marked'] and not reference['marked']
        assert reference['source']['mapping']['mode'] == 'transmission'
    assert imported['groups'][1]['source']['mapping']['numerator'] == [ids['if1']]
    assert imported['groups'][2]['source']['mapping']['numerator'] == [ids['if2']]


def test_each_combined_measurement_reimports_without_duplicating_or_unlinking_reference(tmp_path, xas_arrays):
    store, p, info, req, ids = staged(tmp_path, xas_arrays, reverse=True)
    req.reference_numerator, req.reference_denominator = ids['it'], ids['ref']
    p = store.import_data(p['id'], req)
    original_ids = [g['id'] for g in p['groups']]
    # Saved projects retain enough detector provenance even after upload expiry.
    store.storage.path(p['id'], f"upload-{info['upload_id']}.npz").unlink()
    for ident in original_ids:
        staged_columns = store.inspect_group_columns(p['id'], ident)
        mapping = staged_columns['current_mapping']
        assert mapping['additional_fluorescence'] is None
        assert not mapping['reference_numerator'] and not mapping['reference_denominator']
        request = ImportRequest.model_validate(mapping | {
            'version': p['version'], 'upload_id': staged_columns['upload_id']})
        before = copy.deepcopy(p)
        p = store.import_data(p['id'], request, replace_group_id=ident)
        assert [g['id'] for g in p['groups']] == original_ids
        assert [g['reference_id'] for g in p['groups']] == [original_ids[-1], original_ids[-1], None]
        for current, previous in zip(p['groups'], before['groups'], strict=True):
            if current['id'] != ident:
                assert current == previous
            np.testing.assert_allclose(current['mu'], previous['mu'], atol=1e-14)
            np.testing.assert_allclose(current['energy'], previous['energy'], atol=1e-10)


def test_combined_alignment_reuses_shared_reference_shift_for_every_measurement(tmp_path, xas_arrays):
    from xraylarch_web.athena_preprocessing import ImportPreprocessing

    store, p, info, req, ids = staged(tmp_path, xas_arrays)
    req.reference_numerator, req.reference_denominator = ids['it'], ids['ref']
    p = store.import_data(p['id'], req)
    arrays = store.storage.read_arrays(p['id'], f"upload-{info['upload_id']}.npz")
    arrays[ids['energy']] += .003  # A shared +3 eV scan-axis error.
    arrays[ids['if1']] = 20000 * np.interp(xas_arrays[0] - 5, *xas_arrays)
    store.storage.write_arrays(p['id'], f"upload-{info['upload_id']}.npz", arrays)
    req.version = p['version']
    req.preprocessing = ImportPreprocessing(standard_id=p['groups'][0]['id'], align=True)
    imported = store.import_data(p['id'], req)
    assert imported['groups'][:3] == p['groups']
    transmission, fluorescence, reference = imported['groups'][3:]
    for group in (transmission, fluorescence, reference):
        assert group['parameters']['energy_shift'] == pytest.approx(-3, abs=.03)
    first = transmission['source']['import_preprocessing']['alignment']
    second = fluorescence['source']['import_preprocessing']['alignment']
    assert first == second and first['used_references']
    assert first['moving_id'] == reference['id'] and first['standard_id'] == p['groups'][-1]['id']


@pytest.mark.parametrize('invalid', ['missing', 'duplicate', 'dead_denominator'])
def test_bad_second_recipe_leaves_no_partial_project_or_preferences(tmp_path, xas_arrays, invalid):
    store, p, info, req, ids = staged(tmp_path, xas_arrays)
    if invalid == 'missing': req.additional_fluorescence.numerator = ['missing']
    if invalid == 'duplicate': req.additional_fluorescence.numerator = [ids['if1'], ids['if1']]
    if invalid == 'dead_denominator':
        # One zero I0 point is dropped with a warning; a monitor dead for
        # most of the scan still refuses the whole import.
        arrays = store.storage.read_arrays(p['id'], f"upload-{info['upload_id']}.npz")
        arrays[ids['i0']][len(arrays[ids['i0']]) // 2:] = 0
        # Keep primary arithmetic valid while making only the second denominator zero.
        req.numerator = [ids['if1']]
        store.storage.write_arrays(p['id'], f"upload-{info['upload_id']}.npz", arrays)
    for operation in (store.preview_columns, store.import_data):
        with pytest.raises(ValueError): operation(p['id'], req)
        assert store.load(p['id']) == p
        assert not list(store.storage.workspace_dir(p['id']).glob('undo-*.json'))
        assert AthenaPreferences(store.settings).read_columns() is None


def test_combined_count_enforces_group_limit_before_building_groups(tmp_path, xas_arrays, monkeypatch):
    store, p, info, req, ids = staged(tmp_path, xas_arrays)
    group = store.make_group('existing', *xas_arrays, data_type='xanes')
    p['groups'] = [dict(group, id=f'group-{i}') for i in range(99)]
    monkeypatch.setattr(store, 'load', lambda ident: copy.deepcopy(p))
    monkeypatch.setattr(store, 'make_import_group', lambda *args, **kwargs: pytest.fail('Group construction must follow the combined count check.'))
    with pytest.raises(ValueError, match='at most 100'):
        store.import_data(p['id'], req)


@pytest.mark.parametrize('existing', [97, 98])
def test_combined_reference_counts_once_towards_group_limit(tmp_path, xas_arrays, monkeypatch, existing):
    store, p, info, req, ids = staged(tmp_path, xas_arrays)
    req.reference_numerator, req.reference_denominator = ids['it'], ids['ref']
    p['groups'] = [{'id': f'existing-{index}'} for index in range(existing)]
    monkeypatch.setattr(store, 'load', lambda ident: copy.deepcopy(p))
    monkeypatch.setattr('xraylarch_web.athena._exchange_budget', lambda *args: None)
    def reached_construction(*args, **kwargs):
        raise RuntimeError('Group capacity accepted')
    monkeypatch.setattr(store, 'make_import_group', reached_construction)
    with pytest.raises(RuntimeError if existing == 97 else ValueError,
                       match='Group capacity accepted' if existing == 97 else 'at most 100'):
        store.import_data(p['id'], req)


@pytest.mark.parametrize('update', [
    {'mode': 'fluorescence'}, {'data_type': 'chi'}, {'numerator': []}, {'denominator': None},
    {'additional_fluorescence': {'numerator': [], 'denominator': 'i0'}},
    {'additional_fluorescence': {'numerator': ['if'], 'denominator': []}},
    {'additional_fluorescence': {'numerator': ['if'], 'denominator': 'i0', 'signal_multiplier': float('nan')}},
])
def test_combined_request_requires_both_explicit_energy_recipes(update):
    base = dict(version=0, upload_id='u', energy_column='energy', mode='transmission', numerator=['i0'], denominator='it',
                additional_fluorescence={'numerator': ['if'], 'denominator': 'i0'})
    with pytest.raises(ValidationError): ImportRequest.model_validate(base | update)


def test_both_modes_remember_remap_and_reset_for_new_layouts(tmp_path, xas_arrays):
    store, p, info, req, ids = staged(tmp_path, xas_arrays)
    p = store.import_data(p['id'], req)
    preferences = AthenaPreferences(store.settings)
    assert preferences.read_columns().mapping['additional_fluorescence'] == req.additional_fluorescence.model_dump()
    changed = copy.deepcopy(info)
    for i, col in enumerate(changed['columns']): col['column_id'] = f'new_{i}'
    restored = preferences.column_choices(changed, p)
    assert restored['matching_columns']
    assert restored['mapping']['numerator'] == ['new_1']
    assert restored['mapping']['additional_fluorescence']['numerator'] == ['new_3']
    assert restored['mapping']['additional_fluorescence']['denominator'] == 'new_1'
    changed['columns'][3]['name'] = 'different_detector'
    reset = preferences.column_choices(changed, p)
    assert not reset['matching_columns'] and reset['mapping']['additional_fluorescence'] is None
    memory = preferences.read_columns().model_dump()
    for selected in (['missing'], [ids['if1'], ids['if1']]):
        memory['mapping']['additional_fluorescence']['numerator'] = selected
        with pytest.raises(ValidationError): ColumnMemory.model_validate(memory)


def test_http_accepts_combined_preview_import_and_reader_review_gate(tmp_path, xas_arrays):
    store, p, info, req, ids = staged(tmp_path, xas_arrays)
    req.reference_numerator, req.reference_denominator = ids['it'], ids['ref']
    metadata = store.storage.read_json(p['id'], f"upload-{info['upload_id']}.json")
    metadata['file_plugin'] = {'review_required': True}
    store.storage.write_json(p['id'], f"upload-{info['upload_id']}.json", metadata)
    with TestClient(create_app(store.settings)) as client:
        base = f"/api/athena/projects/{p['id']}"
        preview = client.post(base + '/preview-columns', json=req.model_dump())
        assert preview.status_code == 200 and len(preview.json()['traces']) == 3
        blocked = client.post(base + '/import', json=req.model_dump())
        assert blocked.status_code == 400 and store.load(p['id']) == p
        req.reader_reviewed = True
        response = client.post(base + '/import', json=req.model_dump())
        assert response.status_code == 200 and len(response.json()['groups']) == 3
        assert response.json()['version'] == 1
