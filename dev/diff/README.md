# Diferencial de suriaX 0.4.1: esquema 1 frente a 2 del HIR, en tres targets

Este directorio mide, sobre un conjunto fijo de programas, **cuánto mejora el
esquema actual del HIR (el 2) frente al inicial (el 1)** y si, por estar
versionado, **el 1 sigue funcionando** en los tres ejecutores de suriaX. Está
escrito para que otra persona lo **replique paso a paso** (es la base de un
póster). Hay dos comparaciones, y conviene no confundirlas:

1. **Esquema 1 frente a esquema 2 del HIR** (la principal). El mismo
   compilador, la V0, emite el `.phir` de cada programa con
   `--hir-schema 1` y con `--hir-schema 2`:
   - en el **esquema 1** cada tipo va escrito *inline* en su nodo;
   - en el **esquema 2** (el de hoy) el `Module` lleva un **pool de tipos**
     (`Module.types`) y los nodos, un índice (`type_id`).

   Los tres lectores aceptan los dos esquemas: al cargar un 1, lo normalizan
   al pool. Qué cambió exactamente está en [schema/README.md](schema/README.md).
2. **Compilador V0 frente a compilador V1** (un apartado aparte). La V0
   (Python, `V0/main.py`) y la V1 (el compilador escrito en suriaX, `src/`,
   que corre en la VM) compilan el mismo programa, las dos al esquema 2. Se
   compara su `.phir` byte a byte y lo que pasa al ejecutarlo.

Los **tres targets**:

- el **intérprete** tree-walk en Python (`runtime/interpreter/`);
- la **VM** en C++ (`build/bin/suriax-hir`);
- el **web**, en WebAssembly, ejecutado con node (`web/main.ts --run`).

Qué se mide, por programa y por `.phir` (esquema 1, esquema 2 y compilador V1):

- el **tamaño**: el `.phir` del programa y la suma de todas las unidades;
- la **emisión**, es decir, compilar a `.phir`;
- en cada target, la **lectura** (cargar, decodificar y ligar sin ejecutar);
- en cada target, la **ejecución**;
- la salida estándar y el **código de salida**, comparados con la
  referencia.

Cada celda se clasifica así:

- **OK**: la misma salida (ignorando `\r\n` frente a `\n`) y el mismo código
  que la referencia. La referencia es el intérprete con el esquema 2.
- **NOT SUPPORTED**: un compilador o un target **rechaza de forma explícita**
  algo que aún no soporta, con su código (`WEBxxx`, `VMxxx`, o la V1 con un
  error de sintaxis que todavía no conoce).
- **ERROR**: una divergencia de verdad al ejecutar. Es un trap, otra salida,
  otro código o una salida que no es la que exige la semántica documentada.

Cada medida se corre **30 veces** y la primera se descarta por calentamiento.
Se informa la **mediana** de las 29 restantes, con el mínimo, el máximo y el
rango intercuartílico (RIC).

Los resultados de la última corrida están en [RESULTS.md](RESULTS.md) y los
datos crudos, en [results.json](results.json).

---

## 1. Requisitos

Las versiones son las de la corrida publicada; si usas otras, anótalo.

| Qué | Para qué | Versión usada | Mínimo |
|---|---|---|---|
| git | clonar y anotar el commit | — | — |
| Python | V0, intérprete, arnés | Python 3.14.7 | 3.10 |
| pyyaml (opcional) | que la V0 lea `.suriaX_config.yaml`; sin él usa los valores por defecto y avisa | 6.0.3 | — |
| CMake | construir la VM | 4.4.3 | 3.20 |
| Ninja | generador de CMake | 1.x | — |
| Compilador de C++20 | la VM | MSVC 19.51 (Visual Studio, `vcvars64`) | MSVC 19.3x, GCC 10, Clang 12 |
| node | el target web | node v24.21.0 | 23 (quita los tipos de los `.ts` sin banderas) |

