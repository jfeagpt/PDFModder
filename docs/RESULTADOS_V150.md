# Resultados y reproducción de PDF Modder 1.5.0

Las cifras finales y los tiempos del ejecutable se generan en
[RESULTADOS_MEDIDOS_V150.md](RESULTADOS_MEDIDOS_V150.md) al empaquetar,
a partir de los informes de la compilación concreta.

## Alcance

Se han separado tres comprobaciones: observación manual de Acrobat XI Pro,
pruebas del motor y la interfaz de PDF Modder, y pruebas del paquete de Windows.
El registro de Acrobat está en `OBSERVACION_ACROBAT_V150.md`. Sus pruebas no
acreditan la compatibilidad del motor de PDF Modder ni viceversa.

La interfaz reúne las herramientas a la derecha, con miniaturas a la izquierda,
edición directa, formato contextual y pictogramas propios. No es una reproducción
completa de Acrobat. Exporta TXT, PNG, JPEG y SVG; no convierte a Word, Excel,
PowerPoint o RTF. El recorte de páginas se configura por márgenes, no dibujando
un rectángulo. Sustituir una página cambia también sus anotaciones.

## Corpus y protocolo

El corpus sintético distribuible de `examples/` se complementa con cuatro PDF
privados aportados para las pruebas: factura de una página, mapa de doce páginas,
informe con texto digital y duplicados OCR de una página y anexo etiquetado de
tres páginas. Los archivos privados y sus derivados quedan en `tmp/` y se
excluyen de las fuentes publicables, el ejecutable y el instalador.

`scripts/acceptance_v150.py` intenta 16 operaciones por documento: mover y editar
una cifra; agregar texto; agregar, mover/redimensionar y girar una imagen; exportar
TXT y PNG; recortar, eliminar, extraer y girar páginas; dividir; reemplazar;
insertar; combinar. Cada operación comienza desde los bytes originales, salvo
las transformaciones de la imagen añadida. Los originales se comparan por SHA-256.
Los resultados `blocked` son límites explícitos, no operaciones completadas.

Los PDF resultantes se guardan mediante escritura completa y se reabren.
PyMuPDF y pypdf contrastan número de páginas y las cifras editadas. La edición
del mapa puede extraerse con un espacio entre operadores mediante pypdf aunque
PyMuPDF muestre la cifra seguida; el informe registra esa divergencia y compara
los dígitos sin eliminar ningún otro carácter.

El motor valida vecinos, recursos, estructura y apariencia de cada transición.
La comparación de imágenes usa 144 ppp y admite como máximo 8 niveles por canal
de 255, con cero píxeles fuera de tolerancia en el área que debe permanecer
igual. Las exclusiones corresponden a los caracteres cambiados y a su destino,
con un margen de 0,75 puntos para antialiasing; cuando corresponde se añaden
contornos tipográficos verificados. No se excluye una página o un bloque entero
para ocultar diferencias. Los vecinos se comprueban también como texto y geometría.

Con `--poppler`, un renderizador independiente contrasta además la primera
página de cada cambio o movimiento de texto aceptado. El informe conserva el
número y porcentaje de píxeles excluidos. Esto no acredita la comparación con
Poppler de todas las operaciones de imágenes y páginas, que conservan las
validaciones del motor y del parser independiente.

## Límites concretos

- El mapa permite las operaciones de páginas con destinos de nombres distintos;
  las colisiones entre nombres y algunas duplicaciones siguen bloqueadas.
- Los documentos de una sola página no pueden quedar vacíos al eliminarlas.
- El anexo etiquetado conserva límites para artefactos, texto recortado con
  semántica no reproducible, contenido nuevo y combinación de árboles accesibles.
  No se quitan etiquetas para habilitar operaciones.
- El movimiento con recorte nuevo requiere un tramo aislado y un recorte
  rectangular verificable. No abarca todos los recortes, fuentes o contenedores.
- El texto blanco sigue siendo blanco al moverlo a un fondo blanco: el color
  no cambia automáticamente.
- No se ha probado esta entrega en otro ordenador físico. Un ensayo con PATH
  reducido en este Windows comprueba dependencias empaquetadas, pero no equivale
  a todas las configuraciones de Windows.

## Reproducción

Instale las dependencias de desarrollo con `scripts/install.ps1 -Development`.
En Windows x64, con Python 3.12:

```powershell
.venv/Scripts/python.exe scripts/verify_source_v150.py
.venv/Scripts/python.exe scripts/acceptance_v150.py --poppler RUTA_FACTURA RUTA_MAPA RUTA_OCR RUTA_ANEXO
powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipTests
powershell -ExecutionPolicy Bypass -File scripts/verify_executable.ps1
.venv/Scripts/python.exe scripts/package_v150.py --prepare RUTA_SUMMARY_ACEPTACION
.venv/Scripts/python.exe scripts/build_current_installer.py
.venv/Scripts/python.exe scripts/verify_install_uninstall_v09.py
.venv/Scripts/python.exe scripts/package_v150.py --finish RUTA_RESULTADO_INSTALACION
```

Sustituya los argumentos `RUTA_...` por las rutas reales. Poppler se localiza
mediante `POPPLER_BIN`, PATH o el entorno de herramientas disponible; no es una
dependencia de la aplicación instalada. Cada comprobación emite la ruta de su
informe. El verificador de instalación exige que no exista una instalación real
de esta versión y utiliza una carpeta aislada dentro de `output/portability`.
Comprueba instalación, inventario, edición con el ejecutable instalado y retirada,
conservando archivos personales y modificados.

El empaquetador exige informes actuales ligados a las huellas del código y del
ejecutable. No toma los resultados de entregas anteriores como prueba de 1.5.0.
`ENTREGA.json` resume las pruebas de fuente, ejecutable y corpus;
`INSTALACION-VERIFICADA.json` registra el resultado de instalación y retirada.
