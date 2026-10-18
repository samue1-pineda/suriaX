# Registro de cambios

[![Versión](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/samue1-pineda/suriaX/badges/version.json)](version.py)

Lo que cambió en cada versión de suriaX, de la más nueva a la más antigua.
Lo que **sigue fallando** en la versión publicada está en
[c_errorstfix.md](c_errorstfix.md); cuando algo de allí se corrige, sale de
ese documento y queda registrado aquí.

Cada entrada dice qué cambió y por qué importa, no solo el nombre del
arreglo: suriaX es un compilador para aprender, y el porqué es la mitad de
la lección.

---

## [0.4.1] — en desarrollo

La 0.4.0 (el commit del punto fijo del bootstrap) no tuvo entrada propia:
sus cambios están en esta sección, junto con los de la 0.4.1.

La 0.3.0 fue un rescate de urgencia. Esta versión repone lo que faltó, pone
la documentación al día, estabiliza el linker, los genéricos y las
excepciones, y empieza el bootstrap.

**El paradigma queda declarado:** suriaX es un lenguaje **imperativo con
herramientas funcionales** que usa **programación genérica**. Imperativo de
sistemas, con propiedad (move, free, préstamos); de lo funcional, lo que no
rompe la propiedad: funciones como valores, enums con datos y `match`,
`map`/`filter`/`fold`, `const` y lambdas que no escapan. Tipado estático,
fuerte y nominal, sin inferencia: variables, parámetros y retornos se
anotan siempre. La programación genérica está más cerca de Ada que de la STL
de C++. De los templates toma lo que no cuesta seguridad de tipos: la
deducción de los argumentos de tipo desde los argumentos de la llamada y
cotas al estilo de los conceptos (`<T: Ord>`). La especialización, SFINAE y
la metaprogramación no entran. El recorrido genérico de contenedores llega
junto al `for`, en una versión posterior.

### Añadido

- **El esquema 1 del HIR vuelve a funcionar (rollback).** El esquema está
  versionado: `python V0/main.py prog.srcx --emit-hir --hir-schema 1` emite el
  esquema inicial (cada tipo escrito dentro de su nodo, sin pool de tipos), y
  el intérprete, la VM y el target web aceptan el 1 y el 2. Al cargar un 1 lo
  normalizan a la forma de hoy, así que el MIR, la VM y el WebAssembly tienen
  un solo camino. Los campos del 1 volvieron con su tag y su significado
  originales (`Expr.restype = 3`, `VarDecl.type = 2`, `Parameter.type = 1`,
  `FunctionDecl.return_type = 3`, `Field.type = 1`); los que nacieron después
  llevan un gemelo con tag nuevo (`LambdaExpr.return_type = 5`,
  `EnumItem.payload_types = 4`). Medido: el mismo programa da la misma
  ejecución en los dos esquemas, normalizar un 1 da el 2 byte a byte, y un 2
  sale idéntico al de antes (221 `.phir`). El 2 sigue siendo el de por
  defecto porque ocupa menos (la V1 completa pesa un 32 % más en el 1). El
  `.proto` original del esquema 1 queda en `dev/diff/schema/`.
- **Un diferencial de dos compiladores por tres targets** (`dev/diff/`):
  cada programa se compila con la V0 y con la V1, y cada HIR se ejecuta en el
  intérprete, la VM y el target web (WebAssembly). Compara la salida byte a
  byte y el código de salida, y mide la emisión, la lectura y la ejecución
  (30 corridas, la primera descartada, la mediana). Los resultados están en
  `dev/diff/RESULTS.md` y los pasos para replicarlos, en su README. El
  intérprete y la VM coinciden en todo; el target web, en el resultado de lo
  que soporta, salvo la división por cero y `MIN / -1` (ver
  `c_errorstfix.md`).
- **Una reproducción para cada error conocido** (`dev/repros/`):
  `bash dev/repros/run.sh <programa> [i] [c] [w] [v1]` lo muestra en el
  intérprete, la VM, el target web o la V1, y cada entrada de
  `c_errorstfix.md` dice qué sale hoy.
- **El playground separa al compilador del target web.** Eran un solo
  archivo y el fallo de uno se llevaba al otro: si node tardaba de más, el
  servidor respondía un 500 y la página perdía también las fases que el
  compilador sí había producido. Ahora son capas (`playground/capas/`) con un
  adaptador por proveedor, y cada uno responde con uno de cuatro estados:
  `ok`, `error_del_programa`, `no_disponible` o `error_interno`. Si falla el
  target web, las fases del compilador llegan intactas; si falla el
  compilador, el servidor contesta igual y dice quién falló. La arquitectura,
  las normas que sigue y las que le faltan están en
  [playground/ARQUITECTURA.md](playground/ARQUITECTURA.md).
- **La API del playground está descrita y versionada**:
  [playground/openapi.json](playground/openapi.json) (OpenAPI 3.1), que el
  servidor publica en `GET /api/openapi.json`. Las respuestas llevan `api`,
  `status` y `providers`; los errores HTTP, la forma de la RFC 9457. Una
  prueba compara la descripción con las respuestas de verdad.
- **Un depurador.** `python V0/main.py --dap` arranca el depurador
  hablando el protocolo estándar (DAP), que entienden VS Code, Neovim, Emacs
  y otros. Puntos de parada (también dentro de una librería), paso a paso
  —pasar, entrar, salir—, pausa, la pila de llamadas y las variables, que se
  despliegan (los campos de un `struct`, aquello a lo que apunta un puntero).
  Y una columna que es de suriaX: la **propiedad** de cada variable — `dueña`,
  `prestada`, `movida` o `liberada`. El intérprete ya llevaba esa cuenta (es
  la que hace cumplir el uso tras `move` y tras `free`); el depurador la deja
  ver sin leer el valor, así que mirar una variable movida no es el error que
  sería usarla. **Se detiene donde el programa falla** —un error de
  ejecución, un `throw` que ningún `catch` espera, un `expect` que no se
  cumple— con la pila y las variables todavía vivas. Acepta las banderas del
  compilador (`"flags": ["--test"]` depura las pruebas; `--trace-memory`
  escribe la traza en la consola), leídas con el mismo analizador que la
  terminal. Corre en el intérprete; con el depurador apagado su coste no se
  distingue del ruido de la medición.
