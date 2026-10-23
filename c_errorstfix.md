# Errores conocidos de suriaX

[![Versión](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/samue1-pineda/suriaX/badges/version.json)](version.py)

La biblia de los errores de la **versión publicada** (la de
[`version.py`](version.py)): todo lo que se sabe que falla. Si algo está
roto y no aparece aquí, lo que está incompleto es este documento. Solo lista
lo que **sigue abierto**; cuando algo se corrige, sale de aquí y queda en
[CHANGELOG.md](CHANGELOG.md).

Cada versión lanzada al público puede traer errores; aquí van TODOS los
conocidos, no solo los grandes.

## Cómo reproducir un error

Casi cada entrada lleva una línea **Reproducir** con un programa mínimo de
[`dev/repros/`](dev/repros/) y el comando que lo muestra. Desde la raíz del
repositorio:

```bash
bash dev/repros/run.sh <programa> [i] [c] [w] [v1]
```

`i` es la V0 con el intérprete, `c` la V0 con la VM, `w` el target web
(WebAssembly) y `v1` la V1 compilando el programa; sin motores corre `i c`.
El programa se copia a una carpeta temporal, así que no deja nada en el
repositorio. La VM tiene que estar construida y node instalado: ver
[how_to_run.md](how_to_run.md). Cada entrada dice qué sale hoy; si sale otra
cosa, el error cambió o se corrigió.

## Estado general

La regla de la 0.4.1 es que **lo nuevo se construye primero en la V0 y en el
intérprete**; la VM, el target web y la V1 se ponen al día después. Por eso
casi todo lo de abajo es "el motor X todavía no tiene lo que la V0 ya tiene".

- **Frontend de la V0** (lexer → parser → AST tipado → Semántica) y **HIR**:
  completos. El compilador entero —incluida la ejecución— corre **solo con
  la biblioteca estándar de Python**.
- **Intérprete tree-walk**: completo y al día con el lenguaje. Es el target
  `interp` y el oráculo de las pruebas diferenciales.
- **Backend C++** (`backend/`): lowering a MIR, VM de registros y
  verificación de propiedad. Hasta la 0.3.0 daba la misma salida que el
  intérprete en todo el corpus y era unas 150 veces más rápida. Lo que la
  0.4.1 añadió al lenguaje lo **rechaza con su código** (sección 1); lo que
  cambió de comportamiento, en algunos casos lo hace distinto, sin aviso
  (también en la 1).
- **Target web** (`.phir` → WIR → JS/WASM): ejecuta un subconjunto declarado
  y rechaza lo demás con un código `WEB` (sección 2).
- **Bootstrap** (`src/`, la V1, y `src/semilla/`, la V2): la V1 se compiló a
  sí misma en la 0.4.0 (el punto fijo) y daba los mismos diagnósticos que la
  V0 de entonces. **Hoy está atrasada** respecto de la V0 de la 0.4.1, y la
  semilla está rota con la librería de hoy (sección 3).

Es una pre-alpha: hace lo que dice hacer, con los límites de abajo.

---

## 1. VM (backend C++)

**Lo que la 0.4.1 añadió y la VM rechaza** (con su posición, y
`python V0/main.py prog.srcx --run compiler` cae entonces al intérprete con
un aviso):

- **`VM001`**: funciones como valores (`fn(A) -> R`).
  Reproducir: `bash dev/repros/run.sh vm001_fn_valor c` → "la VM no cubre
  este programa (3:1 VM001 …): se ejecuta en el interprete" y `6`.
- **`VM002`**: `case v` sobre un `T?`, `??`, variantes sobre un `E?` y los
  enums genéricos. Un programa que importa una librería con un enum genérico
  se rechaza entero, aunque no lo use (por ejemplo, `#import result`).
  Reproducir: `vm002_opcional`, `vm002_enum_generico` y `lib_result_vm`,
  con `c`.
- **`VM003`**: lo que despacha una cota en ejecución (`print(x)` con
  `T: Print`, `x.metodo()` con `T: Contrato`). Una librería que lo usara haría
  rechazar el programa entero. Reproducir: `vm003_cota c`.
- **`VM004`**: lambdas. **`VM005`**: `print(x)` de un primitivo.
  Reproducir: `vm004_lambda c`, `vm005_print c`.
- **Las llamadas al host nuevas son `RT008`**: la entrada estándar,
  `borrar`, `renombrar`, `modificado`, `sistema.comandos`, `sistema.tiempo` y
  el `text` nuevo (`lower`, `upper`, `is_*`, `split`, `split_whitespace`,
  `lines`, `trim*`, `count`, `rfind`, `replace`): 31 llamadas. Qué motor
  tiene qué está en [lib/LLAMADAS_AL_HOST.md](lib/LLAMADAS_AL_HOST.md).
  Reproducir: `vm_host_text` (intérprete `HOLA`; VM `RT008 … '__mayusculas__'`,
  exit 70) y `vm_host_tiempo`.

