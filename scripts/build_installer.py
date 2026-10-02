"""Instalador offline .NET Framework para el ZIP ya verificado de Windows.

No recompila ni altera el motor. Incluye el ZIP completo y una tabla SHA-256
de cada archivo; el instalador los verifica antes de publicar la carpeta.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,zipfile,sys,re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pdfmodder import __version__

INSTALLER_REVISION = 1


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def check_names(names):
    if len(names)!=len({name.casefold() for name in names}):
        raise RuntimeError('Hay rutas repetidas en el paquete, ignorando mayúsculas.')
    for name in names:
        if (not name.startswith('PDFModder/') or any(part in {'','.','..'} for part in name.split('/'))
                or any(char in name for char in ('\\','\t','\r','\n',':'))):
            raise RuntimeError('Ruta inválida en el paquete: '+name)


def write_payload(source, payload, extras):
    """Overlay installer sources and rebuild the exact corresponding-source inventory."""
    source_prefix='PDFModder/_internal/source/PDFModder/'
    manifest_name='PDFModder/_internal/source/MANIFEST.json'
    extra_names={source_prefix+p.relative_to(ROOT).as_posix() for p in extras}
    source_rows=[]
    def add(output,name,content,info=None):
        output.writestr(info or name,content)
        if name.startswith(source_prefix):
            source_rows.append({'path':name[len(source_prefix):],'sha256':hashlib.sha256(content).hexdigest()})
    with zipfile.ZipFile(source) as existing,zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        if existing.testzip() is not None:raise RuntimeError('El ZIP de origen está dañado.')
        check_names(existing.namelist())
        if manifest_name not in existing.namelist():raise RuntimeError('Falta el manifiesto de las fuentes correspondientes.')
        for item in existing.infolist():
            if item.filename not in extra_names and item.filename!=manifest_name:
                add(output,item.filename,existing.read(item),item)
        for path in extras:
            add(output,source_prefix+path.relative_to(ROOT).as_posix(),path.read_bytes())
        output.writestr(manifest_name,json.dumps(sorted(source_rows,key=lambda row:row['path']),indent=2).encode('utf-8'))


def build():
    label='v'+(__version__ if __version__.split('.')[-1]!='0' else '.'.join(__version__.split('.')[:2]))
    source=ROOT/'releases'/label/f'PDFModder-{label}-Windows-x64.zip'
    meta=json.loads((source.parent/'VERSION.json').read_text(encoding='utf-8'))
    if not meta['frozen_verified'] or sha(source)!=meta['archive_sha256']:
        raise RuntimeError('El ZIP no corresponde a la entrega verificada.')
    if meta['application']!='PDF Modder '+__version__ or meta['version_label']!=label:
        raise RuntimeError('La entrega verificada no corresponde a la versión actual.')
    target=source.parent/f'PDFModder-{label}-Instalar.exe'
    if target.exists():raise FileExistsError('El instalador de esta versión ya existe; no se sobrescribe: '+str(target))
    installer_source=(ROOT/'installer/PdfModderInstaller.cs').read_text(encoding='utf-8-sig')
    assembly_version=__version__+'.'+str(INSTALLER_REVISION)
    for attribute in ('AssemblyVersion','AssemblyFileVersion'):
        if not re.search(r'\b'+attribute+r'\("'+re.escape(assembly_version)+r'"\)',installer_source):
            raise RuntimeError('Actualice la versión '+attribute+' del instalador a '+assembly_version)
    if f'version = "{__version__}"' not in installer_source:
        raise RuntimeError('La versión del marcador de instalación no corresponde al editor.')
    identity=ET.parse(ROOT/'installer/asInvoker.manifest').getroot().find('{urn:schemas-microsoft-com:asm.v1}assemblyIdentity')
    if identity is None or identity.get('version')!=assembly_version:
        raise RuntimeError('El manifiesto Windows del instalador tiene otra versión.')
    staging=ROOT/'build/installer';staging.mkdir(parents=True,exist_ok=True)
    payload=staging/'PDFModderPayload.zip'
    # Add the corresponding installer source and build instructions to the
    # existing application's source offer without changing executable/DLLs.
    extras=[ROOT/'installer/PdfModderInstaller.cs',ROOT/'installer/asInvoker.manifest',
            Path(__file__),ROOT/'scripts/verify_installer.py',ROOT/'scripts/verify_installer_ui.ps1',ROOT/'docs/INSTALACION_WINDOWS.md']
    write_payload(source,payload,extras)
    with zipfile.ZipFile(payload) as archive:
        names=archive.namelist();check_names(names)
        rows=[]
        for name in names:
            content=archive.read(name)
            rows.append(hashlib.sha256(content).hexdigest()+'\t'+str(len(content))+'\t'+name)
        assert hashlib.sha256(archive.read('PDFModder/PDFModder.exe')).hexdigest()==meta['exe_sha256']
        assert 'PDFModder/_internal/shiboken6/Shiboken.pyd' in names
        assert 'PDFModder/_internal/shiboken6/shiboken6.abi3.dll' in names
        source_rows=json.loads(archive.read('PDFModder/_internal/source/MANIFEST.json'))
        for row in source_rows:
            assert hashlib.sha256(archive.read('PDFModder/_internal/source/PDFModder/'+row['path'])).hexdigest()==row['sha256']
    manifest=staging/'PDFModderPayload.tsv';manifest.write_text('\n'.join(rows)+'\n',encoding='utf-8')
    compiler=Path(os.environ.get('SystemRoot','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():raise RuntimeError('No se encuentra el compilador .NET Framework de Windows.')
    args=[str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
          '/out:'+str(target),'/win32manifest:'+str(ROOT/'installer/asInvoker.manifest'),
          '/win32icon:'+str(ROOT/'assets/icons/pdfmodder.ico'),
          '/resource:'+str(payload)+',PDFModderPayload.zip',
          '/resource:'+str(manifest)+',PDFModderPayload.tsv',
          '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
          '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
          '/reference:System.Web.Extensions.dll',str(ROOT/'installer/PdfModderInstaller.cs')]
    subprocess.run(args,check=True,cwd=ROOT)
    report={'application':'PDF Modder '+__version__,'installer_revision':INSTALLER_REVISION,
            'created_utc':datetime.now(timezone.utc).isoformat(),
            'installer_sha256':sha(target),'installer_bytes':target.stat().st_size,
            'source_archive_sha256':meta['archive_sha256'],'exe_sha256':meta['exe_sha256'],
            'payload_sha256':sha(payload),'manifest_files':len(rows),'tested':False,
            'note':'El ejecutable y las dependencias del PDF son los de la entrega verificada. Este JSON registra la construcción; las pruebas del instalador se documentan aparte.'}
    target.with_suffix('.exe.sha256').write_text(sha(target)+'  '+target.name+'\n',encoding='ascii')
    (target.parent/'INSTALADOR.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'installer':str(target),**report},ensure_ascii=False,indent=2))


if __name__=='__main__':build()
