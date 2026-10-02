# Cómo usar suriaX: los comandos

Guía de uso de los comandos de suriaX: compilar y ejecutar un archivo,
inspeccionar cada fase, correr las pruebas, construir la VM, usar el
compilador escrito en suriaX (la V1) y construir la documentación. La
referencia COMPLETA de cada bandera está en [FLAGS.md](FLAGS.md); la
arquitectura interna, en [ARCHITECTURE.md](ARCHITECTURE.md).

Todos los comandos se escriben desde la raíz del repositorio.

---

## 0. Los comandos de un vistazo

| Para... | Comando | Más |
|---|---|---|
| compilar (y ver los errores) | `python V0/main.py archivo.srcx` | §1 |
| compilar y ejecutar | `python V0/main.py archivo.srcx --run` (o `suri archivo.srcx`) | §1 |
| ver una fase (tokens, AST, HIR) | `--emit-tokens`, `--emit-ast-json`, `--emit-hir --hir-pretty` | §1 |
| un reporte para un bug | `python V0/main.py archivo.srcx --run --debug` | §1 |
| ejecutar un `.phir` ya emitido | `python runtime/interpreter/main.py dumps/x.phir --exec` | §1.b |
| las pruebas | `python test/main.py` (todas: `--todo`) | §1.c |
| construir la VM | `cmake -S . -B build -DSURIAX_BUILD_NATIVE=OFF` y `cmake --build build --target suriax-hir` | §1.d |
| ejecutar en la VM | `build/bin/suriax-hir dumps/x.phir --run` | §1.d |
| compilar con la V1 | `suriax-hir dumps/main.srcx.phir --run -- prog.srcx salida/prog.phir --stdlib lib` | §1.e |
| el punto fijo | `python test/main.py bootstrap` | §1.e |
| construir la documentación | `sphinx-build -b html documentation/source documentation/build/html` | §1.f |
| comprobar el entorno | `python V0/main.py --check` | §3 |
| generar la configuración | `python V0/main.py --init-config` | §2 |

---

## 1. Compilar y ejecutar

El pipeline **compila y EJECUTA**: `.srcx` → lexer → parser → AST-tipado →
Semántica → **HIR (`.phir`)** → la VM (`suriax-hir`, si está construida) o el
intérprete tree-walk. Lo que todavía no existe (un ejecutable propio, el JIT)
está en la §2.

> **`fn main` es OPCIONAL.** Las sentencias en el nivel superior del archivo
> se ejecutan tal cual (modo script): `__write__("hola\n");` a solas es un
> programa válido. Si defines `main`, es la función de entrada; si solo hay
> definiciones (ni `main` ni sentencias top-level), el programa corre y no
> imprime nada (exit 0).

> La lista **completa** de banderas, directivas, variables de entorno y
> códigos de salida vive en [FLAGS.md](FLAGS.md); abajo está lo de uso diario.

### Requisitos

- **Python 3.10+**, y nada más para compilar y ejecutar: el frontend, el
  **HIR** (`--emit-hir`, que se serializa con un codec propio) y el
  **intérprete** corren solo con la librería estándar. Ni protobuf, ni
  `protoc`, ni pyyaml, ni LLVM. La VM (`suriax-hir`, más rápida) es opcional:
  hay que construirla con CMake (sección 3).
- `pyyaml` solo hace falta para leer un `.suriaX_config.yaml` propio (sin él
  se usan los valores por defecto y se avisa) y para `--init-config`.
- Lo demás es opcional y por componente: ver la sección 3.

### Entrypoint: `V0/main.py`

```bash
# compilar (frontend completo: reporta errores y símbolos)
python V0/main.py archivo.srcx

# compilar Y EJECUTAR: en la VM si está construida ('target: native', el
# defecto), si no en el intérprete con un aviso; '--run interpreter' o
# '--run compiler' fuerzan el motor
python V0/main.py archivo.srcx --run

# verificar dependencias / generar el .suriaX_config.yaml
python V0/main.py --check
python V0/main.py --init-config

# que version es esta (la lee de 'version.py', la fuente unica)
python V0/main.py --version
```