- **Lo que una herramienta de línea de comandos le pide a la máquina**
  (en el intérprete). `sistema.entrada` lee la entrada estándar, así que un
  programa ya funciona en una tubería (`cat datos.txt | prog`).
  `sistema.archivos` gana `borrar` (un archivo o una carpeta vacía),
  `renombrar` (de una vez: la forma segura de reescribir un archivo) y
  `modificado` (la fecha, en milisegundos). `sistema.comandos` lanza otro
  programa sin intérprete de órdenes de por medio —un argumento con espacios
  o con `;` es un argumento— y devuelve su código, su salida y sus errores.
  `sistema.tiempo` da la hora, un reloj para medir y `dormir`. Bajo el
  depurador la entrada está vacía: allí la entrada estándar es el canal del
  editor. La VM y el target web todavía no las tienen.
- **`Vector.at_mut(i)` y `Dictionary.at_mut(clave)`**: un `ptr mutable` al
  elemento, para cambiarlo en su sitio. Deja de valer si el contenedor crece
  (`RT003`).
- **Predicados en `Vector`**: `v.any(p)`, `v.all(p)`, `v.count_if(p)` y
  `v.find(p)` con `p: fn(T ptr) -> bool` (una función con nombre o una
  lambda). `any`, `all` y `find` se detienen en cuanto saben la respuesta;
  `find` da el índice del primero que cumple como un `int?` (`null` si
  ninguno). El predicado recibe una copia, como en `filter`: con un `T` con
  destructor son `SEM038`.
- **`result.Result<T, E>`** (`Ok(T)`, `Err(E)`), un enum genérico estándar
  en su propio paquete, con `is_ok()` y `unwrap_or(d)`. Va aparte para que la
  VM, que rechaza con `VM002` todo programa que cargue un enum genérico, siga
  ejecutando los programas que no lo importan.
- **`Dictionary.get_or(k, default)`**: el valor o `default`, sin lanzar y sin
  agregar la clave. **`Dictionary.items()`**: un `Vector<Pair<K, V>>` con
  copias, en el orden de `keys()`, con el nuevo
  **`collections.pair.Pair<K, V>`** (`key`, `value`). Con un valor con
  destructor los dos son `SEM038`, como `get` y `values()`.
- **`print` es variádico**: `print("total:", n, 1.5)` escribe cada
  argumento separado por un espacio, sin salto de línea al final, en orden.
  Solo como sentencia; dentro de una expresión, o sin argumentos, es
  `SEM008`. El HIR no cambia: la semántica lo descompone en `print` de un
  argumento.
- **Lambdas que no escapan**: `lambda (int ptr x) -> bool: x[0] > 3` o, con
  más de una sentencia, `lambda (int ptr x) -> bool { ...; return ...; }`.
  Los tipos se escriben siempre. Solo pueden ser el argumento de un
  parámetro `fn(...) -> R` (`SEM050`), y leen los locales y parámetros de
  alrededor sin poder modificarlos (`SEM003`/`SEM015`/`SEM036`). Un
  parámetro de tipo función es **prestado**: solo se llama o se pasa a otro
  (`SEM051`); para guardar una función recibida se declara
  `(fn(...) -> R)?`. Participan en la deducción:
  `func.map(&v, lambda (int ptr x) -> str: f"{x[0]}")`. Las ejecuta el
  intérprete; la VM las rechaza con `VM004` y el target web con `WEB104`.
- **Cotas en los genéricos**: `<T: Ord + Contrato>` en funciones, structs,
  enums, `type` y `@impl`. Con la cota, `<`, `hash`, `print` y los métodos
  del contrato se comprueban en la definición, y cada instancia la cumple en
  su llamada: el error dice qué cota falta y desde qué argumento se dedujo el
  tipo. Sin cota todo sigue igual (comprobación por instancia, `SEM043`).
- **Conceptos nativos `Eq`, `Ord`, `Hash` y `Print`**, que se cumplen solos:
  los tipos nativos que ya los tienen y un tipo propio con el hook
  (`__cmp__` lo hace `Ord`). Son nombres predefinidos que solo existen como
  cota; un trait del programa con el mismo nombre manda.
- **Traits que piden métodos de `@impl`**, además de dunders: un método de
  nombre llano en el contrato se cumple con uno del `@impl` del tipo.
- **Deducción de argumentos de tipo**, un subconjunto de la de los templates
  de C++: se leen de los argumentos en las formas `T`, `T ptr`, `T?`,
  `Nombre<..T..>` y `fn(..T..) -> R`, sin conversiones. `func.map(&v, f)` ya
  no necesita `<int, str>`. Dos argumentos que dan tipos distintos, o un `T`
  que no se puede leer, es `AST007`; se escriben todos o ninguno. Sigue sin
  haber inferencia: las variables se anotan siempre.
- **Métodos genéricos**: `fn map<U>(...)` dentro de `@impl Caja<T>`.
- **`Vector.sort` pide `T: Ord`**: el error sale en la llamada a `sort`.
- La VM rechaza con `VM003` lo que despacha una cota en ejecución
  (`print(x)` con `T: Print`, `x.metodo()` con un contrato); las cotas, la
  deducción y los métodos genéricos no cambian el HIR.
- **Desenvolver un `T?`**: `match` con `case null` y `case v` (`v` es el
  contenido, prestado como el payload de `case E.A(x)`), y `x ?? d`, que da
  `d` si `x` es `null` y solo entonces lo evalúa (asocia a la derecha, por
  debajo de `or`; `d` tiene que ser exactamente `T`). No hay estrechamiento
  tras un `if (x != null)`: se desenvuelve con `match` o `??`.