No se instala nada con `pip` ni con `npm`: el web no tiene dependencias y la
V0 solo usa la librería estándar de Python. La versión de suriaX es la
**0.4.1**, la que dice `version.py`. El arnés la anota en `RESULTS.md`.

## 2. Construir la VM

Todos los comandos se escriben **desde la raíz del repositorio**. Se usa
`-j 1` (un solo proceso de compilación) para que la construcción no compita
por la CPU ni por la memoria.

**Windows.** `cl.exe` solo está en el `PATH` dentro del entorno de Visual
Studio. Cambia `<versión>` por la tuya (por ejemplo, `18` o `2022`).

Desde `cmd`:

```bat
call "C:\Program Files\Microsoft Visual Studio\<versión>\Community\VC\Auxiliary\Build\vcvars64.bat"
cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release -DSURIAX_BUILD_NATIVE=OFF
cmake --build build --target suriax-hir -j 1
build\bin\suriax-hir.exe --help
```

Desde PowerShell o Git Bash, lo mismo en una línea a través de `cmd`:

```powershell
cmd /c '"C:\Program Files\Microsoft Visual Studio\<versión>\Community\VC\Auxiliary\Build\vcvars64.bat" && cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release -DSURIAX_BUILD_NATIVE=OFF && cmake --build build --target suriax-hir -j 1'
```

**Linux:**

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DSURIAX_BUILD_NATIVE=OFF
cmake --build build --target suriax-hir -j 1
./build/bin/suriax-hir --help
```

`SURIAX_BUILD_NATIVE=OFF` deja fuera la memoria nativa del intérprete, que
pide pybind11 y aquí no se usa. Si la VM está en otro lugar, pásala con
`--vm <ruta>` o con la variable `SURIAX_HIR_BIN`. Las trampas de Windows están
en [CMake/README.md](../../CMake/README.md).

## 3. Tener node a mano

El arnés busca node en este orden:

1. `--node <ruta>`;
2. la variable `SURIAX_NODE`;
3. el `PATH`;
4. la instalación por defecto de Windows (`C:\Program Files\nodejs\node.exe`).

Para comprobarlo:

```bash
export PATH="/c/Program Files/nodejs:$PATH"   # Git Bash, si node no está en el PATH
node --version                                 # v23 o más
```

```powershell
$env:PATH = "C:\Program Files\nodejs;$env:PATH"   # PowerShell
node --version
```

## 4. Probar la bandera `--hir-schema` a mano

Antes de medir conviene ver con los ojos que los dos esquemas se emiten y se
ejecutan. Desde la raíz, en una carpeta de trabajo, con un
`.suriaX_config.yaml` que fije el target:

```bash
mkdir -p dev/diff/work/manual && cp dev/diff/programs/02_aritmetica.srcx dev/diff/work/manual/
printf 'version: 1\ntarget: native\n' > dev/diff/work/manual/.suriaX_config.yaml
cd dev/diff/work/manual

# esquema 1 (tipos inline) y esquema 2 (pool de tipos), cada uno con sus librerías al lado
python ../../../../V0/main.py 02_aritmetica.srcx --emit-hir s1/02_aritmetica.srcx.phir --hir-schema 1
python ../../../../V0/main.py 02_aritmetica.srcx --emit-hir s2/02_aritmetica.srcx.phir --hir-schema 2
ls -l s1 s2                                                    # tamaños

