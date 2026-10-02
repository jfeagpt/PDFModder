# Organizador de páginas · 0.8

El organizador muestra el orden final antes de previsualizar. Permite arrastrar
filas de miniaturas, subir o bajar una selección, girarla en pasos de 90°,
duplicarla, quitar páginas del orden e insertar páginas en blanco o de otros PDFs
en una posición explícita. El giro modifica la rotación de la página; no
rasteriza ni transforma sus letras. La aceptación del diálogo entrega un plan al
proceso de trabajo. La previsualización y el guardado utilizan el PDF reconstruido
y validado; cerrar o cancelar el diálogo no modifica el documento.

## Contrato del motor

```python
output, report = organize_pages_pdf(data, plan, additions={"anexo": pdf_bytes})

plan = [
    {"source": "current", "page": 2, "rotation": 90},
    {"source": "current", "page": 0, "rotation": 0},
    {"source": "blank", "width": 595.276, "height": 841.890, "rotation": 0},
    {"source": "anexo", "page": 0, "rotation": 270},
    {"source": "current", "page": 0, "rotation": 90},
]
```

Los índices `page` parten de cero. `rotation` es un **incremento horario** sobre
el giro que ya tiene esa página: 0, 90, 180 o 270. Las dimensiones de una página
en blanco se expresan en puntos PDF, antes de ese giro. El motor recibe bytes y
no abre rutas de disco. Los identificadores externos son claves de `additions`;
no pueden llamarse `current` ni `blank`. Las opciones desconocidas se rechazan.

El informe incluye `operation="organize_pages"`, `verified`, `page_count`,
`assignments`, estadísticas de validación por página y `page_map`.
`page_map` contiene el índice del documento actual o `None` para páginas nuevas;
un duplicado repite el índice de origen. `source_sha256` identifica exactamente
los documentos utilizados. El historial de la aplicación conserva los bytes de
cada estado; este motor no sobrescribe originales.

## Destinos y conservación

- Un enlace a otra página o un marcador apunta a la **primera aparición final**
  de su página de destino en el mismo documento de procedencia.
- Un enlace a su propia página apunta a **esa copia**, incluso si está duplicada.
- Las coordenadas y el zoom originales de los destinos `/XYZ` se mantienen en
  coordenadas PDF. El cambio de rotación se respeta al mostrar el destino.
- Si una página conservada enlaza a otra que se excluyó, se bloquea la operación.
  No se borra silenciosamente ese enlace.
- Los marcadores de páginas excluidas se retiran y sus hijos conservados se
  promueven. Sus títulos se enumeran en `removed_bookmarks`.
- Se mantienen los metadatos Info y XMP del documento actual. Los metadatos de
  los PDFs insertados no reemplazan a los del documento actual. Se incorporan
  sus marcadores compatibles.
- Se preservan texto, operadores de contenido, fuentes, imágenes, vectores,
  cajas Media/Crop/Bleed/Trim/Art, enlaces y anotaciones admitidas. Se remapean
  las relaciones `/P`, `/Parent`, `/Popup` y `/IRT` de anotaciones a su copia.

El clonador de pypdf no ofrece por sí solo la política de destinos de duplicados
necesaria aquí: al escribir puede escoger la última copia. Por eso se reconstruyen
los destinos en un grafo intermedio independiente antes de la escritura final.
También se restaura `/Parent` de los Popup, que el clonado genérico excluye como
si fuera un padre del árbol de páginas. Si una relación de anotación sale de la
misma página, se bloquea el plan en vez de improvisar su duplicación.

## Alcance y bloqueos

Se mantienen los controles previos de las operaciones de páginas. Se rechazan
PDFs etiquetados, cifrados o restringidos, firmas declaradas, formularios y XFA,
documentos reparados, capas, destinos nombrados, acciones no admitidas y otras
estructuras que no pueden conservarse con esta reconstrucción. El organizador
no elimina esas estructuras para hacer que la operación pase. Estos límites
son específicos de organizar páginas y no amplían las capacidades del editor
de texto sobre PDFs etiquetados.