`main.py`:

1. añade `V0/` y la raíz del repo a `sys.path` (no necesitas `PYTHONPATH`);
2. verifica **solo** las dependencias que la operación pedida necesita y
   aborta con un mensaje claro si falta alguna;
3. carga la config anclada al fuente, decodifica, tokeniza, parsea, resuelve
   tipos, corre la Semántica y —si se pide— emite el HIR y lo ejecuta;
4. reporta diagnósticos en **consola** y en `./log/<fuente>.log` (+ los
   JSONL estructurados `errors.jsonl` / `notes.jsonl`).

Códigos de salida: `0` ok · `1` errores de compilación (el programa tiene
errores) · `2` archivo no encontrado · `3` dependencia faltante · `4` error
de extensiones (`EXT`) · `5` configuración inválida (`CFG`) · `6` error
**interno** del compilador (`ICE000`: falló el compilador, no el programa) ·
`70` error de ejecución (runtime). La tabla completa está en
[FLAGS.md](FLAGS.md).

### Volcados y depuración

Todo artefacto de inspección va a `./dumps` (configurable con
`output.dumps_dir`):

| Flag | Produce |
|---|---|
| `--emit-tokens` | `<fuente>.tokens.txt` — el arreglo de tokens |
| `--emit-ast-json` | `<fuente>.ast.json` — AST-tipado anotado |
| `--emit-hir` | `<fuente>.phir` — HIR serializado (+ un `.phir` por librería) |
| `--hir-text` | añade `<fuente>.phir.txt` — el árbol crudo del protobuf (para depurar el *formato*) |
| `--hir-pretty` | escribe `<fuente>.phir.pretty` — el HIR **legible**: una línea por sentencia, con tipos resueltos y posiciones. Es la vista para leer lo que le llegó al intérprete |
| `--debug` | **`<fuente>.debug.txt`** — reporte UNIFICADO (ver abajo) |
| `--time` | tiempos por fase, a consola |
| `--trace-exec` | traza de ejecución (llamadas/retornos anidados) |
| `--trace-memory` | traza de memoria (`&`, `move`, `free`, `catch`) |
| `--emit-lang-info` | imprime la especificación del lenguaje en JSON (keywords, tokens, directivas, hooks, códigos de error, sintaxis para colorear, snippets) y termina — fuente del LSP/extensión; no necesita un fuente |
| `--emit-diagnostics` | JSON con TODOS los diagnósticos (código/mensaje/línea/columna/fase) a stdout, sin tocar disco; exit 0 aunque haya diagnósticos — canal en vivo del LSP |
| `--emit-index` | los diagnósticos más el índice del archivo (símbolos con tipo, firma y comentario, sus usos, los miembros de cada tipo) — canal del LSP para hover, ir a la definición y completar |

**`--debug` es el atajo para reportar un bug**: reúne en un solo `.txt` el
entorno, el estado de dependencias, métricas, tokens, AST-tipado, tabla de
símbolos, HIR en texto, la traza de ejecución y los tiempos por fase. Implica
`--time` y `--hir-pretty`. Combínalo con `--run --trace-exec --trace-memory`
para incluir la ejecución paso a paso:

```bash
python V0/main.py archivo.srcx --run --debug --trace-exec --trace-memory
# -> dumps/archivo.srcx.debug.txt
```

### La directiva `#test <fase>`

Si un `.srcx` **empieza** con `#test <fase>`, el compilador corre el pipeline
hasta esa fase, vuelca su salida y termina. Las fases anteriores se ejecutan
solas (no hay que encadenarlas a mano) y el objetivo es **case-insensitive**
(`#test HIR` == `#test hir`):

| Directiva | Vuelca |
|---|---|
| `#test lexer` | el arreglo de tokens |
| `#test parser` | el AST en JSON |
| `#test ast` | el AST-tipado (con `restype`) en JSON |
| `#test sem` | la tabla de símbolos (+ hooks y conversiones) |
| `#test hir` | el HIR en texto protobuf |