- **Enums genéricos**: `enum Res<T, E> { Ok(T), Err(E), };`. Las variantes
  se escriben siempre con sus tipos, `Res<int, str>.Ok(5)`, también en un
  `case`; sin ellos es `SEM027`.
- Solo el intérprete ejecuta `??`, `case v` y los enums genéricos: la VM los
  rechaza con `VM002` y el target web con `WEB100`/`WEB101`. El HIR los lleva
  con dos campos nuevos (`CaseArm.binds`, `EnumDecl.type_params`), aditivos.
- **Funciones con nombre como valores**: el tipo `fn(int, str) -> bool`
  (sin `->`, devuelve `void`; una función opcional va entre paréntesis,
  `(fn(int) -> int)?`). Son valores las funciones del módulo, las de una
  librería (`stdp.println`) y los métodos `Tipo.metodo`; se guardan en una
  variable, un campo o un vector, se pasan, se devuelven y se llaman. La
  llamada se comprueba como una directa (aridad, tipos y `move`), `==` es
  identidad y un f-string la escribe `<fn doble>`. No capturan nada: una
  función genérica, un prototipo, un hook o un método de un tipo genérico no
  pueden ser valores (`SEM044`). El HIR lo lleva con un `TypeKind` nuevo
  (`FUNCTION_TYPE = 13`), aditivo. Solo en el intérprete: la VM las
  rechaza con `VM001` al bajar al MIR, con la posición de la función o la
  expresión (`suri --run compiler` cae entonces al intérprete; una función de
  librería como `Vector.sort_by` solo falla si se llama), y el target web con
  `WEB103`, con cualquier política. Las vistas de la VM y `formatType` del
  web escriben `fn(A) -> R` igual que `--hir-pretty`.
- **`Vector.sort_by(f)` y `Vector.filter(f)`**: `sort_by` ordena con una
  `fn(T ptr, T ptr) -> int` (negativo, 0 o positivo, como `__cmp__`), estable
  y sin copiar, así que vale para un `T` con destructor. `filter` devuelve un
  vector nuevo con copias de los que cumplen una `fn(T ptr) -> bool`
  (`SEM038` con un `T` con destructor).
- **Paquete `func`**: `func.map<T, U>(&v, f)` y `func.fold<T, A>(&v, init,
  f)`. Hoy los argumentos de tipo se escriben, y `f` recibe un puntero a una
  copia del elemento, así que con un `T` con destructor son `SEM038`.
- **Hook `__cmp__`**: `hook fn __cmp__(T ptr a, T ptr b) -> int` (negativo,
  0 o positivo) da `<`, `<=`, `>` y `>=` a un tipo propio. Los enums sin datos
  se ordenan por su valor, como los números.
- **Los genéricos pueden ordenar su `T`**: `a < b` sobre un `T` se acepta y
  cada instancia comprueba que su tipo concreto se ordene (`SEM039`, en la
  llamada). Antes era imposible escribir un sort o un heap genéricos.
- **`Vector.sort()`**: estable (mezcla de abajo hacia arriba, O(n log n)) y
  sin copiar los elementos, así que vale también para tipos con destructor.
  Y `==` entre vectores: mismo largo y mismos elementos.
- **`text` para herramientas que analizan texto** (en el intérprete).
  Nuevas: `split` (como `str.split(sep)` de Python), `split_whitespace`,
  `lines` (corta en `\n` y `\r\n`, igual que `sistema.entrada`),
  `trim`/`trim_start`/`trim_end`, `contains`, `count`, `rfind`, `replace`,
  `repeat`, `pad_left`/`pad_right`, y con Unicode completo y sin idioma:
  `lower`, `upper` (`upper("ß")` es `"SS"`), `is_digit` (dígito decimal de
  cualquier escritura), `is_alpha`, `is_alnum`, `is_space`, `is_upper`,
  `is_lower`, sobre un `char`. Un argumento sin respuesta (separador vacío,
  `repeat` negativo) es `excepciones.ValorInvalido`. Partir, recortar,
  contar y las clases son llamadas al host: escritas en suriaX, partir un
  archivo de 10 000 líneas tardaba 2,8 s en el intérprete; en el host, 21 ms.
- **`&n == &n` era `false`**: se comparaban dos envoltorios del puntero en
  vez de la dirección.
- **`SEM033` a `SEM038` no salían en `--emit-lang-info`** (faltaban en el
  `__all__` de su módulo).
- **El runner de pruebas ya no muere si una prueba termina el proceso**
  (`SystemExit`): cuenta como un fallo más y la corrida sigue, con su resumen.
- **Una sola lista de las llamadas al host**
  ([lib/LLAMADAS_AL_HOST.md](lib/LLAMADAS_AL_HOST.md)): cada una con su firma
  y qué motor la cumple. Estaba repartida entre la librería, el intérprete y
  la VM sin que nada comprobara que dijeran lo mismo; ahora una prueba los
  compara.
- **La extensión de VS Code dice lo que está mal mientras escribes.** Un
  servidor de lenguaje nuevo (`python V0/main.py --lsp`, en `tooling/lsp`)
  habla el protocolo estándar (LSP): errores del texto sin guardar, hover con
  la firma y el comentario, ir a la definición (también dentro de una
  librería), el esquema del archivo y completar. No reimplementa nada: pide
  al compilador lo mismo que `--emit-index`, en el mismo proceso, y sirve a
  cualquier editor que hable LSP. La extensión pasa a ser un cliente delgado
  —dos archivos de JavaScript escritos a mano, sin paquetes de npm ni paso de
  compilación— que lanza el servidor y el depurador con los ajustes
  `suriax.pythonPath` y `suriax.compilerRoot`; en una carpeta sin confianza
  solo colorea. Un fallo del compilador no tumba al servidor: sale como
  `ICE000` en el documento. `tooling/vscode/empaquetar.py` arma el `.vsix`
  sin vsce. El reparto completo y lo que falta están en
  [tooling/vscode/ARQUITECTURA.md](tooling/vscode/ARQUITECTURA.md). Sin
  probar todavía en una ventana real de VS Code.
