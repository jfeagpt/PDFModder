"""Cierra la entrega ZIP sólo después de pruebas y smoke del ejecutable.

Ejecutar desde Windows después de build.ps1 y los cuatro recorridos de interfaz. Copia documentos,
licencias y fuentes verificadas; nunca cambia el ejecutable que pasó la prueba.
"""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile
import xml.etree.ElementTree as ET
import sys


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pdfmodder import __version__


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    bundle=ROOT/'dist/PDFModder'
    internal=bundle/'_internal'
    exe=bundle/'PDFModder.exe'
    smoke=json.loads((ROOT/'output/packaged-extended-smoke.json').read_text(encoding='utf-8'))
    assert smoke['ok'] and smoke['frozen'] and smoke['stage']=='complete'
    assert smoke['app_version']==__version__ and smoke['exe_sha256']==digest(exe)
    assert Path(smoke['source']).resolve()==(internal/'examples/digital.pdf').resolve()
    assert smoke['page_count']==3
    required={'agregar_texto_negrita_color','agregar_imagen_real','mover_y_redimensionar_imagen',
              'extraer_pagina_pdf','eliminar_pagina','deshacer_eliminacion','combinar_pdf',
              'reabrir_pdf_ampliado','verificar_pagina_extraida_y_combinada'}
    assert required.issubset({step['step'] for step in smoke['steps'] if step['ok']})
    tagged=json.loads((ROOT/'output/packaged-tagged-smoke.json').read_text(encoding='utf-8'))
    assert tagged['ok'] and tagged['frozen'] and tagged['stage']=='complete'
    assert tagged['app_version']==__version__ and tagged['exe_sha256']==digest(exe)
    assert Path(tagged['source']).resolve()==(internal/'examples/etiquetado.pdf').resolve()
    assert tagged['page_count']==2
    required_tagged={'doble_clic_nativo_etiquetado','previsualizar_linea_y_accesibilidad',
                     'aplicar_sustitucion_etiquetada','deshacer_linea_etiquetada',
                     'rehacer_linea_etiquetada','guardar_segunda_copia_etiquetada',
                     'reabrir_texto_etiquetado','verificar_control_tras_justificacion_etiquetada'}
    assert required_tagged.issubset({s['step'] for s in tagged['steps'] if s['ok']})
    assert all(r['accessibility']['verified'] for r in tagged['engine_validation_reports'])
    clipped=json.loads((ROOT/'output/packaged-clipped-smoke.json').read_text(encoding='utf-8'))
    assert clipped['ok'] and clipped['frozen'] and clipped['stage']=='complete'
    assert clipped['app_version']==__version__ and clipped['exe_sha256']==digest(exe)
    assert Path(clipped['source']).resolve()==(internal/'examples/recortado.pdf').resolve()
    assert clipped['page_count']==2
    required_clipped={'abrir_seleccionar_campo_recortado','previsualizar_campo_largo',
                      'aplicar_campo_largo','guardar_copia_recortada','reabrir_texto_real_recortado',
                      'previsualizar_campo_corto','aplicar_campo_corto','deshacer_segunda_edicion',
                      'rehacer_segunda_edicion','guardar_segunda_edicion','verificar_pagina_control'}
    required_clipped.update({'mover_texto_con_recorte','deshacer_movimiento_recortado',
                             'rehacer_movimiento_recortado','guardar_movimiento_recortado',
                             'reabrir_movimiento_recortado','previsualizar_caracter_no_usado',
                             'cancelar_caracter_no_usado'})
    required_clipped.update({'previsualizar_intro_recortado','aplicar_intro_recortado','guardar_parrafo_recortado',
                             'reabrir_parrafo_recortado','mover_con_solapamiento_explicito','deshacer_solapamiento_exacto'})
    assert required_clipped.issubset({s['step'] for s in clipped['steps'] if s['ok']})
    assert len(clipped['engine_validation_reports'])==2
    assert all(r['verified'] and r['font_resources_unchanged'] and r['operators_preserved']
               and abs(r['cursor_residual'])<1e-6 for r in clipped['engine_validation_reports'])
    advanced=json.loads((ROOT/'output/packaged-v08-smoke.json').read_text(encoding='utf-8'))
    assert advanced['ok'] and advanced['frozen'] and advanced['stage']=='complete'
    assert advanced['app_version']==__version__ and advanced['exe_sha256']==digest(exe)
    assert Path(advanced['source']).resolve()==(internal/'examples/herramientas-v08.pdf').resolve()
    assert advanced['page_count']==4
    required_advanced={'previsualizar_fecha_y_retirar_ocr_duplicado','revisar_tres_coincidencias_marcar_dos',
                       'aplicar_dos_reemplazos_en_una_transaccion','exportar_imagen_original',
                       'previsualizar_recorte_giro_instancia','verificar_imagenes_compartidas_intactas',
                       'previsualizar_parrafo_interlineado_saltos','previsualizar_reordenar_duplicar_girar_insertar',
                       'deshacer_organizador_exactamente','rehacer_organizador_exactamente',
                       'guardar_copia_v08','reabrir_fecha_ocr_parrafo_coincidencias_imagen',
                       'verificar_pagina_duplicada','verificar_pagina_insertada_y_original'}
    assert required_advanced.issubset({s['step'] for s in advanced['steps'] if s['ok']})
    assert all(r['verified'] for r in advanced['engine_validation_reports'])
    independent=json.loads((ROOT/'output/acceptance-v08/report.json').read_text(encoding='utf-8'))
    assert independent['verified'] and independent['source_unchanged']
    acceptance=json.loads((ROOT/'output/acceptance-tagged/report.json').read_text(encoding='utf-8'))
    assert acceptance['verified'] and acceptance['source_unchanged']
    suites=list(ET.parse(ROOT/'output/pytest-results.xml').getroot().iter('testsuite'))
    count=sum(int(s.attrib['tests']) for s in suites)
    assert count>=416
    assert all(int(s.attrib[k])==0 for s in suites for k in ('failures','errors','skipped'))
    suite_seconds=round(sum(float(s.attrib['time']) for s in suites),3)
    assert suite_seconds>0
    frozen_runs={'extended':smoke,'tagged':tagged,'clipped':clipped,'v08':advanced}
    assert all(step['ok'] for report in frozen_runs.values() for step in report['steps'])

    # Source copies were frozen with the tested build. Documentation and test
    # evidence may be refreshed afterwards; implementation cannot be changed.
    for path in (ROOT/'pdfmodder').glob('*.py'):
        assert digest(path)==digest(internal/'source/PDFModder/pdfmodder'/path.name),path
    assert digest(ROOT/'run_pdfmodder.py')==digest(internal/'source/PDFModder/run_pdfmodder.py')
    for name in ('licenses','source'):
        shutil.copytree(ROOT/'build/delivery'/name,internal/name,dirs_exist_ok=True)
    shutil.copytree(ROOT/'docs',internal/'docs',dirs_exist_ok=True)
    for name in ('README.md','LICENSE'):
        shutil.copy2(ROOT/name,bundle/name)
        shutil.copy2(ROOT/name,internal/name)

    checks=bundle/'COMPROBACIONES'
    checks.mkdir(exist_ok=True)
    for relative in ('pytest-results.xml','packaged-extended-smoke.json','packaged-extended-smoke.png',
                     'smoke-ampliado.pdf','smoke-extraidas.pdf',
                     'packaged-tagged-smoke.json','packaged-tagged-smoke.png','smoke-etiquetado-editado.pdf',
                     'packaged-clipped-smoke.json','packaged-clipped-smoke.png',
                     'smoke-recortado-editado.pdf','smoke-recortado-segunda-edicion.pdf',
                     'smoke-recortado-movido.pdf',
                     'smoke-recortado-parrafo.pdf',
                     'packaged-v08-smoke.json','packaged-v08-smoke.png',
                     'smoke-v08-editado.pdf','smoke-v08-imagen.png',
                     'acceptance-v08/report.json','acceptance-v08/final.pdf',
                     'acceptance-v08/organizado.pdf','acceptance-v08/ocr-capa-buscable-editada.pdf',
                     'acceptance-tagged/report.json','acceptance-tagged/original.pdf','acceptance-tagged/editado.pdf',
                     'acceptance-tagged/antes-1.png','acceptance-tagged/despues-1.png',
                     'acceptance-tagged/antes-2.png','acceptance-tagged/despues-2.png',
                     'acceptance/report.json','acceptance/edicion.pdf',
                     'acceptance-extensions/report.json','acceptance-extensions/final.pdf',
                     'acceptance-extensions/extraidas.pdf','acceptance-extensions/antes-1.png',
                     'acceptance-extensions/despues-1.png','vertical/report.json'):
        target=checks/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'output'/relative,target)
    for entry in json.loads((internal/'source/MANIFEST.json').read_text(encoding='utf-8')):
        assert digest(internal/'source/PDFModder'/entry['path'])==entry['sha256'],entry['path']
    # Recheck after refreshing staged source: an old staging tree must never
    # replace the corresponding implementation that passed the frozen checks.
    for path in (ROOT/'pdfmodder').glob('*.py'):
        assert digest(path)==digest(internal/'source/PDFModder/pdfmodder'/path.name),path
    assert digest(ROOT/'run_pdfmodder.py')==digest(internal/'source/PDFModder/run_pdfmodder.py')
    metadata={'application':f'PDF Modder {__version__}','platform':'Windows 11 x64',
              'delivery_status':'verified','frozen_verified':True,
              'tests_passed':count,'tests_seconds':suite_seconds,
              'frozen_steps_total':sum(len(report['steps']) for report in frozen_runs.values()),
              'frozen_seconds_total':round(sum(report['elapsed_seconds'] for report in frozen_runs.values()),3),
              'frozen_extended_verified':True,
              'frozen_extended_seconds':smoke['elapsed_seconds'],
              'frozen_tagged_verified':True,'frozen_tagged_seconds':tagged['elapsed_seconds'],
              'frozen_clipped_verified':True,'frozen_clipped_seconds':clipped['elapsed_seconds'],
              'frozen_v08_verified':True,'frozen_v08_seconds':advanced['elapsed_seconds'],
              'exe_sha256':digest(exe),'source_manifest':'_internal/source/MANIFEST.json'}
    metadata.update({f'frozen_{name}_steps':len(report['steps']) for name,report in frozen_runs.items()})
    labels={'extended':'Ampliado: texto, imágenes y páginas','tagged':'Etiquetado: texto y accesibilidad',
            'clipped':'Recortado: sustitución y vecinos','v08':'Herramientas 0.8: OCR, revisión, imágenes y organización'}
    lines=[f"PDF Modder {__version__} — ejecutable Windows verificado.",
           f"SHA-256 del ejecutable: {metadata['exe_sha256']}",
           '', 'Cuatro recorridos ejecutados sobre este mismo PDFModder.exe:']
    lines.extend(f"- {labels[name]}: {len(report['steps'])} pasos; {report['elapsed_seconds']:.3f} s."
                 for name,report in frozen_runs.items())
    lines.extend([f"Total: {metadata['frozen_steps_total']} pasos; {metadata['frozen_seconds_total']:.3f} s.",
                  '',f"Batería desde código: {count} pruebas aprobadas en {suite_seconds:.3f} s, sin errores ni omisiones.",
                  'Las pruebas desde código y las comparaciones independientes complementan los recorridos del ejecutable; son evidencias distintas.',
                  'ENTREGA.json y los informes packaged-*-smoke.json registran versión, SHA-256 y resultados.',
                  'La compatibilidad queda limitada a las operaciones y documentos comprobados.'])
    note='\n'.join(lines)+'\n'
    # These notices replace the candidate's previous pending-verification text
    # only after every evidence and corresponding-source gate above has passed.
    (bundle/'ENTREGA.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False),encoding='utf-8')
    (checks/'ESTADO.txt').write_text(note,encoding='utf-8')
    (bundle/'LEEME-INICIO.txt').write_text(
        f'PDF Modder {__version__} para Windows 11 x64\n\n'
        '1. Extrae TODO el ZIP a una carpeta.\n'
        '2. Abre PDFModder.exe. No necesitas instalar Python.\n'
        '3. Conserva la carpeta _internal junto al ejecutable.\n'
        '4. Abre un PDF o arrastra el archivo a la ventana.\n'
        '5. Doble clic para editar; Previsualizar y después Aplicar. Guarda una copia con Guardar como.\n\n'
        'Guía: _internal/docs/GUIA_V08.md\n'
        'Es una aplicación portable; no requiere instalación ni permisos de administrador.\n\n'
        +note,encoding='utf-8')
    archive=ROOT/'dist/PDFModder-Windows-x64.zip'
    temporary=archive.with_suffix('.zip.tmp')
    paths=sorted(path for path in bundle.rglob('*') if path.is_file())
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for path in paths:
            assert not path.is_symlink() and path.resolve().is_relative_to(bundle.resolve())
            output.write(path,path.relative_to(bundle.parent).as_posix())
    with zipfile.ZipFile(temporary) as check:
        assert check.testzip() is None
    temporary.replace(archive)
    archive.with_suffix('.zip.sha256').write_text(f'{digest(archive)}  {archive.name}\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'files':len(paths),**metadata},indent=2))


if __name__=='__main__':
    main()