**Lo que la VM hace DISTINTO del intérprete, sin aviso:**

- **No ejecuta un programa sin `main`.** El intérprete corre las sentencias
  sueltas (modo script) y un archivo con solo definiciones; la VM, que es el
  motor por defecto de `--run`, dice "el programa no declara 'main'" y sale
  con 70. `--check-mir` lo da por bueno, así que no cae al intérprete.
  Reproducir: `nuevo_vm_script` (intérprete `hola`, VM exit 70) y
  `nuevo_vm_solo_defs`.
- **No conoce `__cmp__` ni la igualdad por valor**: `a < b` entre structs
  compara los *handles* y `==` sin `__eq__` es identidad, también entre dos
  variantes sin datos de un enum con datos (`Nada == Nada` es `false`).
  Reproducir: `vm_cmp` (intérprete `false`, VM `true`) y `vm_igualdad` (el
  intérprete da `true` en las 7 líneas; la VM, `false` en 5).
- **No destruye las globales**, ni al terminar bien ni tras un error.
  Reproducir: `vm_global_destruye` (intérprete `fin de main` y `free 1`; VM
  solo `fin de main`).
- **Un programa que aborta por un `RT` o por `salir()` no cierra sus
  ámbitos**, y ningún aborto destruye las globales; con una excepción sin
  atrapar, la VM sí destruye los locales. Reproducir: `vm_aborta_rt` (la VM
  libera el local pero no la global) y `vm_aborta_pasos`, que se corre con
  `--emit-hir` y `build/bin/suriax-hir dumps/vm_aborta_pasos.srcx.phir --run
  --pasos 1000` (`RT010` sin `free 1`).
- **No corre las pruebas del lenguaje**: lee un `test` con `expect`, pero
  `--test` usa siempre el intérprete (la VM no tiene modo de pruebas).
- **Leer una celda que se sacó con `mem.take`** lee `0` (el intérprete da
  `RT001`): la VM no lleva el estado de cada celda de un bloque, tampoco el de
  una celda sin escribir. Reproducir: `vm_mem_take` (intérprete `RT001`,
  exit 70; VM `tomado=5 despues=0`, exit 0).
- **Sus errores de ejecución no dicen en qué archivo ocurrieron** (el
  intérprete sí). La posición de una excepción de la librería (`e.linea`) es
  la de DENTRO de la librería (0:0 en `Vector`), y un `IndiceFueraDeRango` sin
  atrapar sale como `RT020`; el intérprete da la llamada del programa y
  `EXC002`. Reproducir: `vm_indice` y `host_escribir`.
- **Un préstamo que se cruza con una transferencia en otra rama** da códigos
  distintos al ejecutar: el intérprete `RT001`, la VM `RT003`. (Que no se
  detecte al compilar está más abajo.) Reproducir: `vm_prestamo_ramas`.
- **17 pruebas de `backend` fallan** (`python test/main.py backend`: 106
  pasadas, 17 fallidas). Dos por la destrucción de las globales
  (`test_destruir_por_tipo_en_los_dos_motores`,
  `test_una_global_propia_y_un_null_copiado`). Las otras 15 no son de la VM:
  sus programas usan `sizeof` sin `__sizeof__` o `&xs[i]` de un escalar, que
  la 0.4.1 convirtió en errores de compilación; hay que actualizar las
  pruebas (el programa de referencia de
  `test/backend/backend_cpp_support.py`, `test_sizeof_sin_hook_es_rt011_…`
  y `test_lo_que_ningun_motor_ejecuta_falla_igual_en_la_VM`).

- **`test/backend/test_backend_cpp_reader` falla entero (6 de 6)**: es parte
  de las 15 de arriba; su programa de referencia usa `sizeof(p)` sin
  `__sizeof__`, que hoy es `SEM001`.
- **Un `.phir` del compilador de agosto (commit `8b8e65e`) dice
  `schema_version: 1`, igual que uno de `--hir-schema 1`, y se acepta**,
  aunque no es una entrada soportada: su `try` usa los tags 2 y 3, que
  después cambiaron, y los tres lectores lo verían como un `try` sin ramas,
  sin avisar (deducido del código; no hay un `.phir` real para comprobarlo,
  porque aquel compilador necesita `google.protobuf`). Decisión del
  mantenedor: dejarlo documentado. Ver `dev/diff/schema/README.md`.

**Construirla:** el binario de `build/bin/` está al día; `build-msvc/` es un
build viejo (anterior a la 0.4.1) que se puede borrar. En esta máquina el
build con MSVC necesita `-j 1`: en paralelo se queda sin memoria (`C1060`)
en varios archivos (`view.cpp`, `rutas.cpp`, `suriax_hir.cpp`).

**Límites que ya tenía:**

- **Sin JIT ni binario**: la VM interpreta el MIR; no genera `.exe` ni `.o`.
  Decidido: el target nativo será una VM con JIT, no LLVM (pospuesto para
  una versión posterior).