```
#test lexer
int a = 10;
printf(f"hola{a}");
```

→ `DIRECTIVE('test')` `IDENTIFIER('lexer')` `INT('int')` `IDENTIFIER('a')`
`ASSIGN` `INT_LIT(10)` `SEMICOLON` `IDENTIFIER('printf')` `L_PAREN`
`STRING_LIT(Str(['hola', Interp('a')]))` `R_PAREN` `SEMICOLON` `EOF`

Un objetivo desconocido lista los disponibles en vez de fallar de forma
confusa.

> **NOTA**: `printf` **no** es una palabra reservada. Por la filosofía libsrX
> (pocos tokens, casi todo viene de librerías nativas) es un `IDENTIFIER`. El
> `;` es el terminador de sentencia obligatorio.
>
> Ojo con la distinción **tipo vs literal**: `int` (la palabra clave de tipo) es
> el token `INT`, mientras que `10` (el literal) es `INT_LIT`. Igual para
> `float`/`FLOAT_LIT`, `char`/`CHAR_LIT` y `str`/`STRING_LIT`.

---

## 1.b. Ejecutar con el intérprete

El intérprete consume el **`.phir`** (el HIR serializado), no el fuente. Con
`--run` el compilador lo emite y lo ejecuta en un solo paso; también puedes
invocarlo por separado:

```bash
python V0/main.py archivo.srcx --emit-hir          # -> dumps/archivo.srcx.phir

# resumen del módulo (funciones, tipos, hooks) sin ejecutar
python runtime/interpreter/main.py dumps/archivo.srcx.phir

# ejecutar
python runtime/interpreter/main.py dumps/archivo.srcx.phir --exec

# ejecutar los bloques   test "..." { }   del archivo
python runtime/interpreter/main.py dumps/archivo.srcx.phir --test

# opciones de depuración del intérprete
python runtime/interpreter/main.py dumps/x.phir --exec --trace-exec --trace-memory
python runtime/interpreter/main.py dumps/x.phir --text     # Module completo en texto
```

Cada `.libsrx` importada emite **su propio `.phir`** junto al principal; el
*module linker* del intérprete los liga al cargar.

---

## 1.c. La suite de pruebas

```bash
python test/main.py                    # las categorías de siempre
python test/main.py unit negative_tests  # solo algunas
python test/main.py backend bootstrap  # a pedido: las que comparan implementaciones
python test/main.py --todo             # todas
python test/main.py --json resumen.json  # + resumen legible por máquina (CI)
SURIAX_UPDATE_GOLDEN=1 python test/main.py snapshot   # regenerar golden
```

Categorías: `unit` (lexer/parser/tipos), `grammar` (la EBNF regla a regla, en
tres niveles: forma del AST, código de error exacto y ejecución de punta a
punta), `negative_tests` (cada código de error se dispara donde debe y **no**
en programas válidos), `snapshot` (golden del AST/símbolos/HIR + estabilidad
de códigos y `schema_version`), `e2e` (programas reales que compilan y
ejecutan, comparando salida — incluye librerías/paquetes, `try`/`catch` y
memoria) y `fuzz` (entradas adversariales y de escala). El runner es propio,
sin framework externo.

Cada prueba termina **pasada** (`✓`), **fallida** (`✗`) u **omitida** (`○`).
Una omitida es una que NO se ejecutó porque falta algo en la máquina (node, el
binario C++, el módulo `memory_c`, pyyaml...): se lista al final con su
motivo, va en el `--json` y en el informe de la CI, y **nunca cuenta como
pasada**. No hace fallar la corrida: el código de salida depende solo de los
fallos. Un fallo se muestra como en Python —traceback desde la prueba, la
línea del `assert` y, si la aserción no trae mensaje, las variables locales
con las que falló—. El runner se relanza solo en el modo UTF-8 de Python, así
que la salida no depende de la codificación de la máquina (en Windows antes
se caía).

**Todas** las pruebas del repositorio viven bajo `test/`. Además de las seis
categorías hay dos carpetas que no lo son:

