# Auditoría de rutas de edición para 1.5.0

Fecha: 24/09/2026. Inspección del código fuente, sin ejecutar Acrobat ni las pruebas.
Este informe no acredita compatibilidad con los cuatro documentos del usuario.

## Rutas ya implementadas

| Herramienta | Entrada de interfaz | Implementación / worker |
|---|---|---|
| Editar texto existente | `MainWindow.start_edit`, doble clic en `PdfCanvas.mouseDoubleClickEvent` | `RichEditing.start_rich_edit` → `rich_selection`, `rich_preview`, `rich_prepare`, `rich_commit`; ruta conservadora `start_legacy_edit` → `preview`, `commit` |
| Fuente, tamaño, negrita, cursiva, color, subrayado por fragmentos | `EditorToolbar`, `PageEditor.merge_style/change_face` | `richtext.py`; fuente y cobertura comprobadas, sin sustitución silenciosa |
| Nueva línea, párrafo, sangría, tabuladores | `PageEditor.keyPressEvent/merge_paragraph` | `richmodels.py`, `paragraphs.py`, `richtext.py` |
| Mover texto | `MainWindow.move_selection`, `arrow_move`, propiedades numéricas | `EditRequest`, `Session.preview`, `engine.edit_pdf`; rutas nativas de `native_layout.py` y `clipped_layout.py` |
| Cambiar área de texto sin escalar letras | Tiradores `PdfCanvas`; `RichEditing.resize_text_area` | Recompone sólo la selección; aviso de desbordamiento |
| Agregar texto | `add_text_action` → `ExtendedEditing.begin_text/placed/text_dialog/insert_text` | `Session.insert_text`, `composition.py`; texto nuevo con fuente explícita |
| Copiar formato para nuevo texto | `copy_format_action`, `paste_format_action` | `RichEditing.copy_text_format/begin_copied_text/place_copied_text` |
| Agregar imagen | `add_image_action` → `begin_image/placed/add_image` | worker `image`, operación `add`; `media.add_image_pdf` |
| Mover y ampliar imagen | `image_mode_action`, ocho tiradores, `image_properties` | `transform_image`, worker `image`, `media.transform_image_pdf` |
| Voltear, girar libremente, recortar y sustituir imagen | `AdvancedEditing.edit_selected_image`, menú contextual | `ImageEditorDialog` → worker `image`, operación `edit`; `media.edit_image_pdf` |
| Encajar / rellenar / estirar imagen | `ImageEditorDialog.fit_box` | Matriz PDF; conserva píxeles originales, recorte recuperable |
| Exportar imagen | `image_context/export_selected_image` | `Session.export_image`, `media.export_image_pdf`; escritura temporal y atómica |
| Seleccionar objetos superpuestos | `elements_box`, `refresh_elements/select_element/next_element` | `elements.py`; zona explícita, niveles línea/palabra/carácter |
| Agrupar, alinear, distribuir y ordenar objetos | `objects_action` → `ObjectEditing.open_objects` | `ObjectDialog` → `object_operation`, `objects.py`; límites de aislamiento explícitos |
| Eliminar páginas | `delete_pages_action` → `page_dialog('delete')` | `Session.delete_pages`, `pageops.delete_pages_pdf`; historial |
| Extraer páginas | `extract_pages_action` → `page_dialog('extract')` | `Session.extract_pages`, `pageops.extract_pages_pdf`; nuevo PDF |
| Rotar, duplicar, reordenar páginas | `organize_action` → `AdvancedEditing.open_organizer` | `PageOrganizerDialog` plan → `Session.organize_pages`, `pageops.organize_pages_pdf` |
| Insertar páginas desde archivo | `PageOrganizerDialog.choose_pdf` | `import_requested`, fuentes identificadas por SHA-256; plan con posición final |
| Combinar varios PDF | `merge_action` → `choose_merge`, `MergeDialog` | `merge_pdfs` agrega al actual; `combine_pdfs` crea sesión nueva desde lista |
| Buscar y reemplazar revisado | `replace_action`, Ctrl+H | `SearchReplaceDialog`, `find_replacements`, `preview_replacements` |
| Guardar PDF | `save_action` → `choose_save/save_as` | `Session.save`, `validation.atomic_save` |

## Huecos concretos del código inspeccionado

- No hay exportación de documento a PNG/JPEG/TXT ni Word/Excel. No confundir exportar una imagen del PDF con exportar el documento.
- No hay división del documento en múltiples archivos. Se puede componer con extracción validada y selección explícita de grupos, con publicación atómica de cada salida y protección de originales.
- No hay sustitución explícita de páginas. El organizador permite quitar e insertar, pero eso no equivale a conservar los enlaces/anotaciones del destino como puede hacer Acrobat. Debe definirse si se sustituye toda la página o sólo su contenido.
- No hay recorte de páginas. Implementar CropBox es distinto de recortar imágenes; deberá comprobar rotación, MediaBox, coordenadas de enlaces, anotaciones y texto. Un recorte visual no elimina contenido confidencial.
- Una ventana gestiona una sesión/documento. Abrir cuatro documentos en una interfaz requiere ventanas independientes o un modelo de pestañas con sesiones propias. No compartir el mismo `Session` entre documentos.
- El modo de imágenes es independiente del de textos: «Editar texto e imágenes» debe alternar por impacto del clic o proporcionar un selector claro, sin crear una acción que sólo cambie el rótulo.

