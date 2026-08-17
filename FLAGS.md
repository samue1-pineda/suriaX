# FLAGS de suriaX

Referencia **completa** de banderas, directivas, variables de entorno y códigos
de salida disponibles HOY (Pre-Alpha V.0.0.1). Generado a partir de los
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
| `--check` | verifica las dependencias del compilador y termina |
| `--init-config` | genera un `.suriaX_config.yaml` por defecto y termina (requiere `pyyaml`) |
| `--emit-lang-info` | imprime en stdout la **especificación del lenguaje** en JSON (keywords por categoría, tokens, directivas, hooks, códigos de error). Fuente única para el LSP/extensión. No necesita `source` |
| `--emit-extensions` | descubre las **extensiones del proyecto** (HTIMS: `extends.srcx` + la lista `extensions:` del YAML) y emite en stdout un JSON con el proyecto, los hooks declarados con su firma y posición, y las líneas de config equivalentes. **No importa ni ejecuta** el `.py` del usuario (lo lee con `ast.parse`). Sin `source` usa el directorio actual como raíz; con él, la raíz del proyecto de ese fuente. **exit 4** si el manifiesto o una declaración tienen errores. Ver [htims/readme.md](htims/readme.md) |

### 2.2 Ejecución

| Flag | Qué hace |
|---|---|
| `--run` | fuerza el target `interp`: emite el HIR y lo ejecuta con el intérprete tree-walk (`runtime/interpreter`). Equivale a `target: interp` en el YAML |

### 2.3 Volcados / emisión (a `<dumps_dir>`, por defecto `./dumps`)

| Flag | Produce |
|---|---|
| `--emit-tokens [ARCHIVO]` | `<fuente>.tokens.txt` — el arreglo de tokens |
| `--emit-ast-json [ARCHIVO]` | `<fuente>.ast.json` — el AST-tipado anotado por la Semántica |
| `--emit-hir [ARCHIVO]` | `<fuente>.phir` — el HIR serializado en protobuf (+ un `.phir` por librería importada). Requiere `protobuf` |
| `--hir-text` | añade `<fuente>.phir.txt` — el **árbol crudo** del protobuf, para depurar el *formato* (qué tag lleva qué). Para leer el programa, `--hir-pretty` |
| `--hir-pretty` | escribe `<fuente>.phir.pretty` — la vista **legible** del HIR: una línea por sentencia, expresiones con su tipo resuelto, hooks enlazados y la posición del fuente al margen. Es como se lee *lo que le llegó al intérprete*. Se escribe en streaming (para un programa de 175 k tokens: 306 ms y 1,3 MB, frente a 1,9 s y 20,6 MB del texto protobuf) |
| `--emit-stage FASE` | vuelca **una** fase del pipeline (`lexer`, `parser`, `ast`, `sem`, `hir`) a stdout, sin que el archivo traiga `#test`. Mismo contenido que la directiva; lo consume el visualizador de la extensión. Una fase desconocida lista las válidas y sale con 2 |
| `--dump-symbols-table [ARCHIVO]` | `<fuente>.symbols.mmd` — la tabla de símbolos como diagrama de clases UML (Mermaid `classDiagram`): structs→clases con campos y métodos, enums→`<<enumeration>>`, campos nominales→asociaciones. Lo consume la web de `/documentation`. Solo librería estándar (sin protobuf) |

> En los tres `--emit-*` con `[ARCHIVO]`, si das una ruta va ahí; sin ella, al
> `dumps_dir` con el nombre por defecto.

### 2.4 Depuración / observabilidad

| Flag | Qué hace |
|---|---|
| `--time` | imprime cuánto tomó cada fase de la compilación (ms), a consola |
| `--trace-exec` | traza la ejecución (llamadas/retornos anidados) al `--run` |
| `--trace-memory` | traza las instrucciones de memoria (`&`, `move`, `free`) al `--run` |
| `--debug` | reporte **UNIFICADO** en `<dumps_dir>/<fuente>.debug.txt` (entorno, dependencias, métricas, tokens, AST, símbolos, HIR en texto, traza y tiempos). **Implica `--time` y `--hir-pretty`.** Combínalo con `--run --trace-exec --trace-memory` para incluir la ejecución paso a paso |
| `--stdin` | con `--emit-diagnostics` o `--emit-stage`: lee el **fuente** de la entrada estándar en vez del disco. El argumento de archivo sigue siendo obligatorio y sigue anclando la resolución de `.libsrx`, pero no hace falta que exista todavía — permite a un editor analizar un buffer sin guardar |
| `--emit-diagnostics` | corre el frontend y emite en stdout un JSON con **todos** los diagnósticos (código/mensaje/línea/columna/fase/severidad) y notas, sin tocar disco. Incluye una detección **ligera** de la fase HIR: marca los constructos RBMM (`region`, `new`, `at`, …) con `HIR005` **sin** construir el HIR ni requerir protobuf, para que el editor no se los salte. Canal en vivo para el LSP; **exit 0** aunque haya diagnósticos (van en el JSON) |

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
| `SURIAX_NATIVE_MEM` | backend de memoria: `0` fuerza Python puro; `1` exige el nativo C++ (error si no cargó). Sin definir: usa el nativo si `memory_c` carga, si no cae a Python |
| `SURIAX_UPDATE_GOLDEN` | `1` regenera los golden de la categoría `snapshot` en vez de compararlos |
| `LLVM_PATH` | ruta a LLVM para el backend/`--check` (alternativa a autodetección por `llvm-config`) |
| `SURIAX_SYSROOT` | sysroot para el linker del backend nativo (fase futura) |

---

## 6. Códigos de salida (`V0/main.py`)

| Código | Significado |
|---|---|
| `0` | ok |
| `1` | errores de compilación (léxicos/sintácticos/semánticos/HIR) |
| `2` | archivo fuente no encontrado |
| `3` | dependencia faltante para la operación pedida |
| `4` | error de las **extensiones** del proyecto (`EXT0xx`: manifiesto `extends.srcx` o declaraciones). Se detecta antes del léxico, así que la compilación no llega a empezar |
| `70` | error de ejecución (runtime del intérprete: `RTxxx`, throw no capturado) |

---

## 7. La suite de pruebas: `python test/main.py [categorías]`

```bash
python test/main.py                          # todas las categorías
python test/main.py unit negative_tests      # solo algunas
SURIAX_UPDATE_GOLDEN=1 python test/main.py snapshot   # regenerar golden
```

Categorías: `unit`, `grammar`, `negative_tests`, `snapshot`, `e2e`, `fuzz`.
