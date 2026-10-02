# Registro de cambios

Lo que cambió en cada versión de suriaX, de la más nueva a la más antigua.
Lo que **sigue fallando** en la versión publicada está en
[c_errorstfix.md](c_errorstfix.md); cuando algo de allí se corrige, sale de
ese documento y queda registrado aquí.

Cada entrada dice qué cambió y por qué importa, no solo el nombre del
arreglo: suriaX es un compilador para aprender, y el porqué es la mitad de
la lección.

---

## [0.3.1] — en desarrollo

La 0.3.0 fue un rescate de urgencia. Esta versión repone lo que faltó, pone
la documentación al día, estabiliza el linker, los genéricos y las
excepciones, y empieza el bootstrap.

### Añadido

- **Excepciones del runtime que se pueden atrapar (`EXC`).** Dividir entre
  cero (`EXC001`) o leer fuera de un índice (`EXC002`) ya no termina el
  programa de golpe: el runtime lanza un valor y el `try` más cercano lo
  recibe, igual que un `throw`. Los tipos viven en la librería estándar
  `excepciones`.
- **La librería `excepciones`: el repertorio en un solo lugar**, como en
  Python. Trae las que lanza el runtime (`DivisionPorCero`,
  `IndiceFueraDeRango`) y las de uso general para lanzar desde el programa:
  `ValorInvalido`, `NoEncontrado`, `NoImplementado` y `EstadoInvalido`.
- **`throw r;` cede el valor sin escribir `move`**, igual que `return r;`.
  Después de un `throw` la variable no puede volver a usarse, así que el
  `move` no le diría nada al lector; el compilador lo inserta y el HIR lo
  muestra (`throw move r`).
- **Errores nuevos**:
  - `SEM034`: un `throw` escrito dentro de un `__free__` (un destructor
    nunca lanza);
  - `SEM035`: una división entre un cero escrito (`x / 0`);
  - `SEM036`: ceder (`move`, `return`, `throw`) algo con destructor a
    través de un puntero, que es de otro;
  - `RT019`: desbordamiento de pila;
  - `RT020`: `throw` no capturado;
  - `RT021`: un `__free__` que lanza al ejecutarse.
- **El frontend de suriaX, escrito en suriaX** (`src/frontend/`): primer paso
  del bootstrap.
  - El lexer se compara token a token con el de la V0: leyendo su propio
    fuente, los dos dan los mismos 3833 tokens.
  - El parser, con toda la gramática menos `#extern cpp`, se compara nodo
    por nodo con el árbol de la V0, y también el primer error de 33
    programas inválidos. Leyendo `expresiones.libsrx`, los dos dan las mismas
    3260 líneas de árbol.
- **Series de programas de prueba** que se leen como ejemplos:
  - `test/e2e/excepciones/`: dieciocho programas comentados, al estilo de la
    suite de CPython;
  - `test/e2e/fuego/`: programas reales y completos.
- **El comando `suri`** (`pip install -e .`), con `pyproject.toml` repuesto.
- **Los errores internos tienen código propio**: `ICE000`, código de salida
  6, con el traceback original y la fase. Los casos conocidos se catalogan
  como comportamiento indefinido en `c_errorstfix.md`.
- **La VM de C++ ejecuta todo el corpus igual que el intérprete**, incluidos
  el lexer y el parser del bootstrap, y es entre 130 y 320 veces más rápida (9 con cadenas).
  - Nuevo en la VM:
    - las excepciones del runtime (`EXC001`, `EXC002`), que se atrapan;
    - `RT001`/`RT002`/`RT003` (uso tras `move` o `free`) y `RT021`;
    - los nullables de un struct, un puntero o una cadena;
    - `error T`;
    - las conversiones de la tabla `__cast__` (`cast<dt.int8>(300)` da
      44);
    - `==` con `__eq__`;
    - las variantes nombradas por la ruta de otra unidad;
    - los temporales que mueren al cerrar su sentencia.
  - `test/backend/test_vm_diferencial_*.py` compara los dos motores programa por
    programa: salida, código de salida y códigos de error.
- **Un banco de medida, `dev/bench_vm.py`**, y el documento de la decisión
  que lo usa
  ([`vm_decision.rst`](documentation/source/vm_decision.rst)): por qué hay
  una VM de registros, cómo se midió y qué enseñó la medición.
- **Una guía de CMake** ([`CMake/README.md`](CMake/README.md)): compilar en
  Linux, macOS y Windows, las reglas del build y cómo añadir un binario
  nuevo.
- **`suriax-hir --run --trace`**: escribe cada llamada y cada retorno de la
  VM.
- **La librería `sistema`: archivos, argumentos y salida**, lo que necesita un
  compilador escrito en suriaX:
  - `leer`, `escribir`, `existe`, `listar`, `argumentos`, `argumento`,
    `escribir_error` y `salir`;
  - los argumentos van después de `--` (`suri prog.srcx -- a b`);
  - un fallo de archivo es la excepción nueva
    `excepciones.ErrorDeArchivo` (`EXC003`).

  Son llamadas al host, no syscalls, con el mismo contrato en el intérprete
  y en la VM:
  - UTF-8 sin traducir los fines de línea;
  - mensajes de error canónicos;
  - el listado sale ordenado;
  - `salir` no desenrolla.
