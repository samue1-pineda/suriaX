# Cómo ejecutar un archivo

Guía de cómo se ejecuta un archivo `.srcx`(Pre-Alpha) y cómo se
ejecutará a futuro. Para la arquitectura interna ver
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Estado actual (Pre-Alpha)

El pipeline **compila y EJECUTA**: `.srcx` → lexer → parser → AST-tipado →
Semántica → **HIR (protobuf)** → intérprete tree-walk. El backend C++/LLVM es
lo que falta (ver [ROADMAP.md](ROADMAP.md)).

> **`fn main` es OPCIONAL.** Las sentencias en el nivel superior del archivo
> se ejecutan tal cual (modo script): `__write__("hola\n");` a solas es un
> programa válido. Si defines `main`, es la función de entrada; si solo hay
> definiciones (ni `main` ni sentencias top-level), el programa corre y no
> imprime nada (exit 0).

> La lista **completa** de banderas, directivas, variables de entorno y
> códigos de salida vive en [FLAGS.md](FLAGS.md); abajo está lo de uso diario.

### Requisitos

- **Python 3.10+**
- Para **todo el frontend** (lexer → Semántica, con sus diagnósticos en
  consola) **NO** hace falta ninguna dependencia externa: solo la librería
  estándar. Ni LLVM, ni protobuf, ni pyyaml.
- Para **emitir el HIR o ejecutar** (`--emit-hir`, `--run`) hace falta
  `protobuf` (Python) y `protoc`. Si falta, el compilador aborta con un
  mensaje que dice qué instalar — no revienta.

### Entrypoint: `V0/main.py`

```bash
# compilar (frontend completo: reporta errores y símbolos)
python V0/main.py archivo.srcx

# compilar Y EJECUTAR con el intérprete
python V0/main.py archivo.srcx --run

# verificar dependencias / generar el .suriaX_config.yaml
python V0/main.py --check
python V0/main.py --init-config
```

`main.py`:

1. añade `V0/` y la raíz del repo a `sys.path` (no necesitas `PYTHONPATH`);
2. verifica **solo** las dependencias que la operación pedida necesita y
   aborta con un mensaje claro si falta alguna;
3. carga la config anclada al fuente, decodifica, tokeniza, parsea, resuelve
   tipos, corre la Semántica y —si se pide— emite el HIR y lo ejecuta;
4. reporta diagnósticos en **consola** y en `./log/<fuente>.log` (+ los
   JSONL estructurados `errors.jsonl` / `notes.jsonl`).

Códigos de salida: `0` ok · `1` errores de compilación · `2` archivo no
encontrado · `3` dependencia faltante · `70` error de ejecución (runtime).

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
| `--emit-lang-info` | imprime la especificación del lenguaje en JSON (keywords, tokens, directivas, hooks, códigos de error) y termina — fuente del LSP/extensión; no necesita un fuente |
| `--emit-diagnostics` | JSON con TODOS los diagnósticos (código/mensaje/línea/columna/fase) a stdout, sin tocar disco; exit 0 aunque haya diagnósticos — canal en vivo del LSP |

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
python test/main.py                    # todas las categorías
python test/main.py unit negative_tests  # solo algunas
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

Los tests de `grammar` existen para **localizar** un fallo sin leer el resto
del pipeline: si falla el de AST, el problema está en el parser; si ése pasa
y falla el de ejecución, está en el HIR o en el intérprete.

---

## 2. Cómo se ejecutará a futuro (compilador completo)

A futuro, `V0/main.py` (o el binario distribuido `suriaX`) orquestará el
pipeline completo descrito en [ARCHITECTURE.md](ARCHITECTURE.md)

### Selección de target

El backend C++ consulta `compilerconfig` y emite el artefacto según la
plataforma/flag:

| Flag        | Target | Artefacto | Paso final |
|-------------|--------|-----------|------------|
| `IS_WEB`    | wasm   | `.wasm`   | (playground) |
| `IS_WIN32`  | native | `.exe`    | linker      |
| `IS_LINUX`  | native | `.o`      | **linker** → ejecutable |

> En Linux el backend produce un `.o`; un paso de **linker** (etapa final dentro
> del backend C++) lo enlaza para generar el ejecutable. `compilerconfig` aporta
> las rutas/flags del linker.

### Forma de invocación prevista

```bash
# compilar a nativo (según plataforma)
suriaX build archivo.srcx -o programa

# compilar a WebAssembly (playground / target web)
suriaX build archivo.srcx --target wasm

# visualizar la salida de una etapa concreta (objetivo educativo del lenguaje)
suriaX inspect archivo.srcx --stage hir
```

*(La CLI definitiva puede cambiar; esto refleja la intención de diseño.)*

