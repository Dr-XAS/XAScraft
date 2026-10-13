"""Agent saves are portable, compact and safe to retry without rerunning a fit."""
import copy
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from test_artemis import model, spectrum
from test_artemis_persistence import workspace, draft
from tests.test_agent_views import numeric_runs
from xraylarch_web import artemis_persistence as persistence
from xraylarch_web.artemis import PathInput, inspect_path
from xraylarch_web.artemis_structures import FeffJobs
from xraylarch_web.artemis_provenance import INPUT_GENERATOR
from xraylarch_web.athena import AthenaStore


def named_job(store, model):
    jobs = FeffJobs(store.settings.data_root)
    ident = 'e' * 32
    directory = jobs.root / ident
    directory.mkdir()
    source = model['paths'][0]
    path = inspect_path(PathInput(filename=source['filename'], content=source['content'])) | {'id': 'feff0001'}
    jobs._save(directory, dict(id=ident, status='complete', created=time.time(), elapsed_seconds=1,
        warnings=['Native diagnostic retained for review.'],
        diagnostics=[dict(code='feff_native_warning', severity='warning', message='Native diagnostic retained for review.', raw='WARNING: synthetic diagnostic')],
        provenance=dict(input_generator=INPUT_GENERATOR, engine='FEFF8L', feff_input='synthetic input', cif='synthetic CIF')))
    jobs._write_private_text(directory / 'paths.json', json.dumps([path]))
    return ident, jobs.get(ident)['paths'][0]


def test_numeric_save_warnings_history_and_retry_survive_job_expiry(workspace, model, monkeypatch):
    store, client, project, gid = workspace
    jid, path = named_job(store, model)
    base = f"/api/artemis/projects/{project['id']}/groups/{gid}"
    body = dict(model, version=project['version'], paths=[dict(id='path1', feff_job=jid, feff_path='feff0001')])
    direct = client.post(base + '/fit?view=summary', json=body)
    assert direct.status_code == 200, direct.text
    assert 'FEFF: Native diagnostic retained for review.' in direct.json()['warnings']
    response = client.post(base + '/fits', json=body, headers={'Idempotency-Key': 'save-once'})
    assert response.status_code == 200, response.text
    saved = response.json()
    record = saved['fit']
    assert saved['project']['version'] == project['version'] + 1
    assert record['result']['saved'] and 'Nothing was saved' not in record['result']['note']
    assert not record['stale'] and len(record['model_sha256']) == 64
    assert record['result']['feff_jobs'][0]['diagnostics'][0]['raw'] == 'WARNING: synthetic diagnostic'
    assert not [p for p, n in numeric_runs(saved) if n > 8]
    assert 'content' not in json.dumps(saved)
    assert saved['project']['groups'][0]['artemis']['latest_fit']['id'] == saved['fit_id']
    shutil.rmtree(FeffJobs(store.settings.data_root).root / jid)
    monkeypatch.setattr(persistence, 'fit_group', lambda *_: pytest.fail('history or replay reran optimizer'))
    replay = client.post(base + '/fits', json=body, headers={'Idempotency-Key': 'save-once'}).json()
    assert replay['idempotent_replay'] and replay['fit_id'] == saved['fit_id']
    assert replay['project']['version'] == saved['project']['version']
    changed = client.post(base + '/fits', json=dict(body, transform=dict(body['transform'], kmax=11)), headers={'Idempotency-Key': 'save-once'})
    assert changed.status_code == 400 and 'different fit inputs' in changed.text
    history = client.get(base + '/fits').json()
    assert history['count'] == 1 and history['fits'][0] == record
    full = client.get(base + f"/fits/{saved['fit_id']}?view=full").json()['fit']
    assert full['model']['paths'][0]['content'] == path['content']
    assert full['result']['warnings'] == record['result']['warnings']
    assert AthenaStore(store.settings).load(project['id'])['groups'][0]['artemis']['history'][0]['result'] == full['result']
    # Removal/undo cannot turn a timed-out retry into a new fit.
    removed = client.post(base + '/remove-fit?view=summary', json=dict(version=saved['project']['version'], fit_id=saved['fit_id']))
    assert removed.status_code == 200 and removed.json()['groups'][0]['artemis']['saved_fits'] == 0
    replay = client.post(base + '/fits', json=body, headers={'Idempotency-Key': 'save-once'}).json()
    assert replay['idempotent_replay'] and not replay['fit_present'] and replay['fit'] is None


def test_browser_draft_preserves_feff_warnings_and_archive_exchange(workspace, model):
    store, client, project, gid = workspace
    _, path = named_job(store, model)
    saved_model = draft(model)
    saved_model['paths'][0]['metadata']['feff'] = path['metadata']['feff']
    base = f"/api/artemis/projects/{project['id']}/groups/{gid}"
    response = client.post(base + '/fit-saved?view=summary', json=dict(version=project['version'], model=saved_model))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['fit']['result']['warnings'][-1] == 'FEFF: Native diagnostic retained for review.'
    exported = store.export_project(project['id'], 'json')
    # Use the same inert import path as the browser, including strict archive validation.
    parsed = store._parse_project(exported, 'exchange.json')
    archived = parsed['groups'][0]['artemis']['history'][0]
    assert archived['result']['metadata']['feff_sources']['cu1']['diagnostics'][0]['raw'] == 'WARNING: synthetic diagnostic'
    saved_model['paths'][0]['metadata']['feff']['path_sha256'] = '0' * 64
    invalid = client.post(base + '/model', json=dict(version=saved['project']['version'], model=saved_model))
    assert invalid.status_code == 400 and 'does not match' in invalid.text