- **La VM libera memoria.** Cada objeto muere con su dueño:
  - al cerrar su ámbito;
  - al salir por `return`, `break` o una excepción;
  - al terminar la expresión que lo creó, si nadie lo tomó;
  - al asignarle otra cosa a su lugar.

  Los handles llevan una generación: un objeto liberado da `RT003`, nunca
  el objeto de otro. Las cadenas se recogen con un barrido conservador y
  amortizado. `suriax-hir --run --memoria` dice qué quedó vivo al terminar,
  y el diferencial exige que no quede nada: todo el corpus, el lexer y el
  parser del bootstrap terminan con cero objetos y cero cadenas vivas.
- **Los genéricos se monomorfizan en el backend**: una función por juego de
  tipos concretos. El HIR lleva ahora los parámetros de tipo de cada
  función y struct (`FunctionDecl.type_params`, `StructDecl.type_params`).
- **Un build de diagnóstico con sanitizadores** (`-DSURIAX_SANITIZE=address`
  o `address;undefined`). La CI corre las pruebas e2e contra la VM con ASan
  y UBSan. En MSVC es ASan con los iteradores verificados de Debug.
- **`finally`**: un bloque que corre al salir del `try` por cualquier camino
  (normal, `return`, `break`/`continue`, excepción atrapada o no), en el
  intérprete, la VM y el parser del bootstrap. El valor de un `return` se
  calcula antes del `finally`, y lo del `try` se destruye antes de él.
  - `PAR027`: `return`, o `break`/`continue` que salen del `finally`. Salir
    de él reemplazaría la salida en curso y se tragaría una excepción en
    vuelo (la regla de PEP 765).
  - `RT022`: el `finally` lanzó mientras ya subía otra excepción.

  No hay una variante que corra solo al fallar (`errdefer` en Zig): un
  `catch` que relanza ya lo dice, y el `__free__` ya limpia los recursos.
- **Operadores de bits**: `&`, `|`, `^`, `~`, `<<`, `>>` y sus compuestas,
  sobre `int`. La precedencia es la de Python y Rust (`a & b == c` es
  `(a & b) == c`), `>>` conserva el signo y un desplazamiento fuera de
  `[0, 64)` es `excepciones.DesplazamientoInvalido` (`EXC005`). El lexer no
  emite `>>`: el parser junta dos `>` pegados, así `Vector<Vector<int>>` sigue
  cerrando dos genéricos.
- **`with`**: un recurso (`with (var File f = open(...))`), la forma de
  llamada (`with open(var File f, "x.txt", "w")`), un guardián sin nombre
  (`with (cambiar_idioma("en"))`, que se deshace con su `__free__`) y un
  receptor (`with (ventana) { .ancho = 900; .show(); }`, sin copiar el lugar).
  Es azúcar sobre RAII. `.campo` sin un `with` de un valor es `PAR028`.
- **`sistema.archivos.File`** y `open(ruta, modo)` ("r", "w", "a"), para
  usar con `with`: se cierra solo al salir del bloque.
- **`collections.Dictionary<K, V>`** (`put`, `get`, `contains`, `remove`,
  `len`, `keys`, `values`), escrito en suriaX. Claves nativas (`int`, `bool`,
  `char`, `str`, enums sin payload) o structs con `__hash__` y `__eq__`.
- **`hash(x)`** y el hook `__hash__`: nativo sobre los primitivos (splitmix64
  y FNV-1a, el mismo número en los dos motores) y resuelto con el tipo
  concreto en un genérico.
- **`--run compiler|interpreter`**: `--run` a secas ejecuta en el motor del
  `target` del yaml, y por defecto (`native`) es la **VM compilada**. Sin la
  VM construida, o si su MIR no cubre el programa, se interpreta con un aviso.
  `suriax-hir` gana `--quiet`, `--arg0` y `--check-mir`.
- **La VM baja todo lo que el intérprete ejecuta** (lo que ningún motor
  ejecuta, `&v[i]`, es `RT011` en los dos al ejecutarlo):
  - `&p.x` sobre un campo escalar: el campo guarda una celda en todas las
    instancias de su struct, que se copia y se libera con él;
  - `&n` sobre un local, un parámetro o una global escalar: el escalar vive
    en una celda del montón y su handle es la dirección (`p[0]` la lee);
  - `int?`, `float?`, `bool?` y `char?`: el valor es una celda (o null), que
    se copia y se libera como cualquier objeto;
  - `%` entre flotantes (`fmod`), `<`/`>` entre cadenas, y un enum dentro de
    un f-string, con el mismo texto que el intérprete;
  - `sizeof` sin `__sizeof__` es `RT011` al ejecutar, como en el intérprete,
    en vez de un programa que la VM no acepta.
- **`#extern cpp` en la VM.** `suriax-hir --run` construye el C++ del
  programa junto al `.phir` (o carga el de `--extern <biblioteca>`) y liga
  sus prototipos con la misma tabla de tipos que el intérprete. Un bloque de
  `int` o `float` cruza como la memoria de la VM, sin copiarse: C++ escribe
  en las mismas celdas. El corredor del intérprete (`runtime/interpreter/
  main.py --exec`) también liga ahora el `#extern cpp`.
