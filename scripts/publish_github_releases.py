"""Publica entregas locales en GitHub Releases, sin incorporar credenciales al editor.

Ejecutar después de empaquetar. GITHUB_TOKEN necesita permiso Contents: write
en jfeagpt/PDFModder. Nunca sustituye ni borra assets existentes.
"""
import argparse
from getpass import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfmodder import __version__

REPOSITORY = 'jfeagpt/PDFModder'
API = 'https://api.github.com/repos/' + REPOSITORY


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def release_files(folder):
    version = folder.name.removeprefix('v')
    names = [f'PDFModder-v{version}-Instalar.exe',
             f'PDFModder-v{version}-Windows-x64.zip',
             f'PDFModder-v{version}-codigo.zip']
    installer = folder / names[0]
    if not installer.is_file():
        raise ValueError('Falta el instalador de ' + folder.name)
    manifest = folder / 'PDFModder-update.json'
    manifest.write_text(json.dumps({'schema': 1, 'version': version,
        'windows': {'filename': installer.name, 'size': installer.stat().st_size,
                    'sha256': sha256(installer)}}, indent=2), encoding='utf-8')
    files = [folder / name for name in names if (folder / name).is_file()]
    return files + [manifest] + [p.with_suffix(p.suffix+'.sha256') for p in files
                                 if p.with_suffix(p.suffix+'.sha256').is_file()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='Publicar todas las entregas con instalador')
    parser.add_argument('--version', default=__version__)
    parser.add_argument('--prepare-only', action='store_true', help='Preparar manifiestos sin red ni credenciales')
    args = parser.parse_args()
    folders = sorted((ROOT/'releases').glob('v*')) if args.all else [ROOT/'releases'/('v'+args.version)]
    folders = [p for p in folders if p.is_dir() and
               (p/('PDFModder-'+p.name+'-Instalar.exe')).is_file()]
    if not folders:
        raise ValueError('No hay una entrega empaquetada con instalador.')
    prepared = [(folder, release_files(folder)) for folder in folders]
    newest = max((p.name for p in folders),key=lambda tag:tuple(int(n) for n in tag[1:].split('.')))
    if args.prepare_only:
        print(json.dumps([{'version':p.name,'assets':[f.name for f in fs]} for p,fs in prepared], indent=2))
        return
    token = os.environ.get('GITHUB_TOKEN') or getpass('Token GitHub (no se guarda): ')
    if not token:
        raise ValueError('No se ha aportado una credencial.')
    session = requests.Session()
    session.headers.update({'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                            'X-GitHub-Api-Version':'2026-03-10','User-Agent':'PDFModder-release-publisher'})
    repo = session.get(API, timeout=30)
    repo.raise_for_status()
    if repo.json().get('private'):
        raise ValueError('El repositorio es privado. Este canal requiere un repositorio público; no se cambia su visibilidad automáticamente.')
    for folder, files in prepared:
        tag = folder.name
        response = session.get(API+'/releases/tags/'+quote(tag,safe=''), timeout=30)
        if response.status_code == 404:
            response = session.post(API+'/releases', json={'tag_name':tag,'name':'PDF Modder '+tag[1:],
                'body':'Instalador Windows x64, versión portable y código fuente. Consulte README y los avisos incluidos.',
                'target_commitish':os.environ.get('GITHUB_SHA', 'main'),
                'draft':False,'prerelease':False,'make_latest':'true' if tag==newest else 'false'}, timeout=30)
        response.raise_for_status()
        release = response.json()
        existing = {a['name']:a for a in release.get('assets',[])}
        upload = release['upload_url'].split('{',1)[0]
        if not upload.startswith('https://uploads.github.com/repos/'+REPOSITORY+'/releases/'):
            raise ValueError('Destino de subida inesperado.')
        for path in files:
            if path.name in existing:
                entry = existing[path.name]
                if entry.get('size') != path.stat().st_size or entry.get('digest') != 'sha256:'+sha256(path):
                    raise ValueError('Asset existente distinto o sin huella verificable: '+path.name+'. No se reemplaza.')
                continue
            with path.open('rb') as stream:
                result = session.post(upload, params={'name':path.name}, data=stream,
                                      headers={'Content-Type':'application/octet-stream'}, timeout=(30,600))
            result.raise_for_status()
            asset = result.json()
            if asset.get('size') != path.stat().st_size or asset.get('digest') != 'sha256:'+sha256(path):
                raise ValueError('La subida no coincide con el archivo local: '+path.name)
        print(release['html_url'])
    session.close()


if __name__ == '__main__':
    main()
