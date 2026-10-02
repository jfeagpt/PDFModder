"""Public asset channel, bounded caching and server-directed backoff; no network."""
import copy
import email.utils
import hashlib
import io
import urllib.error

import pytest

from pdfmodder import updates_v170 as updates


def manifest(payload=b'MZ updater fixture'):
    return {'schema': 1, 'version': '1.8.1', 'windows': {
        'filename': 'PDFModder-v1.8.1-Instalar.exe', 'size': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest()}}


def http_error(url, code, headers=None):
    return urllib.error.HTTPError(url, code, 'fixture', headers or {}, None)


def finished(updater, qtbot):
    qtbot.waitUntil(lambda: not updater.status()['busy'], timeout=2000)
    return updater.status()


def test_public_manifest_download_does_not_consult_rest_api(monkeypatch):
    calls = []

    def document(url, *args, **kwargs):
        calls.append((url, kwargs))
        return manifest()

    monkeypatch.setattr(updates, '_bounded_json', document)
    selected = updates.read_release()
    assert calls == [(updates.LATEST_MANIFEST_URL, {})]
    assert selected['url'] == 'https://github.com/jfeagpt/PDFModder/releases/download/v1.8.1/PDFModder-v1.8.1-Instalar.exe'
    assert selected['size'] == manifest()['windows']['size']


@pytest.mark.parametrize('change', [
    lambda item: item.update(schema=True),
    lambda item: item.update(version='1.8.1-beta'),
    lambda item: item.update(repository='another/repo'),
    lambda item: item['windows'].update(filename='../PDFModder-v1.8.1-Instalar.exe'),
    lambda item: item['windows'].update(sha256='broken'),
    lambda item: item['windows'].update(size=True),
    lambda item: item['windows'].update(size=updates.MAX_PACKAGE_BYTES + 1),
    lambda item: item['windows'].update(url='https://github.com/another/repo/installer.exe'),
])
def test_invalid_public_metadata_cannot_fall_back_to_another_endpoint(monkeypatch, change):
    value = manifest()
    change(value)
    calls = []
    monkeypatch.setattr(updates, '_bounded_json', lambda url, *args, **kwargs: calls.append(url) or value)
    with pytest.raises(ValueError):
        updates.read_release()
    assert calls == [updates.LATEST_MANIFEST_URL]


@pytest.mark.parametrize('code', [403, 429])
def test_asset_rate_limit_honors_retry_after_without_api_or_automatic_retry(monkeypatch, code):
    calls = []
    monkeypatch.setattr(updates.time, 'time', lambda: 1000)

    def limited(url, *args, **kwargs):
        calls.append(url)
        raise http_error(url, code, {'Retry-After': '120'})

    monkeypatch.setattr(updates, '_bounded_json', limited)
    with pytest.raises(updates.RateLimited) as caught:
        updates.read_release()
    assert caught.value.retry_at == 1121
    assert calls == [updates.LATEST_MANIFEST_URL]


def test_legacy_fallback_only_on_404_and_respects_rest_reset(monkeypatch):
    calls = []
    monkeypatch.setattr(updates.time, 'time', lambda: 1000)

    def legacy(url, *args, **kwargs):
        calls.append((url, kwargs))
        if url == updates.LATEST_MANIFEST_URL:
            raise http_error(url, 404)
        raise http_error(url, 403, {'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '4600'})

    monkeypatch.setattr(updates, '_bounded_json', legacy)
    with pytest.raises(updates.RateLimited) as caught:
        updates.read_release()
    assert caught.value.retry_at == 4601
    assert calls == [(updates.LATEST_MANIFEST_URL, {}), (updates.LATEST_URL, {'api': True})]


def test_retry_after_http_date_and_primary_reset_choose_later_deadline(monkeypatch):
    monkeypatch.setattr(updates.time, 'time', lambda: 1000)
    limited = updates._rate_limit(http_error(updates.LATEST_MANIFEST_URL, 429, {
        'Retry-After': email.utils.formatdate(1200, usegmt=True),
        'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1300'}))
    assert limited.retry_at == 1301


def test_updater_cooldown_persists_across_manual_clicks(monkeypatch, tmp_path, qtbot):
    calls = []
    clock = [1000]
    monkeypatch.setattr(updates.time, 'time', lambda: clock[0])

    def limited(*args):
        calls.append(True)
        raise updates.RateLimited(1200)

    monkeypatch.setattr(updates, 'read_release', limited)
    updater = updates.AppUpdater('1.8.0', tmp_path)
    assert updater.check()
    status = finished(updater, qtbot)
    assert status['state'] == 'rate_limited' and status['retryAt'] == 1200
    assert 'a las' in status['message']
    assert not updater.check() and not updater.download() and len(calls) == 1
    clock[0] = 1201
    monkeypatch.setattr(updates, 'read_release', lambda *_: updates.validate_public_manifest(manifest()))
    assert updater.check()
    status = finished(updater, qtbot)
    assert status['state'] == 'available' and status['retryAt'] == 0


def test_check_check_download_reuses_verified_metadata_then_expires(monkeypatch, tmp_path, qtbot):
    payload = b'MZ updater fixture'
    selected = updates.validate_public_manifest(manifest(payload))
    calls, downloads = [], []
    clock = [1000]
    monkeypatch.setattr(updates.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(updates, 'read_release', lambda *_: calls.append(True) or copy.copy(selected))
    monkeypatch.setattr(updates, 'open_public', lambda url: downloads.append(url) or io.BytesIO(payload))
    updater = updates.AppUpdater('1.8.0', tmp_path)
    for _ in range(2):
        assert updater.check()
        assert finished(updater, qtbot)['state'] == 'available'
    assert updater.download()
    assert finished(updater, qtbot)['state'] == 'ready'
    assert len(calls) == 1 and downloads == [selected['url']]
    updates.verify_file(tmp_path / selected['filename'], selected)
    clock[0] += updates.METADATA_CACHE_SECONDS + 1
    assert updater.check()
    assert finished(updater, qtbot)['state'] == 'available'
    assert len(calls) == 2


def test_redirect_cannot_leave_repository_even_on_github_host():
    request = updates.urllib.request.Request(updates.LATEST_MANIFEST_URL)
    with pytest.raises(ValueError, match='otro repositorio'):
        updates.TrustedRedirects().redirect_request(request, None, 302, 'fixture', {},
            'https://github.com/another/repo/releases/download/v1.8.1/PDFModder-update.json')