La fidelidad comprobada no implica identidad binaria. El archivo se escribe por
completo y se limpian objetos no referenciados mediante el mismo camino de
exportación utilizado por las demás operaciones de páginas.

## Diálogo y concurrencia

`PageOrganizerDialog(pages, parent=None)` recibe una lista de metadatos:

```python
{"page": 0, "width": 595.0, "height": 842.0, "rotation": 0, "png": png_bytes}
```

Aquí `width` y `height` corresponden a las dimensiones **visibles actuales**
(`page.rect`); `rotation` es el giro actual. `png` es opcional. El diálogo
muestra los números finales y conserva internamente las dimensiones originales
de sus miniaturas; `plan()` sólo devuelve datos serializables de la operación.

- `import_requested(paths, position)` solicita al controlador leer varios PDFs.
  `position` es un índice final desde cero.
- `add_source(source_id, pages, label=None, position=None)` inserta sus metadatos.
- `thumbnail_requested(source_id, page)` pide una miniatura visible; sólo puede
  haber una solicitud pendiente. `set_thumbnail(...)` entrega sus bytes PNG.
- `set_busy(bool)` y `set_error(message)` conservan el plan y muestran el estado
  de una carga o un fallo.

El módulo del diálogo sólo utiliza Qt y conversiones de unidades; no importa ni
abre MuPDF. El controlador ejecuta las operaciones del motor fuera del proceso
GUI. La caché mantiene hasta 64 miniaturas reducidas a 140 × 160 píxeles y se
solicitan páginas visibles, sin renderizar todas a máxima resolución.

## Comprobaciones reproducibles

```powershell
.venv\Scripts\python.exe -m pytest tests/test_page_organizer.py tests/test_pageops.py -q
```

La nueva batería usa PDFs sintéticos reproducibles y los ejemplos públicos del
proyecto; no contiene documentos privados. Cubre combinaciones de reordenación,
giros y CropBox desplazado, duplicados, blancos, anexos, metadatos, destinos
internos/URI, marcadores, anotaciones y Popup. Una prueba modifica la nota de una
copia y reabre el resultado para demostrar que las otras permanecen intactas.

La validación contrasta extracción MuPDF y pypdf, todos los operadores de
contenido, huellas de los programas de fuente y geometría. Renderiza cada página
contra su página de origen con el giro solicitado, a 144 ppp y los mismos
parámetros. **No se excluye ninguna región de la página.** Se utiliza el umbral
común de 8/255 por canal para diferencias de rasterizado; el corpus del
organizador ha dado diferencia máxima **0/255**. Cada PDF nuevo pasa estas
comprobaciones antes de devolverse; no se extrapola compatibilidad universal.

Las pruebas Qt usan controles reales para ordenar, girar, duplicar, insertar,
restablecer y cancelar, y prueban la petición asíncrona de archivos y miniaturas.
El movimiento de filas se comprueba por el modelo que utiliza el arrastre
interno de QListWidget. La integración de sesión y el paquete Windows se
comprueban en la batería general del proyecto.

## Referencias de las API

- [pypdf 6.6.0: unión, duplicados y reset_translation](https://pypdf.readthedocs.io/en/6.6.0/user/merging-pdfs.html).
- [pypdf 6.6.0: PageObject y rotación](https://pypdf.readthedocs.io/en/6.6.0/modules/PageObject.html).
- [pypdf 6.6.0: PdfWriter](https://pypdf.readthedocs.io/en/6.6.0/modules/PdfWriter.html).
- [Qt: QListWidget](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QListWidget.html).
- [Qt: modelo/vista y arrastre interno](https://doc.qt.io/qtforpython-6.10/overviews/qtwidgets-model-view-programming.html).

No se añaden dependencias: el organizador utiliza PySide6, PyMuPDF y pypdf ya
fijados en el proyecto. Siguen siendo aplicables sus avisos LGPL/AGPL/BSD y las
condiciones de distribución documentadas en el inventario de licencias.