## Reorganización de interfaz recomendada

`MainWindow._create_ui` crea barra Documento, miniaturas a la izquierda, lienzo central y propiedades a la derecha. `ExtendedEditing._create_extended_ui` y `AdvancedEditing._create_advanced_ui` añaden otras dos barras superiores. Es viable cambiar la presentación sin reescribir los motores.

1. Conservar arriba Abrir, Guardar como, Deshacer/Rehacer, navegación, zoom, ajustar y búsqueda. Añadir botón visible Herramientas para mostrar/ocultar el panel derecho.
2. Panel derecho Herramientas con grupos plegables: **Edición del contenido** (Editar texto e imágenes, Agregar texto, Agregar imagen, Exportar archivo), **Páginas** (Rotar, Eliminar, Extraer, Reemplazar, Recortar, Dividir, Insertar desde archivo, Organizador) y **Crear** (Combinar archivos).
3. Debajo, sección contextual **Formato** y controles de imagen. Conservar las propiedades avanzadas en un grupo plegable; así no desplazan las herramientas principales fuera del área visible.
4. Reutilizar cada `QAction` mediante `QToolButton.setDefaultAction`. Su estado habilitado y sus atajos seguirán los `*_refresh_*` existentes. No duplicar acciones con callbacks independientes que queden habilitados durante una operación.
5. Guardar referencias al `QSplitter`, panel y barras (ahora variables locales) para reorganizarlos sin depender de índices. Ejecutar la reconstrucción tras `_init_objects`, cuando ya existen todas las acciones.
6. Usar pictogramas originales y una organización familiar. No extraer recursos gráficos o marcas de Acrobat para distribuirlos con PDF Modder.

## Riesgos de integración

- Tres rutas de edición: rica, nativa/con recorte, conservadora OCR/etiquetas. No quitar controles de validación para que todas parezcan aceptar lo mismo. `MainWindow.start_edit` actualmente deriva a modo conservador si **cualquier** glifo de la página tiene modo OCR 3, aunque la selección no lo tenga; revisar esta decisión sólo con una regresión específica.
- La aceptación rica ya es Aceptar/Cancelar junto al texto y Ctrl+Intro. La conservadora todavía usa vista previa y segundo Aplicar. La interfaz debe mostrar cuál está activa.
- `Session` conserva snapshots, previsualización pendiente, mapa de páginas originales e identidades de instancias. Una función nueva de páginas debe actualizar estos mapas y el historial, no sólo reemplazar bytes.
- Capacidades de página se calculan en `tagged_pages.page_capabilities` y `page_catalog`. Mantenerlas al conectar botones nuevos: formularios reales, destinos ambiguos, acciones o árboles etiquetados no admiten todas las operaciones.
- Las imágenes se editan por instancia. Sustituir directamente un xref compartido alteraría otras apariciones; usar `media.py`.
- PDF y render se ejecutan serialmente en un proceso worker. No mover estas funciones al hilo GUI al reorganizar herramientas.
- Zoom/CropBox/rotación ya están resueltos por `PdfCanvas.pdf_point/viewport_point`; usar esas conversiones también para un recorte visual de páginas.

## Pruebas existentes a reutilizar

- Interacción: `test_inline_v09.py`, `test_accept_buttons.py`, `test_rich_ui_v09.py`, `test_ui_composition.py`.
- Imágenes: `test_images_v09.py`, `test_image_tools.py`, `test_media.py`, `test_media_clips.py` (giro libre, recorte recuperable, instancia compartida, proporción y rotación/CropBox).
- Páginas: `test_page_organizer.py`, `test_pageops.py`, `test_page_catalog_v093.py`, `test_tagged_pages.py` (orden final, miniaturas, enlaces y destinos, validación de estructura).
- Texto del mapa: `test_move_serialization_v093.py`, `test_compat_ui_v092.py`, `test_native_panel_v092.py`, `test_native_paint_order_v092.py`.
- Estado/seguridad de trabajo: `test_instance_changes.py`, `test_integrity.py`, `test_objects_v09.py`, `test_validation_edges.py`.

Esta auditoría sólo localiza cobertura ya escrita; no afirma que esas pruebas se hayan ejecutado en 1.5.0. Las nuevas funciones necesitarán regresiones específicas, además de una comprobación de UI que accione herramientas desde su ubicación nueva.