# los tres targets, con cada esquema
python ../../../../runtime/interpreter/main.py s1/02_aritmetica.srcx.phir --exec
../../../../build/bin/suriax-hir s1/02_aritmetica.srcx.phir --run --quiet
node ../../../../web/main.ts s1/02_aritmetica.srcx.phir --run
```

En PowerShell los comandos son los mismos, salvo:

- la carpeta se crea con `New-Item -ItemType Directory -Force dev/diff/work/manual`;
- el YAML se escribe con
  `Set-Content -Encoding utf8 .suriaX_config.yaml "version: 1`ntarget: native"`;
- la VM se llama `..\..\..\..\build\bin\suriax-hir.exe`.

La bandera también se documenta en [FLAGS.md](../../FLAGS.md):

- `--hir-schema 2` es el valor por defecto;
- cualquier valor distinto de 1 o 2 lo rechaza la CLI con el código 2.

## 5. Generar los programas sintéticos

Los tres sintéticos ya están en `programs/`. Este paso los vuelve a generar y
comprueba que salen iguales:

```bash
python dev/diff/gen_synthetic.py
sha256sum dev/diff/programs/06_sintetico_*.srcx       # Linux / Git Bash
```

```powershell
python dev/diff/gen_synthetic.py
Get-FileHash dev/diff/programs/06_sintetico_*.srcx     # PowerShell
```

Con la semilla por defecto (`20261017`), los hashes tienen que ser estos:

```text
0e77b124618c70391afc4b8d20a3796f90b558d2f7f04a08e6d244979c29f4a7  06_sintetico_10.srcx
b18b3462bfdfa30a73bef38a58d4a58ae507c5116fb0ef3bb934148a44a55f07  06_sintetico_1000.srcx
f3e721f33a7b5208193fc158f63476f9ef6e6ea958f4d025aa7722422c4e2129  06_sintetico_10000.srcx
```

El generador es determinista y cada archivo tiene exactamente N sentencias;
un contador independiente lo comprueba. La cabecera de
[gen_synthetic.py](gen_synthetic.py) explica qué cuenta como sentencia y qué
construcciones usa.

## 6. Correr el arnés

Primero, una **prueba rápida**: 3 corridas por medida, unos 4 minutos.

```bash
python dev/diff/run_diff.py --reps 3
```

Después, la **corrida completa**: 30 corridas por medida. `RESULTS.md` dice
cuánto tardó ("Duración de la corrida"). Lo más lento es la V1 compilando el
sintético de 10.000 sentencias.

```bash
mkdir -p dev/diff/work && nohup python dev/diff/run_diff.py > dev/diff/work/full.log 2>&1 &   # Linux / Git Bash
```

```powershell
New-Item -ItemType Directory -Force dev/diff/work | Out-Null
Start-Process python -ArgumentList "dev/diff/run_diff.py" -RedirectStandardOutput dev/diff/work/full.log -NoNewWindow   # PowerShell
```

| Opción | Qué hace |
|---|---|
| `--reps N` | corridas por medida; la primera se descarta. Por defecto, 30 |
| `--only 01 08` | solo los programas cuyo nombre contiene esos textos |
| `--cell-budget S` | si el calentamiento de una celda dice que N corridas pasarían de S segundos (por defecto 1200), esa celda hace menos corridas, y queda escrito en `RESULTS.md` |
| `--timeout S` | límite de UNA corrida. Por defecto, 3600 s |
| `--vm`, `--node` | rutas de la VM y de node |
| `--render-only` | no mide nada: reescribe `RESULTS.md` y las figuras (`.svg`) desde el `results.json` que ya existe |

Qué hace el arnés, en orden:

1. **Anota el entorno**: SO, CPU, carga, versiones de Python, node y del
   compilador de C++, hash de la VM, versión de suriaX, commit y si hay
   cambios sin commit.
2. **Arma la V1** como `test/bootstrap/test_bootstrap_v1.py`: copia `lib/` y
   los paquetes `frontend`, `semantica` y `hir` de `src/` en
   `work/v1/lib/`, y la V0 compila `src/main.srcx`.
3. **Mide el arranque** de Python, node y la VM, sin hacer nada. Es la línea
   base.
4. **Mide cada programa** de `programs/`, en `work/programs/<programa>/`.
   Emite tres `.phir`, cada uno con sus unidades de librería en su carpeta:

   | Carpeta | Comando |
   |---|---|
   | `s1/` | `python V0/main.py prog.srcx --emit-hir s1/prog.srcx.phir --hir-schema 1` |
   | `s2/` | `python V0/main.py prog.srcx --emit-hir s2/prog.srcx.phir --hir-schema 2` |
   | `v1/` | `build/bin/suriax-hir work/v1/dumps/main.srcx.phir --run --quiet --pasos 0 -- prog.srcx v1/prog.srcx.phir --stdlib <repo>/lib` |

   Luego, con cada `.phir` y en cada target, mide la lectura y la ejecución:

   | Target | Lectura | Ejecución |
   |---|---|---|
   | intérprete | `python dev/diff/read_interp.py x.phir` | `python runtime/interpreter/main.py x.phir --exec` |
   | VM | `build/bin/suriax-hir x.phir --link` | `build/bin/suriax-hir x.phir --run --quiet` |
   | web | `node dev/diff/read_web.ts x.phir` | `node web/main.ts x.phir --run` |

5. **Escribe los resultados** después de cada programa: `results.json` (los
   datos crudos) y, desde esos mismos datos, `RESULTS.md` y las figuras
   (`figure.svg`, `size_change.svg`, `methodology.svg`). Una corrida
   interrumpida deja guardado lo medido hasta ahí.

En `<repo>/lib`, `<repo>` es la ruta del repositorio en cada máquina.

**Sin rutas de la máquina.** El propio arnés limpia todo lo que publica
(`RESULTS.md` y `results.json`), incluidas las salidas capturadas y los
comandos:

- las herramientas aparecen con su nombre y su versión (`Python 3.14.7`,
  `node v24.21.0`, `MSVC 19.51…`, `build/bin/suriax-hir.exe`);
- el repositorio, como `<repo>`;
- la carpeta personal, como `<home>`.

Los `.phir`, las salidas y el registro (`work/run.log`) van a `dev/diff/work/`,
que git ignora.

## 7. Leer los resultados

[RESULTS.md](RESULTS.md) va en este orden:

1. **Resumen**:
   - el **recuento** OK / NOT SUPPORTED / ERROR por `.phir` (esquema 1,
     esquema 2 y compilador V1);
   - el **esquema 2 frente al 1**: el tamaño, la emisión, la lectura y la
     ejecución por target, y en cuántos programas el 2 es mejor, peor o
     indistinguible;
   - las **pruebas estadísticas**: Wilcoxon de rangos con signo para el
     tamaño (pareada por programa, exacta) y U de Mann-Whitney para la
     lectura (por celda, con Holm), con sus límites escritos al lado.
2. **Entorno** y cómo se mide.
3. **Apartado 1**, esquema 1 frente a esquema 2, programa por programa.
   Termina con una tabla de los sintéticos.
4. **Apartado 2**, compilador V0 frente a compilador V1.
5. **NOT SUPPORTED y ERROR**, con su causa.
6. **Reducciones** de repeticiones y **límites** de la medición.

Cómo leer las tablas:

- **Celdas de tiempo**: en **negrita**, la mediana; entre corchetes, el
  mínimo y el máximo; RIC es el rango intercuartílico.
- **Esquema 1 → 2**: aparece como `mediana 1 → mediana 2 (cambio %; RIC 1 /
  RIC 2)` y un veredicto. Si los RIC de los dos se **solapan**, la diferencia
  se marca **"dentro del ruido"**. Es un criterio simple, no una prueba
  estadística, y no hay que leer en él más de lo que dice: las pruebas van
  en su propia subsección.
- **Tamaño**: es exacto (no tiene ruido).

[results.json](results.json) guarda, ya sin rutas de la máquina:

- los comandos;
- cada tiempo;
- las salidas de la primera corrida;
- los códigos de salida;
- si todas las corridas dieron lo mismo (`deterministic`).

### Las figuras del póster

- `figure.svg`, el resultado central: el estado de los 11 programas en los
  tres targets (OK, No soportado o Error, con color, etiqueta y la causa en
  palabras cuando no es OK). Hecha para un hueco de 26 × 21 cm: a esa
  escala el texto sale a unos 20 pt.
- `size_change.svg`, el detalle del tamaño: el cambio del `.phir` del
  esquema 1 al 2 para los 11 programas, en una sola escala y con la mediana
  (−7,3 %). En el póster va como un número; este gráfico es para el informe
  o el QR.
- `methodology.svg`, la metodología: las tres fases (diseño,
  implementación, evaluación) con su objetivo, la referencia y las tres
  categorías. Para un hueco de 26 × 28 cm.

Las escribe **el mismo `run_diff.py` que escribe `RESULTS.md`**, en el mismo
paso y desde el mismo `results.json`: no hay un segundo script que correr,
así que la figura y el informe no pueden venir de corridas distintas. Para
rehacerlas sin volver a medir:

```bash
python dev/diff/run_diff.py --render-only    # RESULTS.md y las tres .svg
```

`figure.py` y `methodology.py` son módulos de `run_diff.py`, no scripts:
`figure.py` clasifica cada celda con la misma función que escribe
`RESULTS.md` (`cell_status`), y hasta el título de `figure.svg` ("los estados
son idénticos") se calcula de los datos. Son SVG sin dependencias, con fondo
blanco: escalan sin perder calidad al imprimirlos.

`contract.svg` es la excepción: es un diagrama conceptual (el `.phir` como
contrato entre el frontend y los tres backends), no un resultado, así que no
sale de ninguna corrida y se edita a mano.

## 8. Los programas

| Archivo | Qué prueba |
|---|---|
| `01_hola.srcx` | hola mundo |
| `02_aritmetica.srcx` | precedencia, `/` y `%` con operandos negativos (en suriaX truncan hacia cero, como C; Python divide al piso), floats |
| `03_control.srcx` | `if`/`else if`/`else`, `while`, `break`, `continue`, bucles anidados |
| `04_vector.srcx` | `Vector` (`array.vector`): llenar, recorrer y sumar |
| `05_funciones.srcx` | recursión (factorial, fibonacci, mcd, Ackermann, recursión mutua) |
| `06_sintetico_{10,1000,10000}.srcx` | sintéticos generados (§5) |
| `07_division_cero.srcx` | error de ejecución: división entera por cero |
| `08_desbordamiento.srcx` | `int` de 64 bits que **envuelve** al desbordar (`documentation/source/type_system.rst`) |
| `09_structs.srcx` | **extra**: un struct por valor; muestra por qué los sintéticos no usan structs |

`02_aritmetica.expected` y `08_desbordamiento.expected` tienen la salida que
exige la **semántica documentada**: dividir truncando hacia cero y envolver a
64 bits con signo. Se calcularon aparte, con aritmética de Python explícita:

1. el cociente es `|a| // |b|`, con el signo de C;
2. el resultado se reduce con `x & (2**64 - 1)` y se lee en complemento a
   dos.

