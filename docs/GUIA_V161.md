# Firma visible en PDF Modder 1.6.1

La firma digital puede incorporar un sello visible: nombre del titular a la
izquierda y datos del certificado y fecha a la derecha. Se genera con el
certificado elegido; no se reutilizan los datos ni el logotipo de una captura.

1. Abra el PDF y termine las ediciones pendientes.
2. Pulse **Firmar…** y elija su certificado instalado en Windows. La alternativa
   avanzada sigue permitiendo archivos PFX/P12.
3. Active **Mostrar firma en la página**. Elija la página y ajuste posición y
   dimensiones en milímetros, medidas desde la esquina superior izquierda de
   la página tal como se ve, incluso si está girada o recortada.
4. Pulse **Previsualizar firma y posición** para ver el sello sobre la página. La vista previa no
   firma ni solicita el PIN; la fecha definitiva se establece al firmar.
5. Pulse **Elegir destino y firmar…** y guarde una copia. Windows puede solicitar
   permiso o el PIN para usar la clave del certificado. El original se conserva.

La apariencia forma parte del campo de firma PDF y queda cubierta por su firma
criptográfica. No es una imagen pegada después de firmar. La aplicación comprueba
la integridad y la cobertura del archivo completo antes de guardar la copia.

El sello visible, por sí solo, no demuestra que una firma sea válida. Compruebe
el panel de firmas del lector PDF. La fecha procede del reloj del ordenador:
esta versión no añade un sello de tiempo de una autoridad ni consulta revocación
o confianza de la cadena. Continúan los límites de certificados y documentos
descritos en [GUIA_V160.md](GUIA_V160.md).

La firma visible es opcional. Desactive la casilla para conservar la firma
invisible del flujo anterior. Las posiciones y tamaños inválidos se rechazan;
no se desplaza el contenido existente para hacer sitio al sello.

El tamaño mínimo es 74,1 × 24,7 mm; los certificados con muchos datos requieren
un recuadro mayor. Se avisa si no cabe todo el contenido, sin truncarlo. Elija
una zona libre para evitar tapar o superponer información del documento.

Por ahora, los PDF etiquetados admiten la firma sin sello: incorporar un campo
visible requiere también integrarlo en su estructura accesible. La aplicación
lo explica antes de firmar. Tampoco admite sello visible en páginas con unidades
especiales `/UserUnit`; sí contempla CropBox desplazado y los giros de página
de 0, 90, 180 y 270 grados. La selección de lugar y dimensiones se realiza con
campos numéricos, no mediante arrastre.

## Compilar la entrega

Desde el entorno de desarrollo de Windows, ejecute el flujo específico de
1.6.1 con los módulos de firma seleccionados, o use `scripts/build.ps1 -SkipTests`
para compilar después de sus propias comprobaciones. Los resultados efectivos
de la entrega figuran en `RESULTADOS_V161.md` y `ENTREGA.json`.

La implementación utiliza `PdfSigner`, `SigFieldSpec` y la apariencia del campo,
según la [documentación oficial de pyHanko 0.33](https://docs.pyhanko.eu/en/v0.33.0/lib-guide/signing.html#signature-appearance-generation).
Las fuentes Liberation incluidas generan texto vectorial con sus propios
recursos incrustados; no se necesita instalar una tipografía adicional.
