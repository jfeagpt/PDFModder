# Corpus sintético de PDF Modder 0.5.0

Los documentos públicos se generan localmente desde código propio, con datos ficticios y cuatro variantes Liberation Sans **2.1.5** bajo SIL OFL 1.1, copiadas sin modificar de la [distribución oficial](https://github.com/liberationfonts/liberation-fonts/releases/tag/2.1.5). Los hashes se registran en `assets/fonts/PROVENANCE-Liberation.json`. Bitstream Vera, distribuida legítimamente con ReportLab, se conserva para probar restricciones de incrustación; otros ejemplos usan los recursos estándar PDF Helvetica y Courier. No se utilizan PDFs comerciales ni fuentes copiadas de Windows en el corpus público. Este corpus demuestra comportamiento con estas construcciones PDF; no demuestra compatibilidad universal ni sustituye las pruebas con archivos reales del usuario.

Desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe scripts\generate_examples.py
```

`make_corpus(output: Path) -> dict[str, Path]`, en `tests/corpus.py`, ofrece el mismo generador a las pruebas. La geometría y el contenido son reproducibles; los PDFs cifrados contienen aleatoriedad criptográfica y no se espera que sus bytes sean idénticos entre ejecuciones. `examples/expected.json` registra textos, dimensiones, rotación, geometrías de las apariciones relevantes, número de elementos y huellas SHA-256 de la ejecución actual. Todas las coordenadas de regiones usan el espacio PyMuPDF sin rotación, en puntos con eje Y hacia abajo.

| Clave | Archivo | Cobertura preparada |
|---|---|---|
| `main` | `digital.pdf` | Dos páginas; Liberation Sans completa incrustada; tamaño fraccionario 11,25 pt; fecha `10/09/2026`; importe `1.234,56 €` con extremo derecho x = 530 pt; acentos, ñ y €; tres apariciones de TOTAL en página 1 y otra en página 2; palabra y línea para mover; columnas separadas; tabla con fondo verde y líneas vectoriales; imagen vecina; enlace, nota y marcadores alejados; página 2 de control. |
| `rotated` | `rotated_crop.pdf` | MediaBox 640 × 880; CropBox [30, 40, 610, 840]; rotación de página 90°; fecha y línea para selección y movimiento a diferentes zooms. |
| `subset` | `subset.pdf` | TrueType parcial producido por ReportLab; fecha y texto ASCII; no contiene glifos de ñ, á ni €. Permite demostrar rechazo al faltar caracteres o resolución manual con la fuente completa. |
| `local_font` | `font_local.pdf` | Liberation Sans sin programa incrustado; el archivo original en `assets/fonts/LiberationSans-Regular.ttf` permite probar resolución local/importación explícita. No se instala ninguna fuente en Windows. |
| `missing_font` | `font_missing.pdf` | Recurso de fuente sin incrustar con nombre sintético inexistente `PDFModderMissing-Regular`. El renderizador puede mostrar una sustitución al leer; el editor debe impedir la sustitución silenciosa al escribir. |
| `unsupported` | `unsupported_regions.pdf` | Escala horizontal 130 %, matriz inclinada, opacidad 45 %, contorno, textos solapados y una línea con dos estilos; texto simple de control. Las regiones no admitidas deben bloquearse explícitamente. |
| `form` | `form.pdf` | Campo AcroForm `importe` y texto ordinario independiente; permite comprobar detección y preservación/bloqueo del formulario. |
| `signature` | `signature_marker_invalid.pdf` | Campo `/Sig` con `/V` y `/ByteRange` deliberadamente inválidos. Solo prueba detección conservadora del marcador; NO es una firma criptográfica y NO demuestra verificación de firmas reales. |
| `restricted` | `restricted.pdf` | AES-256, contraseña de usuario vacía, solo permiso de impresión; permite probar bloqueo por restricciones aunque pueda abrirse sin contraseña. |
| `encrypted` | `encrypted.pdf` | AES-256 y contraseña de usuario `lectura-pruebas`; propietario `propietario-pruebas`; solo permiso de impresión. Credenciales de prueba públicas, sin datos sensibles. |
| `embedding_restricted` | `font_embedding_restricted.pdf` | Vera incrustada: la fuente distribuida por ReportLab declara `fsType = 4` (Preview & Print), por lo que la reutilización para editar se rechaza en modo estricto. No se alteran los bits de licencia. |

Los fixtures `font_local` y `font_missing` modifican diccionarios de fuentes creados por el generador mediante API de objetos PDF, nunca cadenas de un PDF arbitrario. El marcador de firma usa objetos de pypdf y no simula autenticidad criptográfica.

La versión 0.3 añade `etiquetado.pdf` y `etiquetado_actualtext.pdf`, generados con `tests/tagged_corpus.py` y `.venv/Scripts/python.exe scripts/acceptance_tagged.py --generate-examples`. Contienen dos páginas, MCID/ParentTree, roles, idioma español y una figura con texto alternativo. Las variantes de prueba cubren MCR, OBJR, estilos mixtos, orden lógico distinto del pintado, ActualText y estructuras defectuosas o semánticas anidadas. Véase [ETIQUETADO.md](ETIQUETADO.md) para su alcance y [VERIFICACION_WINDOWS.md](VERIFICACION_WINDOWS.md) para los resultados ejecutados.

La versión 0.5.0 incorpora `examples/recortado.pdf`: dos páginas de 450 × 400 pt, recursos estándar Courier y Helvetica, un campo verde con recorte explícito, `SOL` seguido de los vecinos `LUNA FIN`, un alfabeto de referencia, una fecha y una segunda página de control. Permite comprobar sustituciones de distinta longitud dentro del espacio disponible sin desplazar los vecinos. Su generador independiente es `scripts/generate_clipped_example.py`, que utiliza PyMuPDF y pypdf, sin pytest ni documentos privados. El identificador PDF puede variar al regenerar; el contenido, geometría, recursos y operadores son reproducibles. No lo genera `scripts/generate_examples.py`.

```powershell
.\.venv\Scripts\python.exe scripts\generate_clipped_example.py
# Opcional: --output ruta.pdf para escribir otra copia del ejemplo.
```

En un campo recortado compatible, la ruta variable interpreta `Tj`/`TJ`, conserva el recurso de fuente, tamaño y escala y recompone los avances del fragmento sustituido. Compensa el cursor PDF para mantener fijos los caracteres vecinos; no justifica automáticamente el campo ni redistribuye el resto de la línea. Una sustitución más larga debe caber en el área explícita y superar las comprobaciones de códigos, geometría y contenido. No se sustituye la fuente por una parecida. Los límites completos se describen en [EDICION_CON_RECORTES.md](EDICION_CON_RECORTES.md).

La fuente principal conserva el programa completo para que los nuevos caracteres se puedan verificar. Las cuatro variantes Liberation Sans incluidas declaran `fsType = 0`, comprobado con fontTools. La variante en subconjunto se crea con `reportlab.pdfbase.ttfonts.TTFont`, cuya integración y registros están documentados en [la guía oficial de fuentes de ReportLab](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/). Las operaciones de construcción, CropBox y anotaciones usan la [API de páginas de PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html). Las fuentes se redistribuyen sin modificar junto con `assets/fonts/LICENSE-Liberation.txt` y `assets/fonts/LICENSE-Bitstream-Vera.txt`; las licencias de las bibliotecas son independientes de la licencia de las fuentes.

## Criterio de validación

La extracción por página y región debe confirmar el texto nuevo y los vecinos. Una búsqueda global de la palabra antigua no basta: TOTAL y la fecha aparecen legítimamente varias veces. Para mover una línea, el texto debe desaparecer del origen y existir exactamente una vez en el destino, conservando sus avances internos.

La comparación rasterizada debe emplear idénticos parámetros de renderizado y excluir únicamente pequeñas cajas de glifos originales y nuevos con margen técnico. Al usar Poppler es necesario pasar `pdftoppm -cropbox`: por defecto usa MediaBox y produciría dimensiones diferentes en el fixture rotado. La página de control, fondos, tabla, imagen, enlace y nota quedan fuera de esas exclusiones. Deben comprobarse también los textos vecinos dentro de cada región excluida. Deben mantenerse el número de páginas, sus cajas y rotación, marcadores, anotaciones, enlaces y campos dentro del alcance soportado.

## Comprobación del generador ejecutada en Windows

La comprobación inicial generó los 11 archivos de la tabla con Python 3.12, PyMuPDF 1.26.7, ReportLab 4.4.9 y pypdf 6.6.0. Se renderizaron todos con Poppler y se inspeccionaron visualmente los casos diferentes. Esta medición inicial no incluye los ejemplos etiquetados ni el recortado añadidos después. La extracción independiente pypdf confirma la fecha y el símbolo euro del documento principal; las apariciones TOTAL son tres en página 1 y una en página 2. Ambas páginas comparten el recurso de fuente regular xref 5. Los dos recursos de texto principales declaran `fsType = 0`.

El subconjunto ReportLab contiene una tabla cmap MacRoman (plataforma 1, codificación 0), de 95 entradas, sin tabla Unicode. La extracción funciona gracias al ToUnicode del PDF; esto requiere tratamiento explícito antes de reutilizar el programa de fuente. La firma sintética está en el árbol de campos como `/FT /Sig`, y el importe como `/FT /Tx`. El documento restringido declara permisos -3900; el cifrado exige contraseña y la credencial de lectura devuelve autenticación de usuario, sin permiso de modificación. Estos son controles del corpus, no resultados de aceptación del editor.

Este documento describe los escenarios preparados, no afirma que todas las pruebas hayan pasado. Los resultados ejecutados y sus limitaciones se registran en [VERIFICACION_WINDOWS.md](VERIFICACION_WINDOWS.md). Hasta 0.5.0 se han comprobado operaciones concretas sobre **dos PDFs reales privados**, incluido un flujo de 16 modificaciones con cambios de longitud. Esos archivos, sus datos comerciales, capturas y derivados no se redistribuyen ni son dependencias de las pruebas públicas. Pendiente con más archivos reales: diversidad de exportadores, fuentes CFF/Type3/CID especiales, firmas criptográficas válidas, fórmulas de formularios y fuentes con permisos de incrustación específicos.