Si una celda no da esa salida, es ERROR aunque coincida con la referencia.

## 9. Decisiones tomadas al construir el diferencial

- **La referencia es el intérprete con el esquema 2** emitido por la V0. Es
  el formato de hoy en la implementación original del lenguaje.
- **Cada `.phir` se ejecuta con SUS unidades de librería.** El esquema 1 se
  ejecuta con librerías en esquema 1, y el compilador V1 con las que emitió
  ella misma.
- **El esquema 1 que se mide es el "adaptado a hoy"**, el que emite
  `--hir-schema 1`, y no un `.phir` del compilador de agosto de 2026. Ver
  [schema/README.md](schema/README.md).
- **Los sintéticos no usan structs.** El web todavía los rechaza (WEB100 y
  WEB101), y con structs ningún sintético habría corrido en el web. El rechazo
  queda medido en `09_structs.srcx`.
- **Los sintéticos no comparan enums con `==`.** El web lo rechaza con WEB101;
  se usa `match`.
- **`MIN / -1` va al final de `08`.** En wasm es un trap que corta el programa,
  y así las líneas anteriores sí se comparan en el web.
- **Qué cuenta como NOT SUPPORTED:**
  - un **rechazo explícito con código**: `WEBxxx` en el web, `VMxxx` en la
    VM, o la V1 saliendo con 1 y diagnósticos `archivo:línea:col: CÓDIGO`;
  - las celdas de un `.phir` que no se emitió, que heredan ese estado.