- **Los canales del editor reciben el texto como argumento**
  (`emit_diagnostics`/`emit_index(..., source=...)`): quien tiene el buffer en
  memoria ya no tiene que pasarlo por la entrada estándar.
- **Una extensión de VS Code** ([tooling/vscode](tooling/vscode/README.md)):
  reconoce `.srcx` y `.libsrx`, colorea con las categorías del lenguaje
  (`move` y `free` no se pintan como un `if`), trae los fragmentos y lanza el
  depurador. No tiene JavaScript ni dependencias: sus archivos se **generan**
  desde lo que publica `--emit-lang-info`, y una prueba compara la gramática
  de colores con el lexer sobre todo el suriaX del repositorio. Preliminar y
  sin publicar.
- **El playground tiene su propia lista de lo que se puede usar.** El target
  web gana perfiles (`node web/main.ts prog.phir --policy <nombre>`): `web-v1`
  (el de siempre), `unrestricted` y `playground`, que añade una lista blanca
  de librerías: `io`, `math` y `excepciones`. Un `#import text` daba cuarenta
  `WEB002` dentro de una librería que el usuario no escribió; ahora es un
  `WEB007` en su `#import` que dice por qué, y distingue "nunca" (`sistema`:
  el playground no tiene archivos ni procesos) de "todavía no" (`text`,
  `array`, `collections`, `d_types`, `mem`: usan lo que el target aún no
  baja). La tabla completa está en el README del playground.
- **La página dice cuándo el fallo no es tuyo.** Un fallo interno del
  compilador o del target web se rotula "FALLO INTERNO — no es un error de tu
  programa" y enseña lo que el proceso escribió al fallar. Antes, como llega
  sin diagnósticos, la barra de estado decía "Compilado sin diagnósticos".
- **La página lleva política de contenido (CSP)** y Mermaid se carga con la
  versión exacta (`11.17.2`) en vez de `@11`. Las pestañas se recorren con
  las flechas del teclado y el estado se anuncia a un lector de pantalla.
- **`GET /api/health` y `python playground/server.py --check`**: dicen qué
  tiene el entorno y qué le falta, sin compilar nada.
- **Guía para usar, publicar y conectarse al playground** en su
  [README](playground/README.md), con un `Dockerfile` (Python y node, sin
  paquetes) y el `Procfile`, que se había perdido en el rescate de la 0.3.0.
  El `Dockerfile` está escrito pero sin construir.
- **Las pruebas comprueban: `expect`, `errfinally` y `finally`.**
  `test "nombre" { expect (condición); } errfinally { ... } finally { ... }`.
  Un `expect` que no se cumple termina la prueba y el reporte cita la
  condición y sus valores (`expect falló: total == 10 (izquierda: 7, derecha:
  10)`); ningún `catch` lo atrapa. `errfinally` corre solo si la prueba falló
  y `finally` siempre, después; las dos son opcionales. `expect` solo vale
  dentro de un `test` y una prueba sin ninguno no compila (`PAR029`).
  `expect` y `errfinally` pasan a ser palabras reservadas.
- **`--test`**: `python V0/main.py prog.srcx --test` compila y corre las
  pruebas del programa en un paso (una línea PASS/FAIL por prueba, código 1
  si alguna falla). Corren en el intérprete.
- **La V2: el compilador de suriaX compilado por sí mismo, versionado como
  semilla** (`src/semilla/`). Con ella y la VM suriaX se compila sin la V0:
  `suriax-hir src/semilla/main.srcx.phir --run -- prog.srcx salida/prog.phir
  --stdlib lib`. `python src/semilla/regenera.py` la regenera con ella misma
  (sin la V0) y solo la reemplaza si se compila a sí misma igual (el punto
  fijo); `--desde-v0` arranca de la V0. Una prueba avisa cuando la V1 cambia
  y la semilla quedó vieja.
- **El `.phir` es reproducible**: la ruta de cada librería ya no es la
  absoluta de la máquina sino relativa a su raíz (`<stdlib>/io/main.libsrx`,
  o relativa al proyecto: `lib/calc.libsrx`), en la V0 y en la V1. El mismo
  programa da los mismos bytes en cualquier carpeta y máquina, y con la
  stdlib en cualquier lugar.
- **La V1 da los diagnósticos de la V0** (lote 18): TODOS los que la V0
  puede dar —léxicos, de sintaxis, de nombres y tipos, de propiedad y
  memoria, de hooks, traits y genéricos, del linker y las notas—, la lista
  completa en el mismo orden, con el mismo archivo, código, línea y columna,
  como `ruta:linea:col: CODIGO mensaje` (el error de una librería, con el
  archivo de la librería). Con un error no escribe el `.phir`; un aviso
  (`SEM030`) o una nota no la detienen. Una librería que no carga deja un
  import "opaco" que no arrastra errores en cascada, como en la V0. Lo
  comprueba una prueba diferencial sobre los programas de las pruebas
  negativas y de gramática y 24 sondas (3 de ellas, proyectos con librerías).
- **`sistema.archivos.crear_carpeta(ruta)`** crea una carpeta con las que le
  falten (`mkdir -p`), en el intérprete y en la VM. La V1 la usa para crear
  la carpeta de salida, como la V0.
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

- **Las cotas `Ord` y `Hash` de un TIPO se comprueban por instancia**, como
  las de una función: `Box<U>` con `struct Box<T: Ord>`, dentro de una
  función genérica cuyo `U` no promete `Ord`, ya no es `SEM043`; la llamada
  que lo instancia con un tipo sin orden es `SEM039`. `Print` y los traits
  siguen pidiendo la cota.