### Configuración de compilación: `.suriaX_config.yaml`

El formato de compilación es un YAML con la información que el backend necesita
para compilar de verdad. Genéralo con `python V0/main.py --init-config`. Esquema
actual:

```yaml
version: 1
target: native              # native | wasm | interp
                            #   native/wasm -> HIR -> backend C++ (LLVM)
                            #   interp      -> HIR -> intérprete tree-walk (Python)
platform: linux             # win32 | linux | macos
optimization: O0            # O0 | O1 | O2 | O3

toolchain:                  # rutas que el backend C++ usa para compilar/enlazar
  llvm_required_major: 22
  llvm_path: ""             # o la env var LLVM_PATH
  llvm_config: ""           # detectado vía 'llvm-config'
  llvm_include: ""          # headers de LLVM
  linker: ""                # ld.lld / lld / link ... (detectado)
  sysroot: ""               # o la env var SURIAX_SYSROOT

codegen:                    # target detallado
  triple: x86_64-unknown-linux-gnu
  arch: x86_64
  artifact: o               # o | exe | wasm
  wasm:
    enabled: false
    stack_size: 1048576
    export_all: false

output:                     # salidas del compilador (cada tipo en su carpeta)
  dumps_dir: ./dumps        # volcados: AST .json (--emit-ast-json), tokens .txt (--emit-tokens)
  build_dir: ./build
logging:
  dir: ./log                # <fuente>.log (uno por archivo) + notes.jsonl / errors.jsonl
  enabled: true
cache:
  dir: ./build/cache        # entrada al runtime system / suriniX (build)
  enabled: true

interpreter:                # target 'interp': consume el HIR (runtime/interpreter/)
  entry: main               # función de entrada a ejecutar
  trace_memory: false       # traza regiones/move en runtime (educativo)
  max_steps: 0              # 0 = sin límite; guarda contra bucles infinitos

visualization:              # objetivo educativo: qué etapas volcar
  stages: []                # tokens | ast | hir | mir | llvm-ir
  format: text              # text | json | dot

libraries:                  # búsqueda de .libsrx y bindings C++
  libsrx_paths: ["./lib"]   # RELATIVAS a la raíz del proyecto (donde vive este yaml);
                            # el usuario añade las suyas. El dir del .srcx se busca primero.
  extern_cpp_include: []
  bindings: []

paths:
  input: ""
  output: out
flags:
  is_web: false
```

> Muchos campos (`llvm_config`, `llvm_include`, `linker`, `triple`, `arch`) se
> **autodetectan** al generar el archivo; puedes sobreescribirlos a mano.

---

## 3. Dependencias del compilador (build desde fuente)

El **usuario final no las necesita** el binario distribuido las trae resueltas.
Importan al construir/ejecutar el compilador desde el código:

| Dependencia | Uso | ¿Cuándo hace falta? | Instalación |
|-------------|----------|---|-------------|
| *(ninguna)* | **frontend completo**: lexer → parser → AST-tipado → Semántica, con diagnósticos en consola | siempre disponible: solo librería estándar de Python | — |
| **protobuf** + `protoc` | serialización del HIR (`.phir`) y ejecución | `--emit-hir`, `--run`, `#test hir` | `pip install protobuf` + `protoc` del sistema |
| **pyyaml** | leer/generar `.suriaX_config.yaml` | `--init-config` (sin él se usan los defaults) | `pip install pyyaml` |
| **LLVM-22** | backend / generación de LLVM IR | fase futura (backend C++) | gestor del sistema o `LLVM_PATH`; se detecta con `llvm-config` |
| **pybind11** | bindings C++ (incl. `#extern cpp{}`) | fase futura (backend C++) | `pip install pybind11` |

> **El frontend no depende de nada externo.** Compilar, validar y ver los
> diagnósticos en consola funciona con una instalación pelada de Python; solo
> la fase HIR (y por tanto la ejecución) exige `protobuf`. Está verificado en
> la suite y se puede comprobar bloqueando los módulos a mano.

Instalación conjunta:

```bash
pip install -r V0/requirements.txt
```

Verificación:

```bash
python V0/main.py --check
#tambien (el paquete config/ vive en la raiz del repo)
python -m config.compilerconfig
```

Si falta una dependencia **necesaria para la operación solicitada**, el
compilador aborta con un mensaje que indica qué falta y cómo instalarlo. Las
fases que no la necesitan (p. ej. el lexer, que no usa LLVM) siguen funcionando.

> **Nota sobre LLVM:** se exige exactamente **LLVM-22**. `--check` valida la
> versión vía `llvm-config --version`; si tienes otra (p. ej. 21 o 23), lo
> reportará como incompatible aunque LLVM esté instalado.