- **La verificación de préstamos es local a un bloque**: prestar en una rama
  y transferir en otra no se cruza; compila y `--mir` dice "0 problema(s) de
  propiedad". Reproducir: `vm_prestamo_ramas`.
- **`#extern cpp` en la VM** tiene tres límites que el intérprete no tiene
  igual:
  - hasta 6 parámetros por función. Reproducir: `vm_extern_7` (intérprete
    `28`; VM "tiene mas de 6 parametros" y `RT008`);
  - la llamada se arma con una firma de enteros de 64 bits y doubles, que es
    correcta en las ABI de 64 bits (x86-64 de Linux y de Windows, AArch64)
    y no en una de 32 (no verificable en una máquina de 64 bits);
  - `suriax-hir` no lee el `.suriaX_config.yaml`: el compilador y las
    banderas salen de `$CXX` y `SURIAX_CPP_FLAGS` (y de los `requires(...)`
    de los bloques).

  Una excepción de C++ que cruza la frontera termina el proceso: el
  contrato es `extern "C"`. En la VM sale con 127 y **sin ningún mensaje**,
  y en el intérprete es un ICE000 (el UB-2, abajo). Reproducir:
  `extern_excepcion`.
- **El recolector de cadenas de la VM es conservador**: un registro que
  todavía guarda el índice de una cadena vieja la mantiene viva un rato más.
  `--memoria-max` recoge antes de rendirse, pero puede cortar con algo más de
  memoria de la que el programa usa de verdad. (Es del diseño: no hay un
  programa corto que lo muestre.)

## 2. Target web

**Lo que el diferencial de tres targets
([`dev/diff/RESULTS.md`](dev/diff/RESULTS.md)) encontró distinto:**

- **La división entera por cero no se traduce**: el WebAssembly hace un
  *trap* (`RuntimeError: divide by zero`, con la pila de node, exit 1); el
  intérprete y la VM dan `EXC001`, exit 70. Reproducir: `web_div_cero i w`.
- **`MIN / -1` no envuelve**: `RuntimeError: divide result unrepresentable`
  (exit 1), cuando `int` envuelve a 64 bits y el intérprete y la VM dan
  `-9223372036854775808`. Todo lo demás del desbordamiento (`max + 1`,
  `max * max`, `-min`, `min % -1`) envuelve igual en los tres. Reproducir:
  `web_min_div_menos_uno i w`.
- **Rechaza comparar un enum sin datos** (`c == Color.AZUL`, `WEB101`),
  aunque su propio mensaje dice que esos enums se representan. Reproducir:
  `web_enum_igual i w`.
- **Rechaza `Vector` y los structs** (`WEB002`, `WEB003`, `WEB006`,
  `WEB103`; `WEB100`/`WEB101`), y el primer diagnóstico apunta a
  `<stdlib>/array/vector.libsrx`, no al programa.
- **Su salida no es igual byte a byte en Windows** aunque el resultado sí lo
  sea: node escribe `\n` donde el intérprete y la VM escriben `\r\n`, y el
  CLI añade `[wasm] main() -> N` en la salida de error (no tiene `--quiet`).

**Lo demás:**

- **Rechaza lo nuevo de la 0.4.1** con su código: funciones como valores
  (`WEB103`), lambdas (`WEB104`), `T?` y `??` (`WEB101`, `WEB100`), enums con
  payload y valores de un parámetro de tipo (`WEB100`–`WEB102`), y `sistema`
  entero. Reproducir: `vm001_fn_valor w`, `vm004_lambda w`,
  `vm002_opcional w`, `web_enum_payload w`, `web_sistema w`.
- **No tiene `CMP` en su esquema** (`web/src/hir/schema.ts`): no ordena con
  `__cmp__`. No se llega a ejecutar: un `__cmp__` recibe punteros, que el web
  rechaza antes con `WEB002`.
- **`byte`, el formato de un f-string (`!r`, `:08b`), los operadores de bits
  y `hash(x)`** no bajan: se rechazan con un `WEB` explícito, no se ignoran.
  Reproducir: `web_bits_formato w`, `web_byte w`.
- **Lee las pruebas del lenguaje (`test`, `expect`) pero no las ejecuta**: las
  quita y baja el programa, así que una prueba que falla desaparece sin aviso.
  Reproducir: `web_test w` → `main`, exit 0.
- **`encodeModule` escribe `payloadTypeIds` con los índices del pool
  original** mientras numera uno nuevo (`web/src/hir/encode.ts`). Hoy no se
  nota: solo se usa la longitud.
- **`tsc --noEmit` no se ha corrido** sobre los cambios de la 0.4.1 (no hay
  `tsc` en esta máquina); las pruebas de node sí pasan.
