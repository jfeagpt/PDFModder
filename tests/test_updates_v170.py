"""Focused trust-boundary checks; all network responses are simulated."""
import hashlib
import io
import threading
import urllib.error

import pytest

from pdfmodder import updates_v170 as updates


def publication(payload=b'MZ synthetic installer', version='1.7.1'):
    filename = f'PDFModder-v{version}-Instalar.exe'
    digest = hashlib.sha256(payload).hexdigest()
    url = f'https://github.com/jfeagpt/PDFModder/releases/download/v{version}/'
    release = {'tag_name': 'v' + version, 'draft': False, 'prerelease': False, 'assets': [
        {'name': updates.MANIFEST_NAME, 'state': 'uploaded', 'size': 240,
         'browser_download_url': url + updates.MANIFEST_NAME},
        {'name': filename, 'state': 'uploaded', 'size': len(payload),
         'digest': 'sha256:' + digest, 'browser_download_url': url + filename}]}
    manifest = {'schema': 1, 'version': version,
                'windows': {'filename': filename, 'sha256': digest, 'size': len(payload)}}
    return manifest, release


def test_manifest_requires_exact_stable_version_repo_size_and_hash():
    assert updates.REPOSITORY == 'jfeagpt/PDFModder'
    assert updates.LATEST_URL == 'https://api.github.com/repos/jfeagpt/PDFModder/releases/latest'
    assert updates.RELEASES_URL == 'https://github.com/jfeagpt/PDFModder/releases'
    manifest, release = publication()
    result = updates.validate_manifest(manifest, release)
    assert result['version'] == '1.7.1'
    for value in ('v1.7.1', '01.7.1', '1.7', '1.7.1-beta', '1.7.1\n'):
        with pytest.raises(ValueError):
            updates.version_tuple(value)
    manifest['windows']['size'] += 1
    with pytest.raises(ValueError, match='tamaño'):
        updates.validate_manifest(manifest, release)
    manifest, release = publication()
    release['assets'][1]['browser_download_url'] = 'https://github.com/another/repo/malware.exe'
    with pytest.raises(ValueError, match='dirección'):
        updates.validate_manifest(manifest, release)
    manifest, release = publication()
    release['assets'][1]['browser_download_url'] = release['assets'][1]['browser_download_url'].replace(
        '/jfeagpt/PDFModder/', '/satagrolevante/PDFModder/')
    with pytest.raises(ValueError, match='dirección'):
        updates.validate_manifest(manifest, release)
    manifest, release = publication()
    manifest['windows']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='comprobación'):
        updates.validate_manifest(manifest, release)


def test_redirects_only_accept_https_github_asset_hosts():
    for value in ('http://github.com/a', 'https://github.com.evil.example/a',
                  'https://user:password@github.com/a', 'https://127.0.0.1/a',
                  'https://objects.githubusercontent.com:444/a', 'file:///C:/Windows/a'):
        with pytest.raises(ValueError):
            updates._safe_https(value)
    assert updates._safe_https('https://release-assets.githubusercontent.com/a?signature=test')


def test_404_reports_unavailable_without_claiming_current(monkeypatch, tmp_path, qtbot):
    def missing(*args, **kwargs):
        raise urllib.error.HTTPError(updates.LATEST_URL, 404, 'Not Found', {}, None)
    monkeypatch.setattr(updates, '_bounded_json', missing)
    updater = updates.AppUpdater('1.7.0', tmp_path)
    assert updater.status()['state'] == 'idle'
    updater.check()
    qtbot.waitUntil(lambda: not updater.status()['busy'], timeout=2000)
    status = updater.status()
    assert status['state'] == 'unavailable' and not status['latestVersion']
    assert 'No hay una versión pública' in status['message']


def test_download_checks_sha256_and_removes_failed_partial(monkeypatch, tmp_path, qtbot):
    payload = b'MZ synthetic installer'
    manifest, release = publication(payload)
    selected = updates.validate_manifest(manifest, release)
    monkeypatch.setattr(updates, 'read_release', lambda *_: selected)
    monkeypatch.setattr(updates, 'open_public', lambda *_: io.BytesIO(b'X' * len(payload)))
    updater = updates.AppUpdater('1.7.0', tmp_path)
    updater.download()
    qtbot.waitUntil(lambda: not updater.status()['busy'], timeout=2000)
    assert updater.status()['state'] == 'error'
    assert 'SHA-256' in updater.status()['message']
    assert not list(tmp_path.glob('*.part')) and not list(tmp_path.glob('*.exe'))
    monkeypatch.setattr(updates, 'open_public', lambda *_: io.BytesIO(payload))
    updater.download()
    qtbot.waitUntil(lambda: not updater.status()['busy'], timeout=2000)
    assert updater.status()['state'] == 'ready'
    updates.verify_file(tmp_path / selected['filename'], selected)
    (tmp_path / selected['filename']).write_bytes(b'X' * len(payload))
    with pytest.raises(ValueError, match='SHA-256'):
        updates.verify_file(tmp_path / selected['filename'], selected)


def test_metadata_size_limit_and_cancel(monkeypatch):
    monkeypatch.setattr(updates, 'open_public', lambda *args, **kwargs: io.BytesIO(b'x' * 1024))
    with pytest.raises(ValueError, match='tamaño'):
        updates._bounded_json(updates.LATEST_URL, 100, threading.Event(), api=True)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        updates._bounded_json(updates.LATEST_URL, 2048, cancelled, api=True)