def test_history_staleness_is_scientific_not_project_version(workspace, model):
    store, client, project, gid = workspace
    base = f"/api/artemis/projects/{project['id']}/groups/{gid}"
    saved = client.post(base + '/fits', json=dict(model, version=project['version'])).json()
    old = store.load(project['id'])
    renamed = copy.deepcopy(old)
    renamed['groups'][0]['label'] = 'A different label'
    current = store.save(renamed, old, 'Rename')
    assert not client.get(base + '/fits').json()['fits'][0]['stale']
    current['groups'][0]['result']['arrays']['chi'][10] += 0.01
    store.storage.write_json(project['id'], 'project.json', current)
    assert client.get(base + '/fits').json()['fits'][0]['stale']
    assert client.get(base + '/fits/missing').status_code == 400


def test_concurrent_same_key_commits_only_once(workspace, model, monkeypatch):
    store, client, project, gid = workspace
    base = f"/api/artemis/projects/{project['id']}/groups/{gid}/fits"
    original, barrier = persistence.fit_group, Barrier(2)
    def simultaneous(group, request):
        result = original(group, request)
        barrier.wait(timeout=30)
        return result
    monkeypatch.setattr(persistence, 'fit_group', simultaneous)
    body = dict(model, version=project['version'])
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(client.post, base, json=body, headers={'Idempotency-Key': 'concurrent'}) for _ in range(2)]
        responses = [f.result(timeout=40) for f in futures]
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()['fit_id'] for r in responses}) == 1
    assert client.get(base).json()['count'] == 1


def test_missing_receipt_file_recovers_from_archive(workspace, model, monkeypatch):
    store, client, project, gid = workspace
    original = store.storage.__class__.write_json
    def failing_receipt(self, ident, filename, value):
        if filename.startswith('artemis-fit-'):
            raise OSError('simulated interrupted receipt')
        return original(self, ident, filename, value)
    monkeypatch.setattr(store.storage.__class__, 'write_json', failing_receipt)
    url = f"/api/artemis/projects/{project['id']}/groups/{gid}/fits"
    body = dict(model, version=project['version'])
    first = client.post(url, json=body, headers={'Idempotency-Key': 'receipt'}).json()
    monkeypatch.setattr(persistence, 'fit_group', lambda *_: pytest.fail('retry reran fit'))
    second = client.post(url, json=body, headers={'Idempotency-Key': 'receipt'}).json()
    assert second['idempotent_replay'] and second['fit_id'] == first['fit_id']


def test_model_fingerprint_ignores_presentation_ids(model):
    original = draft(model)
    changed = copy.deepcopy(original)
    changed['revision'] = 7
    changed['paths'][0].update(id='renamed', label='Display label', filename='renamed.dat')
    changed['parameters'][0]['id'] = 'new-row'
    assert persistence.model_fingerprint(changed) == persistence.model_fingerprint(original)


def test_malformed_feff_provenance_cannot_enter_an_archive(workspace, model):
    store, client, project, gid = workspace
    url = f"/api/artemis/projects/{project['id']}/groups/{gid}/fits"
    saved = client.post(url, json=dict(model, version=project['version'])).json()
    full = client.get(url + '/' + saved['fit_id'] + '?view=full').json()['fit']['result']
    full['metadata']['feff_sources'] = {'cu1': {}}
    with pytest.raises(ValueError):
        persistence.validate_result(full)


def test_disabled_path_diagnostics_do_not_claim_to_contribute(workspace, model):
    store, client, project, gid = workspace
    jid, _ = named_job(store, model)
    body = dict(model, version=project['version'], paths=[*model['paths'],
        dict(id='disabled', enabled=False, feff_job=jid, feff_path='feff0001')])
    base = f"/api/artemis/projects/{project['id']}/groups/{gid}"
    direct = client.post(base + '/fit?view=summary', json=body).json()
    saved = client.post(base + '/fits', json=body).json()['fit']['result']
    assert direct['warnings'] == saved['warnings']
    assert 'feff_jobs' not in direct and 'feff_jobs' not in saved


@pytest.mark.parametrize('field,value', [('seconds', {'total': list(range(500))}),
    ('engine', ['larch.feffit']), ('input_sha256', 'unverified'), ('model_sha256', [1] * 64)])
def test_saved_summary_metadata_cannot_smuggle_arrays(workspace, model, field, value):
    store, client, project, gid = workspace
    url = f"/api/artemis/projects/{project['id']}/groups/{gid}/fits"
    saved = client.post(url, json=dict(model, version=project['version'])).json()
    full = client.get(url + '/' + saved['fit_id'] + '?view=full').json()['fit']['result']
    full['metadata'][field] = value
    with pytest.raises(ValueError):
        persistence.validate_result(full)