- **El eliminador de código muerto no cuenta lo que se usa dentro de un
  `finally`** de un `try`: `collectUses` y `blockNames` de `web/src/opt/dce.ts`
  recorren `tryBlock` y `catches`, no `finallyBlock`. No se puede ejecutar:
  el target rechaza `try` (`web_try_finally w` → `WEB100`).

## 3. La V1 y la semilla (bootstrap)

La V1 se pone al día con la V0 en un lote propio, después de cerrar el
lenguaje de la 0.4.1 (decisión del mantenedor). Hasta entonces:

- **Las pruebas `bootstrap` dan 33 pasadas, 20 fallidas y 2 omitidas**
  (`python test/main.py bootstrap`): el parser (7), la V1 (5), la V2 (3), la
  semilla (2), el lexer (1), los diagnósticos (64 de 251 programas) y el
  punto fijo (`'dumps\main.srcx.phir' no se compila a sí mismo`). Todo por
  lo de abajo.
- **La V1 ya no se compila a sí misma ni la semilla compila nada que importe
  `array.vector`**: `vector.libsrx` usa `T: Ord` y tipos `fn(...)`, que la
  V1 no lee (`PAR003 … COLON`, `PAR023 … FUNCTION`); `test_semilla` falla
  también porque `sistema.archivos` cambió. Rodeo: la V2 funciona con
  `--stdlib` apuntando a la librería del último commit
  (`git archive HEAD lib`). Reproducir: `v2_vector v1`.
- **La V1 no conoce lo que añadió la 0.4.1**:
  - **léxico y sintaxis**: literales con exponente, la regla nueva de la
    interpolación (literales sin escapar dentro de `{}`), las posiciones
    reales de las expresiones de una interpolación, las cascadas quitadas, la
    declaración que empieza por `(tipo)?`, `fn(...)` como tipo, `lambda`, `??`,
    `case v`, los enums genéricos, las cotas, los métodos genéricos y los
    métodos llanos en un trait. Las posiciones se ven en el HIR: con
    `f"{a + 2}"`, el `2` lleva la columna 25 con la V0 y la 21 (la del
    comienzo de la interpolación) con la V1, así que los dos `.phir`
    difieren solo en campos `col` (`v1_columnas_fstring`; comparar
    `python runtime/interpreter/main.py x.phir --text` de los dos). Reproducir:
    `v1_exponente v1`
    (`PAR003 … IDENTIFIER`), `vm001_fn_valor v1`, `vm004_lambda v1`,
    `vm002_opcional v1`;
  - **pruebas del lenguaje**: todavía no compila un bloque `test` (lo dice y
    sale con 1). Reproducir: `v1_expect v1`;
  - **semántica**: la deducción nueva, las funciones como valores, los
    diagnósticos nuevos (`SEM040`–`SEM051`) y las ampliaciones de `SEM003`,
    `SEM013`, `SEM015`, `SEM025`, `SEM031` y `AST007`, el `SEM032` de
    `return g;`/`throw g;` y `sizeof` sin `__sizeof__` como error;
  - **enlazador**: todavía se encuentra a sí misma en un `#import` con su
    propio nombre. Reproducir: `v1_enlazador/text v1` (la V0 imprime `true`;
    la V1, `SEM010 'text.srcx' no termina en '#export …'`).
- Las pruebas de la V0 que usan sintaxis nueva van por `analyze` a
  propósito, para no entrar en el corpus del diferencial V0/V1.

## 3b. Segunda caza de fallos (lo que sigue abierto)

De la caza con 17 programas grandes (`audit/caza2/`) se corrigió todo lo que
daba una salida incorrecta o un fallo interno (ver el CHANGELOG). Queda:

- **Mensajes del host, en los dos motores**: `parse_float("3\n")` y
  `parse_int` escriben el salto crudo en el mensaje; "no se pudo escribir"
  no dice que falta la carpeta; ejecutar una carpeta dice "no existe el
  programa" (`runtime/interpreter/intrinsics.py`, `backend/src/vm.cpp`).
  Reproducir: `host_parse_float`, `host_escribir`, `host_ejecutar_carpeta`.
- **Un `?` suelto sin `:`** (`a ? 0`) da `PAR003` con el nombre interno
  `NULLABLE`; la pista del ternario solo sale con la forma `c ? a : b`.
  Reproducir: `par_ternario i`.
- **Un índice no entero sobre un puntero crudo** (`p[1.0]`) no se comprueba
  al compilar: es `EXC002: índice 1.0 fuera de rango` al ejecutar.
  Reproducir: `ptr_indice_float i`.
- **En un genérico, `{x!r}` de un `T` primitivo no distingue `str` de
  `char`** (el intérprete los representa igual): sale sin comillas.
  Reproducir: `generico_repr i`.
- **`print(e)` con `e` de un `catch` sin filtro** (tipo desconocido) es
  `RT006` al ejecutar, no un error al compilar. Reproducir: `print_catch i`.

## 4. Propiedad y memoria (intérprete y V0)

