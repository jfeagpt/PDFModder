# Edición conservadora de PDF etiquetado

Un PDF etiquetado relaciona el contenido visible con un árbol que describe su orden de lectura y su función: párrafos, fragmentos, imágenes o enlaces. Conservar la apariencia no basta para conservar esa relación. El editor mantiene sus comprobaciones de texto, geometría y píxeles y añade el análisis de estructura necesario para admitir operaciones concretas sobre documentos compatibles. No certifica PDF/UA ni la calidad editorial de las etiquetas o los textos alternativos.

## Alcance de texto

La selección de una palabra o fecha puede ocupar una parte de un contenedor marcado. La unidad de reconstrucción semántica es el contenido asociado a su MCID, identificado dentro de su página. Al sustituir o mover caracteres, se conservan los demás caracteres del contenedor en sus posiciones previstas y se reutiliza su asociación estructural. El árbol mantiene su orden de lectura, aunque un fragmento se desplace visualmente a otra posición.

Se admiten referencias de contenido mediante números MCID y diccionarios MCR, así como propiedades marcadas escritas directamente o referidas por nombre desde los recursos de la página. Se verifica la correspondencia con ParentTree y se mantienen la jerarquía, los roles y RoleMap, el idioma, el texto alternativo de figuras y las asociaciones OBJR compatibles de anotaciones. La estructura lógica y estas asociaciones están descritas en la [referencia de estructura de PDF Association](https://pdf-issues.pdfa.org/32000-2-2020/clause14.html).

Una sustitución que abarque varios MCID se bloquea si no puede determinarse una distribución semántica inequívoca del nuevo texto. El movimiento de varios contenedores puede conservar sus asociaciones y estilos porque no reemplaza su contenido. Los límites tipográficos y de aislamiento de la edición ordinaria siguen siendo aplicables; las etiquetas no permiten omitirlos.

El ajuste explícito de espacios de una línea puede desplazar palabras vecinas pertenecientes a otros MCID: cada vecino conserva su propietario, contenido, estilo y distribución interna. Los caracteres nuevos pertenecen al MCID de la palabra sustituida. El árbol determina el orden de lectura incluso cuando el orden de pintado de los streams es diferente.

## ActualText y contenido alternativo

ActualText puede sustituir el texto que una herramienta de lectura recibe de una secuencia o de un elemento estructural. Si coincide con el texto visible completo que se está reconstruyendo y su alcance es inequívoco, debe actualizarse junto con ese texto. Un valor alternativo con significado diferente o un alcance complejo se bloquea con una explicación concreta, para evitar que la pantalla muestre una fecha y la lectura accesible siga anunciando otra. No se inventa un nuevo texto alternativo. Su función y sus ubicaciones se explican en la [guía de sintaxis de PDF etiquetado](https://pdfa.org/download-area/publications/Tagged-PDF-Best-Practice-Guide.pdf).

Una figura existente conserva su imagen y su Alt durante la edición de texto ajeno a ella. Esta comprobación no evalúa si la descripción es adecuada para una persona que utiliza un lector de pantalla.

Si el elemento de texto afectado o un antecesor tiene un Alt no vacío, sustituir su contenido requiere revisión semántica manual y se bloquea. El movimiento sin cambiar el texto puede conservar ese Alt. No se aplica esa prohibición por la mera presencia de una figura ajena con texto alternativo. Cuando se actualiza un ActualText almacenado en propiedades nombradas, también se retira su recurso antiguo si deja de utilizarse, sin modificar los recursos de otras páginas.

También se bloquea reconstruir un MCID dentro de otro contenedor marcado, o que contenga un contenedor marcado interior. Esto incluye ActualText externo y marcadores sin propiedades como ReversedChars, que pueden cambiar el orden de caracteres. Retirar o reinsertar sólo el contenido interior podría dejar vigente una descripción antigua o perder el alcance semántico del contenedor. El mensaje identifica las propiedades semánticas anidadas.

Los MCID anidados también bloquean la reconstrucción del padre y del hijo: además de conservar el árbol habría que mantener el alcance exacto de cada contenedor de contenido marcado. Esta restricción no bloquea editar otro MCID independiente del mismo documento. Las pruebas de regresión incluyen un ActualText en el MCID exterior que, sin esta protección, podría conservar una fecha antigua aunque lo visible hubiera cambiado.

## Bloqueos específicos

Se rechazan MCID duplicados, ParentTree ausente o incoherente, referencias estructurales rotas, contenido marcado sin cerrar, texto visible sin una asociación verificable y capas o propiedades que no se puedan interpretar con garantías. Los atributos de maquetación vinculados a una posición requieren actualización coherente; una operación se bloquea si esa actualización no es compatible.

Añadir texto, añadir/eliminar/transformar imágenes o eliminar/extraer/combinar páginas etiquetadas requiere actualizar asociaciones o propiedades adicionales. Estas operaciones permanecen bloqueadas en el alcance actual. El motivo pertenece a la operación concreta: la presencia de etiquetas por sí sola no impide la edición de texto compatible ni su guardado.

Al abrir un documento etiquetado, la interfaz explica este alcance. Los controles para añadir contenido o reorganizar páginas aparecen deshabilitados y su ayuda indica que requieren asignar o remapear etiquetas. Las operaciones de edición o movimiento de texto existente conservan sus comprobaciones antes de aplicar cualquier cambio.

Las protecciones de documentos cifrados o restringidos, formularios y firmas continúan vigentes. La aceptación de un árbol de etiquetas no concede permisos de edición ni valida una firma digital.

## Corpus y comprobaciones

`tests/tagged_corpus.py` genera documentos reproducibles en memoria, de dos páginas, con fuentes Base-14 Helvetica y Helvetica-Bold y una imagen RGB creada para las pruebas. No contienen datos del usuario. No se presentan como documentos certificados PDF/UA.

El corpus base contiene un párrafo `Fecha: 10/09/2026` en la línea base de 100 puntos, otro `Mover PALABRA fin.` en la línea base de 150 puntos y una figura con Alt. La fecha empieza en X=100 puntos; el segundo párrafo en X=48 puntos. La página 2 conserva un texto y un fondo vectorial de control. Las variantes incluyen varios MCID de distinto estilo en una línea, propiedades nombradas, MCR explícitos, Link con OBJR, ActualText coincidente o alternativo y construcciones deliberadamente defectuosas.

El auditor de pruebas recorre el árbol y los operadores con pypdf sin invocar el analizador de producción. Comprueba ParentTree en ambos sentidos, cobertura y unicidad de MCID, relaciones de parentesco, roles, idioma, Alt, OBJR y texto en orden lógico. Su decodificación textual se limita deliberadamente a las fuentes simples de este corpus; no es un validador general de accesibilidad.

`tests/test_tagged.py` contrasta edición y movimiento, vecinos, aparición única en el destino, guardado y reapertura para una nueva edición, ActualText y bloqueos. La página de control exige identidad de todos sus píxeles a 144 ppp sin máscaras de exclusión y mantiene su texto extraído. Los archivos originales deben conservar sus bytes.

Se incluyen `examples/etiquetado.pdf` y `examples/etiquetado_actualtext.pdf`. El segundo contiene ActualText coincidente en propiedades nombradas. `scripts/acceptance_tagged.py` cambia la fecha, sustituye PALABRA por VOZ ajustando los espacios de la línea, mueve VOZ 20 puntos hacia abajo, guarda una copia y la reabre. Contrasta la lectura lógica y el texto visible, la actualización de ActualText y la ausencia de su recurso antiguo sin uso.

El script produce PDF, imágenes y un informe medido en `output/acceptance-tagged/`. Poppler renderiza el original y el resultado a 144 ppp con CropBox. Sólo se excluyen los envolventes individuales de los caracteres realmente sustituidos o desplazados en las tres operaciones, ampliados 0,75 puntos; los vecinos que no cambian mantienen comprobación visual. La página 2 exige identidad exacta sin exclusiones. El auditor de estructura es independiente del módulo `tagged.py`, pero comparte la biblioteca de parsing pypdf; Poppler aporta un renderizador distinto del motor de edición.

Para ejecutar esta batería desde la carpeta del proyecto:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_tagged.py -q
.venv\Scripts\python.exe scripts\acceptance_tagged.py
```

Para regenerar también los dos ejemplos reproducibles, añada `--generate-examples` al segundo comando.

El resultado válido es el de una ejecución terminada de la batería. Disponer de los generadores y pruebas no demuestra por sí solo compatibilidad con documentos reales ni garantiza que todos los lectores de pantalla interpreten una estructura de la misma forma.
