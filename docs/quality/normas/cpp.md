# C++: C++ Core Guidelines, análisis estático y sanitizadores

La VM de suriaX (`backend/`: lector del HIR, MIR y máquina virtual) está
escrita en C++20. También el módulo de memoria nativa del intérprete
(`runtime/logic_mem/`). Estos son los lineamientos y las herramientas con que
se revisa ese código.

## Lineamiento: C++ Core Guidelines

**Qué es.** La guía de uso moderno de C++ que mantienen Bjarne Stroustrup y
Herb Sutter (isocpp.org). Cubre interfaces, recursos (RAII), punteros y
límites, tipos, conversiones, concurrencia y errores.

**Por qué.** Es la guía de referencia del lenguaje, escrita por su autor. Y es
la única de ese tipo que una herramienta estándar (clang-tidy) verifica regla
por regla con los chequeos `cppcoreguidelines-*`. La VM gestiona memoria a
mano (celdas, bloques, destructores). Las reglas de límites (*bounds*), de
tipos (*type*) y de propiedad (*owning memory*) son justo las que previenen
los errores más graves de un intérprete.

**Cómo se mide.** clang-tidy activa **todas** las reglas
`cppcoreguidelines-*` (`.clang-tidy`); ninguna se desactiva para mejorar el
número. Se informa:

- el % de reglas sin ningún hallazgo;
- el % de archivos limpios;
- los hallazgos por cada 1000 líneas;
- el detalle por regla.

Una regla con hallazgos no significa necesariamente un error: por ejemplo,
`pro-type-union-access` marca cada acceso a la `union` del valor de la VM,
que es una decisión de diseño. El número dice cuánto se aparta el código de
la guía, no cuántos errores tiene.

Complementan las Core Guidelines, sin entrar en su porcentaje, los grupos
`bugprone-*` (errores probables), `performance-*` y `portability-*`.

## Análisis estático: cppcheck

**Qué es.** Un analizador estático de C/C++ que busca errores reales:
comportamiento indefinido, variables sin inicializar, condiciones que siempre
dan lo mismo y fugas. También marca estilo, rendimiento y portabilidad.

**Por qué.** No depende de un compilador ni de la base de compilación, así que
cubre lo que clang-tidy no ve: el módulo nativo `runtime/logic_mem`, que
necesita pybind11 para compilar. Además es otro motor de análisis, con
heurísticas distintas.

**Cómo se mide.** `--enable=warning,style,performance,portability`, con
C++20. Se informa el % de archivos sin hallazgos y cada error o aviso por
separado. Se suprime `missingIncludeSystem`, que solo avisa que cppcheck no
buscó las cabeceras del sistema.

## Sanitizadores

Instrumentan la VM al compilarla y la hacen detenerse ante un error de
memoria o de comportamiento indefinido. Con la VM instrumentada se corren
las categorías de la suite que ejecutan programas en ella (`backend` y
`bootstrap`).

| Sanitizador | Detecta | Compilador |
|---|---|---|
| **ASan** (AddressSanitizer) | desbordes de búfer, uso tras liberar, doble liberación, uso de la pila tras retornar | MSVC (`/fsanitize=address`), GCC, Clang |
| **UBSan** (UndefinedBehaviorSanitizer) | desborde con signo, corrimientos fuera de rango, conversiones inválidas, punteros nulos o desalineados | GCC y Clang (MSVC no lo tiene) |

**UBSan en modo trampa.** En Windows se usa Clang (MSVC no tiene UBSan). Si
el LLVM instalado no trae el runtime de UBSan para x64, el build usa
`SURIAX_SANITIZE_TRAP=ON` (`-fsanitize-trap=undefined`): un comportamiento
indefinido detiene el programa con una instrucción ilegal, y la prueba falla.
No dice qué regla se rompió (eso lo daría el runtime), pero no deja pasar
nada. En Linux (la CI), con GCC o Clang completos, UBSan informa la regla.

**Cómo se mide.** % de pruebas de la VM que terminan limpias bajo cada
sanitizador.

## Herramientas y configuración

| Herramienta | Configuración | Requisito |
|---|---|---|
| clang-tidy | `.clang-tidy` (raíz) | un `compile_commands.json`: CMake con Ninja lo genera en cada build |
| cppcheck | argumentos en `docs/quality/tools/cpp_checks.py` | ninguno |
| ASan / UBSan | `SURIAX_SANITIZE`, `SURIAX_SANITIZE_TRAP` (CMake) | Visual Studio en Windows; Clang para UBSan |

Los builds instrumentados van a sus propias carpetas (`build-asan`,
`build-ubsan`) y no tocan el build normal.

El resultado vigente está en [../cumplimiento/cpp.md](../cumplimiento/cpp.md).