- **Destruir POR TIPO ("drop glue")**: lo que el frontend no puede aplanar
  en su lista de destrucciones —un `T` de un genérico, un `catch (e)` sin
  tipo, el valor viejo de una asignación, las celdas de un bloque— se
  destruye por su tipo concreto, con la misma regla en los dos motores: si
  declara `__free__`, ese (y se hace cargo de sus campos); si no, sus campos,
  del último al primero; un bloque, sus celdas no vacías. En el HIR son dos
  campos nuevos (`Drop.by_type`, `Assignment.drops_old`); en la VM, la
  instrucción `Destruir` y el `__free__` de cada forma.
- **Los contenedores son dueños de sus elementos.** `Vector<R>` y
  `Dictionary<K, R>` destruyen sus elementos al morir, al reemplazarlos
  (`set`, `put`) y al quitarlos (`remove`). Nuevos: `v.at(i)` y `d.at(k)`
  PRESTAN el elemento (un puntero, sin copiarlo) y `v.take(i)` y `d.take(k)`
  lo SACAN; `pop` ya no copia. En `mem`: `take` (saca una celda) y
  `transfer` (mueve un tramo; `move` es palabra reservada), y soltar un
  bloque destruye lo que tiene.
- **SEM038: un genérico que copia su `T`, instanciado con un tipo con
  destructor.** `v.get(0)`, `v[0]` o `v[0] = r` con `v: Vector<R>` copiarían
  un dueño; el error sale en la llamada y dice dónde copia el genérico
  (`vector.libsrx:123: se copia 'self.datos[...]'`), también a través de
  otro genérico que lo llame. Con `Vector<int>` todo sigue igual.
- **Literales `0x`, `0b`, `0o` y `_`.** `0xFF`, `0b1010`, `0o755`,
  `1_000_000`: otra forma de escribir un `int`, como en Python. Uno con prefijo
  es un PATRÓN DE BITS (la regla de Java): `0xFFFFFFFFFFFFFFFF` vale `-1`.
  Mal formado es `LEX007`. El lexer escrito en suriaX los reconoce igual.
- **El tipo `byte`** (0..255): un literal que cabe entra donde se espera uno;
  se compara y se enmascara (`& | ^ ~`), y se calcula en `int` (`cast`). En
  la VM un bloque de `byte` ocupa un byte por celda (antes serían 8), y un
  `byte ptr` cruza a `#extern cpp` como `uint8_t*` sin copiarse.
- **Archivos binarios**: `archivos.read_bytes(path)` -> `vec.Vector<byte>` y
  `archivos.write_bytes(path, &v)`. Y en `Vector`, `adopt` (un vector que se
  hace dueño de un bloque ya lleno) y `data()` (presta el bloque).
- **La librería `text`**: `slice`, `find`, `find_from`, `starts_with`,
  `ends_with`, `join`, `parse_int` y `to_bytes`/`from_bytes` (UTF-8), cada una
  una primitiva del host. `str` -> `int` por fin existe: si no se puede, es
  `excepciones.ConversionInvalida` (`EXC004`, el código que tenía reservado).
  Y `text.parse_float`, con redondeo CORRECTO (el mismo `double` que Python,
  en los dos motores), más `mem.float_bits` / `mem.float_from_bits` (los 64
  bits IEEE-754 de un `float`).
- **Formato en un f-string**, el de Python: `{x!r}` (la representación:
  comillas y escapes, `Color.Verde`, `Punto{x: 1}`), `{n:08b}`, `{n:x}`,
  `{x:.2f}`, `{s:10}`. Un formato que no corresponde al tipo es un error de
  compilación. Un struct se puede escribir en un f-string (con sus campos).
- **Una variante puede llevar un valor con destructor** (era `SEM029`): se
  destruye con la variante que haya al morir. Lo que liga `case A(x)` es un
  préstamo del payload; cederlo es `SEM036`.
- **La vista de desugaring** (`--emit-stage desugar`, `#test desugar`): el
  HIR legible con la línea del fuente, como se escribió, encima de cada
  sentencia, y cada construcción que el compilador reescribe señalada con
  aquello en que la convirtió (`x += v`, `x++`, `with`, `.campo`, la
  declaración de un vector, el `move` de un `throw`, el `cast` de un literal).
- **`--emit-index`**, el canal del editor para *hover*, ir a la definición y
  completar: los diagnósticos más cada símbolo del archivo (tipo, firma con
  los nombres de los parámetros, posición, el comentario de encima y, si es
  de una librería, su archivo), cada uso de cada símbolo y los miembros de
  cada tipo. Una sola pasada del frontend; funciona con `--stdin`.
- **`--emit-lang-info` v4**: publica la sintaxis para colorear (comentarios,
  escapes, literales numéricos, formato de los f-strings) y los *snippets*
  de cada construcción, sacados de las tablas del propio compilador. Un test
  compila cada snippet: lo que inserte el editor es suriaX válido.

