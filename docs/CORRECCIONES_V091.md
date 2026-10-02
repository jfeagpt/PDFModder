# PDF Modder 0.9.1: compatibilidad de contenido y páginas

Esta entrega corrige problemas reproducidos con dos PDF facilitados privadamente.
Los documentos originales y sus resultados de prueba no se distribuyen.

## Qué cambia

- **Estado gráfico:** el valor PDF `false` se leía mediante la veracidad de su
  objeto Python y provocaba un falso aviso de sobreimpresión. Ahora se interpreta
  el valor PDF real, las referencias indirectas, los estados aplicados, la pila
  `q/Q` y los formularios gráficos. `TR /Identity` y `TR2 /Default` se reconocen como
  estados neutros; se respeta la precedencia de `TR2` y de `op` respecto de `OP`.
  Los operadores originales permanecen en el PDF. Los efectos reales que el motor
  no puede reproducir continúan bloqueados con un motivo concreto.
- **PDF etiquetado:** eliminar o extraer páginas ya no está desactivado sólo por
  existir etiquetas. Se conserva el árbol de las páginas restantes y se eliminan
  las asociaciones de las páginas excluidas: `MCID`, `ParentTree`, `MCR`, `OBJR`
  e identificadores estructurales se comprueban. Se permiten giro, página en blanco
  y reordenación de ramas compatibles. El organizador muestra únicamente las
  operaciones disponibles y vuelve a validar el plan antes de aplicarlo.
- **Texto etiquetado con recortes:** doble clic abre el editor nativo sobre la
  página. La sustitución queda dentro de su contenido marcado y conserva los
  recortes; se valida el texto lógico de las etiquetas y se actualiza `ActualText`
  cuando su relación con el texto visible es inequívoca. Un estado de opacidad
  que no cambia la fuente ya no invalida el tamaño vigente del texto.
- **Avisos:** se distingue un documento con una protección real de un documento
  etiquetado compatible. El aviso de apertura indica las acciones disponibles.
- **Fuentes CID CFF parciales:** cuando el carácter falta en el subconjunto
  seleccionado, se pueden utilizar subconjuntos complementarios ya presentes en
  la misma página. Deben coincidir los metadatos de fuente y los programas Type2,
  instrucciones de ajuste y avances CFF de todos los glifos comunes, con al menos
  un glifo visible compartido. No basta el nombre de familia. La comprobación no
  acredita la identidad binaria de una fuente completa desconocida; la evidencia
  indica los recursos usados. No se modifica ni se vuelve a incrustar su programa.
  Se comprueba también que los avances declarados en `/W` o `/DW` no contradigan
  los avances del programa, y se conserva la escala del texto seleccionado.
  Este es el caso del «6» necesario para cambiar el año del mapa.

## Cómo usarlo

1. Instale `PDFModder-v0.9.1-Instalar.exe` y abra **PDF Modder 0.9.1**.
2. Abra el documento original; seleccione la palabra que desea corregir y haga
   doble clic. En el editor sobre la página cambie el texto y pulse **Aceptar ✓**
   o **Ctrl+Intro**. La vista lateral representa el PDF que se guardará.
3. Para documentos etiquetados que mantienen la edición conservadora anterior,
   **Ctrl+Intro** genera la vista previa y **Aplicar cambio** la confirma. La
   propia interfaz indica ese flujo.
4. Use **Eliminar páginas**, **Extraer páginas** u **Organizar páginas** cuando
   estén disponibles. Revise el orden y confirme la vista previa.
5. Guarde con **Guardar como** en un archivo nuevo. Puede deshacer la operación
   antes de guardar; un fallo conserva el documento de trabajo.

## Alcance y límites

Conservar la estructura accesible no equivale a certificar PDF/UA. Se bloquea una
operación si encuentra relaciones a una página excluida, texto alternativo que
necesita revisión, una estructura inválida o ramas que no puedan seguir el orden
solicitado. Duplicar páginas etiquetadas, combinar sus árboles o agregar contenido
nuevo accesible aún requieren soporte adicional. No se elimina la accesibilidad
para permitir esas operaciones.

La cabecera del Anexo contiene artefactos, distintos del texto de sus párrafos.
El soporte demostrado de edición corresponde al texto etiquetado compatible del
cuerpo. Fuentes parciales sin caracteres nuevos, artefactos y atributos semánticos
no reproducibles siguen mostrando su límite concreto. No se sustituyen fuentes
automáticamente por tipografías parecidas.

Los controles laterales y algunas operaciones por lotes conservan el motor
anterior; para la corrección con recursos parciales del mapa se utiliza el editor
nativo mediante doble clic. No se promete compatibilidad universal con otros PDF.

## Comprobación y reproducción

En Windows 11 x64, esta entrega ha superado **653 pruebas automáticas**. El
ejecutable empaquetado ha completado **seis recorridos de interfaz, 118 pasos**,
incluyendo los tres casos nuevos de etiquetas con recortes, estados neutros y
subconjuntos CFF. También han pasado **14 casos de aceptación con Poppler**:
ocho regresiones y seis operaciones sobre los dos documentos comunicados.
En estos últimos se comprobó el cambio 2025 → 2026, dos sustituciones de palabras,
eliminación, extracción y reordenación. La mayor exclusión visual de esos seis
casos fue el 0,156159 % de una página; hubo cero píxeles fuera de tolerancia en el
resto. Las páginas copiadas se compararon completas, sin exclusiones.

Los dos documentos se probaron además desde la interfaz con aceptación, guardado
y reapertura, manteniendo intactos los originales. Estas mediciones corresponden
a este equipo y corpus, no a una garantía de compatibilidad universal.

Las pruebas cubren el guardado completo, reapertura, texto y vecinos, etiquetas,
historial, controles de interfaz y las páginas copiadas. Los PDF aportados se
contrastan además con pypdf y Poppler a 144 ppp. Sólo se excluyen las cajas de los
glifos editados y sus destinos, ampliadas 0,75 pt para el antialias; el umbral es
8/255. Las páginas no editadas y las copiadas no admiten exclusiones ni diferencias.

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe scripts/acceptance_v091.py --anexo "RUTA_ANEXO.pdf" --mapa "RUTA_MAPA.pdf"
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/verify_executable.ps1
```

Para contrastar recursos de fuente que pypdf separa heurísticamente, instale
`pdfminer.six==20251230` en un entorno de validación y añada
`--independent-python "RUTA_A_ESE_PYTHON.exe"` al comando de aceptación. Es una
herramienta de pruebas, no una dependencia del editor distribuido.

Los resultados numéricos de esta compilación están en `ENTREGA.json` junto al
instalador; la prueba de instalación y retirada está en `INSTALACION-VERIFICADA.json`.
La evidencia de 0.9.0 se conserva como histórica y no acredita por sí sola 0.9.1.

En el mapa, pypdf añade un espacio heurístico al extraer el cambio de recurso
tipográfico dentro del año. MuPDF y pdfminer.six extraen «2026» seguido, y el PDF
conserva texto real. El informe registra qué extractor confirma cada fragmento,
sin borrar espacios para hacer que una comprobación pase.

Referencia de semántica gráfica: Adobe, *PDF Reference 1.6*, tabla 4.8, páginas
191–192 ([documento original publicado por Adobe, copia alojada por PRINTING United Alliance](https://printtechnologies.org/standards/files/pdf-reference-1.6-1.pdf)).
