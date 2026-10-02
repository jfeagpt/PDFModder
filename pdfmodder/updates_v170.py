"""Manual public GitHub Releases updater with bounded downloads and SHA-256.

There is no startup request, login, telemetry, embedded credential or automatic
installation. Workers expose plain status snapshots and never call Qt widgets.
API contract: https://docs.github.com/en/rest/releases/releases#get-the-latest-release
Asset contract: https://docs.github.com/en/rest/releases/assets#get-a-release-asset
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = 'jfeagpt/PDFModder'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases'
LATEST_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MANIFEST_NAME = 'PDFModder-update.json'
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
TRUSTED_DOWNLOAD_HOSTS = frozenset({'github.com', 'release-assets.githubusercontent.com',
                                    'objects.githubusercontent.com'})


class NoPublicRelease(ValueError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9]\d{0,4})\.(?:0|[1-9]\d{0,4})\.(?:0|[1-9]\d{0,4})', value):
        raise ValueError('La versión publicada no tiene el formato numérico esperado.')
    return tuple(map(int, value.split('.')))


def _safe_https(url, *, api=False):
    if not isinstance(url, str) or len(url) > 8192 or any(ord(char) < 32 for char in url):
        raise ValueError('La dirección de actualización no es válida.')
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError('La dirección de actualización no es válida.') from error
    hosts = {'api.github.com'} if api else TRUSTED_DOWNLOAD_HOSTS
    if (parts.scheme != 'https' or parts.hostname not in hosts or port not in (None, 443)
            or parts.username is not None or parts.password is not None or parts.fragment):
        raise ValueError('La descarga no pertenece a un servidor HTTPS autorizado de GitHub.')
    return url


class TrustedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 4
    max_repeats = 2

    def redirect_request(self, request, fp, code, message, headers, newurl):
        _safe_https(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def open_public(url, *, api=False):
    _safe_https(url, api=api)
    if api and url != LATEST_URL:
        raise ValueError('La consulta de versión no pertenece al repositorio de PDF Modder.')
    if not api and urllib.parse.urlsplit(url).hostname == 'github.com':
        if not urllib.parse.urlsplit(url).path.startswith(f'/{REPOSITORY}/releases/download/'):
            raise ValueError('El archivo no pertenece al repositorio de PDF Modder.')
    request = urllib.request.Request(url, headers={
        'User-Agent': 'PDFModder-ManualUpdater/1', 'Cache-Control': 'no-cache',
        'Accept': 'application/vnd.github+json' if api else 'application/octet-stream',
        'X-GitHub-Api-Version': '2026-03-10',
    })
    response = urllib.request.build_opener(TrustedRedirects()).open(request, timeout=15)
    try:
        final_url = response.geturl()
        _safe_https(final_url, api=api)
        if api and final_url != LATEST_URL:
            raise ValueError('GitHub ha redirigido la consulta a un destino no autorizado.')
    except Exception:
        response.close()
        raise
    return response


def _bounded_json(url, limit, cancel, *, api=False):
    raw = bytearray()
    started = time.monotonic()
    with open_public(url, api=api) as response:
        reader = getattr(response, 'read1', response.read)
        while True:
            if cancel.is_set():
                raise InterruptedError('Comprobación cancelada.')
            chunk = reader(8192)
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > limit or time.monotonic()-started > 45:
                raise ValueError('La información publicada supera el tamaño o tiempo permitido.')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError('GitHub ha devuelto información de actualización no válida.') from error


def _release_version(release):
    if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
        raise ValueError('La publicación no es una versión estable de PDF Modder.')
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('La etiqueta de la versión publicada no es válida.')
    version_tuple(tag[1:])
    return tag[1:]


def _asset(release, filename, version):
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise ValueError('La publicación no contiene una lista de archivos válida.')
    matches = [item for item in assets if isinstance(item, dict) and item.get('name') == filename]
    if len(matches) != 1 or matches[0].get('state') != 'uploaded':
        raise NoPublicRelease('Esta publicación todavía no tiene un instalador compatible con actualización segura.')
    item = matches[0]
    expected = f'https://github.com/{REPOSITORY}/releases/download/v{version}/{filename}'
    if item.get('browser_download_url') != expected:
        raise ValueError('La dirección del archivo no corresponde a esta publicación de PDF Modder.')
    return item


def validate_manifest(manifest, release):
    version = _release_version(release)
    if (not isinstance(manifest, dict) or type(manifest.get('schema')) is not int
            or manifest['schema'] != 1 or manifest.get('version') != version):
        raise ValueError('El manifiesto no coincide con la versión publicada.')
    item = manifest.get('windows')
    filename = f'PDFModder-v{version}-Instalar.exe'
    if not isinstance(item, dict) or item.get('filename') != filename:
        raise ValueError('El manifiesto no contiene el instalador de Windows esperado.')
    digest = item.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-fA-F]{64}', digest):
        raise ValueError('Falta una comprobación SHA-256 válida del instalador.')
    size = item.get('size')
    if type(size) is not int or not 0 < size <= MAX_PACKAGE_BYTES:
        raise ValueError('El tamaño del instalador excede el límite permitido.')
    asset = _asset(release, filename, version)
    if type(asset.get('size')) is not int or asset['size'] != size:
        raise ValueError('El tamaño publicado en GitHub no coincide con el manifiesto.')
    asset_digest = asset.get('digest')
    if asset_digest is not None and asset_digest != 'sha256:' + digest.lower():
        raise ValueError('La comprobación de GitHub no coincide con el manifiesto.')
    return {'version': version, 'filename': filename, 'url': asset['browser_download_url'],
            'sha256': digest.lower(), 'size': size}


def read_release(cancel=None):
    cancel = cancel or threading.Event()
    try:
        release = _bounded_json(LATEST_URL, MAX_METADATA_BYTES, cancel, api=True)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise NoPublicRelease('No hay una versión pública disponible. El repositorio puede ser privado o aún no tiene releases.') from error
        if error.code in (403, 429):
            raise ValueError('GitHub ha limitado temporalmente las consultas. Inténtalo más tarde.') from error
        raise
    version = _release_version(release)
    asset = _asset(release, MANIFEST_NAME, version)
    if type(asset.get('size')) is not int or not 0 < asset['size'] <= MAX_MANIFEST_BYTES:
        raise ValueError('El manifiesto de actualización supera el tamaño permitido.')
    manifest = _bounded_json(asset['browser_download_url'], MAX_MANIFEST_BYTES, cancel)
    return validate_manifest(manifest, release)


def _link(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def verify_file(path, release):
    path = Path(path)
    if _link(path) or not path.is_file() or path.stat().st_size != release['size']:
        raise ValueError('El instalador está incompleto. Descárgalo de nuevo.')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != release['sha256']:
        raise ValueError('La comprobación SHA-256 ha fallado. El instalador no se ejecutará.')


class AppUpdater:
    def __init__(self, installed_version, directory):
        version_tuple(installed_version)
        self.directory = Path(directory)
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._busy = False
        self._release = None
        self._ready_path = None
        self._status = {'state': 'idle', 'installedVersion': installed_version,
                        'latestVersion': '', 'progress': 0,
                        'message': 'Busca nuevas versiones públicas cuando quieras.'}

    def status(self):
        with self._lock:
            return dict(self._status, busy=self._busy)

    def _set(self, **values):
        with self._lock:
            self._status.update(values)

    def cancel(self):
        self._cancel.set()

    def _start(self, state, message, operation):
        with self._lock:
            if self._busy or self._cancel.is_set():
                return False
            self._busy = True
            self._status.update(state=state, progress=0, message=message)

        def run():
            try:
                operation()
            except InterruptedError:
                self._set(state='cancelled', message='Operación cancelada.')
            except NoPublicRelease as error:
                self._set(state='unavailable', message=str(error))
            except Exception as error:
                message = str(error) if isinstance(error, ValueError) else 'No se pudo conectar o descargar. Comprueba Internet y vuelve a intentarlo.'
                self._set(state='error', message=message[:300])
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=run, name='pdfmodder-updater', daemon=True).start()
        return True

    def check(self):
        def operation():
            self._release = None
            self._ready_path = None
            release = read_release(self._cancel)
            self._release = release
            latest,installed=version_tuple(release['version']),version_tuple(self._status['installedVersion'])
            newer = latest > installed
            message=('Hay una nueva versión disponible.' if newer else
                     'Tu versión es posterior a la última publicada.' if installed>latest else
                     'Tienes la versión más reciente publicada.')
            self._set(state='available' if newer else 'current', latestVersion=release['version'],
                      message=message)
        return self._start('checking', 'Comprobando las versiones públicas de PDF Modder…', operation)

    def download(self):
        def operation():
            self._ready_path = None
            release = read_release(self._cancel)  # Revalidate instead of trusting an old check.
            if version_tuple(release['version']) <= version_tuple(self._status['installedVersion']):
                self._set(state='current', latestVersion=release['version'], message='No hay una versión posterior disponible.')
                return
            self._release = release
            self.directory.mkdir(parents=True, exist_ok=True)
            if any(_link(parent) for parent in (self.directory, *self.directory.parents)):
                raise ValueError('La carpeta local de actualización no es segura.')
            destination = self.directory / release['filename']
            if _link(destination):
                raise ValueError('La ruta local del instalador no es segura.')
            handle, name = tempfile.mkstemp(prefix='PDFModder-', suffix='.part', dir=self.directory)
            temporary = Path(name)
            count, started = 0, time.monotonic()
            self._set(state='downloading', latestVersion=release['version'], message='Descargando y comprobando el instalador…')
            try:
                with os.fdopen(handle, 'wb') as output, open_public(release['url']) as response:
                    reader = getattr(response, 'read1', response.read)
                    while True:
                        if self._cancel.is_set():
                            raise InterruptedError('Descarga cancelada.')
                        chunk = reader(65536)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > release['size'] or time.monotonic()-started > 600:
                            raise ValueError('La descarga supera el tamaño o tiempo permitido.')
                        output.write(chunk)
                        self._set(progress=min(99, count*100//release['size']))
                verify_file(temporary, release)
                if self._cancel.is_set():
                    raise InterruptedError('Descarga cancelada.')
                temporary.replace(destination)
            finally:
                if temporary.is_file() and not _link(temporary):
                    temporary.unlink()
            self._ready_path = destination
            self._set(state='ready', progress=100, message='Instalador comprobado. Puedes iniciar la instalación.')
        return self._start('checking', 'Volviendo a comprobar la publicación antes de descargar…', operation)

    def install(self):
        """Called only after the desktop confirmation and unsaved-work check."""
        with self._lock:
            if self._busy or self._status['state'] != 'ready' or self._ready_path is None:
                return False
            path, release = self._ready_path, dict(self._release)

        def operation():
            if os.name != 'nt':
                raise ValueError('La instalación está disponible en Windows.')
            verify_file(path, release)
            if self._cancel.is_set():
                raise InterruptedError('Instalación cancelada.')
            subprocess.Popen([str(path)], shell=False, cwd=str(path.parent))
            self._set(state='installing', message='El instalador está abierto. Continúa los pasos de instalación.')
        return self._start('verifying', 'Comprobando de nuevo el instalador antes de ejecutarlo…', operation)
