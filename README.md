# PDF Modder 1.8.1

Editor local para Windows 11 x64, en español: texto PDF real, imágenes y páginas.
No necesita cuentas, nube, telemetría ni IA. No realiza OCR; conserva la herramienta
anterior para corregir una capa buscable existente.

## Instalar o ejecutar

Descargas y versiones públicas: [GitHub Releases](https://github.com/jfeagpt/PDFModder/releases).
El botón **Buscar actualizaciones** consulta este mismo repositorio, sin iniciar sesión.

Instalador: `releases/v1.8.1/PDFModder-v1.8.1-Instalar.exe`. Incluye las dependencias
y registra su desinstalador en Aplicaciones instaladas. La alternativa portable
requiere toda la carpeta `PDFModder`, con `_internal` junto a `PDFModder.exe`.
Ejecute el instalador y pulse **Instalar**; después abra **PDF Modder 1.8.1** desde
el acceso creado. **Actualizar ahora** descarga, verifica e instala la actualización,
cierra la aplicación tras resolver los cambios pendientes y retira la instalación
anterior identificada cuando la nueva instalación termina correctamente. Conserva
documentos personales y preferencias. Para retirarla, use **Desinstalar PDF Modder 1.8.1** o
la entrada correspondiente de Aplicaciones instaladas de Windows.

Desde el código, con Python 3.12 x64:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -Development
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

Con el entorno ya instalado: `.venv/Scripts/python.exe run_pdfmodder.py`.

## Corrección 1.8.1

La búsqueda de actualizaciones usa el manifiesto de descarga público de GitHub,
sin consumir normalmente la cuota de la API REST compartida por dirección IP.
Reutiliza los metadatos validados durante cinco minutos y evita consultarlos de nuevo
entre Buscar y Descargar. Si GitHub indica un plazo de espera, lo muestra y evita
reintentos prematuros. Conserva la comprobación SHA-256 antes de ejecutar el instalador.
Consulte [la corrección y sus límites](docs/GUIA_V181.md).

## Novedades 1.8.0 (histórico)

Lectura continua con páginas apiladas, carga de páginas cercanas y caché limitada.
Selección y copia de varios párrafos y páginas, mediante arrastre o Mayús+clic.
Actualización con retirada de la instalación anterior y botón para preparar una copia
sin etiquetas de accesibilidad. Consulte [uso y límites](docs/GUIA_V180.md).

## Novedades 1.7.1 (histórico)

Propiedades y metadatos, exportación cifrada con contraseña o certificado, pestaña Recientes,
portapapeles de texto e imágenes, botones de modos y nuevos pictogramas. Actualizaciones
manuales mediante GitHub Releases públicas. Consulte [uso y límites](docs/GUIA_V171.md).

## Novedades 1.6.2 (histórico)

Puede elegir el área de la firma visible dibujando un rectángulo con el cursor
sobre el documento. Escape cancela la selección; la vista previa y el guardado
utilizan el área elegida. Consulte [cómo utilizarla](docs/GUIA_V162.md).

## Novedades 1.6.1 (histórico)

Firma visible opcional con los datos del certificado, vista previa sobre la
página y controles de posición y dimensiones en milímetros. La apariencia
queda cubierta por la firma criptográfica. Consulte [cómo utilizarla](docs/GUIA_V161.md).

## Novedades 1.6.0 (histórico)

Firma digital local con certificados instalados en Windows o PFX/P12; inserción accesible de texto e imágenes
y movimiento de texto etiquetado con recortes compatibles. Paneles laterales
plegados y resaltado desactivado al iniciar; botones de zoom y giro de imagen
mediante tirador. Consulte [uso, alcance y comprobaciones de 1.6.0](docs/GUIA_V160.md).

## Herramientas 1.5.0 (histórico)

El panel derecho **Herramientas** reúne **Edición del contenido**, **Formato** y
**Páginas**. Permite seleccionar texto e imágenes en el mismo modo, mantiene el
formato junto a la selección y añade accesos a operaciones de imagen y páginas.
Los pictogramas son propios de PDF Modder.

Esta versión incorpora reemplazar páginas completas, recortar el área visible
sin borrar contenido, dividir un PDF por grupos o número de páginas y exportar
a TXT, PNG, JPEG o SVG. Conserva la previsualización, el historial y los bloqueos
de integridad. No convierte a Word o Excel ni garantiza compatibilidad universal.
Consulte la [guía de uso y alcance de 1.5.0](docs/GUIA_V150.md), los
[resultados de esta entrega](docs/RESULTADOS_V150.md) y el
[registro de observaciones de Acrobat](docs/OBSERVACION_ACROBAT_V150.md).

## Correcciones 0.9.3

Permite eliminar páginas de documentos compatibles con formularios vacíos y
destinos con nombre, conservando sus referencias. Corrige el falso bloqueo al mover
texto causado por el redondeo decimal de operadores PDF. Consulte
[cambios, pruebas dirigidas y límites 0.9.3](docs/CORRECCIONES_V093.md).
En aquella entrega quedó pendiente la comprobación final del ejecutable y del
instalador; los resultados de 1.5.0 se documentan por separado.

## Correcciones 0.9.2

Esta revisión se centra en los campos numéricos y nombres compuestos por varios
fragmentos PDF, manteniendo su orden visual durante la edición sobre la página
y desde el panel. Consulte [cambios y límites 0.9.2](docs/CORRECCIONES_V092.md).
Por petición del usuario, esta entrega se compila y empaqueta sin más pruebas:
la verificación final del ejecutable y del instalador queda pendiente. Los informes
de versiones anteriores no acreditan esta compilación.

## Correcciones 0.9.1

La comprobación de color distingue la sobreimpresión desactivada de la activada,
y reconoce las transferencias neutras. Los PDF etiquetados compatibles permiten
eliminar, extraer, girar y reorganizar páginas conservando sus relaciones accesibles.
El doble clic en texto etiquetado con recortes usa la edición nativa validada.
Consulte [correcciones, pruebas y límites 0.9.1](docs/CORRECCIONES_V091.md).

## Edición 0.9

1. Abra o arrastre un PDF. Seleccione palabra, línea, bloque o caracteres.
2. Doble clic, o modo **Escribir** y clic: el cursor se coloca en el punto elegido.
   No se selecciona todo automáticamente; use Ctrl+A si quiere sustituir todo.
3. Arrastre para marcar letras. La barra junto al texto cambia sólo ese rango:
   fuente, variante real, tamaño, color, espaciado entre caracteres y subrayado.
4. **Intro** crea un párrafo; **Mayús+Intro**, una línea del mismo párrafo. Los
   controles incluyen sangrías, tabulaciones, interlineado y espacio anterior/posterior.
5. La muestra lateral y **Ver PDF real** muestran el PDF generado por el motor.
   **Aceptar ✓ / Ctrl+Intro** valida y aplica una operación de historial.
   **Cancelar × / Esc** descarta el borrador. Un fallo conserva lo escrito.
6. Ocho tiradores cambian el área de texto y redistribuyen sin escalar letras.
   El desbordamiento se informa antes de aceptar. **Mover** distingue arrastrar
   objetos de seleccionar letras; las flechas dentro del editor mueven el cursor.
7. **Objetos y bloques…** permite agrupar textos e imágenes, alinear, distribuir,
   unir fragmentos elegidos, dividir selecciones y ordenar ámbitos PDF compatibles.
8. **Copiar formato** y **Añadir con formato copiado** reutilizan en la misma página
   el recurso verificado; se comprueba la cobertura de los caracteres nuevos.
9. Imágenes: ocho tiradores, volteo, giro libre, **Encajar**, **Rellenar recortando**
   y **Estirar** explícito. El recorte nuevo es reversible y afecta sólo a esa instancia.
10. Use **Guardar como…** y reabra la copia. El archivo original se protege.

Consulte [guía y límites 0.9](docs/GUIA_V09.md), [verificación 0.9](docs/VERIFICACION_V09.md)
y [licencias](docs/LICENCIAS.md). Las pruebas históricas no acreditan el paquete nuevo.

## Compatibilidad

El modo estricto no elige fuentes parecidas ni simula negrita/cursiva. Qt muestra
programas tipográficos verificados cuando puede cargarlos; las incompatibilidades
se indican. El render del PDF es la referencia final frente al borrador Qt.
La edición rica admite texto horizontal compatible, páginas giradas y CropBox.
Recursos, recortes, permisos, firmas y elementos vecinos siguen verificándose.

OCR invisible y documentos etiquetados mantienen las comprobaciones de sus capas
y relaciones. El editor rico admite selecciones etiquetadas compatibles con recortes;
artefactos, semántica ambigua y operaciones no soportadas se explican al intentar editarlos. Los grupos se
guardan como datos propios de PDF Modder, no como etiquetas accesibles. Una edición
externa puede invalidarlos. Cambiar el orden requiere ámbitos gráficos completos
y aislables; no se separa un operador de sus matrices ni se incluyen vecinos implícitos.

Se conservan búsqueda/reemplazo revisado, organizador de páginas, exportación de
imágenes e historial de la base 0.8. La [referencia histórica](docs/HISTORICO_README_V083.md)
documenta esas rutas. Su aceptación antigua en dos pasos sigue utilizándose para
OCR/etiquetas y el panel lateral, no en el nuevo editor rico.

## Construir

```powershell
.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=tmp/pytest-local
powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipTests
.venv/Scripts/python.exe scripts/build_current_installer.py
```

Para reproducir la entrega verificada de 1.5.0, ejecute
`scripts/verify_source_v150.py` antes de compilar y
`scripts/verify_executable.ps1` después. El protocolo de aceptación y los pasos
para empaquetar con sus informes se describen en `docs/RESULTADOS_V150.md`.
El constructor del instalador por sí solo no acredita las pruebas.

`-SkipTests` evita repetir la batería ya ejecutada. PyInstaller se ejecuta en Windows;
el paquete reúne código, avisos, dependencias y desinstalador. Las versiones se fijan
en `requirements.txt`. Este proyecto se distribuye bajo AGPL-3.0-or-later por sus
condiciones y las de PyMuPDF/MuPDF; Qt/PySide6 tienen condiciones LGPL/comerciales.
Consulte `docs/LICENCIAS.md`. No se redistribuyen fuentes instaladas del usuario.
