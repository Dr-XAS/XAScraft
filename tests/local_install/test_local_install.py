from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
import io
import json
import os
import socket
import shutil
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from xascraft_local import common, install, manager, services, source


def distribution(path):
    for directory in source.SOURCE_DIRS:
        (path / directory).mkdir(parents=True)
    (path / "larch/version.py").write_text("__release_version__ = '2026.3.1'\n")
    (path / "backend/xraylarch_web/app.py").write_text("print('application')\n")
    (path / "frontend/package.json").write_text('{}')
    (path / "installers/local/run.py").write_text('pass')
    (path / "examples/reference.dat").write_text('real distribution fixture')
    return path


def installed(root):
    common.prepare_root(root)
    release = root / "releases" / ('a' * 32)
    release.mkdir()
    common.write_json(release / "release.json", {"ready": True, "label": "local-test"})
    common.write_json(root / "current.json", {"release": release.name, "ports": {
        "frontend": common.available_port(0), "backend": common.available_port(0)}})
    return release


def test_snapshot_separates_user_data_secrets_and_generated_dependencies(tmp_path):
    original = distribution(tmp_path / "original")
    for name in ('frontend/.env.local', 'frontend/node_modules/secret.js',
                 'backend/data/project.json', 'frontend/.next/server.js', 'larch/__pycache__/x.pyc'):
        file = original / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('private')
    destination = tmp_path / "snapshot"
    metadata = source.snapshot(original, destination)
    assert (destination / 'examples/reference.dat').exists()
    assert not list(destination.rglob('.env*'))
    assert not (destination / 'backend/data').exists()
    assert not (destination / 'frontend/node_modules').exists()
    assert not (destination / 'frontend/.next').exists()
    assert metadata['label'].startswith('local-')
    (original / 'backend/xraylarch_web/app.py').write_text('changed')
    second = source.snapshot(original, tmp_path / 'second')
    assert metadata['content_sha256'] != second['content_sha256']


def test_source_package_roundtrip_and_tamper_detection(tmp_path):
    original = distribution(tmp_path / 'source')
    archive = tmp_path / 'xascraft-source.zip'
    source.package_source(original, archive, 'xascraft-v0.1.0')
    unpacked = tmp_path / 'unpacked'
    source.extract_zip(archive, unpacked)
    metadata = source.snapshot(unpacked, tmp_path / 'roundtrip')
    assert metadata['label'] == 'xascraft-v0.1.0'
    (unpacked / 'frontend/package.json').write_text('{"changed":true}')
    with pytest.raises(RuntimeError, match='manifest'):
        source.snapshot(unpacked, tmp_path / 'bad')