- **Qué cuenta como ERROR:**
  - un trap;
  - otra salida u otro código de salida;
  - una salida distinta de la esperada;
  - una salida distinta entre corridas;
  - en el apartado de compiladores, un `.phir` de la V1 distinto del de la V0.
- **Qué NO cuenta como error** (la celda es OK y se anota):
  - `\r\n` frente a `\n`;
  - la marca `[wasm] main() -> N` del web en stderr;
  - el prefijo `error de ejecucion: ` de la VM.
- **La `lib/` no se copia** en la carpeta del programa. La V0 la encuentra
  sola y escribe `<stdlib>/...`; la V1 la recibe con `--stdlib`. Si se
  copiara, los HIR diferirían por la ruta y no por el compilador.

## 10. Fallos encontrados y reproducciones mínimas

Los encontró este diferencial en la **0.4.1** (commit `94aebd4` más los
cambios sin commit del momento; el entorno exacto está en `RESULTS.md`). Para
reproducirlos hace falta:

- una carpeta con un `.suriaX_config.yaml` que diga `version: 1` y
  `target: native`;
- la V1 armada como en el §6, paso 2.

1. **La V1 da otras columnas que la V0 dentro de una interpolación de
   f-string** (ERROR del compilador V1). Pasa en `02`, `03`, `05` y `08`.
   Para reproducirlo:

   ```text
   #from io #import stdp
   fn main() -> int {
       var int a = 1;
       stdp.println(f"{a + 2}");
       return 0;
   }
   ```

   - **Con la V0**, el literal `2` lleva `col: 25`, que es su columna.
   - **Con la V1** lleva `col: 21`, la de `a`, donde empieza la
     interpolación. En `{2 + 3 * 4}` (programa `02`), todos los nodos quedan
     en la columna 45.

   Para verlo, compara `python runtime/interpreter/main.py x.phir --text` de
   los dos `.phir`. El árbol y la salida son los mismos; cambian las
   posiciones, que son las que usan los mensajes de error.
