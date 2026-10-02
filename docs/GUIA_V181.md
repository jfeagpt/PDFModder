# Corrección del actualizador en PDF Modder 1.8.1

La versión anterior utilizaba la API REST de GitHub para consultar la última
versión y volvía a consultarla al descargar. La API sin autenticación tiene una
cuota compartida por dirección IP; otros equipos de la misma red también pueden
consumirla. Un 403/429 provocaba el aviso genérico «GitHub ha limitado temporalmente
las consultas. Inténtalo más tarde».

La ruta habitual ahora es el manifiesto público:
`https://github.com/jfeagpt/PDFModder/releases/latest/download/PDFModder-update.json`.
Este enlace oficial de descarga no necesita una cuenta o credenciales en PDF Modder
y no usa la API REST para consultar la versión. Si el manifiesto no existe (404),
se permite la ruta heredada para identificar una publicación anterior incompatible.
No se cambia de ruta ni se repite la consulta cuando el servidor limita la descarga.

Los metadatos validados se conservan cinco minutos. Buscar seguido de Descargar
reutiliza esa información; nunca utiliza indefinidamente una versión en caché.
Una nueva descarga siempre debe coincidir con el tamaño y SHA-256 del manifiesto.
También se comprueba otra vez el instalador antes de iniciarlo.

Si se recibe un plazo Retry-After o x-ratelimit-reset, el estado muestra la hora
para volver a consultar y el botón espera hasta entonces. No hay un bucle de
reintentos automáticos. Los errores no se confunden con «Tienes la última versión».

Para actualizar desde una versión cuyo buscador sigue bloqueado, descarga directamente
el instalador 1.8.1 desde GitHub Releases y ejecútalo. El instalador ofrece retirar
la instalación anterior identificada, conserva los documentos y preferencias y
solicita cerrar normalmente la aplicación anterior. Las siguientes actualizaciones
utilizan la ruta corregida.

GitHub puede limitar también descargas, y los fallos de Internet siguen siendo
posibles: esta corrección elimina la dependencia habitual de la cuota REST,
no garantiza la disponibilidad permanente del proveedor.

Comprobaciones dirigidas: manifiestos válidos e inválidos, restricciones de rutas,
SHA-256, respuestas HTTP, espera de reintentos y caché; además, recorrido del
ejecutable e instalación/actualización aisladas. Se contrastará la descarga pública
final con el propio actualizador. No se repite el corpus PDF completo histórico.

Fuentes oficiales:

- [Límites REST de GitHub](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
- [Enlaces a versiones y a su última descarga](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases).