| Carpeta | Qué es |
|---|---|
| `test/web/` | La suite del backend web (TypeScript). La engancha `test/unit/test_web_backend.py`, que la corre con `node --test`, así que `python test/main.py` sigue siendo el único comando. Sin node se OMITE (visible en el resumen) |
| `test/manual/` | Utilidades que se corren a mano (p. ej. el volcado del lexer), no en cada corrida |

Los tests de `grammar` existen para **localizar** un fallo sin leer el resto
del pipeline: si falla el de AST, el problema está en el parser; si ése pasa
y falla el de ejecución, está en el HIR o en el intérprete.

---

## 1.d. La VM (`suriax-hir`): construir y usar

La VM es el backend nativo en C++: lee el `.phir`, lo baja a MIR y lo
ejecuta, con la misma salida que el intérprete y mucho más rápido. Solo
necesita **CMake 3.20+ y un compilador de C++20**: no tiene dependencias (lee
el `.phir` con su propio decodificador, sin protobuf).

```bash
# Linux / macOS
cmake -S . -B build -DSURIAX_BUILD_NATIVE=OFF
cmake --build build --target suriax-hir
./build/bin/suriax-hir --help
```

```bat
:: Windows: MSVC + Ninja, desde un entorno de Visual Studio (cl.exe no está
:: en el PATH de una terminal normal)
call "C:\Program Files\Microsoft Visual Studio\<versión>\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release -DSURIAX_BUILD_NATIVE=OFF
cmake --build build --target suriax-hir
build\bin\suriax-hir.exe --help
```

`SURIAX_BUILD_NATIVE=OFF` deja fuera la memoria nativa del intérprete
(`memory_c`), que además pide pybind11. Las trampas de Windows, las opciones
de CMake, los builds con sanitizadores y cómo añadir un binario nuevo están en
[CMake/README.md](CMake/README.md).

Con la VM construida, `python V0/main.py archivo.srcx --run` ya la usa (el
`target` por defecto es `native`). Para usarla directamente sobre un `.phir`:

```bash
build/bin/suriax-hir dumps/x.phir --run                 # ejecuta (imprime '[vm] main() -> N')
build/bin/suriax-hir dumps/x.phir --run --quiet         # solo la salida del programa
build/bin/suriax-hir dumps/x.phir --run -- a b c        # argumentos del programa
build/bin/suriax-hir dumps/x.phir --run --memoria       # + objetos, cadenas y bytes al terminar
build/bin/suriax-hir dumps/x.phir --run --pasos 0 --memoria-max 512M   # sin límite de pasos, 512 MB
build/bin/suriax-hir dumps/x.phir --pretty              # el HIR legible
build/bin/suriax-hir dumps/x.phir --mir                 # el MIR + la verificación de propiedad
```

`--pasos N` (por defecto 100 millones; `0` = sin límite) y `--memoria-max`
(la memoria del PROGRAMA, en bytes o con `K`/`M`/`G`) son para máquinas
modestas: cortan con un error que dice dónde (`RT010`, `RT023`) en vez de que
el sistema mate el proceso. Las pruebas buscan la VM en `build/bin` y en los
`build-*/bin`; `SURIAX_HIR_BIN` fija otra.

---

## 1.e. La V1: el compilador escrito en suriaX

`src/` es el compilador reescrito en suriaX. La V0 lo compila y la VM lo
ejecuta. Su `.phir` es idéntico, byte a byte, al de la V0, y se compila a sí
mismo (el punto fijo). Lo detallado está en [src/readme.md](src/readme.md).

La V1 importa sus paquetes como librerías, así que se arma un proyecto con
ellos dentro de su `lib/` (así lo hace la prueba):