2. **El web no traduce la división entera por cero** (ERROR, programa
   `07_division_cero.srcx`). `10 / cero()` da:
   - en el intérprete y en la VM, `EXC001: división por cero` con código 70;
   - en el web, el trap de wasm `RuntimeError: divide by zero`, con la pila
     de node y código 1.
3. **El web no envuelve `MIN / -1`** (ERROR):

   ```text
   var int min = 0 - 9223372036854775807 - 1;
   stdp.println(f"{min / -1}");
   ```

   - El intérprete y la VM dan `-9223372036854775808`: envuelven, como dice
     `type_system.rst`.
   - El web atrapa con `RuntimeError: divide result unrepresentable` y sale
     con código 1.

   `min % -1` sí da `0` en los tres.
4. **El web no acepta comparar enums sin datos con `==`** (NOT SUPPORTED,
   aunque su propio mensaje dice que esos enums se representan):

   ```text
   enum Color { ROJO, VERDE, AZUL };
   fn main() -> int { var Color c = Color.AZUL; if (c == Color.AZUL) { return 7; } return 0; }
   ```

   El web da `WEB101: el operando es de tipo 'Color' ...`. El intérprete y la
   VM lo ejecutan y devuelven 7.
5. **La V1 no compila `lib/array/vector.libsrx` de hoy** (NOT SUPPORTED,
   programa `04_vector.srcx`). Cualquier programa con
   `#import array.vector` falla en la V1:
   - PAR003 en la cota `@impl Vector<T: Ord>` (línea 275);
   - PAR023 en los parámetros de tipo función `fn(T ptr, T ptr) -> int`
     (líneas 358 y 490).
6. **El web no ejecuta `Vector` ni structs** (NOT SUPPORTED). `Vector` da
   WEB002, WEB003, WEB006 y WEB103; los structs, WEB100 y WEB101. Las
   limitaciones están documentadas, pero dejan `04` y `09` fuera del web.