### Cambiado

- **La gramática (`docs/gramar/grammar.ebnf`) se reescribió desde el
  parser**: había quedado atrás (sin `with`, excepciones, genéricos, bits,
  asignación compuesta...). Ahora es la del parser real, con comentarios solo
  para las categorías de tokens, y dos pruebas la atan al lexer: no usa reglas
  sin definir y nombra exactamente sus palabras reservadas. El glosario de
  tokens (`docs/gramar/t_types.md`) documenta los 33 tokens que le faltaban y
  otra prueba lo ata a `TokenType`.
- **La documentación, al día con el bootstrap**: los README, la arquitectura
  (la V1 y el plan de versiones V1–V3), `#from` de tipos (`libsrx`), qué hace
  `--run` (la VM si está construida, si no el intérprete) en el uso y en
  `how_to_run.md`, y la lista de errores abiertos (lo que encontró el
  bootstrap y lo que ya no era cierto, como "no hay diccionario").
- **`how_to_run.md` es ahora la guía de los comandos**, por tarea: una tabla
  de un vistazo; construir y usar la VM (Linux, macOS y Windows); compilar con
  la V1 y reproducir el punto fijo; construir la documentación. Reemplaza la
  CLI "a futuro" que no existía. Se corrigió que la VM necesitara protobuf de
  C++ (lo decían cuatro documentos; lee el `.phir` con su propio
  decodificador).
- **La V1 compila su primer subconjunto de punta a punta** (bootstrap,
  `src/main.srcx`): funciones, variables del módulo, escalares, `var`/`const`,
  aritmética, comparaciones, lógica, `if`/`else`, `while`, llamadas y
  `return`. Sobre esos programas el `.phir` que escribe la V1 (corriendo en la
  VM) es idéntico, byte a byte, al de la V0; lo comprueba
  `test/bootstrap/test_bootstrap_v1.py`. Paquetes nuevos: `src/semantica/`
  (tipos en una arena, tabla de símbolos, resolución) y `src/hir/` (emisor y
  formato de protobuf).
- **La V1 cubre también structs, enums, `match`, punteros, `move`/`free`,
  cadenas y la propiedad** (qué se destruye al cerrar cada bloque, los
  temporales, `transfers`, `drops_old`): 11 programas con el `.phir`
  idéntico al de la V0. Lo que la V0 emite y por qué, verificado regla por
  regla, está en `src/hir/contrato.md`.
- **El bootstrap llegó al punto fijo**: la V1 —el compilador escrito en
  suriaX— se compila a sí misma, y sus 30 unidades son idénticas, byte a
  byte, a las que produce la V0; la V1 compilada por sí misma vuelve a dar
  lo mismo. Lo comprueba una prueba en cada corrida
  (`test/bootstrap/test_punto_fijo.py`).
- **Límites de la VM para máquinas con poca memoria**: `suriax-hir --run
  --pasos N` (0 = sin límite; antes el límite era fijo) y `--memoria-max
  512M`, la memoria máxima del programa contada por la VM (`RT023` al
  pasarla, después de recoger las cadenas sin uso). `--memoria` reporta
  además el pico en bytes.
- **La V1 compila métodos, excepciones y `with`**: `@impl` y `dunder fn`
  (también los de una librería), los hooks con receptor genérico (`v[i]`),
  `hash`, `throw`/`try`/`catch`/`finally` y el `with`. Con esto compila,
  idénticas a las de la V0, TODAS las librerías que ella misma importa.
- **La V1 compila genéricos**: structs y funciones con parámetros de tipo,
  instancias anidadas, argumentos de tipo escritos o deducidos y la
  propiedad dentro de un genérico, con el `.phir` idéntico al de la V0
  (también la unidad de `mem`).
- **La V1 compila programas con librerías**: `#import` y `#from` (archivos,
  paquetes, submódulos), la visibilidad, los hooks de las librerías, los
  nombres canónicos de los tipos y un `.phir` por unidad, cada uno idéntico
  al de la V0 (tres proyectos de prueba en `test/bootstrap/v1_proyectos/`).
  Acepta `-O0` (el defecto) y reserva `-O1`/`-O2`.
- **`sistema.rutas`**: las rutas del sistema de archivos calculadas como
  `os.path` de Python (`absoluta`, `normaliza`, `une`, `carpeta_de`,
  `nombre_de`, `es_carpeta`, `es_archivo`, `directorio_actual`, `entorno`,
  `separador`). La VM reimplementa `ntpath`/`posixpath` (con las mismas
  llamadas de Windows que Python) y una prueba diferencial la compara con el
  intérprete. La necesita el compilador escrito en suriaX para escribir las
  mismas rutas que el de Python.
- **Revisión de calidad y normas** (`docs/quality/`): qué normas sigue el
  compilador y por qué (ISO/IEC 25010 como modelo de calidad; ISO/IEC/IEEE
  12207 y 29119 como referencias de proceso y de pruebas; PEP 8, 20 y 257;
  C++ Core Guidelines), cuánto las cumple (porcentajes generados a partir de
  lo que miden las herramientas) y las automatizaciones que lo miden
  (`python docs/quality/tools/quality.py all`): flake8, black, pylint,
  pydocstyle, coverage.py, cppcheck, clang-tidy, ASan, UBSan y un buscador de
  dependencias del sistema operativo. No corren con la suite: se usan en los
  lotes grandes. La configuración está en `.flake8`, `.clang-tidy` y
  `pyproject.toml`.
