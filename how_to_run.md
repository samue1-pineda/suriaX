# Cómo usar suriaX

Guía de uso para quien llega por primera vez: cómo ejecutar un programa, las
tareas de todos los días y, al final, la referencia. La lista **completa** de
banderas está en [FLAGS.md](FLAGS.md); la arquitectura interna, en
[ARCHITECTURE.md](ARCHITECTURE.md); lo que hoy falla, en
[c_errorstfix.md](c_errorstfix.md).

**Índice**

1. [Tu primer programa en tres pasos](#1-tu-primer-programa-en-tres-pasos)
2. [Tareas comunes](#2-tareas-comunes)
   - [2.1 Ejecutar con el intérprete o con la VM](#21-ejecutar-con-el-intérprete-o-con-la-vm)
   - [2.2 Construir la VM](#22-construir-la-vm)
   - [2.3 Usar la VM directamente](#23-usar-la-vm-directamente)
   - [2.4 El target web (WebAssembly)](#24-el-target-web-webassembly)
   - [2.5 Las pruebas de tu programa (`--test`)](#25-las-pruebas-de-tu-programa---test)
   - [2.6 Ver lo que entrega cada fase](#26-ver-lo-que-entrega-cada-fase)
   - [2.7 Reportar un bug: `--debug`](#27-reportar-un-bug---debug)
   - [2.8 El depurador y el servidor de lenguaje (editor)](#28-el-depurador-y-el-servidor-de-lenguaje-editor)
   - [2.9 La suite de pruebas del proyecto](#29-la-suite-de-pruebas-del-proyecto)
3. [Referencia](#3-referencia)

---

## Antes de empezar: convenciones de esta guía

- **Todos los comandos se escriben desde la raíz del repositorio** (la
  carpeta que tiene `V0/`, `lib/` y `build/`).
- Los bloques marcados `bash` valen igual en **Git Bash** (Windows) y en una
  terminal de **Linux o macOS**. Cuando PowerShell es distinto, va aparte.
- Lo que cambia entre sistemas:

  | | Git Bash (Windows) | PowerShell (Windows) | Linux / macOS |
  |---|---|---|---|
  | Python | `python` | `python` | `python` (en algunas distribuciones, `python3`) |
  | la VM | `build/bin/suriax-hir` (el `.exe` es opcional) | `.\build\bin\suriax-hir.exe` | `./build/bin/suriax-hir` |
  | una variable de entorno para un comando | `PYTHONUTF8=1 python ...` | `$env:PYTHONUTF8 = "1"` y luego el comando | `PYTHONUTF8=1 python ...` |
  | ver el código de salida | `echo $?` | `$LASTEXITCODE` | `echo $?` |

- **En Windows, activa `PYTHONUTF8=1`** si la salida de tu programa va a un
  archivo o a otro programa (`> salida.txt`, `| ...`) y lleva caracteres
  fuera del juego de Windows (`✓`, emoji, ideogramas). Sin ella el
  intérprete falla con un error interno (`ICE000`, ver
  [c_errorstfix.md](c_errorstfix.md), UB-1). Con ella funciona:

  ```powershell
  # PowerShell: vale para el resto de la sesión
  $env:PYTHONUTF8 = "1"
  ```

  ```bash
  # Git Bash: para toda la sesión
  export PYTHONUTF8=1
  ```

> Esta guía se comprobó en Windows 11 (Git Bash y PowerShell, Python 3.14,
> la VM construida con MSVC). Los comandos de Linux son los mismos de Git
> Bash; no se ejecutaron en Linux en esta revisión.

---

## 1. Tu primer programa en tres pasos

**Paso 1. Comprueba que tienes Python 3.10 o superior.** Es lo único que
hace falta: el compilador entero (y el intérprete que ejecuta los programas)
usa solo la biblioteca estándar de Python.

```bash
python --version
```

Se espera algo como `Python 3.14.7` (cualquier 3.10 o superior sirve).

**Paso 2. Escribe `hola.srcx`** en la raíz del repositorio:

```srcx
#from io #import stdp

fn main() -> int {
    stdp.println("hola, suriaX");
    return 0;
}
```

`#from io #import stdp` trae la librería de entrada/salida (vive en
`lib/io/`); `println` no es una palabra del lenguaje, es una función de esa
librería. Toda sentencia termina en `;`.

**Paso 3. Compílalo y ejecútalo:**

```bash
python V0/main.py hola.srcx --run
```

Se espera:

```text
frontend OK: 23 tokens, 2 items, 2 simbolos globales, 0 hooks, 0 casts
HIR (… bytes) generado en: …/dumps/hola.srcx.phir
  unidad 'IO.stdpf': … bytes -> …/dumps/IO.stdpf.phir
  unidad 'IO.stdp': … bytes -> …/dumps/IO.stdp.phir
  unidad 'IO': … bytes -> …/dumps/IO.phir
hola, suriaX
```

(Las rutas salen completas y los tamaños dependen de la ruta del archivo.)

Las líneas de arriba son del compilador: el *frontend* (las fases que leen y
comprueban el programa) terminó sin errores y se escribió el **HIR**, la
representación intermedia del programa, en un archivo `.phir` por cada
unidad (tu programa y cada librería que importa). La última línea es la
salida de tu programa. El número que devuelve `main` es el código de salida
del comando (`echo $?` en Git Bash, `$LASTEXITCODE` en PowerShell): aquí,
`0`.

Si el programa tiene un error, no se ejecuta; se explica qué pasó y dónde, y
el código de salida es `1`:

```text
=== errores semanticos (1) ===
  [critical] AST006: no se puede inicializar 'x' (int) con un valor de tipo 'str'  (line 2, column 5)
HIR no emitido: hay errores previos
(diagnosticos registrados en …/log/err.srcx.log)
```

**Dónde quedan los archivos.** Lo que produce el compilador va a `dumps/`
y los registros de errores a `log/`, las dos carpetas **junto al archivo
fuente** (en la raíz del repositorio, las dos están en `.gitignore`). Puedes
guardar tus programas en cualquier carpeta: la librería estándar se
encuentra igual.

> **`fn main` es opcional en el intérprete**: un archivo con sentencias
> sueltas (un *script*) se ejecuta en orden. **Hoy la VM todavía exige
> `main`** y responde `error de ejecucion: el programa no declara 'main'`
> (código `70`), así que un script se ejecuta con `--run interpreter`
> (siguiente sección):
>
> ```srcx
> #from io #import stdp
> stdp.println("hola");
> ```
>
> ```bash
> python V0/main.py script.srcx --run interpreter    # imprime: hola
> ```

---

## 2. Tareas comunes

### 2.1 Ejecutar con el intérprete o con la VM

suriaX tiene dos motores que ejecutan el mismo `.phir`:

- **el intérprete** (*tree-walk*, en Python): recorre el HIR y lo ejecuta.
  Siempre está disponible y tiene todo el lenguaje;
- **la VM** (`suriax-hir`, en C++): baja el HIR a **MIR** (una forma más
  cercana a la máquina, con registros y saltos) y lo ejecuta, mucho más
  rápido. Hay que construirla (sección 2.2) y todavía no tiene todo lo
  nuevo del lenguaje.

```bash
python V0/main.py hola.srcx --run                # el motor por defecto
python V0/main.py hola.srcx --run interpreter    # fuerza el intérprete
python V0/main.py hola.srcx --run compiler       # fuerza la VM
```

Sin valor, `--run` usa el motor que pide el `target` del
`.suriaX_config.yaml`; el valor por defecto es `native`, es decir, **la
VM**. Si la VM no está construida, o el programa usa algo que la VM todavía
no ejecuta, se ejecuta en el intérprete **avisándolo**:

```text
la VM no cubre este programa (4:31  VM004: 'prog.srcx' usa una lambda: ...): se ejecuta en el interprete
```

Sin `--run`, `python V0/main.py hola.srcx` solo **compila**: comprueba el
programa y muestra los errores, sin escribir el `.phir` ni ejecutarlo.

Hay dos atajos que compilan y ejecutan con el motor por defecto:

```bash
python main.py hola.srcx       # el lanzador de la raíz: añade --run
python -m suri hola.srcx       # el comando 'suri' sin instalarlo
```

`pip install -e .` instala el comando `suri` (`suri hola.srcx`), que hace lo
mismo que `python -m suri`.

### 2.2 Construir la VM

Necesita **CMake 3.20 o superior y un compilador de C++20**; no tiene otras
dependencias. `-DSURIAX_BUILD_NATIVE=OFF` deja fuera un módulo opcional del
intérprete que además pide `pybind11`.

**Windows (MSVC + Ninja).** El compilador `cl.exe` no está en el PATH de una
terminal normal: se carga con `vcvars64.bat` de Visual Studio. Desde
PowerShell, en un solo paso:

```powershell
cmd /c 'call "C:\Program Files\Microsoft Visual Studio\<versión>\Community\VC\Auxiliary\Build\vcvars64.bat" && cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release -DSURIAX_BUILD_NATIVE=OFF && cmake --build build --target suriax-hir -j 1'
.\build\bin\suriax-hir.exe --help
```

- `<versión>` es la carpeta de tu Visual Studio, por ejemplo `18`.
- `-j 1` compila un archivo por vez. En paralelo, MSVC puede quedarse sin
  memoria con `fatal error C1060: espacio de montón insuficiente en el
  compilador` (pasa en una máquina de 7 GB). Si tienes memoria de sobra,
  quítalo y será más rápido.
- El aviso `"vswhere.exe" no se reconoce como un comando...` que imprime
  `vcvars64.bat` no impide la compilación.
- La última línea es `[11/12] Linking CXX executable bin\suriax-hir.exe` y
  `--help` empieza por `uso: suriax-hir <archivo.phir> [opciones]`.

Cuando la carpeta `build/` ya está configurada, recompilar es solo
`cmake --build build --target suriax-hir`; si no hay nada que hacer,
responde `ninja: no work to do.`

**Linux / macOS:**

```bash
cmake -S . -B build -DSURIAX_BUILD_NATIVE=OFF
cmake --build build --target suriax-hir
./build/bin/suriax-hir --help
```

Las trampas de Windows, las demás opciones de CMake y los builds con
sanitizadores están en [CMake/README.md](CMake/README.md).

Con la VM en `build/bin/`, `python V0/main.py prog.srcx --run` ya la usa.
Las pruebas la buscan en `build/bin` y en los `build-*/bin`; la variable
`SURIAX_HIR_BIN` fija otra.

### 2.3 Usar la VM directamente

La VM lee un `.phir` ya escrito. Primero se emite con `--emit-hir`:

```bash
python V0/main.py hola.srcx --emit-hir          # -> dumps/hola.srcx.phir
build/bin/suriax-hir dumps/hola.srcx.phir --run
```

```text
hola, suriaX
[vm] main() -> 0
```

En PowerShell, la VM se llama `.\build\bin\suriax-hir.exe` con los mismos
argumentos.

| Comando | Qué hace |
|---|---|
| `build/bin/suriax-hir dumps/x.phir --run` | ejecuta e imprime al final `[vm] main() -> N` |
| `build/bin/suriax-hir dumps/x.phir --run --quiet` | solo la salida del programa |
| `build/bin/suriax-hir dumps/x.phir --run -- a b c` | pasa `a b c` como argumentos del programa (`sistema.proceso.argumento(1)` es `a`) |
| `build/bin/suriax-hir dumps/x.phir --run --memoria` | al terminar, cuántos objetos y cadenas creó y liberó (`[memoria] ...`) |
| `build/bin/suriax-hir dumps/x.phir --run --pasos 0 --memoria-max 512M` | sin límite de pasos y con un tope de 512 MB para el programa |
| `build/bin/suriax-hir dumps/x.phir --run --trace` | cada llamada y retorno (`[call]` / `[ret ]`) |
| `build/bin/suriax-hir dumps/x.phir --pretty` | el HIR legible |
| `build/bin/suriax-hir dumps/x.phir --mir` | el MIR y, al final, la verificación de propiedad (`0 problema(s) de propiedad`) |
| `build/bin/suriax-hir dumps/x.phir --check-mir` | sale con `0` si la VM puede ejecutar el programa entero, `1` (y qué falta) si no |

`--pasos N` (por defecto 100 millones) y `--memoria-max` existen para
máquinas modestas: cortan con un error que dice dónde (`RT010`, `RT023`) en
vez de que el sistema mate el proceso. La lista completa está en
[FLAGS.md](FLAGS.md#suriax-hir--el-backend-nativo-en-c).

### 2.4 El target web (WebAssembly)

El **target web** traduce el `.phir` a WebAssembly (el formato que ejecutan
los navegadores) y a JavaScript. Necesita **node 22 o superior** y ejecuta
un **subconjunto** del lenguaje: lo que no soporta lo rechaza con un código
`WEB`, sin ejecutar nada.

```bash
python V0/main.py hola.srcx --emit-hir
node web/main.ts dumps/hola.srcx.phir --run       # ejecuta el WebAssembly
node web/main.ts dumps/hola.srcx.phir --run-js    # ejecuta la versión en JavaScript
node web/main.ts dumps/hola.srcx.phir --emit-wat hola.wat --emit-wasm hola.wasm
```

`--run` imprime la salida del programa y `[wasm] main() -> 0`; `--run-js`,
`[js] main() -> 0`. Las demás opciones están en
[web/README.md](web/README.md). Con un programa que el target no soporta,
termina con código `1`:

```text
  [critical] WEB104: una lambda (una función sin nombre que lee su entorno): el target web todavía no las ejecuta; ...
no se puede ejecutar: el target web rechazó el programa
```

### 2.5 Las pruebas de tu programa (`--test`)

Un programa puede traer sus propias pruebas en bloques `test "nombre" { }`,
con `expect (condición);`:

```srcx
fn doble(int x) -> int { return x * 2; }

test "doble de 2 es 4" {
    expect (doble(2) == 4);
}

test "doble de 3 es 7 (falla a proposito)" {
    expect (doble(3) == 7);
}
```

```bash
python V0/main.py pruebas.srcx --test
```

```text
  PASS  doble de 2 es 4
  FAIL  doble de 3 es 7 (falla a proposito)  (expect falló: doble(3) == 7  (izquierda: 6, derecha: 7)  [8:5])

tests: 1 pasaron, 1 fallaron
```

`--test` corre las pruebas y **no** el `main`. Sale con `1` si alguna
falla. Las pruebas corren siempre en el intérprete. (Esto es distinto de la
suite del proyecto, sección 2.9.)

### 2.6 Ver lo que entrega cada fase

Ver qué produce cada fase del compilador es el objetivo del proyecto. Las
fases, en orden: **lexer** (parte el texto en *tokens*), **parser** (arma el
árbol del programa, el AST), **AST tipado** (el árbol con el tipo de cada
expresión), **semántica** (la tabla de símbolos y las comprobaciones) y
**HIR** (lo que reciben los motores).

**A la pantalla, con `--emit-stage`:**

```bash
python V0/main.py hola.srcx --emit-stage lexer     # los tokens
python V0/main.py hola.srcx --emit-stage parser    # el AST en JSON
python V0/main.py hola.srcx --emit-stage ast       # el AST tipado en JSON
python V0/main.py hola.srcx --emit-stage sem       # la tabla de símbolos
python V0/main.py hola.srcx --emit-stage hir       # el HIR en texto
python V0/main.py hola.srcx --emit-stage desugar   # el HIR legible, señalando el "azúcar"
```

La primera muestra, por ejemplo:

```text
=== #test lexer  (23 tokens) ===
[  0] Token(DIRECTIVE, '#from', 'from', 1:1)
[  1] Token(IDENTIFIER, 'io', 'io', 1:7)
...
```

`desugar` muestra, encima de cada sentencia, cómo se escribió, y en qué
convirtió el compilador cada atajo (`x += v`, `x++`, `with`...). Una fase
desconocida lista las válidas y sale con `2`.

**Desde el propio archivo, con `#test <fase>` en la primera línea.** El
compilador vuelca esa fase y termina:

```srcx
#test lexer
int a = 10;
printf(f"hola{a}");
```

```bash
python V0/main.py lex.srcx
```

```text
=== #test lexer  (13 tokens) ===
[  0] Token(DIRECTIVE, '#test', 'test', 1:1)
[  1] Token(IDENTIFIER, 'lexer', 'lexer', 1:7)
[  2] Token(INT, 'int', 'int', 2:1)
[  3] Token(IDENTIFIER, 'a', 'a', 2:5)
[  4] Token(ASSIGN, '=', '=', 2:7)
[  5] Token(INT_LIT, '10', 10, 2:9)
[  6] Token(SEMICOLON, ';', ';', 2:11)
[  7] Token(IDENTIFIER, 'printf', 'printf', 3:1)
[  8] Token(L_PAREN, '(', '(', 3:7)
[  9] Token(STRING_LIT, 'f"hola{a}"', Str(['hola', Interp('a')]), 3:8)
[ 10] Token(R_PAREN, ')', ')', 3:18)
[ 11] Token(SEMICOLON, ';', ';', 3:19)
[ 12] Token(EOF, '', None, 4:1)
```

Las fases de la directiva son las mismas de `--emit-stage` (`lexer`,
`parser`, `ast`, `sem`, `hir`, `desugar`) y no distinguen mayúsculas
(`#test HIR` vale). Como solo se tokeniza, `printf` no tiene que existir.

> `printf` no es una palabra reservada: sale como `IDENTIFIER`. La palabra
> de tipo `int` es el token `INT`; el literal `10`, `INT_LIT`.

**A un archivo en `dumps/`:**

| Bandera | Escribe |
|---|---|
| `--emit-tokens` | `<fuente>.tokens.txt`: los tokens |
| `--emit-ast-json` | `<fuente>.ast.json`: el AST tipado |
| `--emit-hir` | `<fuente>.phir` (y uno por librería) |
| `--hir-pretty` | `<fuente>.phir.pretty`: el HIR legible, una línea por sentencia, con los tipos y lo que el compilador inserta (`drop`, `⟨transfiere⟩`) |
| `--hir-text` | con `--emit-hir`: además `<fuente>.phir.txt`, el árbol crudo del formato |
| `--hir-schema 1` | con `--emit-hir`: el `.phir` en el **esquema 1** (cada tipo inline, sin pool de tipos) en vez del 2. Los tres lectores aceptan los dos |
| `--dump-symbols-table` | `<fuente>.symbols.mmd`: la tabla de símbolos como diagrama de clases (Mermaid) |

### 2.7 Reportar un bug: `--debug`

`--debug` reúne en **un solo archivo** el entorno, las dependencias, los
tokens, el AST tipado, la tabla de símbolos, el HIR, los tiempos de cada
fase y, si se ejecuta, la traza:

```bash
python V0/main.py prog.srcx --run --debug --trace-exec --trace-memory
# -> dumps/prog.srcx.debug.txt
```

`--trace-exec` (llamadas y retornos) y `--trace-memory` (`&`, `move`,
`free`) son del intérprete: con ellas se ejecuta en el intérprete aunque la
VM esté construida, y se avisa. Por separado:

```bash
python V0/main.py prog.srcx --run --trace-exec     # [call] main() ... [ret ] main -> 0
python V0/main.py prog.srcx --time                 # cuánto tardó cada fase
```

### 2.8 El depurador y el servidor de lenguaje (editor)

Los dos los lanza un **editor**, no se usan a mano: hablan por la entrada y
la salida estándar con un protocolo estándar.

- `python V0/main.py --dap` es el **depurador** (protocolo *DAP*, el de los
  depuradores de VS Code y otros editores): puntos de parada, paso a paso,
  la pila, las variables y su estado de propiedad. Depura en el intérprete.
- `python V0/main.py --lsp` es el **servidor de lenguaje** (protocolo
  *LSP*): errores mientras escribes, información al pasar el ratón, ir a la
  definición, los símbolos del archivo y completar.

En VS Code se usan con la extensión de [`tooling/vscode`](tooling/vscode/README.md)
(cómo probarla e instalarla está en su README; con un `.srcx` abierto, `F5`
depura). Otro editor configura `python V0/main.py --lsp` como cualquier
servidor LSP.

Lo que un editor usa por debajo también se puede pedir a mano; las tres
escriben JSON en la pantalla:

```bash
python V0/main.py prog.srcx --emit-diagnostics   # todos los errores, sin tocar el disco
python V0/main.py prog.srcx --emit-index         # los errores y los símbolos del archivo
python V0/main.py --emit-lang-info               # la especificación del lenguaje
```

Con `--stdin`, `--emit-diagnostics`, `--emit-index` y `--emit-stage` leen el
fuente de la entrada estándar (el nombre de archivo sigue haciendo falta,
aunque no exista):

```bash
cat prog.srcx | python V0/main.py nuevo.srcx --emit-diagnostics --stdin
```

### 2.9 La suite de pruebas del proyecto

Son las pruebas del **compilador** (no las de tu programa):

```bash
python test/main.py                       # las categorías de siempre (unos 6 minutos)
python test/main.py unit negative_tests   # solo algunas categorías
python test/main.py unit/test_lex         # categoría/prefijo: solo esos módulos
python test/main.py backend               # a pedido: la VM contra el intérprete
python test/main.py bootstrap             # a pedido: la V1 contra la V0
python test/main.py --todo                # todas
python test/main.py --json resumen.json   # además, un resumen en JSON (lo usa la CI)
```

No hace falta `PYTHONUTF8`: el runner se relanza solo en modo UTF-8. Al
final imprime el resultado:

```text
resultado: 1831 pasadas, 0 fallidas, 10 omitidas (1841 pruebas en 123 módulos).
```

Cada prueba termina **pasada** (`✓`), **fallida** (`✗`) u **omitida**
(`○`). Una omitida no se ejecutó porque falta algo en la máquina (node, la
VM, `memory_c`, `protobuf`...); se lista con su motivo y **nunca** cuenta
como pasada, pero no hace fallar la corrida. El código de salida es `1` si
algo falló y `2` con una categoría que no existe.

Las categorías de siempre son `unit`, `grammar`, `negative_tests`,
`snapshot`, `e2e` y `fuzz`; `backend` y `bootstrap` comparan dos
implementaciones y se piden por nombre. Hoy `backend` y `bootstrap` tienen
fallos conocidos (ver [c_errorstfix.md](c_errorstfix.md)).

Los ejemplos de la documentación se comprueban aparte (compilan, se
ejecutan y hacen lo que dice el texto):

```bash
python test/docs_examples.py
```

---

## 3. Referencia

### 3.1 Los comandos de un vistazo

| Para... | Comando | Dónde |
|---|---|---|
| compilar (y ver los errores) | `python V0/main.py prog.srcx` | §1 |
| compilar y ejecutar | `python V0/main.py prog.srcx --run` (o `python main.py prog.srcx`) | §2.1 |
| elegir el motor | `--run interpreter` / `--run compiler` | §2.1 |
| las pruebas del programa | `python V0/main.py prog.srcx --test` | §2.5 |
| ver una fase | `python V0/main.py prog.srcx --emit-stage lexer` | §2.6 |
| reporte para un bug | `python V0/main.py prog.srcx --run --debug` | §2.7 |
| ejecutar un `.phir` en el intérprete | `python runtime/interpreter/main.py dumps/prog.srcx.phir --exec` | §3.3 |
| construir la VM | `cmake --build build --target suriax-hir` (tras configurar) | §2.2 |
| ejecutar en la VM | `build/bin/suriax-hir dumps/prog.srcx.phir --run` | §2.3 |
| el target web | `node web/main.ts dumps/prog.srcx.phir --run` | §2.4 |
| la suite del proyecto | `python test/main.py` | §2.9 |
| compilar con la V1 | ver §3.5 | §3.5 |
| la documentación | `sphinx-build -b html -W --keep-going documentation/source documentation/build/html` | §3.6 |
| comprobar el entorno | `python V0/main.py --check` | §3.4 |
| crear la configuración | `python V0/main.py --init-config` | §3.4 |
| la versión | `python V0/main.py --version` | §3.2 |

### 3.2 El compilador: `python V0/main.py`

`main.py` añade solo lo que necesita al `sys.path` (no hace falta
`PYTHONPATH`), comprueba **solo** las dependencias de lo que se le pidió,
carga la configuración del proyecto del fuente, compila y, si se pide,
ejecuta. Los diagnósticos salen en la consola y en `log/<fuente>.log` (más
`errors.jsonl` / `notes.jsonl`), junto al fuente.

```bash
python V0/main.py --version     # suriaX <versión> (la lee de version.py)
python V0/main.py --help        # todas las banderas
```

**Códigos de salida:**

| Código | Significado |
|---|---|
| `0` | bien (o lo que devolvió `main` con `--run`) |
| `1` | el programa tiene errores de compilación (o una prueba de `--test` falló) |
| `2` | no se encontró el archivo, o una bandera o fase que no existe |
| `3` | falta una dependencia para lo que se pidió |
| `4` | error en las extensiones del proyecto (`EXT`) |
| `5` | `.suriaX_config.yaml` inválido (`CFG`) |
| `6` | error **interno** del compilador (`ICE000`): falló el compilador, no tu programa |
| `70` | error al ejecutar (`RTxxx`, una excepción sin atrapar) |

**Banderas.** Las de uso diario están en la sección 2; todas, con el detalle,
en [FLAGS.md](FLAGS.md#2-compilador-python-v0mainpy-source-flags).

| Bandera | Qué hace |
|---|---|
| `--run [interpreter\|compiler]` | emite el HIR y lo ejecuta (§2.1) |
| `--test` | corre los bloques `test` (§2.5) |
| `--emit-stage FASE` | vuelca una fase a la pantalla (§2.6) |
| `--emit-tokens`, `--emit-ast-json`, `--emit-hir`, `--hir-pretty`, `--hir-text`, `--dump-symbols-table` | escriben artefactos en `dumps/` (§2.6) |
| `--debug`, `--time`, `--trace-exec`, `--trace-memory` | depuración y medida (§2.7) |
| `--emit-diagnostics`, `--emit-index`, `--emit-lang-info`, `--stdin` | los canales del editor (§2.8) |
| `--dap`, `--lsp` | el depurador y el servidor de lenguaje (§2.8) |
| `--emit-extensions` | las extensiones del proyecto en JSON (ver [htims/readme.md](htims/readme.md)) |
| `--check`, `--init-config`, `--version` | el entorno y la configuración (§3.4) |

### 3.3 El intérprete por separado

El intérprete consume el `.phir`, no el fuente. `--run` lo hace en un paso;
también se puede invocar aparte:

```bash
python V0/main.py prog.srcx --emit-hir                          # -> dumps/prog.srcx.phir
python runtime/interpreter/main.py dumps/prog.srcx.phir         # resumen: funciones, tipos, hooks
python runtime/interpreter/main.py dumps/prog.srcx.phir --exec  # ejecuta
python runtime/interpreter/main.py dumps/prog.srcx.phir --test  # corre los bloques 'test'
python runtime/interpreter/main.py dumps/prog.srcx.phir --exec --trace-exec --trace-memory
python runtime/interpreter/main.py dumps/prog.srcx.phir --pretty   # el HIR legible
python runtime/interpreter/main.py dumps/prog.srcx.phir --text     # el árbol crudo
```

Cada librería importada tiene su propio `.phir` junto al principal; el
intérprete los liga al cargar.

### 3.4 Entorno y configuración

```bash
python V0/main.py --check          # qué hay instalado, la configuración y las rutas
python V0/main.py --init-config    # crea .suriaX_config.yaml en la carpeta actual (pide pyyaml)
```

`--check` marca cada dependencia como `[OK ]` u `[OPCIONAL]` y termina en
`0` aunque falten las opcionales.

**Dependencias.** Para compilar y ejecutar basta Python; lo demás es por
componente:

| Dependencia | Para qué | ¿Cuándo hace falta? | Instalación |
|---|---|---|---|
| *(ninguna)* | el compilador, el HIR y el intérprete | siempre: solo la biblioteca estándar | — |
| `pyyaml` | leer un `.suriaX_config.yaml` propio y `--init-config` | si usas un yaml propio (sin él se usan los valores por defecto y se avisa) | `pip install pyyaml` |
| CMake 3.20+ y un compilador de C++20 | la VM | solo para construirla (§2.2) | el del sistema; en Windows, MSVC |
| un compilador de C++ (`g++`/`clang++`) | programas con `#extern cpp{}` | solo si el programa trae ese bloque | el del sistema (o `$CXX`) |
| `pybind11` + CMake | la memoria nativa del intérprete (`memory_c`) | opcional: sin ella la memoria corre en Python, igual | `pip install pybind11` |
| node 22+ | el target web | solo para ese target (§2.4) | el gestor del sistema |
| Sphinx y sus extensiones | el sitio de documentación | solo para construirlo (§3.6) | `pip install -r documentation/requirements.txt` |
| `protobuf` | una prueba que compara el codec del HIR con `google.protobuf` | solo esa prueba (sin él se omite) | `pip install protobuf` |

Todo junto, para desarrollar: `pip install -r requirements.txt`.

**El archivo `.suriaX_config.yaml`.** Es la configuración del proyecto: el
compilador la busca a partir de la carpeta del fuente. `--init-config` lo
genera con lo que detecta en la máquina (compiladores, plataforma); estos son
los campos:

```yaml
version: 2
target: native              # native: '--run' usa la VM
                            # interp: el intérprete, y compilar ya ejecuta (sin '--run')
                            # wasm:   hoy '--run' ejecuta en el intérprete; el target
                            #         web se usa con 'node web/main.ts' (§2.4)
platform: win32             # win32 | linux | macos
optimization: O0

toolchain:                  # compiladores para '#extern cpp{}'
  linker: ...               # detectado
  sysroot: ''
  cxx_compiler: ...         # detectado: $CXX, g++ o clang++
  c_compiler: ...
  include_c_paths: []
  cxx_flags: []             # banderas extra de este proyecto para '#extern cpp'
  c_flags: []
codegen:
  triple: ...
  arch: ...
  artifact: exe
  wasm:
    enabled: false
    stack_size: 1048576
    export_all: false
output:
  dumps_dir: ./dumps        # .phir, .ast.json, .tokens.txt, .debug.txt...
  build_dir: ./build
logging:
  dir: ./log
  enabled: true
cache:
  dir: ./build/cache
  enabled: true
interpreter:
  entry: main               # la función de entrada
  trace_memory: false
  max_steps: 0              # 0 = sin límite
visualization:
  stages: []
  format: text
libraries:
  libsrx_paths:             # relativas a la carpeta del yaml; antes se busca
  - ./lib                   #   junto al fuente y al final en la stdlib
  extern_cpp_include: []
  bindings: []
project: ''
extensions: []
paths:
  input: ''
  output: out
flags:
  is_web: false
```

> En Windows, el `linker` detectado puede ser el `link.EXE` de Git (no es un
> enlazador): ver [c_errorstfix.md](c_errorstfix.md), sección Windows.

Las variables de entorno (`SURIAX_STDLIB`, `SURIAX_HIR_BIN`,
`SURIAX_CPP_FLAGS`...) están en [FLAGS.md](FLAGS.md#5-variables-de-entorno).

### 3.5 La V1: el compilador escrito en suriaX

`src/` es el compilador reescrito en suriaX (la **V1**). La V0 (el
compilador en Python) lo compila y la VM lo ejecuta. Los detalles están en
[src/readme.md](src/readme.md).

> **Hoy la V1 está atrasada respecto de la V0** (ver
> [c_errorstfix.md](c_errorstfix.md), sección 3): no conoce la sintaxis que
> usa `lib/array/vector.libsrx`, así que **no puede compilarse a sí misma**
> ni compilar un programa que importe `array.vector`. Un programa que use
> solo lo que la V1 conoce (por ejemplo, el `hola.srcx` del paso 1) sí se
> compila.

La V1 importa sus paquetes como librerías, así que se arma un proyecto con
ellos dentro de su `lib/`. En una carpeta aparte (aquí `v1`, en la raíz del
repositorio; `v1/` y `salida/` no están en `.gitignore`, así que bórralas
al terminar):

```bash
mkdir v1 && cp -r lib v1/lib
cp -r src/frontend src/semantica src/hir v1/lib/
cp src/main.srcx v1/
printf 'version: 1\ntarget: native\n' > v1/.suriaX_config.yaml
cd v1

python ../V0/main.py main.srcx --emit-hir     # la V0 compila la V1 -> dumps/main.srcx.phir

# la V1 compila un programa: escribe salida/hola.phir y un .phir por librería
cp ../hola.srcx .
../build/bin/suriax-hir dumps/main.srcx.phir --run --quiet -- hola.srcx salida/hola.phir --stdlib ../lib
../build/bin/suriax-hir salida/hola.phir --run
```

El último comando imprime `hola, suriaX` y `[vm] main() -> 0`.

- La stdlib le llega con `--stdlib` o con la variable `SURIAX_STDLIB`.
- Acepta `-O0` (el defecto); `-O1` y `-O2` son un error (sale con `2`): la
  V1 no optimiza.
- Con un programa con errores escribe un diagnóstico por línea, como
  `malo.srcx:2:5: AST006 no se puede inicializar 'x' (int) con un valor de tipo 'str'`,
  sale con `1` y no escribe el `.phir`.

Que la V1 se compile a sí misma (el *punto fijo*) se pedía así; **hoy
falla** por lo dicho arriba:

```bash
../build/bin/suriax-hir dumps/main.srcx.phir --run --quiet --pasos 0 -- main.srcx etapa2/main.srcx.phir --stdlib ../lib
```

**La V2 (la semilla).** `src/semilla/` guarda la V1 compilada por sí misma:
con ella y la VM se compila sin Python. Desde la raíz del repositorio (con
el `hola.srcx` del paso 1; escribe en `salida/`):

```bash
build/bin/suriax-hir src/semilla/main.srcx.phir --run --quiet -- hola.srcx salida/hola.phir --stdlib lib
build/bin/suriax-hir salida/hola.phir --run
```

Tiene el mismo límite que la V1 (no compila lo que importa `array.vector`).
La semilla se regenera con `python src/semilla/regenera.py`, que solo la
reemplaza si lo que sale se compila a sí mismo igual; hoy no puede,
porque la semilla no compila la V1 de hoy. Ver
[src/semilla/readme.md](src/semilla/readme.md). Todo esto lo comprueba
`python test/main.py bootstrap`.

### 3.6 La documentación

El sitio (Sphinx) se construye como en la CI
([docs.yml](.github/workflows/docs.yml)):

```bash
pip install -r documentation/requirements.txt
sphinx-build -b html -W --keep-going documentation/source documentation/build/html
```

`python test/docs_examples.py` compila y ejecuta los ejemplos de la
documentación y comprueba que hacen lo que dice el texto (al final:
`OK — los N ejemplos verificables se comportan como la documentación
promete.`). Un bloque que no es un programa completo se marca
`:class: fragmento` y no se verifica.

### 3.7 Lo que todavía no existe

- **Un ejecutable propio** (`.exe`, `.o`): la VM interpreta el MIR. El JIT
  es el siguiente gran paso (ver [ROADMAP.md](ROADMAP.md)).
- **Un comando para construir proyectos**: se compila un archivo por vez;
  las librerías se resuelven solas desde los `#import`.
