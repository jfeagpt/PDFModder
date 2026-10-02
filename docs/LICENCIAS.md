# Licencias y redistribución

El código propio de PDF Modder se entrega bajo **AGPL-3.0-or-later**. El texto íntegro está en `LICENSE`. Esta decisión permite entregar una aplicación de código abierto basada en la edición comunitaria de PyMuPDF, sin SDK de pago obligatorio. Las licencias de bibliotecas, intérprete y fuentes siguen siendo las de sus titulares; la licencia de la aplicación no cambia las de los documentos editados.

Este documento registra las decisiones de la entrega y las fuentes oficiales consultadas el 10 de septiembre de 2026. El uso privado/local no publica automáticamente archivos PDF ni código. Si se distribuyen copias de la aplicación a terceros, la AGPL exige conservar avisos, conceder sus derechos y facilitar el código fuente correspondiente de la obra cubierta. También contiene obligaciones para versiones modificadas que ofrezcan interacción remota. PDF Modder no implementa un servicio de red. Véase el [texto oficial de la AGPL](https://www.gnu.org/licenses/agpl-3.0.html).

## Componentes fijados

| Componente | Versión | Licencia declarada / uso |
|---|---|---|
| [PyMuPDF / MuPDF](https://pypi.org/project/PyMuPDF/1.26.7/) | 1.26.7 | AGPL v3 o contrato comercial de Artifex. Lectura, render y edición del PDF. |
| [PySide6, Essentials, Addons y Shiboken6](https://pypi.org/project/PySide6/6.10.2/) | 6.10.2 | Qt for Python Community: LGPLv3/GPLv3 según componente; alternativa comercial. La aplicación usa QtCore, QtGui y QtWidgets. |
| [fontTools](https://pypi.org/project/fonttools/4.61.1/) | 4.61.1 | MIT. Inspección tipográfica. |
| [pypdf](https://pypi.org/project/pypdf/6.6.0/) | 6.6.0 | BSD-3-Clause. Inspección, análisis de operadores de imagen y clonación de páginas. Contrasta texto escrito por MuPDF; Poppler aporta el contraste visual independiente de la cadena completa. |
| [Pillow](https://pypi.org/project/Pillow/12.1.0/) | 12.1.0 | MIT-CMU; sus ruedas contienen además avisos de bibliotecas nativas. |
| [NumPy](https://pypi.org/project/numpy/2.4.1/) | 2.4.1 | BSD-3-Clause y avisos de bibliotecas incluidas en su rueda. |
| [ReportLab](https://pypi.org/project/reportlab/4.4.9/) | 4.4.9 | BSD. Generador del corpus de pruebas; no es el editor. |
| [pytest](https://pypi.org/project/pytest/9.0.2/) / [pytest-qt](https://pypi.org/project/pytest-qt/4.5.0/) | 9.0.2 / 4.5.0 | MIT. Herramientas de pruebas. |
| [PyInstaller](https://pyinstaller.org/en/v6.18.0/license.html) | 6.18.0 | GPL con excepción para aplicaciones empaquetadas; determinados archivos Apache-2.0. Herramienta de construcción. |
| [CPython](https://docs.python.org/3.12/license.html) | 3.12 x64 | PSF y avisos de componentes incorporados; versión exacta en el inventario de cada paquete. |

Estas versiones existen en las publicaciones oficiales enlazadas; no se presentan como las últimas disponibles. Las versiones exactas instaladas, transitivas y avisos de sus ruedas se recopilan durante cada construcción. `requirements.txt` fija también las ruedas transitivas Qt. El inventario `requirements-build-lock.txt` permite reconstruir el entorno concreto; no equivale a una garantía de binarios idénticos ni a un archivo de hashes de descarga.

## PyMuPDF / MuPDF: decisión de licencia

Artifex mantiene ambas bibliotecas y [ofrece AGPL y licencia comercial](https://pymupdf.readthedocs.io/en/latest/about.html). No basta con mantener cerrado el código de la aplicación y añadir el nombre de PyMuPDF a los créditos para distribuir una solución propietaria. Esta entrega distribuye su código como AGPL. Si se desea una licencia propietaria o no se pueden cumplir las obligaciones AGPL, hay que evaluar un contrato comercial con [Artifex](https://artifex.com/licensing/). Esa alternativa no es una dependencia de funcionamiento ni se compra automáticamente.

El paquete generado incluye el código completo de **PDF Modder** y scripts de reconstrucción. Los textos de licencia e inventario se incorporan a `_internal/licenses`; el código de la aplicación, a `_internal/source/PDFModder`. Los enlaces a repositorios de terceros son información de procedencia, **no sustituyen por sí solos una entrega u oferta válida de código correspondiente**. Antes de redistribuir binarios a terceros, acompañe las fuentes correspondientes exactas de los componentes AGPL/LGPL/GPL incluidos y sus modificaciones, o utilice otra modalidad permitida por su licencia. La compilación local no descarga silenciosamente esos archivos de terceros.

## Qt / PySide: bibliotecas reemplazables

[Qt documenta varias modalidades de licencia](https://doc.qt.io/qt-6/licensing.html), y algunos módulos sólo están disponibles bajo GPL o comercial. [Qt for Python](https://doc.qt.io/qtforpython-6.10/commercial/index.html) distingue sus distribuciones comunitaria y comercial. Esta aplicación utiliza la comunitaria, conserva los avisos de las ruedas y se empaqueta como **onedir**: las DLL de Qt y extensiones de Python permanecen separadas. No hay cifrado, verificación de firma propia ni bloqueo deliberado de su sustitución por versiones modificadas compatibles. No se prohíbe la ingeniería inversa necesaria para depurar modificaciones de esas bibliotecas.

Para reemplazarlas, conserve una copia del paquete y sustituya en `_internal/PySide6` (y `shiboken6` cuando proceda) los binarios por una compilación compatible con la ABI, arquitectura y versión de Python; alternativamente reconstruya el paquete desde el código entregado. Cambiar una DLL por una versión incompatible puede impedir su arranque. El formato onedir facilita esa sustitución, pero no exime del resto de [obligaciones LGPL descritas por Qt](https://www.qt.io/development/open-source-lgpl-obligations), incluido el código correspondiente de Qt cuando sea exigible.

## Inventario y avisos transitivos

### Firma local incorporada en 1.6.0

pyHanko 0.33.0 y pyhanko-certvalidator 0.29.1 se distribuyen bajo MIT.
cryptography 50.0.1 utiliza Apache-2.0 o BSD-3-Clause y contiene avisos de
sus componentes nativos. Sus licencias, las de ASN.1, XML y demás dependencias
se recopilan con las ruedas exactas en el inventario de la entrega. No se
incluyen certificados personales ni claves privadas. La firma utiliza un
certificado aportado por el usuario; no requiere un SDK de pago ni un servicio
de sellado de tiempo. Véase la [documentación de pyHanko](https://docs.pyhanko.eu/en/v0.33.0/).

`scripts/collect_licenses.py` recorre las distribuciones del entorno de construcción, copia archivos `LICENSE`, `COPYING`, `NOTICE`, `COPYRIGHT` y directorios `licenses`, además de sus metadatos. Conserva también los avisos de herramientas de pruebas/construcción, aunque alguna no forme parte del ejecutable. Incluye la licencia del intérprete. El inventario JSON registra versiones, enlaces declarados, requisitos y SHA-256 de cada aviso copiado; el manifiesto del código registra sus archivos y hashes.

El script aborta si falta una versión de runtime fijada o no encuentra su licencia. Es una recopilación reproducible de los avisos publicados, no una auditoría jurídica automática de cada componente nativo. Para una distribución pública, revise los avisos del paquete final y las fuentes correspondientes de los binarios realmente incorporados.

## Fuentes tipográficas y documentos

No se copian ni redistribuyen fuentes de `C:\Windows\Fonts` en el paquete. Que una fuente esté instalada no autoriza a redistribuir su archivo. La aplicación comprueba, cuando existe, el campo `OS/2.fsType`; ese dato es una señal técnica sobre la incrustación, no una licencia completa ni prueba de titularidad. Las fuentes importadas por el usuario mantienen sus condiciones originales. Consulte al proveedor oficial si esas condiciones no permiten la operación.

Los ejemplos generados por las pruebas son documentos sintéticos; su generador se incluye para reproducirlos. Los recursos tipográficos propios o de terceros que el corpus incluya deben conservar su licencia al lado del archivo. No se empaquetan documentos reales del usuario ni fuentes extraídas de ellos automáticamente.