- **Un puntero a un local sin destructor que escapa** (a un vector, a un
  campo de salida) no se detecta: se lee el local muerto. Con destructor sí
  es `RT003`. Reproducir: `ptr_local_escapa i` (`r.p.v = 42`, exit 0) y
  `ptr_local_escapa_free i`.
- **La verificación de `move` no ve los bucles ni el paso de `try` a
  `catch`**: compila y es `RT001` al ejecutar. Reproducir: `move_bucle i`,
  `move_try i`.
- **Un puntero al campo de un elemento** (`&b[i].campo`) no detecta que su
  elemento fue reemplazado: lee el valor viejo. El de `Vector.at` sí
  (`RT003`). Reproducir: `ptr_campo_elemento i` → `1`.
- **`free` sobre un bloque crudo de `mem` compila**
  (`var int ptr mutable q = mem.reserve<int>(1); free q;`): el intérprete
  da `RT005` ("'free' sobre un valor que no es puntero") y la VM termina con
  0 sin decir nada. Un bloque se devuelve con `mem.release<int>(q)`.
  Reproducir: `free_bloque_mem`.
- **La destrucción de las globales no se ve en `--hir-pretty`**: la decide el
  intérprete mirando el valor, no viaja en el HIR (añadirla obliga a tocar el
  modelo C++ de la VM). Sí sale en `--trace-memory` (`[mem] drop global 'g'`).
  Reproducir: `vm_global_destruye` con `--hir-pretty`.
- **Un `__cmp__` que lanza a mitad de `v.sort()`** deja el vector en un
  estado no especificado: leerlo después da `RT001`. Reproducir:
  `cmp_lanza_sort i`.

## 5. Diagnósticos que faltan (análisis de flujo)

Todo lo de esta sección necesita seguir los caminos de una función, que la
Semántica de hoy no hace (quedó fuera de la 0.4.1 por decisión).

- **Que falte un `return` solo se ve al ejecutar** (`RT017`).
  Reproducir: `falta_return i`.
- **Un `SEM045` falso** si el parámetro de una lambda escrita en el valor de
  una global se llama igual que una global declarada después (caso extremo).
  Reproducir: `sem045_lambda i`.
- **Una global que lee otra declarada después A TRAVÉS de una función**
  llamada en su valor inicial sigue siendo `RT006` (el uso directo ya es
  `SEM045`). Reproducir: `global_por_funcion i`.
- **El aviso de código inalcanzable (`SEM048`) solo mira el mismo bloque**:
  un `if` cuyas dos ramas devuelven no hace inalcanzable lo que sigue.
  Reproducir: `sem048_ramas i` (sin aviso).

## 6. Librería y llamadas al host

- **`v.at(i)`/`at_mut(i)` no sirven con elementos escalares** (`SEM013` al
  compilar): se lee con `get`/`v[i]` y se escribe con `set`/`v[i] = x`.
  Prestar un escalar exige punteros al interior de un bloque, que ningún
  motor tiene; por eso `func.map`/`func.fold` le pasan a `f` un puntero a
  una COPIA (`SEM038` con un `T` con destructor). Reproducir:
  `lib_at_escalar i`.
- **Los predicados de `Vector`, `Dictionary.get_or`/`items` y
  `Result.unwrap_or` copian**: con un tipo con destructor son `SEM038` (se
  recorre con `at`, se abre con `match`). Reproducir: `lib_predicado_copia i`.
- **`result.Result` es del intérprete**: la VM rechaza todo programa que
  importe `result` (`VM002`), aunque no lo use. Reproducir:
  `lib_result_vm c`.
- **`text.is_digit` acepta dígitos de cualquier escritura (`'٣'`) y
  `text.parse_int` solo los ASCII**: un texto que pasa `is_digit` carácter a
  carácter puede no convertirse. Reproducir: `lib_digito i` → `true` y
  `EXC004`.
- **`pad_left`/`pad_right` cuentan caracteres, no columnas**: con emoji o
  ideogramas no alinean en una terminal. Reproducir: `lib_pad i`.
- **Lanzar un programa espera sin límite** a que termine, y lo que escribe se
  guarda entero en memoria (`subprocess.run` sin `timeout` en
  `runtime/interpreter/intrinsics.py`).

## 7. Playground

El detalle está en [playground/ARQUITECTURA.md](playground/ARQUITECTURA.md).

- **La página no tiene prueba automática**: se comprobó a mano en Chrome sin
  ventana. Su accesibilidad (WCAG 2.2) está hecha solo en lo básico
  (pestañas, estado, nombres de botones); contraste y lector de pantalla, sin
  evaluar. `app.js` sigue siendo un solo archivo de más de mil líneas.
- **Un hook de una librería importada se reporta en el archivo del usuario**
  (`WEB005` en la línea 175 de un programa de siete, y seis `WEB007` sin
  posición): la posición es la de la librería y el archivo, el del programa.
  Reproducir: compilar `dev/repros/web_sistema.srcx` en la página.