- **La suite ya no depende del sistema operativo**: no necesita
  `SURIAX_HIR_BIN` ni `PYTHONUTF8` (encuentra la VM en `build*/bin` y lee la
  salida de cada subproceso como UTF-8). Lo que cambia entre sistemas está en
  `test/helpers.py` (`hir_binary`, `run_with_timeout`, `link_lib`).
- **Los cuatro módulos de prueba más grandes se partieron por tema**
  (`test_vm_diferencial_*`, `test_backend_cpp_*`, `test_diagnostics_*`,
  `test_libraries_*`), con lo compartido en un `*_support.py`. Y
  `python test/main.py backend/test_vm_diferencial` corre solo los módulos que
  empiezan así.
- **`SURIAX_SANITIZE_TRAP`** (CMake): UBSan sin runtime, para un Clang que no
  lo trae (Windows x64).
- **Las pruebas que comparan implementaciones corren a pedido**: las
  categorías `backend` (la VM contra el intérprete) y `bootstrap` (el
  frontend escrito en suriaX contra la V0) salen de la corrida de siempre.
  Se piden con `python test/main.py backend bootstrap` o `--todo`; en la CI
  cada una tiene su workflow, que corre solo si cambian sus archivos, y el
  release corre todo.
- **`python main.py prog.srcx` ejecuta en la VM** (el `target` por defecto,
  `native`), o en el intérprete con un aviso si la VM no está construida.
- **Un enum se escribe por su NOMBRE en un f-string** (`Verde`, `Punto`,
  `Circulo(2.5)`), en los dos motores; antes una variante sin payload salía
  como su número.
- **Los temporales con destructor de la condición de un `if` o un `while`
  mueren al terminar de evaluarla**, como en C++ al final de la expresión
  completa. Antes el intérprete los acumulaba hasta el final de la sentencia
  (en un `while`, uno por vuelta) y la VM perdía todos menos el último.
- **Un prototipo de `#extern cpp` que devuelve un puntero ya no se liga**:
  suriaX recibía la dirección como un entero, que no apunta a nada que el
  programa pueda usar. Se omite diciendo por qué, como uno que devuelve
  `str`.
- **Asignar un struct lo copia**, igual que declararlo (`b = a;`,
  `e.dentro = c;`); antes los dos nombres compartían el objeto.
- **Copiar un struct copia el almacenamiento de sus vectores**: un bloque de
  `mem` en un campo es del struct. Antes `var b = a;` daba dos vectores con
  los mismos datos, y un `push` sobre uno escribía en el otro.
- **Toda librería de `lib/` es un paquete**, aunque tenga un solo archivo:
  crecer es añadir un submódulo sin mover nada. Una prueba lo exige.
  - `excepciones` conserva sus tipos en la raíz: `exc.DivisionPorCero` no
    cambia.
  - `sistema` se parte en `sistema.archivos` y `sistema.proceso`.
  - `math` documenta cómo extenderse.
  - `d_types` ya no importa a su propio submódulo, que creaba una unidad
    suelta.
- **Un solo estándar de C++ para todo el proyecto: C++20.** Lo fija
  `version.py` (`CXX_STANDARD`), y de ahí lo leen CMake y los bloques
  `#extern cpp`. Pasar otro a CMake es un error de configuración: dos
  estándares en el mismo proceso compilan y fallan después, lejos de su
  causa.
- **El backend C++ ya no necesita protobuf.** Lee el HIR con un modelo
  generado desde el `.proto` (`backend/tools/gen_hir_cpp.py`), que se guarda
  en el repositorio. Construirlo solo pide CMake y un compilador.
- **La CI construye el backend**: sus pruebas se omitían en cada corrida.

- **La división por cero y el índice fuera de rango dejan de ser `RT`**:
  `RT016` pasa a ser `EXC001` y `RT013` pasa a ser `EXC002`. Los `RT` quedan
  para lo que no tiene arreglo dentro del programa y nunca se atrapan.
- **Un parámetro por valor es dueño de lo que recibe.** Pasarle algo con
  destructor exige `move` (`SEM032`, la misma regla que un `var`); antes
  `recibe(move a)` no dejaba a nadie como dueño y el `__free__` no corría
  nunca.
- **`catch (T e)` filtra por el tipo estático del valor lanzado**, como la
  VM de C++. Antes miraba el valor al ejecutar y confundía un `char` con un
  `str` de un carácter, y un `a.Error` con el `Error` de otra librería.
- **El linker busca también en la carpeta que contiene al paquete del
  fuente**, así que un submódulo importa a su hermano y un programa guardado
  dentro de su paquete lo encuentra.
- **Un submódulo roto solo es un error para quien lo importa**, en la línea
  de ese import, como en Python.