- **Una excepción de la librería estándar lleva la posición de la llamada
  del programa** en `e.linea`/`e.columna` y en el mensaje sin atrapar, no una
  línea de la librería; el `IndiceFueraDeRango` de `Vector` sin atrapar sale
  como `EXC002`. Solo en el intérprete.
- **`print(x)` escribe un primitivo en todas partes**, como un f-string
  (antes `print(5)` era `SEM001` fuera de un genérico). Un `int ptr` o un
  `int?` siguen siendo `SEM001`. La VM lo rechaza con `VM005`; el target web
  lo traduce.
- **`sizeof` de un tipo sin `__sizeof__` no compila** (`SEM001`): un
  primitivo (`sizeof(int)`), un tipo propio sin el hook o una función. Antes
  compilaba y era siempre `RT011` al ejecutar. Dentro de un genérico,
  `sizeof` de su `T` lo decide cada instancia, en la llamada. Para un tamaño
  fijo están los tipos de `d_types` (`sizeof(dt.int32)`).
- **Construcciones dudosas son error**: un `case` repetido (`SEM046`), un
  patrón que liga el mismo nombre dos veces (`SEM002`) y una sentencia que
  calcula un valor y lo tira (`f;`, `a == b;`, `x;`: `SEM047`). El código
  detrás de `return`, `throw`, `break` o `continue` en el mismo bloque es un
  **aviso** (`SEM048`).
- **Aviso `SEM049`**: una función pública de una librería que nombra en su
  firma un tipo que el consumidor no ve.
- **`func.map(&v, f)` sin argumentos de tipo** da un solo `AST007` que dice
  cuáles faltan y cómo se escriben (antes, tres `AST006` confusos).
- **`--test` aísla cada prueba**: corre con sus globales recién iniciadas
  (también las de las librerías) y las destruye al terminar, así que el
  resultado ya no depende del orden. `PASS` y `FAIL` salen los dos por la
  salida estándar y en orden; antes los fallos iban por la de error y se
  desordenaban en una tubería. El código de salida no cambia.
- **Un error que nadie atrapa destruye las globales**, sea un `throw`, una
  `EXCxxx` o un `RT` (un `File` global se vuelca): ya se destruían los
  locales al desenrollar, y las globales eran lo único que quedaba vivo. El
  error se escribe primero. Solo `sistema.proceso.salir` termina sin
  destruirlas.
- **`--check` marca `protobuf` y `pybind11` como `[OPCIONAL]`** y termina
  en 0 si solo faltan ellos.
- **Literales con exponente**: `1e3`, `2.5e-3`, `1E+10`, `1e300` son
  siempre `float` (`0x1e3` sigue siendo un entero hexadecimal). Un literal
  que no cabe en un `float` es `LEX006`, también uno distinto de cero que
  quedaría en `0.0` (`1e-400`, casi seguro una errata); `1e` sin dígitos,
  `LEX007`. Valen lo mismo que `text.parse_float` del mismo texto, que con
  `1e-400` da `0.0` porque lee datos, no código.
- **F-strings con la regla de Python 3.12 y C#**: entre `{` y `}` va código,
  y sus literales se escriben sin escapar (`f"{'}'}"`, `f"{len("ab")}"`); sus
  comillas y llaves no cierran la cadena. Un `\` en la interpolación es
  `LEX005`, con la forma correcta en el mensaje.
- **`(fn(int) -> int)? h = null;` declara sin `var`**, como ya lo hacía
  `fn(int) -> int g`. Con un tipo con nombre (`(Caja ptr)? p`) sigue siendo
  una expresión, porque `(c) = d;` es válido; si falla, el error sugiere
  `var`.
- **`dos(a < b, c > (d))` sigue siendo una llamada genérica**, pero si esa
  lectura falla el error explica la ambigüedad y sugiere `(a < b)`.
- **Mensajes**: una palabra reservada usada como nombre lo dice (`int
  error;`, `PAR003`); `PAR025` distingue bloques anidados, cadenas de
  operadores y expresiones anidadas.

- **Devolver por valor COPIA** (también `throw`, el campo de un literal, el
  payload de una variante y ligar un enum con datos): `dame().n = 5` cambiaba
  la global que `dame` devolvió, y `v.get(0).push(8)` el vector guardado.
- **`SEM041`: escribir en una copia temporal** (`v[i].n = 5`, `v[i].push(x)`,
  `f().n = 5`): con la copia, el cambio se perdería en silencio. Para
  modificar un elemento en su sitio, `at_mut`.
- **`SEM040`: una variable sin valor** (`var int x;`). Valía `null`: `x + 1`
  era un fallo interno y un `bool` sin valor tomaba la rama falsa en silencio.
  El mensaje sugiere un valor según el tipo.
- **`SEM032` también en `return g;` y `throw g;`** con `g` una global con
  destructor: el recurso se destruía dos veces.
- **Las globales se destruyen al terminar el programa** (en el intérprete),
  en orden inverso a su declaración y las de las librerías después. Un `File`
  global no llegaba a escribirse. No se destruyen si el programa termina por
  un error sin atrapar ni con `salir`.
- **`==` compara valores.** Sin `__eq__`, dos structs son iguales si lo son
  sus campos (recursivamente) y dos enums con datos si son la misma variante
  con el mismo payload. Antes se comparaba la identidad del objeto del
  intérprete: `var P b = a; a == b` daba `false`. Un puntero se compara por
  su dirección. `__eq__` sigue mandando cuando existe.
- **`__eq__`, `__cmp__` y `__hash__` sobre un enum sin datos son `SEM006`**:
  se aceptaban y no se llamaban nunca (ese enum es un entero en los motores).
- **El playground escucha solo en la máquina local por defecto**
  (`127.0.0.1`; antes `0.0.0.0`). Publicarlo en la red pasa a ser una
  decisión: `HOST=0.0.0.0`, que ya traen el `Procfile` y el `Dockerfile`.
  **Un despliegue que arranque con `python playground/server.py` a secas deja
  de ser alcanzable** hasta que defina `HOST`.
- **La API del playground rechaza lo que antes dejaba pasar**: un cuerpo que
  no sea `application/json` es un 415 (una página ajena no puede poner a
  compilar a un servidor local con un formulario), un `source` que no sea
  texto es un 400 y el método equivocado un 405. Un fallo del compilador ya
  no es un 500 con un solo campo: es un 200 con la forma de siempre y
  `status: error_interno`. Una variable de configuración que no sea un número
  impide arrancar en vez de usar el valor por defecto.
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

- **Documentación al día con la 0.4.1**: la versión ya no se escribe a mano
  en `c_errorstfix.md`, el ROADMAP ni el CHANGELOG (el badge sale de
  `version.py`). El ejemplo de `.suriaX_config.yaml` de `usage.rst` usaba
  claves de LLVM que hoy son `CFG004`, y los ejemplos de `docs/syntax.md` no
  compilaban. Se corrigió lo que se daba por pendiente y ya existe (`&` de
  un campo escalar en la VM, `#extern cpp` en la VM, las posiciones de un
  f-string, la E/S de archivos, las funciones como valores) y lo que se daba
  por hecho y hoy está roto (el punto fijo de la V1).