- **Mermaid viene de un CDN** (versión fija, sin comprobación de integridad).
- **El `Dockerfile` no se ha construido nunca.**
- **El caso más hondo que el lenguaje admite es caro**: una cadena de ~496
  operadores tarda unos 2 s y responde unos 9 MB, porque la vista de texto
  del HIR (el formato de protobuf, indentado) crece con el cuadrado de la
  profundidad.
- **Una compilación que no termine bloquea a las demás**: el compilador corre
  en el proceso del servidor, de uno en uno. Lo acota el tamaño del fuente.
- **Sin límite de peticiones por cliente**: se delega en la plataforma.

## 8. Editor y depurador

- **La extensión de VS Code no se ha probado dentro del editor**: los colores
  se comprobaron con su motor (el tokenizador que trae VS Code) y el
  depurador hablándole el protocolo, pero ni una cosa ni la otra en una
  ventana de verdad. No está publicada: le falta un icono, y el publicador
  `suriax` es provisional.
- **El depurador solo depura el intérprete**, no la VM, y bajo él la entrada
  estándar del programa está vacía (es el canal del protocolo).
- **Solo se pueden mirar nombres**, no expresiones (`a + 1`, `p.x`).
  Reproducir: `python dev/repros/dap.py dev/repros/dap_prog.srcx 4` →
  `'a + 1' no es un nombre a la vista`.
- **"Sin atrapar" es una aproximación**: si hay un `try` con algún `catch`
  alrededor, se da por hecho que lo recibirá, aunque el `catch` filtre por
  un tipo que no coincide. Con el filtro "todos" se detiene siempre.
  Reproducir: `python dev/repros/dap2.py dev/repros/dap_sin_atrapar.srcx`
  (no se detiene).
- **Depurando con `--test`, el marco de una prueba se llama `<módulo>`**, no
  con el nombre de la prueba. Reproducir: `python dev/repros/dap.py
  dev/repros/dap_prog.srcx 9 --test`.
- **No hay puntos de parada con condición** (se ignora la condición) ni se
  pueden cambiar valores (`setVariable` no está soportado).
- **El servidor de lenguaje reanaliza el archivo entero en cada cambio**:
  `src/semantica/resolver.libsrx` (4447 líneas) tarda 1,3–1,4 s por
  análisis en esta máquina, y mientras tanto no contesta hover ni
  definición. El remedio está en el compilador: una caché de librerías entre
  análisis (`nueva_compilacion()` la vacía en cada uno) o análisis
  incremental. Medir: `python dev/repros/lsp_t.py src/semantica/resolver.libsrx`.
- **El servidor de lenguaje solo analiza los documentos abiertos**, y un
  importador no se vuelve a analizar cuando cambia una librería abierta sin
  guardar. Sin referencias, renombrar, tokens semánticos ni acciones de código.

## 9. Rendimiento (medido en el intérprete)

- Unas 37 000 vueltas de bucle y 21 000 llamadas por segundo (según el
  cuerpo; `perf_bucle`): contar palabras en 71 KB tarda 40 s, y en 896 KB,
  ordenando las más frecuentes, 3 minutos; un diff de 200×200 líneas, 18 s;
  `Dictionary`, unas 4 000 operaciones por segundo. La pila admite entre ~830
  y ~1250 llamadas anidadas (según el marco) antes de `RT019`, que no se
  puede atrapar (`pila i`).

## 10. Herramientas y CLI

- **Con `target: wasm` en el yaml, `--run` ejecuta en el intérprete sin
  avisar** (`V0/driver/pipeline.py`), aunque el propio driver dice que
  ejecutar en otro motor del que se pidió no puede pasar en silencio.
- **La ayuda de `python V0/main.py --help` está desactualizada** (texto de
  `V0/cli/args.py`; `FLAGS.md` está bien): `--emit-hir` dice que escribe un
  `.phir.txt` y que requiere protobuf (ninguna de las dos); `--emit-stage` no
  lista `desugar`; `--stdin` no menciona `--emit-stage`; `--emit-ast-json`
  dice "JSONARCHIVO".
- **`#test <fase desconocida>` sale con 0** (lista las fases), mientras que
  `--emit-stage` con una fase desconocida sale con 2.

## 11. Windows

- **Imprimir caracteres fuera de cp1252 con la salida redirigida es un
  ICE000** (el UB-1, abajo). La suite no lo ve porque corre en modo UTF-8.
- **El `linker` autodetectado puede ser el `link.EXE` de Git** (coreutils,
  no un enlazador); `--init-config` lo escribe en el yaml. El mismo problema
  aparece al construir el backend con un `clang++` suelto: la guía
  [`CMake/README.md`](CMake/README.md) explica cómo usar MSVC.