- **Ceder algo a través de un puntero es un error de compilación** (`SEM036`):
  `move c.dentro`, `return c.dentro` o `throw c.dentro` con `c` un puntero.
  Antes compilaba y el valor se destruía dos veces.
- **La suite no cuenta como pasado lo que no ejecutó**: las pruebas
  omitidas se ven y se cuentan aparte, y los fallos se explican como en
  Python.

### Corregido

- **Un ejemplo de la documentación tenía la cadena partida** (`f.write("hola`
  y en la línea siguiente `");`, en la sección de `with`): ahora es
  `"hola\n"`. Tres ejemplos que no son programas completos quedan marcados
  como fragmentos, y la verificación de ejemplos vuelve a pasar entera.

- **`#from lib #import Tipo` no servía para usar el tipo**: el struct o el
  enum entraba como un VALOR, así que `Plano p` y `Plano{...}` eran un error
  ("el tipo no está declarado"). Ahora entra al espacio de tipos como uno
  propio (también con `as`) y es el mismo tipo que `lib.Plano`. El
  intérprete ya no intenta ligar en ejecución un struct traído así (no tiene
  valor que ligar). Lo encontró el bootstrap.
- **Una función genérica traída con `#from` perdía su `T`**: `#from mem
  #import reserve` y después `reserve<int>(3)` devolvía un `T ptr mutable`
  sin ligar (un error falso), aunque `mem` documenta esa forma. La copia del
  símbolo no llevaba los parámetros de tipo.
- **La VM no ejecutaba un `dunder fn` llamado como método**:
  `p.__doble__()` quedaba "sin resolver" (la VM indexaba el método por su
  nombre sin guiones, `doble`), mientras el intérprete lo ejecutaba.
- **La VM no ejecutaba una función traída con `#from`**: `#from cosa
  #import doble` y después `doble(3)` quedaba "sin resolver" (la VM tomaba
  todo `#from` por un submódulo), mientras el intérprete la ejecutaba.