- **En un genérico, `return v` con `v` ligado por un `case` sobre un
  puntero vaciaba al dueño**: el payload salía del sujeto y lo dejaba en
  `null` (`4 Ok(null)`), aun con `T = int`. Lo prestado se devuelve copiado.
- **Segunda caza de fallos** (17 programas grandes que usan juntas las
  novedades de la 0.4.1; `audit/caza2/`). Daban una salida incorrecta o un
  fallo interno sin aviso:
  - `v["a"]` sobre un `Vector<int>` era un fallo interno; el índice se
    compara con el de `__index__`/`__index_set__`, y en `s[i]` con `int`
    (`AST006`);
  - `print("total:", n)` descartaba `n`; `len("ab", "xyz")` y `hash(1, 2)`
    compilaban (`SEM008`);
  - un dueño `R?` que valía `null` llamaba a `__free__` al cerrar su ámbito;
  - un f-string dentro de un genérico escribía distinto que fuera
    (`P{x=3, s='hi'}`, `Ok(0)`);
  - en un enum con datos, las variantes sin datos ignoraban `__eq__`,
    `__hash__` y `__cmp__`, y `Vector.at` no las prestaba;
  - un `__eq__` con la firma mal escrita compilaba (`SEM006`).

  Y faltaban o sobraban diagnósticos: un método o campo sobre un primitivo
  (`s.len()`) solo fallaba al ejecutar (`SEM042`, con la forma de suriaX); un
  falso `AST006` en una global de una librería importada con alias; `SEM030`
  sobre un `E ptr`; tapar lo que liga un `case` en su rama (`SEM002`). Los
  mensajes de `break`/`expect` dentro de una lambda, de ceder lo que liga un
  patrón y del ternario, `&&`, `||` y `!` dicen ahora qué pasa y qué se
  escribe en suriaX.
- **Un parámetro de tipo repetido** (`Par<T, T>`) ligaba en silencio el
  último argumento; ahora es `SEM002`, en struct, enum, type y fn.
- **`const` y `T ptr` sin `mutable` no protegían de los métodos ni de los
  campos anidados**: `k.sube()` sobre un `const`, `v.push(3)` sobre un
  `Vector<int> ptr`, `c.n = 5`. Ahora son `SEM003`/`SEM015`, como ya lo era
  `p.n = 7`. `&c.n` sobre un `const` ya no da un `ptr mutable`, y lo que liga
  un `case` sobre algo que no se puede modificar tampoco se modifica.
- **Lo que fallaba siempre al ejecutar ahora no compila**:
  - una global que usa otra declarada después (`SEM045`; antes `RT006`);
  - `s[i] = c` sobre un `str` (`SEM031`; antes `RT014`);
  - `&b[i]` de un elemento escalar (`SEM013`; antes `RT011` en los dos
    motores). Dentro de un genérico se decide en cada instancia: `v.at(i)`
    sobre un `Vector<int>` es un error en la llamada;
  - `print(5)` sobre un primitivo (`SEM001`, que dice cómo escribirlo);
  - `hash` de una función, un `float` o un tipo sin `__hash__` dentro de un
    genérico (un `Dictionary` con esa clave), con el mismo código que fuera.
- **`Vector<void>`** (cualquier argumento de tipo `void`) es `SEM025`.
- **Un aviso dentro de una librería impedía ejecutar el programa**: su
  `.phir` no se emitía con cualquier diagnóstico, también un aviso. Ahora
  solo lo que bloquea.
- **Los diagnósticos escriben los tipos como el lenguaje**: `'C ptr'`,
  `'C ptr mutable'`, no `'ptr C'`. Y `Vector<int>` ya no sale como `Vector`.
- **Dos sitios del frontend descartaban la causa de un fallo**
  (`semantic/hooks.py` y `semantic/extensions.py`): un defecto interno sale
  ahora como `ICE000` y `EXT030` cita el error del parser.
- **Una llamada a un método no comprobaba sus argumentos**: ni la aridad
  ni el tipo. `v.push("hola")` sobre un `Vector<int>` compilaba y era un
  fallo interno del intérprete. Ahora es `SEM008` o `AST006`, como una
  llamada a una función.
- **`Vector` dejaba leer y escribir entre la longitud y la capacidad**:
  `get(i)` y `v[i]` daban `null`, y `set`/`v[i] = x` guardaban un elemento que
  `len`, `pop` y `sort` no veían. Fuera de `[0, len)` lanzan
  `excepciones.IndiceFueraDeRango`.
- **Los errores de ejecución dentro de una librería dicen su archivo**:
  `RT020: throw 7 (lib/falla.libsrx:2:5)`. Antes salía solo `(2:5)`, una
  línea que no es del programa. Los del programa principal siguen como
  `(3:5)`, igual que los diagnósticos de compilación.
