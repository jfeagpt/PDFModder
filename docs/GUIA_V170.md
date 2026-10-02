# PDF Modder 1.7.0

La barra superior añade Propiedades del documento, Seguridad y Buscar actualizaciones.
Junto a Deshacer/Rehacer aparecen Cortar, Copiar, Pegar y Eliminar. Seleccionar,
Escribir y Mover tienen sus propios botones; sus ayudas muestran la acción.

## Propiedades

Abra un PDF y pulse Propiedades. Puede ver título, autor, asunto, palabras clave,
programa creador/productor y fechas. La ubicación, tamaño y número de páginas
son información calculada: cambiar la ubicación requiere Guardar como, y el
número de páginas cambia con las herramientas de páginas. Los cambios de
metadatos se previsualizan/aplican y se pueden deshacer antes de guardar una copia.
No se modifican metadatos de un documento firmado: alteraría su firma.

## Seguridad

Seguridad exporta una copia cifrada y conserva el documento de trabajo.
La contraseña de apertura limita quién puede abrir la copia. Con certificado,
se cifra para el destinatario elegido: este necesita su clave privada, además
del certificado público. Un certificado público importado no permite descifrar
el documento por sí solo. El cifrado no sustituye a una firma digital.

La copia cifrada por certificado debe abrirse con un lector compatible con ese
cifrado y acceso a la clave privada. La edición del PDF cifrado en PDF Modder
sigue limitada; guarde también una copia de trabajo sin cifrar en un lugar seguro.
No se almacenan contraseñas ni se exportan claves privadas de Windows.

## Portapapeles e historial reciente

Seleccione un texto o imagen y utilice los botones, el menú del botón derecho
o Ctrl+X/C/V y Supr. Al pegar un objeto, elija su posición sobre la página.
Dentro de un editor de texto, los atajos actúan sobre las letras del borrador.
Copiar conserva las propiedades disponibles y verificadas; las operaciones
incompatibles muestran el motivo en lugar de sustituir fuentes silenciosamente.
La pestaña Recientes permite reabrir archivos por su ruta local. No sube PDFs
ni historial a Internet y no almacena la contraseña del documento.

## Actualizaciones y publicación

Buscar actualizaciones consulta manualmente las Releases públicas de
https://github.com/jfeagpt/PDFModder. No requiere una cuenta en el editor.
Si encuentra una versión posterior, permite descargarla, comprueba su tamaño y
SHA-256 y ofrece abrir el instalador. Se pide guardar o descartar el trabajo antes
de instalar. Un repositorio privado o sin releases produce un aviso específico.

Cada release requiere su instalador y PDFModder-update.json; también pueden
publicarse el código y la versión portable. La publicación no está implementada
dentro de PDF Modder: las credenciales administrativas nunca forman parte del
programa distribuido. Desde el proyecto, scripts/publish_github_releases.py
prepara los manifiestos con --all --prepare-only, o sube las entregas con --all
usando una credencial administrativa legítima. No cambia la visibilidad del
repositorio ni sustituye archivos de releases ya publicadas.

La prueba de publicación y la descarga desde GitHub requieren acceso operativo
al repositorio y releases publicadas. La entrega local y sus comprobaciones se
documentan por separado; un aviso de actualización no demuestra una subida.