- **Dentro de una librería, construir una variante con el payload de un tipo
  de la misma librería era un error falso** (`E.Uno(P{...})`: "se esperaba
  'P', se encontró 'lib.P'") y la unidad no se emitía. El símbolo de la
  variante guardaba el payload como se escribió. Lo encontró el bootstrap.
- **Una prueba fallaba siempre en Windows**
  (`test_un_struct_que_se_contiene_por_valor_no_cuelga`): usaba
  `signal.SIGALRM`, que solo existe en POSIX. Ahora el tiempo límite es
  portable.
- **El backend no enlazaba con Clang en Windows**: CMake le pasaba la opción
  de pila de GNU ld (`-Wl,--stack`) a un Clang que usa el enlazador de MSVC.
- **`#extern cpp` podía fallar al leer los mensajes del compilador de C++**
  si no venían en UTF-8 (MSVC escribe en la página de códigos de la consola).
- **Un tipo sin importar en `type_service.py`** (`Dict`): no fallaba porque
  las anotaciones no se evalúan, pero `typing.get_type_hints` sí lo haría.
- **Un temporal que posee solo por sus campos no se destruía**
  (`Caja{ r: R{...} };` descartado, `hace();`, `E.V(R{...});`), en ningún
  motor; tampoco un `T` descartado dentro de un genérico (`v.pop();`). Ahora
  muere al cerrar la sentencia, por su tipo.
- **`return 5;` en una `fn -> dt.int8`** era un error: `return` no convertía
  el literal como las demás posiciones de escritura.
- **Un struct en un f-string**: el intérprete escribía el `repr` de Python y
  la VM fallaba. Los dos escriben `Punto{x: 1, y: 2}`.
- **Destructores que no corrían** (en los dos motores):
  - un parámetro genérico `T` (`toma<R>(R{...})`): la función es su dueña y
    lo destruye al salir;
  - un `catch (e)` sin tipo: lo atrapado se destruye al cerrar la rama;
  - reasignar (`a = R{...}`, `p.x = R{...}`): el valor viejo perdía su
    `__free__`; ahora muere al recibir el nuevo;
  - un argumento que nadie recibió porque otro posterior lanzó
    (`usa(R{...}, falla())`, `usa(move r, falla())`): muere en el
    desenrollado, antes que los locales, como en Rust;
  - los elementos de un `Vector` o un `Dictionary`, y las celdas de un
    bloque que se suelta.
- **Asignar un dueño por nombre** (`b = a`, `Caja{ r: a }`) dejaba dos
  dueños: ahora es `SEM032`, como ligarlo. Y **sacar un elemento de un
  bloque** (`return b[0]`, `move b[0]`) es `SEM036`: se saca con `mem.take`.
- **El indexado crudo de un bloque tiene tipo** (`self.datos[i]` con `T ptr
  datos` es un `T`): antes era desconocido y cualquier valor se podía
  escribir en él sin que el frontend lo mirara.
- **`__copy__` del intérprete compartía los structs** entre el bloque viejo
  y el nuevo (la VM los copiaba): ahora copia por valor, como la VM.
- **Un literal de struct en la VM** calcula sus campos antes de reservar el
  objeto: si uno lanza mueren los ya calculados, no un objeto a medias.
- **En la VM**:
  - un temporal se perdía si otra parte de la misma expresión lanzaba antes
    de que alguien lo tomara (`usa(C{...}, falla())`, `File{ contenido:
    leer(r) }`): ahora se libera por el camino de la excepción, sin costo
    cuando nadie lanza;
  - `==` en un genérico con `T` = un struct con `__eq__` comparaba handles
    (daba `false` para dos valores iguales); ahora llama al `__eq__`.
- **El tipo de retorno de un MÉTODO de librería** que usa el alias de otra
  librería (`fn keys(...) -> vec.Vector<K>`) no se canonicalizaba y daba
  `AST006` al guardarlo en un `vec.Vector<str>` del programa.
- **`python main.py prog.srcx -- x`** agregaba su `--run` DESPUÉS del `--`, y
  el programa lo recibía como un argumento suyo (también `suri`).
- **Ordenar un `T?` es `AST006`** (`a < 7` con `a: int?`): null no es menor
  ni mayor que nada, y el intérprete caía con un `ICE000` al compararlo.
- **En la VM**:
  - copiar un `P?` que vale null abortaba ("copiar algo que no es un
    objeto");
  - un `T?` declarado sin valor (local o global) valía 0 y no null;
  - una global dueña de un objeto nunca se liberaba (el intérprete tampoco
    corre su `__free__` al salir, y la VM ahora hace lo mismo con su
    memoria).
- **`#extern cpp` en Windows con un `clang++` de ABI de MSVC**: se pasaba
  `-fPIC`, que ese target rechaza, y aun sin él la DLL no exportaba nada (en
  esa ABI un `extern "C"` no se exporta solo). Ahora se exportan los
  prototipos que el objeto define (leyendo su tabla de símbolos COFF) y se
  pide `-m64` a un compilador que produce 32 bits por defecto.
- **Linker y genéricos de librería**:
  - un submódulo que importaba a su hermano daba un "import circular" falso;
  - un temporal pasado a un genérico se destruía aunque el genérico lo
    guardara;
  - `Caja<R>` de una librería no destruía su campo;
  - el campo de un struct de librería quedaba sin tipo (`len(e.msg)` fallaba
    al ejecutar);
  - un enum de librería no se podía desestructurar por su ruta, y un
    `match` incompleto sobre él no se reportaba;
  - las firmas con genéricos de librería no se canonizaban (AST006);
  - la recursión mutua se comprobaba contra firmas aún sin enlazar.
- **Excepciones**:
  - un temporal lanzado se destruía antes de que el `catch` lo leyera;
  - lo declarado dentro de un `catch` no se destruía nunca;
  - un `__free__` que lanzaba durante el desenrollado reemplazaba al `throw`
    en curso sin decir nada;
  - dos `SEM004` falsos, uno de los cuales rechazaba un programa válido.
  - relanzar desde un `catch (e)` sin tipo (`throw e;`) perdía el tipo del
    valor, y un `catch (T x)` de más arriba ya no lo reconocía.
- **Diagnósticos**:
  - una librería con errores mostraba una posición que no existía y un
    "no tiene un submódulo" en cascada;
  - `internal`/`private` decían que el símbolo no existía, en vez de por qué
    no se ve;
  - los errores de una librería al emitir su `.phir` se ocultaban;
  - un fuente que no es UTF-8 era un traceback (ahora `LEX008`).
- **Errores internos (ICE000) que dejan de serlo**:
  - una recursión sin caso base (ahora `RT019`);
  - un dígito no ASCII como `²` en el lexer (ahora `LEX001`).
- **Ejecución**: `v[i] = x` a través de un puntero a un `Vector` indexaba
  memoria cruda.
- **La VM de C++** (todos encontrados por el diferencial contra el
  intérprete):
  - dos llamadas anidadas en un f-string (`{raiz(varianza(v))}`) llamaban
    dos veces a la misma, porque el sitio de llamada se buscaba por posición;
    ahora se identifica por su nodo;
  - el `println` de la librería se llamaba a sí mismo (confundía sitios de
    llamada de unidades distintas) hasta agotar la pila;
  - dos variables del mismo nombre en ámbitos distintos compartían slot;
  - leer fuera de un índice devolvía basura en vez de lanzar;
  - un parámetro por valor no se destruía nunca;
  - `return t;` destruía `t` antes de entregarla al llamador;
  - un temporal con destructor no se destruía nunca;
  - `sizeof(dt.int8)` daba 2: el tipo del dueño de un hook se leía en la
    tabla de tipos de otra unidad;
  - `cast<dt.int8>(300)` no truncaba;
  - un `char` no ASCII (`'ñ'`) valía su primer byte;
  - `==` entre structs comparaba identidad aunque el tipo tuviera
    `__eq__`;
  - en Windows, una recursión de unos 790 niveles mataba el proceso: la pila
    era de 1 MB;
  - recorrer una cadena era cuadrático (cada `s[i]` la decodificaba entera,
    y cada cadena nueva se buscaba entre todas las anteriores). El lexer del
    bootstrap pasó de 2.7 s a 0.04 s.
- **La VM no tenía semántica de valor**: `var C b = a;`, pasar por valor y
  meter en un campo compartían el objeto. Modificar la copia modificaba el
  original.
- **`free &x` en la VM no dejaba a `x` liberado**: usarlo después no daba
  `RT003`, y su destructor podía volver a correr al cerrar el ámbito.
- **Reasignar una variable con destructor después de un `move`** la dejaba
  sin dueño en la VM: su destructor ya no corría.
- **Tras `__release__`, tocar el bloque en la VM daba `EXC002`** en vez de
  `RT003` (uso después de liberar), como en el intérprete.
- **La VM, con un paquete importado entero** (`#import math` y luego
  `math.constants.PI`, `IO.stdp.println(...)`), dejaba la llamada o la
  global sin resolver: solo traducía alias de un tramo.
- **La VM escribía los `float` con 17 dígitos fijos**: `PI` salía
  `3.1415926535897931` en vez de `3.141592653589793`. Ahora sigue a
  `str(x)` de Python: la representación más corta, y científica fuera de
  [1e-4, 1e16).
- **Un error de un intrínseco del host salía sin posición** (línea 0), y el
  de un `cast` de ancho fijo guardaba la posición sin mostrarla en el texto.
  Ahora los dos llevan la del sitio de llamada, como en la VM.
- **El intérprete ejecutado desde `runtime/interpreter/main.py`** agotaba la
  pila a unos 200 marcos, porque no subía el límite de recursión como
  `suri`. El mismo `.phir` daba dos resultados según la puerta de entrada.
- **Las unidades de librería se emiten junto al `.phir` principal**, que es
  donde las buscan los dos motores. Antes iban a `dumps/`, y con
  `target: native` el backend no las encontraba.
- **Repositorio y CI**:
  - la CI dependía de un archivo que no existe en un checkout limpio;
  - `README.md` publicaba marcadores de conflicto de merge;
  - tres ejemplos de `docs/examples/` no compilaban;
  - la documentación se puso al día con la 0.3.0 (MIR, VM, genéricos de
    función, codec propio del HIR).

## [0.3.0]

Publicada como rescate de urgencia (se perdió el equipo de desarrollo), con
errores y archivos faltantes que repone la 0.3.1.

### Añadido

- **Genéricos de función** (`fn make<T>(int cap) -> Vector<T>`), y el vector
  de la stdlib sirve para cualquier tipo (`make<T>`, `dynamic<T>`).
- **Indexado de cadenas**: `s[i]` da un `char` y `len(s)` la longitud en
  caracteres.
- **El HIR ya no necesita protobuf ni `protoc`**: se serializa con un codec
  propio contra el mismo `hir.proto`.
- **Backend C++ con MIR, VM de registros y verificación de propiedad.**
- **Los literales de cadena adyacentes se concatenan** (`"uno " "dos"`),
  como en C, C++ y Python. Cada literal conserva su prefijo: `f"a{x}" "{y}"`
  interpola `{x}` y no `{y}`.
- **`move` como expresión** (`var Buffer b = move origen;`); ligar sin
  `move` algo con destructor es `SEM032`.
- **`match` avisa cuando no es exhaustivo** (`SEM030`), y un aviso ya no
  detiene la compilación.

### Cambiado

- **Un `struct` es un valor**: ligar copia; un parámetro `ptr` no se copia.
- **El `int` envuelve a 64 bits**, igual en todos los ejecutores.

### Corregido

- **Errores de ejecución con código en vez de tracebacks**:
  - dividir por cero (entonces `RT016`);
  - caerse por el final de una función con retorno (`RT017`: devolvía `null`
    en silencio).
- **Indexar un primitivo es `SEM031`** al compilar, no un fallo al ejecutar.
- **Genéricos en la destrucción**: la sustitución no llegaba ahí, así que
  `Caja<R>` no destruía su `R`.
- **Tamaño infinito**:
  - los ciclos que pasaban por un genérico se aceptaban;
  - la guarda del análisis de tamaño estaba mal puesta.
- **Vistas**:
  - `--hir-pretty` reventaba con `try`/`catch`;
  - la notación de un tipo perdía información (`error int`, `Vector<int>`);
  - la destrucción que inserta el compilador no se veía en ninguna vista.
- **El lector de HIR en C++** congela el contrato de la frontera: sus vistas
  son idénticas byte a byte a las de Python.

## [0.2.0]

### Cambiado

- **El modelo de memoria por regiones se retiró.** No podía verificarse; en
  su lugar hay ownership con destrucción automática al cerrar el ámbito. Se
  liberaron 8 palabras reservadas (ver
  [la decisión de memoria](documentation/source/memory_decision.rst)).
- **La versión tiene una sola fuente**: `version.py`. Antes el README, su
  traducción y la documentación decían tres versiones distintas.

### Corregido

- **Librerías y despacho**:
  - todas las librerías de `lib/` compilan, con una prueba que lo verifica;
  - el despacho entre módulos funciona: un dunder sobre un tipo de otra
    librería se encuentra y se llama.
- **La documentación publicada se reconstruye** cuando cambian los
  documentos que viven junto al código.