- **`frontend OK` ya no aparece encima de los errores** del frontend.
- **Un programa que se llama como una librería que importa ya no se importa
  a sí mismo** (`falla.srcx` con `#import falla`): la búsqueda salta el
  propio archivo y, si no hay otra librería, el error dice por qué.
- **Un hook o un `__cast__` de una librería en la misma línea que uno del
  programa ejecutaba el cuerpo del programa.**
- **Un préstamo de `Vector.at`/`at_mut` que sobrevive a su elemento** (tras
  `set` o `take`) es `RT003`, como en la VM; antes leía el elemento nuevo.
  El puntero que queda colgando cuando un contenedor crece dice que el
  contenedor reubicó su almacenamiento, no "después de 'free'".
- **`--emit-stages` ya no culpa a protobuf** de cualquier fallo al cargar el
  emisor del HIR: dice la causa real.
- **Las expresiones de una interpolación tienen su posición real**: antes
  todas llevaban la de la interpolación (un error en `doble(mas_uno(3))`
  apuntaba al mismo sitio para las dos llamadas) y una f-string partida en dos
  líneas mezclaba la línea de una con la columna de la otra.
- **Sin errores en cascada** tras la recuperación del parser: el `PAR012`
  falso sobre el `};` de `var int xs[3];`, el `SEM001` sobre el nombre de un
  struct roto, el `PAR012` "token inesperado: ERROR" tras cualquier error
  léxico y el `LEX003` tras un escape inválido. Un error léxico dentro de una
  interpolación se informa como tal y en su sitio.
- **Cuatro fallos silenciosos alrededor de genéricos y funciones**, que
  salieron al estudiar qué falta para escribir librerías funcionales:
  - el nombre de una función valía por su retorno (`var int g = doble;`
    compilaba) y llamar a algo que no es una función (`n(3)`, un método que
    no existe) no daba error hasta ejecutar. Ahora es `AST006` o `SEM042`;
  - un genérico podía pedirle a su `T` un método, un campo o `[]` sin que
    nada lo prometiera: fallaba con `RT011` al ejecutar o, peor, hacía otra
    cosa (`map<str>(&v, "hola")` metía los caracteres en un `Vector<int>`).
    Ahora es `SEM043`; el comportamiento se le pasa como función;
  - un `match` sobre un `E ptr` reservado con `mem` no entraba en ninguna
    rama: el árbol de ejemplo de `type_system.rst` calculaba `0` en vez de
    `20`. Un bloque vale lo mismo que su elemento 0.
- **Un método de `@impl` pisaba a una `fn` homónima**: con `fn distancia`
  y `@impl Punto { fn distancia }`, `distancia(5)` ejecutaba el método en el
  intérprete; en la VM dependía del orden (con el método primero, error de
  ejecución). Corregido en los dos y en el índice del target web.
- **`hir.proto` no era un `.proto` válido**: el tipo función se había
  llamado `TypeKind.FUNCTION`, que choca con `SymbolKind.FUNCTION` (en
  protobuf los valores de un enum comparten el ámbito del paquete). `protoc`
  lo rechazaba y la VM no compilaba desde el repositorio. Ahora es
  `FUNCTION_TYPE`, con el mismo número 13: el cable no cambia. El lector
  propio del esquema rechaza ese choque, así que la suite lo ve aunque
  `protoc` no esté instalado.
- **`-x` sobre una función, `str`, `char`, `bool` o un puntero** era un
  fallo interno del intérprete; ahora es `AST006` al compilar.
- **Dos personas compilando a la vez en el playground podían recibir errores
  falsos.** El compilador guarda estado global y el servidor atiende con
  hilos: un programa válido salía con `SEM010` porque otra compilación le
  cambiaba la caché del enlazador a media resolución. Medido: 10 de 90
  compilaciones en paralelo daban un resultado distinto al de la serie. Ahora
  se compila de uno en uno.
- **El playground culpaba al programa de un fallo del target web**: sin
  artefacto y sin diagnósticos decía "el target web todavía no compila
  construcciones del programa", y tiraba lo que node había escrito al fallar.
  Ahora es un `error_interno` y conserva esa salida.
- **El `__eq__` de un enum se aceptaba y `==` no lo llamaba nunca**, mientras
  `hash` sí despachaba a su `__hash__`: un `Dictionary` con un enum de clave
  guardaba la misma clave dos veces y no encontraba ninguna.
- **`cast<char>` de un entero que no es un carácter** era un fallo interno
  (fuera de 0..0x10FFFF), o un sustituto UTF-16 que reventaba al imprimirse.
  Ahora es `ConversionInvalida` (`EXC004`), que se puede atrapar.
- **Una reserva imposible** (`mem.reserve<int>` de un tamaño que no cabe)
  creaba las celdas una a una durante minutos y acababa en un fallo interno;
  ahora falla en el acto con `RT023`.
- **Dos compilaciones a la vez en la misma carpeta se pisaban** los `.phir`
  de las librerías en `dumps/`: una podía leer el archivo vacío o cortado
  (`schema_version 0`, fallo interno). Medido con seis programas a la vez,
  10 de 24 compilaciones fallaban. Ahora se escribe en un temporal y se
  cambia de nombre de una vez: ninguna.
- **`#from paquete #import submodulo` destapaba los `private` del
  submódulo**: `formas.escalar(2)` compilaba desde otro paquete, aunque por
  `#import geo.formas` era `SEM011`. Era el ejemplo de la documentación de
  librerías, que además prometía otro código.
- **Un fallo al construir el índice del editor escapaba del canal**:
  `emit_index` lo construía fuera de la guarda que convierte cualquier fallo
  en `ICE000`. Ahora sale como diagnóstico, con el índice vacío.