def test_archive_inside_an_unrelated_git_tree_keeps_examples(tmp_path):
    if not shutil.which('git'):
        pytest.skip('Git is not installed')
    subprocess.run(['git', 'init', str(tmp_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    original = distribution(tmp_path / 'extracted')
    metadata = source.snapshot(original, tmp_path / 'snapshot')
    assert (tmp_path / 'snapshot/examples/reference.dat').is_file()
    assert metadata['revision'] == ''


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/escape', 'x\\..\\escape', 'trailing./data'])
def test_distribution_rejects_traversal(tmp_path, name):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr(name, 'bad')
    with pytest.raises(RuntimeError, match='Unsafe'):
        source.extract_zip(archive, tmp_path / 'unpacked')
    assert not (tmp_path / 'escape').exists()


def test_distribution_rejects_links_and_size_limit(tmp_path):
    archive = tmp_path / 'bad.zip'
    entry = zipfile.ZipInfo('link')
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr(entry, '/outside')
    with pytest.raises(RuntimeError):
        source.extract_zip(archive, tmp_path / 'unpacked')
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr('large', '0123456789')
    with pytest.raises(RuntimeError):
        source.extract_zip(archive, tmp_path / 'unpacked', max_bytes=5)


def test_source_symlink_cannot_copy_external_secret(tmp_path):
    original = distribution(tmp_path / 'source')
    secret = tmp_path / 'secret'
    secret.write_text('private')
    try:
        (original / 'frontend/leak').symlink_to(secret)
    except OSError:
        pytest.skip('Host does not allow symlink creation')
    with pytest.raises(RuntimeError, match='symlink'):
        source.snapshot(original, tmp_path / 'snapshot')


def test_release_channel_ignores_upstream_prerelease_and_unverified_assets(monkeypatch):
    def release(tag, **overrides):
        return {'tag_name': tag, 'assets': [{'name': 'xascraft-source.zip', 'digest': 'sha256:' + 'a' * 64,
            'browser_download_url': f'https://github.com/Dr-XAS/XAScraft/releases/download/{tag}/xascraft-source.zip'}], **overrides}
    records = [release('2026.3.1'), release('xascraft-v9.0.0', prerelease=True),
               release('xascraft-v7.0.0', draft=True), release('xascraft-v0.9.0'), release('xascraft-v0.10.0')]
    wrong = release('xascraft-v8.0.0')
    wrong['assets'][0]['browser_download_url'] = 'https://github.com/xraypy/xraylarch/asset.zip'
    records.append(wrong)
    monkeypatch.setattr(source, 'get_url', lambda _: io.StringIO(json.dumps(records)))
    assert source.latest_release()['tag'] == 'xascraft-v0.10.0'


def test_update_never_offers_same_version_or_downgrade():
    assert source.newer_release('xascraft-v0.9.0', 'xascraft-v0.10.0')
    assert source.newer_release('local-1234', 'xascraft-v0.1.0')
    assert not source.newer_release('xascraft-v1.2.0', 'xascraft-v1.2.0')
    assert not source.newer_release('xascraft-v1.2.0', 'xascraft-v1.1.0')
    assert not source.newer_release('local-1234', '2026.3.1')


def test_runtime_does_not_inherit_hosted_integration_or_source_paths(tmp_path, monkeypatch):
    for key in ('XRAYLARCH_INTEGRATION_API_ENABLED', 'XRAYLARCH_INTEGRATION_HMAC_SECRET',
                'PYTHONPATH', 'NEXT_PUBLIC_APP_BASE_PATH', 'BACKEND_URL'):
        monkeypatch.setenv(key, 'must-not-leak')
    env = common.runtime_env(tmp_path, tmp_path / 'source', {'created_at': 'today', 'content_sha256': '123456789'})
    assert 'XRAYLARCH_INTEGRATION_HMAC_SECRET' not in env
    assert 'XRAYLARCH_INTEGRATION_API_ENABLED' not in env
    assert env['PYTHONPATH'] == str(tmp_path / 'source/backend')
    assert env['NEXT_PUBLIC_APP_BASE_PATH'] == ''
    assert 'BACKEND_URL' not in env


def test_activation_backs_up_data_and_preserves_address(tmp_path):
    previous = installed(tmp_path)
    project = tmp_path / 'data/project.json'
    project.write_text('{"user":"work"}')
    before = common.read_json(tmp_path / 'current.json')
    candidate = tmp_path / 'releases' / ('b' * 32)
    candidate.mkdir()
    common.write_json(candidate / 'release.json', {'ready': True})
    current = install.activate(tmp_path, candidate)
    assert current['previous_release'] == previous.name
    assert current['ports'] == before['ports']
    assert project.read_text() == '{"user":"work"}'
    assert (Path(current['backup']) / 'data/project.json').read_text() == project.read_text()
    assert previous.exists()


def test_failed_backup_never_switches_release(tmp_path, monkeypatch):
    previous = installed(tmp_path)
    candidate = tmp_path / 'releases' / ('b' * 32)
    candidate.mkdir()
    common.write_json(candidate / 'release.json', {'ready': True})
    monkeypatch.setattr(install.shutil, 'copytree', lambda *_: (_ for _ in ()).throw(OSError('Disk full')))
    with pytest.raises(OSError, match='Disk full'):
        install.activate(tmp_path, candidate)
    assert common.read_json(tmp_path / 'current.json')['release'] == previous.name


def test_failed_candidate_leaves_current_and_data_untouched(tmp_path, monkeypatch):
    root = tmp_path / 'installed'
    previous = installed(root)
    (root / 'data/project.json').write_text('keep')
    before = (root / 'current.json').read_bytes()
    original = distribution(tmp_path / 'source')
    monkeypatch.setattr(install, 'build_release', lambda *_: (_ for _ in ()).throw(RuntimeError('Failed validation')))
    with pytest.raises(RuntimeError, match='Failed validation'):
        install.install_source(root, original, Path('unused'), make_shortcuts=False)
    assert (root / 'current.json').read_bytes() == before
    assert (root / 'data/project.json').read_text() == 'keep'
    assert list((root / 'releases').iterdir()) == [previous]


def test_interrupt_after_activation_does_not_remove_current_release(tmp_path, monkeypatch):
    root = tmp_path / 'installed'
    installed(root)
    original = distribution(tmp_path / 'source')
    def fake_build(root, release, metadata, uv):
        common.write_json(release / 'release.json', {'ready': True, **metadata})
    real_activate = install.activate
    def activate_then_interrupt(root, release):
        real_activate(root, release)
        raise KeyboardInterrupt()
    monkeypatch.setattr(install, 'build_release', fake_build)
    monkeypatch.setattr(install, 'activate', activate_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        install.install_source(root, original, Path('unused'), make_shortcuts=False)
    current = common.read_json(root / 'current.json')
    assert (root / 'releases' / current['release'] / 'release.json').is_file()


def test_download_checksum_mismatch_removes_incomplete_distribution(tmp_path, monkeypatch):
    monkeypatch.setattr(source, 'get_url', lambda *a, **kw: io.BytesIO(b'wrong bytes'))
    target = tmp_path / 'source.zip'
    with pytest.raises(RuntimeError, match='checksum'):
        source.download('https://example.invalid/file', target, 'a' * 64)
    assert not target.exists()


def test_update_refuses_surviving_backend_after_manager_crash(tmp_path):
    installed(tmp_path)
    current = common.read_json(tmp_path / 'current.json')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', current['ports']['backend']))
        listener.listen()
        with pytest.raises(RuntimeError, match='in use'):
            install.install_source(tmp_path, Path('unused'), Path('unused'))


def test_update_refuses_partial_pair(tmp_path, monkeypatch):
    installed(tmp_path)
    monkeypatch.setattr(manager, 'manager_status', lambda _: {'running': False, 'active': True})
    with pytest.raises(RuntimeError, match='Stop XAScraft'):
        install.install_source(tmp_path, Path('unused'), Path('unused'))


def test_operation_lock_prevents_concurrent_install_or_start(tmp_path):
    lock = tmp_path / 'operation.lock'
    with common.exclusive_lock(lock):
        with pytest.raises(RuntimeError, match='already running'):
            with common.exclusive_lock(lock):
                pytest.fail('A second operation acquired the lock')
    with common.exclusive_lock(lock):
        pass


@contextmanager
def control_server(root):
    installed(root)
    control = manager.Manager(root)
    token = 'private-test-token'
    server = ThreadingHTTPServer(('127.0.0.1', 0), manager.handler_for(control, token))
    control.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield control, f'http://127.0.0.1:{server.server_port}', token
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_control_page_needs_capability_and_blocks_cross_origin_mutation(tmp_path):
    with control_server(tmp_path) as (control, base, token):
        with pytest.raises(urllib.error.HTTPError) as error:
            services.request_json(base + '/api/status')
        assert error.value.code == 403
        assert services.request_json(base + '/api/status', token=token)['label'] == 'local-test'
        req = urllib.request.Request(base + '/' + token + '/api/action', data=b'{"action":"quit"}',
                                     headers={'Origin': 'https://unrelated.example'})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        assert error.value.code == 403
        assert not control.busy
        req = urllib.request.Request(base + '/api/status', headers={'Host': 'unrelated.example', 'Authorization': 'Bearer ' + token})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(req)


def test_manager_page_and_logs_are_local_and_escape_user_values(tmp_path):
    with control_server(tmp_path) as (_, base, token):
        (tmp_path / 'logs/install.log').write_text('<script>untrusted</script>')
        page = urllib.request.urlopen(base + '/' + token + '/').read().decode()
        assert 'textContent' in page
        assert 'innerHTML' not in page
        logs = services.request_json(base + '/api/logs', token=token)
        assert logs['install.log'] == '<script>untrusted</script>'


def test_service_stop_owns_children_and_keeps_unrelated_process(tmp_path):
    common.prepare_root(tmp_path)
    pair = services.ServicePair(tmp_path, tmp_path, {'frontend': 1, 'backend': 2})
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        pair._spawn([sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path, os.environ.copy(), 'test')
        child = pair.children[0]
        assert pair.active()
        pair.stop()
        assert child.poll() is not None
        assert unrelated.poll() is None
    finally:
        pair.stop()
        unrelated.terminate()
        unrelated.wait(timeout=10)
