"""Entrega solicitada sin acreditar pruebas del ejecutable final.

Mantiene intactos los controles de package_release.py. Sólo empaqueta la
compilación existente e identifica explícitamente la verificación pendiente.
"""
from pathlib import Path
import hashlib,json,shutil,sys,zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pdfmodder import __version__


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    bundle=ROOT/'dist/PDFModder';internal=bundle/'_internal'
    executable=bundle/'PDFModder.exe'
    assert executable.is_file()
    # Verify the implementation matches the source captured by PyInstaller.
    for path in (ROOT/'pdfmodder').glob('*.py'):
        assert digest(path)==digest(internal/'source/PDFModder/pdfmodder'/path.name),path
    assert digest(ROOT/'run_pdfmodder.py')==digest(internal/'source/PDFModder/run_pdfmodder.py')
    for name in ('licenses','source'):
        shutil.copytree(ROOT/'build/delivery'/name,internal/name,dirs_exist_ok=True)
    shutil.copytree(ROOT/'docs',internal/'docs',dirs_exist_ok=True)
    for name in ('README.md','LICENSE'):
        shutil.copy2(ROOT/name,bundle/name);shutil.copy2(ROOT/name,internal/name)
    checks=bundle/'COMPROBACIONES';checks.mkdir(exist_ok=True)
    for relative in ('pytest-results.xml','agent-v08-smoke.json','agent-v08-smoke.png',
                     'acceptance/report.json','acceptance-extensions/report.json','acceptance-tagged/report.json',
                     'acceptance-v08/report.json','acceptance-v08/final.pdf','acceptance-v08/organizado.pdf',
                     'acceptance-v08/ocr-capa-buscable-editada.pdf'):
        target=checks/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'output'/relative,target)
    suites=list(ET.parse(ROOT/'output/pytest-results.xml').getroot().iter('testsuite'))
    passed=sum(int(s.attrib['tests'])-int(s.attrib['failures'])-int(s.attrib['errors'])-int(s.attrib['skipped']) for s in suites)
    note=('Paquete Windows generado por PyInstaller. No se ha ejecutado esta compilación final. '
          'La batería de 409 pruebas pasó antes del último ajuste de anchura nativa; '
          'la prueba privada de factura con ocho campos pasó después de ese ajuste. '
          'Las últimas repeticiones solicitadas no se ejecutaron por permisos rechazados. '
          'La prueba de 23 pasos desde código y los informes Poppler no acreditan el ejecutable congelado.')
    metadata={'application':f'PDF Modder {__version__}','platform':'Windows 11 x64',
              'delivery_status':'packaged_pending_final_executable_verification','frozen_verified':False,
              'earlier_suite_passed':passed,'source_smoke_steps':23,'source_smoke_seconds':10.085,
              'exe_sha256':digest(executable),'verification_note':note,
              'source_manifest':'_internal/source/MANIFEST.json'}
    (bundle/'ENTREGA.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    (checks/'ESTADO.txt').write_text(note+'\n',encoding='utf-8')
    (bundle/'LEEME-INICIO.txt').write_text(
        'PDF Modder '+__version__+' para Windows 11 x64\n\n'
        '1. Extrae TODO el ZIP a una carpeta.\n'
        '2. Abre PDFModder.exe. No necesitas instalar Python.\n'
        '3. Conserva la carpeta _internal junto al ejecutable.\n'
        '4. Abre un PDF o arrastra el archivo a la ventana.\n'
        '5. Doble clic para editar; Previsualizar y después Aplicar. Guarda una copia con Guardar como.\n\n'
        'Guía: _internal/docs/GUIA_V08.md\n'
        'Es una aplicación portable; no requiere instalación ni permisos de administrador.\n\n'+note+'\n',encoding='utf-8')
    for entry in json.loads((internal/'source/MANIFEST.json').read_text(encoding='utf-8')):
        assert digest(internal/'source/PDFModder'/entry['path'])==entry['sha256'],entry['path']
    target=ROOT/'dist/PDFModder-Windows-x64.zip';temporary=target.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                assert not path.is_symlink() and path.resolve().is_relative_to(bundle.resolve())
                output.write(path,path.relative_to(bundle.parent).as_posix())
    with zipfile.ZipFile(temporary) as archive:assert archive.testzip() is None
    temporary.replace(target)
    target.with_suffix('.zip.sha256').write_text(f'{digest(target)}  {target.name}\n',encoding='ascii')
    print(json.dumps({'archive':str(target),'bytes':target.stat().st_size,**metadata},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
