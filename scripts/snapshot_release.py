"""Archiva una entrega comprobada sin sobrescribir versiones ya guardadas."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pdfmodder import __version__


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    label='v'+(__version__ if __version__.split('.')[-1]!='0' else '.'.join(__version__.split('.')[:2]))
    archive=ROOT/'dist/PDFModder-Windows-x64.zip'
    metadata=json.loads((ROOT/'dist/PDFModder/ENTREGA.json').read_text(encoding='utf-8'))
    assert metadata['application']==f'PDF Modder {__version__}'
    assert metadata['frozen_verified'] and metadata['delivery_status']=='verified'
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
        assert len(check.namelist())==len({name.casefold() for name in check.namelist()})
        assert hashlib.sha256(check.read('PDFModder/PDFModder.exe')).hexdigest()==metadata['exe_sha256']
        assert json.loads(check.read('PDFModder/ENTREGA.json'))==metadata
    staged=ROOT/'build/delivery/source/PDFModder'
    manifest=json.loads((staged.parent/'MANIFEST.json').read_text(encoding='utf-8'))
    assert len(manifest)==len({entry['path'].casefold() for entry in manifest})
    for entry in manifest:
        path=staged/entry['path']
        assert path.resolve().is_relative_to(staged.resolve())
        assert digest(path)==entry['sha256']
    destination=ROOT/'releases'/label
    destination.mkdir(parents=True,exist_ok=False)
    binary=destination/f'PDFModder-{label}-Windows-x64.zip'
    shutil.copy2(archive,binary)
    source=destination/f'PDFModder-{label}-codigo.zip'
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as output:
        for entry in manifest:
            path=staged/entry['path']
            assert path.resolve().is_relative_to(staged.resolve())
            assert digest(path)==entry['sha256']
            output.write(path,'PDFModder/'+entry['path'])
    for path in (binary,source):
        with zipfile.ZipFile(path) as check:assert check.testzip() is None
        path.with_suffix(path.suffix+'.sha256').write_text(f'{digest(path)}  {path.name}\n',encoding='ascii')
    result={**metadata,'archive_sha256':digest(binary),'source_sha256':digest(source),
            'version_label':label,'source_files':len(manifest)}
    (destination/'VERSION.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'saved':str(destination),**result},indent=2))


if __name__=='__main__':main()
