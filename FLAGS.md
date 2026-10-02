# FLAGS de suriaX

Referencia **completa** de banderas, directivas, variables de entorno y códigos
de salida de la versión vigente (la de [`version.py`](version.py)). Generado a partir de los
`argparse` reales de los entrypoints — si algo aquí no concuerda con `--help`,
manda `--help`. Para la guía de uso paso a paso ver
[how_to_run.md](how_to_run.md); para la arquitectura, [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Lanzador raíz: `python main.py`

Atajo de conveniencia (y el que dispara el botón de la extensión de VS Code).
Reenvía a `V0/main.py` **inyectando `--run`** salvo que ya venga o sea un
sub-comando (`--check` / `--init-config` / `-h`). Es decir: por defecto
*compila y ejecuta*.

```bash
python main.py archivo.srcx              # = V0/main.py archivo.srcx --run
python main.py archivo.srcx --emit-hir   # respeta tus flags; añade --run si falta
python main.py --check                   # se delega tal cual (sin --run)
```

Acepta **todas** las banderas de `V0/main.py` (sección 2).

---

## 2. Compilador: `python V0/main.py [source] [flags]`

`source` es el `.srcx`/`.libsrx` a procesar (posicional, opcional: los
sub-comandos y `--emit-lang-info` no lo necesitan).

### 2.1 Sub-comandos (no compilan un fuente; terminan al acabar)

| Flag | Qué hace |
|---|---|
| `-h`, `--help` | ayuda de argparse y termina |
| `--version` | imprime `suriaX <version>` y termina. La lee de `version.py` (raiz del repo), la misma fuente que CMake, la documentacion y las medallas |
| `--check` | verifica las dependencias del compilador y termina |
| `--init-config` | genera un `.suriaX_config.yaml` por defecto y termina (requiere `pyyaml`) |
| `--emit-lang-info` | imprime en stdout la **especificación del lenguaje** en JSON (keywords por categoría, tokens, directivas, hooks, códigos de error, fases; desde la v4 también `syntax` —comentarios, escapes, literales numéricos, formato de los f-strings, para colorear— y `snippets`) junto a `compiler_version`, para que el LSP sepa contra qué compilador habla. Fuente única para el LSP/extensión. No necesita `source` |
| `--emit-extensions` | descubre las **extensiones del proyecto** (HTIMS: `extends.srcx` + la lista `extensions:` del YAML) y emite en stdout un JSON con el proyecto, los hooks declarados con su firma y posición, y las líneas de config equivalentes. **No importa ni ejecuta** el `.py` del usuario (lo lee con `ast.parse`). Sin `source` usa el directorio actual como raíz; con él, la raíz del proyecto de ese fuente. **exit 4** si el manifiesto o una declaración tienen errores. Ver [htims/readme.md](htims/readme.md) |

### 2.2 Ejecución

| Flag | Qué hace |
|---|---|
| `--run [compiler\|interpreter]` | emite el HIR y lo **ejecuta**. Sin valor, en el motor del `target` del YAML: `native` (el defecto) es la **VM compilada** (`suriax-hir`) y `interp` el intérprete tree-walk. `--run compiler` / `--run interpreter` fuerzan el motor. Si la VM no está construida (o su MIR no cubre el programa) se interpreta con un **aviso**. `--trace-exec`/`--trace-memory` son del intérprete |

### 2.3 Volcados / emisión (a `<dumps_dir>`, por defecto `./dumps`)

| Flag | Produce |
|---|---|
| `--emit-tokens [ARCHIVO]` | `<fuente>.tokens.txt` — el arreglo de tokens |
| `--emit-ast-json [ARCHIVO]` | `<fuente>.ast.json` — el AST-tipado anotado por la Semántica |
| `--emit-hir [ARCHIVO]` | `<fuente>.phir` — el HIR serializado en el formato de protobuf (+ un `.phir` por librería importada). No necesita nada instalado: el codec es propio (ver [PROTOBUF_BRIDGE.md](V0/src/HIR/PROTOBUF_BRIDGE.md)) |
| `--hir-text` | añade `<fuente>.phir.txt` — el **árbol crudo** del protobuf, para depurar el *formato* (qué tag lleva qué). Para leer el programa, `--hir-pretty` |
| `--hir-pretty` | escribe `<fuente>.phir.pretty` — la vista **legible** del HIR: una línea por sentencia, expresiones con su tipo resuelto, hooks enlazados, la **destrucción que inserta el compilador** (`drop`, `⟨transfiere⟩`, `⟨temporal …⟩`) y la posición del fuente al margen. Es como se lee *lo que le llegó al intérprete*. Se escribe en streaming (para un programa de 175 k tokens: 306 ms y 1,3 MB, frente a 1,9 s y 20,6 MB del texto protobuf) |
| `--emit-stage FASE` | vuelca **una** fase del pipeline (`lexer`, `parser`, `ast`, `sem`, `hir`, `desugar`) a stdout, sin que el archivo traiga `#test`. Mismo contenido que la directiva; lo consume el visualizador de la extensión. Una fase desconocida lista las válidas y sale con 2 |
| `--dump-symbols-table [ARCHIVO]` | `<fuente>.symbols.mmd` — la tabla de símbolos como diagrama de clases UML (Mermaid `classDiagram`): structs→clases con campos y métodos, enums→`<<enumeration>>`, campos nominales→asociaciones. Lo consume la web de `/documentation`. Solo librería estándar (sin protobuf) |

> En los tres `--emit-*` con `[ARCHIVO]`, si das una ruta va ahí; sin ella, al
> `dumps_dir` con el nombre por defecto.

### 2.4 Depuración / observabilidad

| Flag | Qué hace |
|---|---|
| `--time` | imprime cuánto tomó cada fase de la compilación (ms), a consola. El **TOTAL es el reloj de pared** del proceso, no la suma de las fases: la diferencia va en la fila `arranque` (arranque de Python + importación del compilador), que en un archivo pequeño es la mayor parte del tiempo. `hir-protobuf` es aparte porque el descriptor pool de protobuf se construye una vez por proceso y no es trabajo de emisión |
| `--trace-exec` | traza la ejecución (llamadas/retornos anidados) al `--run` |
| `--trace-memory` | traza las instrucciones de memoria (`&`, `move`, `free`) al `--run` |
| `--debug` | reporte **UNIFICADO** en `<dumps_dir>/<fuente>.debug.txt` (entorno, dependencias, métricas, tokens, AST, símbolos, HIR en texto, traza y tiempos). **Implica `--time` y `--hir-pretty`.** Combínalo con `--run --trace-exec --trace-memory` para incluir la ejecución paso a paso |
| `--stdin` | con `--emit-diagnostics`, `--emit-index` o `--emit-stage`: lee el **fuente** de la entrada estándar en vez del disco. El argumento de archivo sigue siendo obligatorio y sigue anclando la resolución de `.libsrx`, pero no hace falta que exista todavía — permite a un editor analizar un buffer sin guardar |
| `--emit-diagnostics` | corre el frontend y emite en stdout un JSON con **todos** los diagnósticos (código/mensaje/línea/columna/fase/severidad) y notas, sin tocar disco. Canal en vivo para el LSP; **exit 0** aunque haya diagnósticos (van en el JSON) |
| `--emit-index` | lo mismo que `--emit-diagnostics` **más** el índice del archivo: sus símbolos (tipo, firma con nombres, posición, comentario de encima, archivo de la librería), cada uso de cada uno y los miembros de cada tipo (`index_version`). Canal del LSP para hover, ir a la definición y completar; una sola pasada del frontend. Sin índice si el parseo no fue limpio; **exit 0** |

---

## 3. Intérprete: `python runtime/interpreter/main.py <archivo.phir> [flags]`

Consume el `.phir` (HIR serializado), no el fuente. `--run` de `V0/main.py`
hace esto en un solo paso; aquí se invoca por separado.

| Flag | Qué hace |
|---|---|
| *(sin flags)* | resumen del módulo (funciones, tipos, hooks) sin ejecutar |
| `--exec` | liga las unidades (main + librerías) y **ejecuta** la función de entrada |
| `--test` | ejecuta los bloques `test "..." { }` del módulo principal |
| `--entry FN` | función de entrada (por defecto `interpreter.entry` del YAML, o `main`) |
| `--text` | imprime además el `Module` completo en texto protobuf (el árbol crudo) |
| `--pretty` | imprime el HIR en su vista **legible** — la forma de inspeccionar un `.phir` que ya existe |
| `--trace-exec` | traza la ejecución (llamadas y retornos, con anidamiento) |
| `--trace-memory` | traza las instrucciones de memoria (`&`, `move`, `free`) |

---

## 4. Directiva orquestadora `#test <fase>`

Si un `.srcx` **empieza** con `#test <fase>`, el compilador corre el pipeline
hasta esa fase, vuelca su salida y termina. Case-insensitive; un objetivo
desconocido lista los disponibles.

| Directiva | Vuelca |
|---|---|
| `#test lexer` | el arreglo de tokens |
| `#test parser` | el AST en JSON |
| `#test ast` | el AST-tipado (con `restype`) en JSON |
| `#test sem` | la tabla de símbolos (+ hooks y conversiones) |
| `#test hir` | el HIR en texto protobuf |

---

## 5. Variables de entorno

| Variable | Efecto |
|---|---|
| `SURIAX_NATIVE_MEM` | backend de memoria: `0` fuerza Python puro; `1` exige el nativo C++ (error con el motivo si no cargó). Sin definir: usa el nativo si `memory_c` carga, si no cae a Python |
| `SURIAX_STDLIB` | dónde está la stdlib del compilador (el respaldo de `#import` tras el directorio del fuente y `libraries.libsrx_paths`). Por defecto, `lib/` del repositorio |
| `SURIAX_CPP_FLAGS` | banderas extra para compilar los bloques `#extern cpp` (p. ej. `-lX11`). Son de la MÁQUINA; las del proyecto van en `toolchain.cxx_flags` del yaml |
| `SURIAX_ICE_TRACEBACK` | `1` añade la traza completa al mensaje de un error interno (`ICE000`) en el canal del editor (`--emit-diagnostics`). En la CLI la traza sale siempre |
| `SURIAX_SYSROOT` | sysroot para el linker del backend nativo (fase futura) |
| `SURIAX_ROOT` | raíz del compilador para el comando `suri` (sección 8) |
| `SURIAX_UPDATE_GOLDEN` | `1` regenera los golden de la categoría `snapshot` en vez de compararlos |
| `SURIAX_HIR_BIN` | ruta del binario `suriax-hir` que usan las pruebas del backend C++ (una ruta relativa se toma desde la raíz del repositorio). Sin ella, las pruebas lo buscan en `build/bin` y luego en los `build-*/bin` (los de sanitizadores al final), con o sin `.exe` |
| `SURIAX_LIMITE_ETAPA` | segundos que tiene cada etapa del punto fijo del bootstrap (`test/bootstrap/test_punto_fijo.py`); 600 por defecto. Con una VM de sanitizador (`build-asan`, `build-ubsan`) esa prueba se omite: se corre a mano, con este límite alto (con ASan en Debug, unas 2 h por etapa) |
| `PORT`, `SURIAX_MAX_SOURCE_BYTES`, `SURIAX_WEB_TIMEOUT` | playground: puerto, tamaño máximo del fuente y tiempo máximo del backend web (ver [.env.example](.env.example)) |

---

## 6. Códigos de salida (`V0/main.py`)

| Código | Significado |
|---|---|
| `0` | ok |
| `1` | errores de compilación (léxicos/sintácticos/semánticos/HIR): el PROGRAMA tiene errores |
| `2` | archivo fuente no encontrado (o no se puede leer: permisos, es un directorio) |
| `3` | dependencia faltante para la operación pedida |
| `4` | error de las **extensiones** del proyecto (`EXT0xx`: manifiesto `extends.srcx` o declaraciones). Se detecta antes del léxico, así que la compilación no llega a empezar |
| `5` | **configuración** inválida (`CFG0xx`: `.suriaX_config.yaml` malformado, una clave que no existe o un valor del tipo equivocado). Se detecta antes de leer el fuente: el resto del pipeline resuelve rutas contra esa configuración |
| `6` | **error interno del compilador** (`ICE000`): falló el COMPILADOR, no el programa. Sale el traceback de Python de la excepción original, seguido de la fase y el archivo que se procesaba |
| `70` | error de ejecución (runtime del intérprete: `RTxxx`, throw no capturado) |

---

## 7. La suite de pruebas: `python test/main.py [categorías] [--json RUTA]`

```bash
python test/main.py                          # las categorías de siempre
python test/main.py unit negative_tests      # solo algunas
python test/main.py backend                  # a pedido: VM contra intérprete
python test/main.py bootstrap                # a pedido: V1 (suriaX) contra V0
python test/main.py --todo                   # todas
python test/main.py --json resumen.json      # + resumen para máquinas (lo usa la CI)
SURIAX_UPDATE_GOLDEN=1 python test/main.py snapshot   # regenerar golden
```

Categorías de siempre: `unit`, `grammar`, `negative_tests`, `snapshot`, `e2e`,
`fuzz`. A pedido: `backend` (el diferencial de la VM y `suriax-hir`) y
`bootstrap` (el frontend escrito en suriaX contra la V0, y corriendo en la
VM): comparan dos implementaciones y se corren cuando se toca lo que prueban
(en la CI, un workflow por categoría con filtro de rutas; en el release,
todo). Una categoría desconocida termina con `2`.

Cada prueba termina **pasada** (`✓`), **fallida** (`✗`) u **omitida** (`○`). Una
omitida no se ejecutó (falta node, el binario C++, `memory_c`, pyyaml...): se
lista con su motivo y **nunca cuenta como pasada**, pero no hace fallar la
corrida. El código de salida es `1` si hubo algún fallo, `0` si no. El runner
se relanza solo en el modo UTF-8 de Python: la salida no depende de la
codificación de la máquina.

---

## 8. El comando `suri`

Envoltorio de `V0/main.py` para la terminal (tooling de suriniX). Se instala
desde el clon con `pip install -e .` ([pyproject.toml](pyproject.toml)); sin
instalar, `python -m suri`. No declara banderas propias: acepta **las mismas**
que `V0/main.py` (sección 2), y compilar un fuente sin decir qué hacer con él
lo ejecuta, igual que `python main.py`.

```bash
suri archivo.srcx            # = V0/main.py archivo.srcx --run
suri --run archivo.srcx      # lo mismo, explícito
suri archivo.srcx --emit-hir
suri --check
```

Acepta **un** archivo fuente. Busca el compilador en `SURIAX_ROOT`, en la
raíz del repositorio y en el directorio actual, en ese orden; si no lo
encuentra, dice qué rutas probó y termina con `2`.

---

## `suriax-hir` — el backend nativo en C++

Lector del HIR, resolución, lowering a MIR y la VM que lo ejecuta
([`backend/`](backend/README.md)). Se construye con
`cmake --build build --target suriax-hir` y solo necesita CMake y un
compilador de C++20 (no usa protobuf). Cómo construirlo en cada sistema, en
[how_to_run.md](how_to_run.md) §1.d y [CMake/README.md](CMake/README.md).

| Bandera | Qué hace |
|---|---|
| *(ninguna)* | resumen de la unidad: símbolos, hooks e items. Idéntico al de `python runtime/interpreter/main.py <archivo>.phir` |
| `--pretty` | la vista **legible**, byte-idéntica a la de `--hir-pretty` del compilador |
| `--summary` | el resumen, explícito |
| `--link` | liga las unidades referenciadas (transitivamente) y reporta los índices de hooks y conversiones |
| `--verify` | recorre el árbol entero y falla si algún nodo llegó sin caso del `oneof` |
| `--resolve` | **resuelve** la imagen: cada función con sus slots, a qué se resuelve cada llamada y qué destruye cada bloque. Falla si queda una llamada sin resolver. Liga la imagen |
| `--mir` | baja la imagen al **MIR** (registros virtuales + CFG explícito) y lo imprime —una línea por instrucción, agrupadas por bloque—, seguido de la **verificación de propiedad y préstamos** |
| `--run` | **ejecuta** el MIR en la VM y termina con lo que devuelva `main` (imprime `[vm] main() -> N`). Lo que el MIR no sabe bajar se nombra con su posición y no se ejecuta |
| `--quiet` | con `--run`: solo lo que escribe el programa (sin `[vm] main() -> N`). Así la corre `suri --run compiler` |
| `--arg0 <nombre>` | con `--run`: el argumento 0 del programa (`sistema.proceso.argumento(0)`); por defecto, el `.phir` |
| `--check-mir` | baja la imagen al MIR y termina: 0 si lo cubre entero, 1 (y qué falta) si no. No ejecuta nada |
| `--pasos <N>` | con `--run`: el límite de pasos de la VM (por defecto 100 000 000; pasarlo es `RT010`). `0` = sin límite |
| `--memoria-max <tamaño>` | con `--run`: la memoria máxima del PROGRAMA —sus objetos, bloques y cadenas, contados por la VM; no la del proceso—, en bytes o con `K`/`M`/`G` (`512M`, `2G`). Antes de rendirse recoge las cadenas que ya nadie usa; pasarla igual es `RT023`. Por defecto, sin límite. Pensado para máquinas con poca memoria (como `make -jN` o `LLVM_PARALLEL_LINK_JOBS`) |
| `--extern <biblioteca>` | con `--run`: liga los prototipos a esa biblioteca de C++ ya construida. Sin ella, si el programa trae `#extern cpp`, se construye junto al `.phir` (`extern/extern_cpp_vm.*`) con `$CXX`, `g++` o `clang++` y `SURIAX_CPP_FLAGS` |
| `--memoria` | con `--run`: al terminar, cuántos objetos y cadenas creó y liberó la VM y cuáles quedaron vivos |
| `--emit-cpp <archivo>` | escribe los bloques `#extern cpp` del programa como una unidad de traducción de C++, con `#line` al `.srcx`. Liga la imagen: recoge también los de las librerías |

Que las dos vistas sean byte-idénticas a las de Python es lo que convierte
`test/backend/test_backend_cpp_*.py` en un diferencial entre consumidores.