- **Un `var` de nivel superior en una librería podía tumbar al intérprete.**
  Las sentencias de nivel de módulo de una librería corrían con la unidad
  principal puesta, y el tipo de cada expresión es un índice en el pool de
  SU unidad: `public var str t = f"{mitad:.2f}";` resolvía el tipo de `mitad`
  en el pool del programa. Si el índice no existía allí, fallo interno
  (`IndexError`); si existía, otro tipo, en silencio. Dentro de una función
  ya salía bien.
- **Una expresión larga acababa en un fallo interno del compilador.** Nada
  acotaba cuánto anida el árbol: `a + b + c + …` no anida al escribirse pero
  sí al analizarse (un nivel por operador), así que pasaba el parser y
  tumbaba al emisor del HIR con un `RecursionError` — con 3000 términos en la
  terminal y con 300 desde el playground, que usaba el límite de recursión
  por defecto de Python. Ahora el límite es **del lenguaje**: una declaración
  anida hasta 500 niveles y lo que se pasa es `PAR025`, con su posición, en
  cualquier forma (operadores, llamadas, accesos a miembro, `else if`,
  bloques). Quien usa el compilador como librería tiene el mismo margen de
  recursión que la CLI. **Cambia lo que se acepta**: una suma de 2000
  términos, que el frontend compilaba (y el emisor del HIR no), ya no pasa.
- **El target web rechazaba programas válidos por anidar "demasiado"**: su
  lector admitía 200 mensajes anidados "porque el frontend no produce árboles
  tan profundos", y una suma de cien términos ya los producía. El tope pasa a
  1024 y se calcula desde el límite del lenguaje; una prueba compara los dos.
- **Un programa con `test` salía en el target web como ".phir corrupto"**
  (`WEB901`): su lector no conocía `expect` ni las cláusulas `errfinally` y
  `finally`. Ahora las lee, la contención las revisa como al resto del código
  y el target hace con ellas lo que ya hacía con una prueba: las quita y baja
  el programa. Sigue sin ejecutarlas.
- **Una librería denegada por el target web se reportaba dos veces** (una
  sin línea y otra en su `#import`) **y además se revisaba por dentro**. Ahora
  sale una vez, con su posición, y la unidad denegada no se recorre.
- **Los mensajes del playground publicaban rutas del servidor**: `SEM009`
  enumera las carpetas donde buscó la librería. En la CLI ayudan; en una
  página pública cuentan cómo está montada la máquina. Salen como `<repo>`.
- **Un fuente demasiado grande a veces no recibía su 413**: el servidor
  respondía sin leer el cuerpo y el cliente, que aún enviaba, veía una
  conexión abortada.
- **Un valor con destructor declarado dentro de un `test` no se destruía
  nunca**: las pruebas no anotaban lo que muere al cerrar su cuerpo.
- **Un proceso largo (el playground, un LSP en proceso) mostraba resultados
  viejos de las librerías**: la caché del linker vivía el proceso entero. La
  segunda compilación de un programa con una librería rota ya no mostraba sus
  errores, y una librería editada seguía usándose en su versión anterior.
  Ahora la caché es de cada compilación.

- **Un `free` dentro de un `else` no contaba para el aviso `NOTE002`** ("tu
  `__free__` no suelta el campo X"): la búsqueda miraba un campo que no
  existe, así que un destructor que soltaba el campo en el `else` (o al final
  de una cadena de `else if`) recibía un aviso falso.

- **Un enum a través de un puntero** (sus valores son enteros): `&e` daba el
  valor en la VM y `p[0]` fallaba solo ahí; el receptor `T ptr self` de un
  método sobre un enum llegaba como el valor en los dos motores (`self[0]`
  fallaba); y un `match` sobre un puntero a un escalar comparaba el puntero
  y no entraba en ninguna rama, en silencio. Ahora un enum sin payload se
  lee y se escribe a través de un puntero como un `int`, el receptor recibe
  el préstamo, y el sujeto de un `match` se desreferencia también con un
  patrón de valor. Prueba diferencial con la salida esperada.
- **La V1 perdía los `__cast__` de una librería**: al importarlos los
  comparaba por (dueño, clase), y todas las conversiones que salen de un
  primitivo (`int -> int8`, `int -> int16`...) tienen el mismo dueño vacío;
  solo sobrevivía la primera. Ahora van por su par (origen, destino), como
  la tabla de conversiones de la V0.
- **La V1 escribía con su nombre escrito un `type` de librería**
  (`dt.int8` en vez de `dt_variables.int8`): un literal no encontraba su
  conversión y el tipo no unificaba con el que declara la librería.
- **La V1 emitía un `.phir` incompleto sin avisar** cuando el programa usaba
  algo fuera de su subconjunto (`type`, `@trait`, un decorador, `test`,
  `sizeof`, `min`/`max`, los tipos `type`/`self`/`error`, un `__cast__`, la
  conversión implícita de un literal): salía como una sentencia vacía, o sin
  la conversión que la V0 inserta. Ahora se detiene con `ruta:linea:col: la V1 todavía no
  compila ...` y no escribe el `.phir` (en el programa y en cada librería).
- **`noexiste.x` tumbaba el compilador** (ICE000): el error de que el nombre
  no está declarado estaba en una rama que no corría nunca, y la línea
  siguiente usaba un valor vacío. Ahora es `SEM001` en la posición del
  nombre. Lo encontró el lote de diagnósticos de la V1.
- **Un error de sintaxis arrastraba errores semánticos falsos**: la
  compilación normal analizaba el árbol que dejó la recuperación del parser
  y reportaba, por ejemplo, `SEM001: 'suma' no está declarado` sobre una
  función que sí lo está (la recuperación había descartado su declaración).
  Ahora, como el canal del editor (`--emit-diagnostics`), la Semántica solo
  reporta sobre un parseo limpio, y los errores léxicos salen primero: los
  dos canales dan la misma lista.
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
errores y archivos faltantes que repone la 0.4.1.

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