```bash
mkdir v1 && cp -r lib v1/lib
cp -r src/frontend src/semantica src/hir v1/lib/
cp src/main.srcx v1/
printf 'version: 1\ntarget: native\n' > v1/.suriaX_config.yaml
cd v1

python ../V0/main.py main.srcx --emit-hir          # la V0 compila la V1 -> dumps/main.srcx.phir

# la V1 compila un programa: escribe su .phir y uno por librería, en la
# misma carpeta (que tiene que existir: la V1 no la crea)
mkdir -p salida
../build/bin/suriax-hir dumps/main.srcx.phir --run --quiet -- \
    programa.srcx salida/programa.phir --stdlib ../lib

# la V1 se compila a sí misma (pasa del límite de pasos por defecto)
mkdir -p etapa2
../build/bin/suriax-hir dumps/main.srcx.phir --run --quiet --pasos 0 -- \
    main.srcx etapa2/main.srcx.phir --stdlib ../lib
```

La stdlib le llega con `--stdlib` o con `SURIAX_STDLIB` (la V1 es un `.phir`
y no sabe dónde está instalada). Acepta `-O0` (el defecto); `-O1`/`-O2` son un
error: la V1 no optimiza, las optimizaciones llegan con la V3. Todo esto lo
comprueban `python test/main.py bootstrap` (los programas de
`test/bootstrap/v1*/` y el punto fijo en tres etapas).

---

## 1.f. La documentación

El sitio (Sphinx) se construye igual que en la CI
([docs.yml](.github/workflows/docs.yml)):

```bash
pip install -r documentation/requirements.txt
sphinx-build -b html -W --keep-going documentation/source documentation/build/html
```

Los ejemplos de código de la documentación se compilan y se ejecutan para
comprobar que hacen lo que dice el texto:

```bash
python test/docs_examples.py
```

Un bloque que no es un programa completo se marca `:class: fragmento` y no se
verifica.

---

## 2. Configuración y lo que todavía no existe

### Lo que todavía no existe

- **Un ejecutable propio** (`.exe`, `.o`): la VM interpreta el MIR. El JIT y
  los artefactos nativos son el siguiente gran paso (ver
  [ROADMAP.md](ROADMAP.md)).
- **Un comando de build de proyectos**: hoy se compila un archivo por vez
  (`V0/main.py` o `suri`); las librerías se resuelven solas desde los
  `#import`.

### Configuración de compilación: `.suriaX_config.yaml`

El formato de compilación es un YAML con la información que el backend necesita
para compilar de verdad. Genéralo con `python V0/main.py --init-config`. Esquema
actual:

```yaml
version: 2
target: native              # native | wasm | interp
                            #   interp      -> HIR -> intérprete tree-walk (Python)
                            #   native/wasm -> HIR -> backend C++ / target web
platform: linux             # win32 | linux | macos
optimization: O0            # O0 | O1 | O2 | O3

toolchain:                  # compiladores que usa '#extern cpp{}' (y el futuro backend)
  linker: ""                # detectado
  sysroot: ""               # o la env var SURIAX_SYSROOT
  cxx_compiler: ""          # detectado: $CXX, g++ o clang++
  c_compiler: ""            # detectado: $CC, gcc, clang o cc
  include_c_paths: []
  cxx_flags: []             # banderas extra para los bloques '#extern cpp'
                            #   (p. ej. ["-lX11"]). Tambien SURIAX_CPP_FLAGS:
                            #   esas son de la MAQUINA, no del proyecto
  c_flags: []

codegen:                    # target detallado
  triple: x86_64-unknown-linux-gnu
  arch: x86_64
  artifact: o               # o | exe | wasm
  wasm:
    enabled: false
    stack_size: 1048576
    export_all: false

output:                     # salidas del compilador (cada tipo en su carpeta)
  dumps_dir: ./dumps        # .phir, .ast.json, .tokens.txt, .debug.txt...
  build_dir: ./build
logging:
  dir: ./log                # <fuente>.log (uno por archivo) + notes.jsonl / errors.jsonl
  enabled: true
cache:
  dir: ./build/cache        # entrada al runtime system / suriniX (build)
  enabled: true

interpreter:                # target 'interp': consume el HIR (runtime/interpreter/)
  entry: main               # función de entrada a ejecutar
  trace_memory: false       # traza celdas/move/free en runtime (educativo)
  max_steps: 0              # 0 = sin límite; guarda contra bucles infinitos
                            #   (cuenta pasos, no profundidad de recursión)

visualization:              # objetivo educativo: qué etapas volcar
  stages: []
  format: text              # text | json | dot

libraries:                  # búsqueda de .libsrx y bindings C++
  libsrx_paths: ["./lib"]   # RELATIVAS a la raíz del proyecto (donde vive este yaml);
                            # el dir del .srcx se busca primero y la stdlib
                            # del compilador al final (o SURIAX_STDLIB)
  extern_cpp_include: []
  bindings: []

project: ""                 # nombre del proyecto (HTIMS)
extensions: []              # extensiones declaradas (HTIMS, ver htims/readme.md)

paths:
  input: ""
  output: out
flags:
  is_web: false
```

