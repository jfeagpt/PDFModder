# PDF Modder 1.6.0

Instalador Windows x64: `releases/v1.6.0/PDFModder-v1.6.0-Instalar.exe`.
La entrega 1.5.0 permanece en su carpeta. Las comprobaciones de esta versión
son dirigidas a los cambios; no se repite toda la batería de la versión anterior.

## Firmar digitalmente

1. Abra el PDF y termine sus ediciones. Acepte o cancele cualquier vista previa.
2. Pulse **Firmar…** en la barra superior.
3. Elija uno de los **certificados instalados en Windows** que la aplicación
   presenta. Puede añadir un motivo y un lugar. Si su proveedor requiere PIN,
   Windows o el proveedor del certificado lo solicitará durante la firma.
4. Elija otra ruta para guardar la copia firmada.

Se crea una firma criptográfica de aprobación SHA-256 y se comprueba su
integridad antes de guardar los bytes firmados. La firma aparece en el panel de
firmas de un lector compatible; no añade una imagen de firma ni un sello visible.
La copia original y el trabajo abierto continúan sin firmar. Al abrir la copia
firmada, la edición ordinaria queda protegida para no invalidarla.

La aplicación accede al almacén Personal del usuario y del equipo, y utiliza
la clave mediante el proveedor de Windows, sin exportarla. Como alternativa
permanece la importación de un archivo PFX/P12 con contraseña. La contraseña
no se conserva en preferencias, historial ni informes. No se contacta con servicios de
sellado de tiempo, revocación o confianza. La comprobación criptográfica no
acredita la identidad del titular, la confianza del destinatario ni validez
jurídica. El lector del destinatario puede mostrar confianza desconocida.

Alcance inicial: certificados RSA del almacén Personal de Windows con clave
privada accesible, o archivos PFX/P12 con RSA de al menos 2048 bits o EC compatible. El
certificado debe estar vigente según el reloj del equipo y permitir la firma.
No se admiten en este flujo PDF cifrados, certificados caducados ni documentos
que ya contienen firmas o campos de firma. Los proveedores de tarjeta dependen
de sus controladores y acceso a la clave; no se acredita una prueba con DNIe o
una tarjeta física. No se incluyen múltiples firmas ni firma visible.

## Texto e imágenes en PDF etiquetados

**Mover texto:** se conservan las asociaciones del texto, su orden lógico y la
estructura accesible cuando la selección y su recorte pueden aislarse. El recorte
propio se traslada junto al texto, sin ampliar recortes compartidos. Las
selecciones que requieren rehacer atributos de disposición o cajas semánticas
mantienen un aviso específico.

**Agregar texto:** la herramienta pide la posición de lectura al principio o al
final de la página y añade una etiqueta de párrafo. Esta primera versión permite
un párrafo por operación; el ajuste visual de línea dentro de él está permitido.
Para párrafos independientes, repita la inserción. No se asigna una posición
inventada cuando la estructura de la página no permite verificarla.

**Agregar imagen:** indique una descripción alternativa y el inicio/final de
lectura, o marque expresamente que es sólo decorativa. Se crea una figura
etiquetada o un artefacto decorativo, respectivamente. La imagen y las etiquetas
existentes permanecen asociadas a su contenido original.

Estas comprobaciones conservan la estructura admitida, pero no certifican
PDF/UA ni reparan todos los defectos previos del archivo. La sustitución de
páginas entre documentos etiquetados no forma parte de los cambios solicitados
para esta versión.

## Controles

- **Resaltar cambios** comienza desactivado. Puede activarlo en las herramientas
  avanzadas cuando necesite comparar.
- **Edición del contenido**, **Formato** y **Páginas** comienzan plegados. Pulse
  en cada cabecera para desplegarla.
- Los botones **− / +** junto a Zoom reducen o amplían desde el zoom actual.
- Seleccione una imagen y arrastre su interior para moverla. Use los ocho
  tiradores de bordes/esquinas para cambiar sus dimensiones. El tirador circular
  separado del marco permite girarla alrededor del centro sin reducir su tamaño.
  **Mayús** ajusta el giro a pasos de 15 grados y **Esc** cancela el gesto.
  Cada gesto aplicado forma una unidad de deshacer. El PDF renderizado tras
  soltar muestra el resultado real. Una imagen que no pueda aislarse o que salga
  de los límites admitidos conserva un bloqueo concreto.

Después de un giro libre, el diálogo anterior de recorte/encuadre puede rechazar
la imagen por su matriz inclinada. Los tiradores de movimiento, tamaño y giro
siguen admitiendo operaciones encadenadas sobre las instancias compatibles.

La [guía de 1.5.0](GUIA_V150.md) describe el resto de herramientas. Las novedades
y límites de esta guía prevalecen sobre sus restricciones históricas.
