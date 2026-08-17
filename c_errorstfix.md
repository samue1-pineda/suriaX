# Informe de errores y riesgos visibles en el repositorio

**INFORME DE LA VERSION PUBLICA 0.1.4**

Este documento resume los problemas y riesgos que se observan actualmente en el proyecto, errores a solucionar en la proxima version

**importante**: cada version lanzada al publico puede venir con errores, los mas importantes saldran en este resumen.

## Resumen general

El repositorio muestra un estado de desarrollo constante pero todavía no está en una condición de publicación como "versión estable". La parte de frontend e intérprete es la mas avanzada en esta version mientras que el backend C++/LLVM estan congelados, y hay varios puntos que conviene corregir proximamente


## Problemas visibles

### 1. Errores en librerías de ejemplo y math

El archivo [lib/math/basic.libsrx](lib/math/basic.libsrx) contiene funciones con sintaxis que el editor marca como inválida. El error reportado es del tipo:

- se esperaba ';' y se encontró 'fn'

Esto sugiere que la estructura o la gramática aceptada por el parser no está alineada con lo que el archivo intenta escribir.

#### solucion propuesta

ardua revision para la version **0.1.1** del todas las fases antes de la semantica.

**pospuesto para la version 0.1.6**

### 2. Inconsistencias de sintaxis con la filosofía del lenguaje

Se observan varios archivos bajo [lib/](lib/) usando prefijos como "public fn", "private fn" y "public const". Eso puede ser válido según el parser, pero conviene validar si el dialecto actual del proyecto lo acepta de forma consistente en todas las fases del pipeline.

#### solucion propuesta

establecer los prefijos semanticos como opcionales, cualquier funcion creada es publica por defecto propuesto para la version **0.1.12**

### 3. Backend C++ aún incompleto

El roadmap deja claro que el backend C++/LLVM sigue incompleto. En [ROADMAP.md](ROADMAP.md) se indica que:

- el lector de HIR en C++ está pendiente,
- el lowering a MIR no está implementado,
- la generación de LLVM IR no está implementada,
- y la integración con "#extern cpp{}" vía pybind11 sigue pendiente.

#### pospuesto para V.0.4.0

### 4. Dependencia nativa de pybind11 / C++

El archivo [runtime/logic_mem/CMakeLists.txt](runtime/logic_mem/CMakeLists.txt) agrega una dependencia real de pybind11. Aunque el código pueda funcionar sin punteros o sin usar esa ruta, la presencia de esa dependencia significa que la publicación de un binario o paquete nativo no es completamente trivial.

#### recomendacion

si no se desea instalar esta dependencia no usar punteros y/o & asi mismo **RBMM**(*region based memory management*)

### 5. Riesgo de ejecución con hooks y memoria

Los documentos de librerías y el runtime muestran que ciertos mecanismos como hooks, dunders(***intrinsics***), memoria y punteros son parciales o dependientes del intérprete. El archivo [lib/HOOKS.md](lib/HOOKS.md) deja claro que algunos casos cross-módulo aún no funcionan, lo que es un riesgo si se quiere publicar una versión con varias librerías interconectadas.

#### solucion propuesta

para la version **0.2.0** dejar la depencia al runtime para el sistema de librerias nativo

### 6. Documentación desalineada con el código

Hay varios documentos en la raíz y en la documentación que parecen estar desactualizados respecto a lo que el proyecto realmente soporta. Esto es un problema para una publicación porque podria confundir a cualquiera.

#### solucion (casi terminado)

para la version **0.1.1** ardua correcion de los readme, la version se lanza bajo presion y con cambios muy recientes asi que es importante destacar que **multiples archivos y readme pueden ser extraños o poco comprensibles**

*happy coding : )*