> Muchos campos (`linker`, `cxx_compiler`, `c_compiler`, `triple`, `arch`) se
> **autodetectan** al generar el archivo; puedes sobreescribirlos a mano.

---

## 3. Dependencias del compilador (build desde fuente)

El **usuario final no las necesita** el binario distribuido las trae resueltas.
Importan al construir/ejecutar el compilador desde el código:

| Dependencia | Uso | ¿Cuándo hace falta? | Instalación |
|-------------|----------|---|-------------|
| *(ninguna)* | **el compilador entero**: frontend, HIR (`.phir`, codec propio) e intérprete (`--run`) | siempre: solo la librería estándar de Python | — |
| **pyyaml** | leer/generar `.suriaX_config.yaml` | `--init-config`, o para que se aplique un yaml propio (sin él se usan los valores por defecto y se avisa) | `pip install pyyaml` |
| **pybind11** + CMake | memoria nativa del intérprete (`memory_c`, `runtime/logic_mem`) | opcional: sin ella la memoria corre en Python con la misma semántica | `pip install pybind11` y `cmake --build build --target suriax-native` |
| un compilador de C++ (`g++`/`clang++`) | ejecutar programas con `#extern cpp{}` en el intérprete | solo si el programa trae ese bloque | el del sistema (o `$CXX`) |
| CMake 3.20+ y un compilador de C++20 | la VM `suriax-hir` (MIR y VM) | solo para construir `backend/` (sin más dependencias: no usa protobuf) | el del sistema; en Windows, MSVC (§1.d) |
| **node 22+** | target web (WebAssembly) y el panel `.wat` del playground: `node web/main.ts dumps/x.phir --run` (ver [web/README.md](web/README.md)) | solo para ese target | gestor del sistema |
| **Sphinx** | construir el sitio de documentación (§1.f) | solo para la documentación | `pip install -r documentation/requirements.txt` |
| **protobuf** (Python) + `protoc` | la prueba cruzada del codec del HIR contra `google.protobuf` | solo para esa prueba (sin ellos se OMITE, visible) | `pip install protobuf` + `protoc` del sistema |
| LLVM | **nada**: no forma parte del plan (el target nativo es la VM) | nunca | — |

> **El compilador no depende de nada externo.** Compilar, emitir el HIR y
> ejecutar funciona con una instalación pelada de Python. La CI lo comprueba
> en cada push bloqueando `yaml` y `google.protobuf` a nivel de importación
> ([ci.yml](.github/workflows/ci.yml)).

Instalación conjunta (desarrollo):

```bash
pip install -r requirements.txt
pip install -e .          # opcional: instala el comando 'suri'
```

Verificación:

```bash
python V0/main.py --check
#tambien (el paquete config/ vive en la raiz del repo)
python -m config.compilerconfig
```

Si falta una dependencia **necesaria para la operación solicitada**, el
compilador aborta con un mensaje que indica qué falta y cómo instalarlo (código
`3`). Hoy la única operación que la exige es `--init-config` (pyyaml).

> **Nota sobre `--check`:** marca `protobuf` y `pybind11` como `[FALTA]`
> aunque son opcionales (ver [c_errorstfix.md](c_errorstfix.md)). **LLVM no se
> detecta**: quedó fuera del plan en la v0.2.0 (ver
> [docs/llvm_backend.md](docs/llvm_backend.md)).
