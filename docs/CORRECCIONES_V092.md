# PDF Modder 0.9.2: cambios y límites

Esta revisión incorpora correcciones para editar campos numéricos y nombres
fragmentados entre distintas operaciones del PDF. La entrega se compila y
empaqueta sin ejecutar más pruebas, por petición expresa del usuario. La
verificación completa del ejecutable final y del instalador queda pendiente.

## Fuentes parciales y caracteres nuevos

Un PDF puede contener una fuente con todos los glifos necesarios, pero conservar
un mapa Unicode incompleto. La nueva ruta distingue ese caso de una fuente que
carece físicamente del carácter solicitado.

Cuando el glifo ya está en el programa TrueType original, se puede recuperar su
correspondencia Unicode mediante evidencia de otros recursos del mismo documento:
se comparan las instrucciones del glifo, sus componentes y sus métricas. Se crea
un recurso PDF independiente con el mapa ampliado; el programa original de fuente
se conserva. Esta evidencia acredita la correspondencia del carácter, no la
identidad completa entre versiones de una tipografía.

La reutilización de glifos de subconjuntos complementarios requiere comprobaciones
adicionales del programa, los metadatos y los avances. Un nombre de familia igual
no autoriza una sustitución automática. Los códigos ambiguos o sin evidencia se
siguen rechazando.

Algunos campos del mapa aportado usan un subconjunto de **Calibri 6.26** que no
contiene los glifos **0 y 7** necesarios para determinados cambios. La aplicación
no puede generar esos contornos a partir del nombre de la fuente. Por ejemplo,
cambiar un campo de esa fuente a `70,48` puede requerir una fuente completa.

Para ese caso, abra **Tipografía / formato…**, active **Cambiar la fuente
explícitamente** y seleccione o importe la fuente completa adecuada. Para conservar
la tipografía, debe corresponder a la misma variante y versión; una Calibri de
otra versión no se considera idéntica por su nombre. Si elige otra fuente, el
cambio de apariencia es una decisión manual. No se descargan ni se redistribuyen
las fuentes privadas del equipo.

## Orden de objetos y texto fragmentado

Las rutas nativas modifican el texto en su posición dentro del contenido PDF,
conservando los gráficos que se pintan antes o después. Esto evita rechazar de
forma general un campo sólo porque exista un objeto posterior sobre él.

Unir varias operaciones de texto sigue requiriendo aislarlas de objetos o
caracteres intercalados. Si la operación alteraría su orden visual, se bloquea
ese cambio concreto. Los subrayados y las operaciones con solapamientos conservan
sus comprobaciones específicas; no se garantiza cualquier combinación de capas.

## Editor sobre la página y panel lateral

Se ha adaptado la edición del panel lateral para aprovechar las rutas nativas en
selecciones compatibles, además del editor sobre la página. La compatibilidad del
panel sigue siendo parcial: una selección que mezcle propiedades o no pueda
aislarse puede necesitar una selección más precisa. La comprobación completa de
ambas rutas con el paquete final queda pendiente.

Para cambiar el nombre del titular en el mapa, use la selección **Línea** e incluya
el **espacio final** del texto original. Así se trata el campo completo; seleccionar
sólo las letras puede dejar fuera un fragmento de esa misma línea. Después entre
en edición, escriba el nombre y use **Aceptar ✓** o **Ctrl+Intro**. Guarde una copia
mediante **Guardar como…**.

## Estado de esta entrega

El código incluye pruebas y herramientas de aceptación, pero esta entrega no
acredita su ejecución completa sobre la última compilación. Tampoco se ha repetido
la prueba final de instalación, edición, guardado, reapertura y desinstalación.

Los archivos de entrega declaran `tested: false`, `frozen_verified: false` y
`delivery_status: compiled_unverified`. Las sumas SHA-256 identifican los archivos
distribuidos; no son pruebas de funcionamiento. Los documentos privados aportados
no se incluyen en el instalador ni en los archivos de código.