- La suite solo corre en Ubuntu en la CI (el build sí corre en los tres
  sistemas): lo específico de Windows no lo ve un workflow. En esta máquina
  la suite pasa entera sin variables de entorno.

## 12. Repositorio

- **`backend.yml` y `bootstrap.yml` solo corren a mano** (Actions → "Run
  workflow") hasta que la VM y la V1 se pongan al día: fallan por las 17
  pruebas de `backend` de la sección 1 y las 20 de la sección 3, y en cada
  push salían rojos por algo ya sabido. Sus disparadores están comentados en
  el propio workflow, con la nota de restaurarlos. **No es que pasen**: siguen
  fallando si se lanzan, y `release.yml` (corre `python test/main.py --todo`,
  que incluye las dos categorías) no publicará la 0.4.1 hasta que pasen.
- **`tests.yml` falla en GitHub y no en local, por archivos que no se
  versionan**: en el commit `130b528` la CI dio 1811 de 1858 pasadas, 38
  fallidas y 9 omitidas; en local, 1850 pasadas y 0 fallidas. Las 38 tienen
  la misma causa: ese commit añadió `tooling/` al `.gitignore` (y `Procfile`
  ya estaba), así que en un checkout limpio no existen, y dependen de ellos:
  - `test_extension_vscode` (14) y `test_paquete_vsix` (5): leen
    `tooling/vscode/` (`package.json`, la gramática, los fragmentos,
    `generar.py`, `empaquetar.py`, `lanzar.py`);
  - `test_lsp_consultas` (6) y `test_servidor_lsp` (11): importan
    `tooling.lsp`. **No es solo de las pruebas**: `python V0/main.py --lsp`
    en un clon del repositorio termina en `ICE000` (`ModuleNotFoundError:
    No module named 'tooling'`, `V0/cli/__init__.py:200`);
  - `test_depurador_dap` (1): lanza `tooling/vscode/depurar.py`;
  - `test_playground::test_el_procfile_publica_el_servidor` (1): lee el
    `Procfile`.

  Hay que elegir entre versionar `tooling/` (y el `Procfile`) o sacar del
  clon público lo que depende de ellos (la bandera `--lsp` y esas pruebas);
  hoy el repositorio publicado promete un `--lsp` que no tiene.
- `docs.yml` fallaba en el commit `130b528` por tres advertencias que `-W`
  convierte en errores: un enlace de ROADMAP.md a `version.py` dentro de una
  medalla, que `conf.py` no reescribía, y dos bloques `code-block:: suriax`
  en `type_system.rst` (el lexer se registra como `srcx`). Corregido en el
  árbol de trabajo y **sin verificar con Sphinx** (no está instalado en la
  máquina del mantenedor): se confirma en el próximo push.
- `ci.yml` y `docs-examples.yml` pasan en la CI.
- **Aviso del compilador en `backend/src/vm.cpp:213`**: el orden de
  inicialización de `limite_bytes_` y `traza_` (`-Wreorder-ctor` en Clang,
  `-Wreorder` en GCC). Inofensivo, pero ensucia el build.
- **Falta un archivo que se cita**: `docs/propuesta_vm_bytecode.md` (lo citan
  `runtime/interpreter/ARQUITECTURA.md`, que lo llama "regla no negociable",
  `runtime/interpreter/readme.md` y el ROADMAP).
- **Una carpeta que no describe el código**: `V0/src/backend/` (planes de un
  backend LLVM que no existe).
- **Los ejemplos de `docs/examples/*.md` no los verifica ninguna prueba**, y
  7 de sus 22 bloques no compilan (`library_libsrx` 2, 3 y 4;
  `ownership` 3; `structs_and_control` 2 y 3; algunos pueden ser
  fragmentos).
- **`test/docs_examples.py` cita `test/e2e/test_docs_examples.py`, que no
  existe**: los ejemplos de la documentación solo los comprueba el workflow
  `docs-examples.yml`, no `python test/main.py`.
- **`test_escalado_lineal_del_frontend` tiene un umbral frágil**: si su
  medición dura menos de 10 ms la declara no fiable y se omite; en una
  máquina más rápida puede pasar a menudo.
- **`test/web/fixtures/IO.stdp.phir` no está en forma canónica** (mismos
  datos, otro orden de los maps), y **`V0/src/HIR/schema.py::_leer_campo`**
  descarta en silencio una línea del `.proto` que no entiende.
- **`.suriaX_config.yaml` está en `.gitignore`** y una prueba habla de "la
  configuración que se distribuye": hoy se omite diciéndolo.

## 13. Límites del lenguaje que parecen errores

No son fallos: son cosas que el lenguaje todavía no tiene. Se listan porque
quien las encuentra suele pensar que algo se rompió. Cada uno se ve con
`bash dev/repros/run.sh limites/<programa> i`.

- **Las lambdas no escapan, y no hay clausuras que sí lo hagan**: una
  lambda solo es el argumento de un parámetro `fn(...) -> R`, y ese parámetro
  no se guarda ni se devuelve (`SEM051`); para guardar una función recibida
  se declara `(fn(...) -> R)?`, que no admite lambdas. Una función genérica,
  un prototipo o un método de un tipo genérico no pueden ser valores
  (`SEM044`). Un "modo no seguro" para escapar de estas reglas, como el
  `unsafe` de Rust, está anotado como idea para después
  ([FUTURO.md](FUTURO.md)). (`l01_lambda_escapa`, `l02_generica_valor`)
- **Una lambda que lee lo que la función que la recibe está modificando**
  (`v.sort_by` con una lambda que lee `v`) es `RT001` al ejecutar: no se
  detecta al compilar. (`l03_lambda_lee_v`)
- **Un enum sin datos no cumple `Print`**: al ejecutar es un entero, y su
  `__print__` no se llamaría. (`l04_enum_print`)
- No hay bucle `for` ni un concepto de recorrido (iterador o rango): todo
  bucle es un `while`. Van juntos en una versión posterior. (`l05_for`)
- **No hay estrechamiento tras `if (x != null)`**: un `T?` se desenvuelve
  con `match` (`case null` / `case v`) o con `??`. (`l06_estrechar`)
- **`??` no suelta `mutable`**: con `q: (int ptr mutable)?`, `q ?? &n` exige
  que `&n` sea `int ptr mutable` exactamente. (`l07_mutable`)
- **Un `T? ptr` no es un sujeto opcional** para `match`: se desenvuelve el
  `T?` al que apunta; el mensaje (`SEM001: 'v' no está declarado`) no dice
  por qué. (`l08_opcional_ptr`)
- **Un trait de otra librería no puede ser cota** (`SEM021`) ni escribirse
  en `@impl(lib.Contrato)`. (`l09_trait_otra_lib`)
- `.name` de un enum solo vale sobre un item escrito (`TType.PLUS.name`), no
  sobre una variable. (`l10_name_variable`)
- No hay tablas Unicode en la V1 (ver `src/frontend/readme.md`); las
  subcadenas sí existen (`text.slice`).
- **Un bloque de `mem` guardado en un campo es del struct que lo guarda**
  (se copia y se libera con él, como el buffer de un `std::vector`). Un
  struct no puede PRESTAR un bloque ajeno en un campo: para prestar está un
  parámetro `ptr`. (`l11_bloque_en_campo`)
- **Copiar un struct copia todo lo suyo**, incluido el almacenamiento de sus
  vectores. `var vec.Vector<int> b = a;` cuesta O(n); para no copiar se usa
  `move` o un `ptr`. (`l19_copia_vector`)
- No hay literales de arreglo (`[1, 2, 3]`) ni arreglos nativos
  (`int xs[3]`); `int vec.Vector v[5];` sí existe. (`l13_literal_arreglo`,
  `l13b_literal_arreglo`, `l18_vector_decl`)
- Un `-/` dentro de un comentario de bloque lo cierra (no se anidan).
  (`l14_comentario`)
- No hay tipos recursivos (un árbol se guarda en una arena, enlazado por
  índices), ni una forma de sacar un valor de un campo dejando otro en su
  lugar (lo que en Rust es `mem::replace`). (`l15_recursivo`)
- Agotar la pila (`RT019`) no se puede atrapar: un programa recursivo no
  puede recuperarse de un anidamiento demasiado profundo en su entrada.
  (`l16_rt019`)

## Comportamiento indefinido conocido (UB → ICE000)

Un **ICE000** (error interno del compilador, exit 6) es un comportamiento
indefinido: el compilador no sabía qué hacer con ese programa. Cada caso
conocido se anota aquí con el programa que lo provoca y lo que DEBERÍA
pasar. Cuando recibe su propio error, o deja de fallar, sale de la tabla. La
meta es que se vacíe.

| UB | Programa que lo provoca | Hoy | Debería |
|---|---|---|---|
| UB-1 | En Windows, con la salida redirigida y sin `PYTHONUTF8`: `python V0/main.py dev/repros/ub1_unicode.srcx --run interpreter > out.txt` (`stdp.println("listo ✓");`, cualquier carácter fuera de cp1252) | ICE000: `UnicodeEncodeError` en el intrínseco `__write__` (`runtime/interpreter/intrinsics.py`). La VM no lo tiene | Escribir el texto (UTF-8), sin error |
| UB-2 | En Windows, una función de `#extern cpp` que lanza una excepción de C++, llamada desde el intérprete (`dev/repros/extern_excepcion.srcx`) | ICE000: `OSError: Windows Error 0xe06d7363` en `runtime/extern_cpp.py`. En la VM, exit 127 sin mensaje | Terminar con un error de ejecución que nombre la función de C++ (el contrato es `extern "C"`: no se atrapa) |

Si encuentras un ICE000 que no está aquí, es un UB nuevo: anótalo con el
programa mínimo que lo reproduce.
