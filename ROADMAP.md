# Roadmap de suriaX

> Estado global: **Pre-Alpha — "Dejando las arenas movedizas sin dueño"**
> (la version publicada es la medalla del [README](README.md), que sale de
> `version.py`)
> interprete funcional, modelo de memoria por **ownership** (las regiones se
> retiraron: ver [el registro de la decisión](documentation/source/memory_decision.rst))
> y llamadas a c++(pybind11) para memoria
>
> **Paradigma:** imperativo con herramientas funcionales y **programación
> genérica** (más cerca de Ada que de la STL). Tipado estático, fuerte y
> nominal, sin inferencia de tipos. Nicho: herramientas de línea de comandos
> que analizan código o texto.

---

## La versión en curso

[![Versión](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/samue1-pineda/suriaX/badges/version.json)](version.py)

La 0.3.0 fue un rescate de urgencia; la 0.4.1 repone lo que faltó y cierra
el lenguaje del nicho. Lo nuevo se construye primero en la V0 y en el
intérprete; la VM, el target web y la V1 lo rechazan con su código hasta
ponerse al día. El detalle de cada cambio está en el
[CHANGELOG](CHANGELOG.md) y lo que falla, en [c_errorstfix.md](c_errorstfix.md).

**Hecho:**

- Herramientas: playground por capas con API descrita, depurador (DAP) que
  muestra el estado de propiedad de cada variable, servidor de lenguaje
  (LSP) y extensión de VS Code generada del compilador [x]
- Llamadas al host para el nicho: entrada estándar, archivos, lanzar otros
  programas, tiempo, y `text` para analizar texto [x]
- Valores: copia al devolver, variables siempre con valor, globales que se
  destruyen, igualdad por valor, `__cmp__` y `Vector.sort` [x]
- Funciones con nombre como valores (`fn(A) -> R`), `sort_by`, `filter` y el
  paquete `func` (`map`, `fold`) [x]
- Desenvolver `T?` (`match` con `case null`/`case v`, y `??`) y enums
  genéricos (`Res<int, str>.Ok(5)`) [x]
- Cotas (`<T: Ord + Contrato>`), conceptos nativos (`Eq`, `Ord`, `Hash`,
  `Print`), traits con métodos de `@impl`, deducción de argumentos de tipo
  (subconjunto de la de C++) y métodos genéricos [x]
- Diagnósticos: los fallos silenciosos de la caza de fallos pasan a errores
  al compilar (const y punteros de solo lectura, construcciones dudosas,
  `sizeof` sin `__sizeof__`, lo que siempre fallaba al ejecutar) [x]
- Léxico, sintaxis e intérprete: exponentes, f-strings con literales dentro,
  posiciones reales, sin cascadas, `--test` con pruebas aisladas, errores
  con su archivo [x]

- Lambdas que no escapan, con la palabra `lambda` y los tipos escritos
  (`lambda (int ptr x) -> bool: x[0] > 3`), y `print` con primitivos [x]

**Para cerrar la 0.4.1:**

- Poner al día la VM (lo que hoy rechaza con `VM001`–`VM005`, `__cmp__`,
  la destrucción de las globales, las llamadas al host nuevas) y
  reconstruir su binario [ ]
- Poner al día la V1 con el lenguaje de la 0.4.1 y regenerar la semilla [ ]
- Correr las suites `backend` y `bootstrap` y ASan antes del commit del
  hito [ ]

## Después de la 0.4.1

Lo que viene después, con el estado de cada idea, está en
[FUTURO.md](FUTURO.md): es la única lista de ideas. Este roadmap cuenta las
fases y lo que ya se hizo.

## Fase 0: Diseño del lenguaje 

- Filosofía libsrX (pocos tokens, librerías nativas)[x]
- Sintaxis base y conjunto de tokens. [x]
- Gramática EBNF objetivo ([docs/gramar/grammar.ebnf](docs/gramar/grammar.ebnf))[x]
- Modelo de memoria definido: **ownership + drop + arenas explícitas** [x]
  (v0.2.0; reemplaza a *region-based*, retirado por no poder verificarse —
  ver `documentation/source/memory_decision.rst`)
- Definicion del ErrorHandler  y version preeliminar de los errores [x] 


## Fase 1: Frontend: análisis léxico  

- `source_reader`: UTF-8 → Unicode, normalización de saltos de línea[x]
-  Lexer modular (scanners + dispatch )[x]
-  Comentarios, interpolación de strings, `#extern cpp{}` (raw)[x]
-  Recuperación de errores [x]
-  Directiva orquestadora `#test lexer`[x]

## Fase 2 — Frontend: parser y AST 

-  Parser de **descenso recursivo + Pratt** [x]
-  Construcción del **AST** (+ AST-tipado) [x]
-  Directivas en el parser: `#import` / `#export` / `#from` / `#extern` [x]
-  Resolución de librerías `.libsrx` (verificar `#export <alias>`) [x]
   (implementada en `src/linker_p/`, el linker de librerías nativas, con caché por ruta)
-  `#test parser` / `#test ast` (visualización de cada salida) [x]
-  Volcado del AST-tipado a archivo: `--emit-ast-json` en `V0/main.py` [x]

## Fase 3: Sistema de tipos  

> **Type-system para ownership + move-semantics:** nominal y estático, sin
> extensiones especiales. Al retirar las regiones desapareció el requisito que
> nunca se pudo definir —el polimorfismo de región en las firmas—: la propiedad
> se verifica sobre el flujo del cuerpo, no sobre el tipo de la función.
> No se usara Hindley-Milner(HM) debido a la complejidad del sistema de tipado, choques con el futuro manejo de memoria y choque con el enfoque educativo 

## Fase 4: Semántica y modelo de memoria  

- Resolución de símbolos y scopes [x]
-  Verificación de **propiedad**: `free` invalida el valor al compilar, doble
  liberación [x] (`SEM023`/`SEM024`, mismo mecanismo lineal que `move`)
-  **Drop automático** al cerrar el ámbito (invoca `__free__` del tipo) [x]
  (`scope_resolver` anota los puntos, viajan en el HIR, el intérprete los
  ejecuta contra el estado de la celda; incluye el drop de CAMPOS, aplanado
  por el frontend en rutas concretas)
-  Verificación de **move-semantics**: uso-tras-move, doble move [/]
  (lineal, intra-función, sin punto fijo — deliberado, ídem secc. 4)
- Reglas de `mutable`/`const`, `null`/nullable (`?`), punteros (`ptr`/`&`) [x]
- Hooks de tipo dunder con despacho enlazado: `__free__`/`__sizeof__`/
  `__print__`/`__len__`/`__cast__`/`__index__`/`__index_set__`/`__eq__`/
  `__cmp__`/`__hash__`/`__min__`/`__max__` [x] (la lista completa, en
  [lib/HOOKS.md](lib/HOOKS.md))
- `#test sem` (visualización de símbolos/diagnósticos) [x]

## Fase 5: HIR (protobuf)

> Las construcciones de región (`region`/`shrd`, `make T in r`, `x at r`)
> nunca viajaron: se rechazaban fail-fast (`HIR005`) y sus tags quedaron
> `reserved`. Con su retiro en v0.2.0 el rechazo deja de hacer falta —ya no
> existen en el lenguaje— y los tags siguen reservados por si alguna vez
> vuelven. **move-semantics SÍ viaja**
> (`MoveStmt`/`moved_at`: el runtime la hace cumplir). Las **reglas de
> punteros viajan**: `Type.mut` (`ptr mutable T` vs `ptr T`) y el nodo
> dedicado `AddrOf` con la mutabilidad resuelta (`var`→mut, `const`→no-mut).
> `alloc` dejó de ser parte del lenguaje (lo aporta una librería). Cada
> unidad (`.srcx`/`.libsrx`) emite SU propio `.phir` (`Module.libraries`
> las referencia; IMPORT opaco). Los `__cast__` viajan en la tabla de
> conversiones (`SymbolTable.casts`, varios por tipo).

- Esquema `.proto` del HIR (`V0/src/HIR/proto/hir.proto`, v1 con tags
  reservados + diseño en `V0/src/HIR/PROTOBUF_BRIDGE.md`)[x] 
- Generador AST validado → HIR (Python)  (`V0/src/HIR/emmit_IR.py`,
  emisor explícito por clase; `restype` de TODA expresión anotado en sitio
  por la Semántica y serializado)[x]
- Serialización y versionado del esquema  (`schema_version` fail-fast;
  stubs generados en build por `V0/src/HIR/stubs.py`, no commiteados) [x]
- Extensiones para ejecutar: marca de prototipo, `TypeDecl`/metatipo `type` [x]
- `#test hir` (volcado del HIR en texto protobuf) y `--emit-hir` (binario
  `.phir` + vista de texto `.phir.txt` a `./dumps`) [x]
- `cast<T>(x)`: conversión explícita (única vía — sin coerciones
  implícitas); nativa entre primitivos, hook `__cast__` para nominales;
  `type_args` (`<...>`) como regla compartida para futuros genéricos de
  librería (`vec<int>`) [x]
- `#test <fase>` tolerante: case-insensitive, objetivo desconocido lista
  las fases disponibles [x]
- Lector de HIR en C++ (entrada del lowering a MIR) [x]
  (`backend/`: fail-fast de esquema, tabla de símbolos, module linker y
  `switch` exhaustivo por `oneof`; sus vistas son byte-idénticas a las de
  Python y `test/backend/test_backend_cpp_*.py` lo comprueba)

## Fase 5.5: Intérprete tree-walk (consume HIR)

> Ejecuta el **HIR** para ver salidas reales y probar librerías sin el backend
> C++. Consume el mismo contrato que el backend nativo — el HIR es la
> costura de desacople (regla no negociable de la propuesta de la VM de
> bytecode; ese documento, `docs/propuesta_vm_bytecode.md`, se perdió en el
> rescate de la 0.3.0 — ver `c_errorstfix.md`).
> Queda como oráculo de *differential testing*. Diseño completo y orden de
> implementación en
> [`runtime/interpreter/ARQUITECTURA.md`](runtime/interpreter/ARQUITECTURA.md).
> **Depende de Fase 5** (no puede empezar sin el generador AST→HIR).

- Loader del HIR (`runtime/interpreter/loader.py`): deserializa el `.phir`,
  valida `schema_version` fail-fast, indexa hooks O(1); CLI
  `python runtime/interpreter/main.py <archivo>.phir` con resumen del
  módulo [x]
- Interfaz del host (intrínsecos): prototipo + registro Python
  (`intrinsics.py`, `suriax_write`) — IO imprime sin `#extern cpp{}` [x]
- Núcleo tree-walk sobre el HIR: valores, environment, expresiones,
  control de flujo, llamadas, f-strings, `cast` (`evaluator.py`) [x]
- Despacho de hooks en runtime (`HookRef` → hooks; tabla de conversiones
  → `__cast__` por par origen→destino) (`hook/dispatch.py`) [x]
- Module linker: ligar N unidades HIR (main + `.libsrx`), transitivo
  (`loader.load_image`) [x]
- Modelo de memoria en runtime: celdas, `&`/deref implícito,
  `move` con invalidación (RT001/RT002), `free`/use-after-free (RT003),
  `--trace-memory` (`memory/pointer.py`) [x]
- Drop automático al cerrar el ámbito (llamada a `__free__` del tipo) [x]
- Arenas como **tipo de librería** (una fábrica normal más `__free__`, sin
  sintaxis dedicada) [ ]
- Target `interp` en `compilerconfig` + CLI `--run` (V0/main.py llama a
  `runtime/interpreter/main.py --exec` en proceso) [x]
- Structs ejecutables, vectores (`lib/array/vector`) y `#extern cpp` [x]

## Fase 6: Backend C++ 

- Lector de HIR en C++ [x] (`backend/`, ver Fase 5)
- Resolución de la imagen (slots, llamadas y destrucciones por función) [x]
  (`suriax-hir --resolve`)
- **MIR lowering**: registros virtuales + control de flujo explícito [x]
  (`backend/src/mir.cpp`, `suriax-hir --mir`; sin SSA. Lo nuevo de la 0.4.1
  se rechaza con `VM001`–`VM005`. Ver [docs/mir.md](docs/mir.md))
- Verificación de **propiedad** y **préstamos** sobre el MIR [ / ]
  (propiedad por todos los caminos del CFG [x]; préstamos solo dentro de un
  bloque)
- **VM** que ejecuta el MIR [x] (`suriax-hir --run`; misma semántica que el
  intérprete, comprobada por un diferencial)
- **JIT**: el target NATIVO estándar (LLVM queda fuera del plan: el MIR ya es
  un IR de registros con CFG, y meter LLVM en medio añadía una dependencia
  enorme y un segundo modelo de máquina antes de tener el primero
  funcionando) [ ]
- **Hot spots** (próxima versión, junto al JIT) [ ]. Medido con
  `suriax-hir --run --trace` sobre las cargas de `dev/bench_vm.py`:
  - **El trabajo está en funciones HOJA minúsculas.** En el lexer del
    bootstrap, 8 de 37 funciones reciben el 69 % de 75 000 llamadas
    (`es_espacio` 18 %, `inicia_nombre` 14 %, `continua_nombre`, `avanza`,
    `es_digito`...). En el parser, 8 de 128 reciben el 52 % de 265 000
    (`Vector.get` 17 %, `mira` 8 %, `__index_set__`, `len`, `push`...). En
    `vector` y `fib`, el 100 % del trabajo son llamadas.
  - **Primero, el costo por llamada.** Cada llamada reserva dos vectores
    (registros y slots) y copia sus argumentos en otro. La solución es una
    pila de marcos contigua y reutilizada.
  - **Después, inlining de hojas.** Las funciones de pocas instrucciones sin
    llamadas (los predicados del lexer, los accesores de `Vector`) se
    copian en el llamador al bajar al MIR.
  - **El JIT elige qué compilar con contadores.** Un contador por función
    y por arista de retorno de bucle; al pasar un umbral, esa región va al
    JIT. La medición de arriba dice que los umbrales tienen que mirar
    llamadas, no solo bucles.
  - Sin esto, un JIT que compile bucles no toca el cuello de botella del
    bootstrap.
  - **Mover en el último uso.** Desde que la VM libera memoria y copia los
    structs como valores, guardar un parámetro en un contenedor
    (`self.datos[i] = x` en `push`) lo copia y después libera el parámetro.
    Si es el último uso de `x`, moverlo ahorra la copia y el `Free`. `vector`
    pasó de ~146× a ~114× el intérprete por esto.
- Targets por `compilerconfig`: `IS_WEB`→wASM, `IS_WIN32`→.exe, `IS_LINUX`→.o [ ]
- **Linker** por plataforma (Linux web y Windows) [ ]
- Integración del C++ de `#extern cpp{}` [x]
  (en el intérprete con ctypes, `runtime/extern_cpp.py`; en la VM sin
  bindings ni libffi, `backend/src/externo.cpp`: la construye junto al
  `.phir`, la carga y llama con una firma tipada. Falta el enlazado
  ESTÁTICO, que es del binario nativo)
- **`#extern` con un archivo** [ ] (pospuesto por el mantenedor; diseño
  recomendado): `#extern cpp "test.cpp"` mete el archivo en la unidad de
  traducción y un prototipo TIPADO (`fn foo(int a) -> int;`) lo liga. suriaX
  genera el puente `extern "C"`, así el `.cpp` no necesita `extern "C"` y
  puede usar namespaces y sobrecargas. Sin `hook` (ya nombra el conjunto fijo
  de dunders) ni `extends` (suena a herencia); los tipos del prototipo son
  imprescindibles para llamar.
- **Destructores de los elementos de un contenedor genérico** [x]
  (`Vector<R>`, `Dictionary<K, V>`): destruir POR TIPO (`Drop.by_type`, la
  instrucción `Destruir` de la VM), un bloque posee sus celdas no vacías,
  `mem.take`/`mem.transfer` para sacar sin destruir, un campo `R ptr` posee
  si `R` posee (así `Vector<int>` sigue copiable) y SEM038 para un genérico
  que copia su `T`. `Vector.at`/`take` y `Dictionary.at`/`take`.
- **Una variante con un valor con destructor** [x] (era SEM029): se destruye
  por su tipo con la variante que haya al morir.
- **Un tipo nativo `byte`** [x]: bloques compactos en la VM, `read_bytes` /
  `write_bytes`, `#extern cpp` como `uint8_t`. Falta en el target web.
- **Literales `0x`/`0b`/`0o`/`_`** [x], **librería `text`** [x] y **formato
  en un f-string** (`!r`, `:08b`, `:.2f`) [x]. El formato falta en el target
  web (se rechaza con `WEB`).
- **Optimizaciones: en el compilador escrito en suriaX (V1-V2)**, no en la
  VM de la V0. La VM de hoy está estabilizada y es la referencia; los hot
  spots y el JIT anotados arriba se retoman sobre el compilador autocompilado.
- `#test mir` / `#test bytecode` (volcado de cada IR) [ ]
  (el MIR ya se vuelca con `suriax-hir --mir`, pero no desde el compilador
  de Python ni desde `#test`)
- El backend C++ en la CI [x] (`tests.yml` lo construye, y un job aparte lo
  prueba con ASan y UBSan)

## Fase 7: Visualizaciones integradas  

>para debugging se desarrollaran algunas visualizaciones pero la version final y pulida espera a la version web

- Volcado por etapa: **tokens, AST, HIR, MIR, bytecode** [ / ]
  (todo lo que existe se ve ya en [`playground/`](playground/README.md): los
  tokens con su posición, el AST y el AST-tipado como árbol, la tabla de
  símbolos como diagrama de clases, el HIR en su vista legible y el
  WebAssembly como `.wat`. Falta el MIR: existe y se ve con
  `suriax-hir --mir`, pero la página no lo muestra)
- Formatos: texto, **JSON** (consumible por herramientas) y **DOT/Graphviz**
  (árboles y CFG) [ / ]
- Visualización del **CFG** del MIR y del flujo de propiedad (`move`/drop) [ ]
- Volcar una fase sola: `python V0/main.py <archivo> --emit-stage <fase>` [x]
- Vista interactiva paso a paso del pipeline[ ]

## Fase 8: Playground (web)  

> Vive en [`playground/`](playground/README.md) y se despliega en Railway
> con el `Procfile` de la raíz (recreado en la 0.4.1; el `Dockerfile` existe
> pero no se ha construido). El frontend **no** se reimplementó en TypeScript: la página
> pide las fases al compilador de verdad (`driver/artifacts`), que es lo que
> evita tener dos respuestas para la misma pregunta.

- Editor web con las fases del compilador [x]
- Visualizaciones integradas en el playground [x]
  (tokens con resaltado de su línea al pasar el ratón, AST y AST-tipado como
  árbol plegable, símbolos como diagrama de clases, HIR legible, `.wat`)
- Ejecutar el programa desde la página [ ]
  (el intérprete corre en el servidor: ejecutar código de cualquiera exige
  aislamiento y límites, que es otra decisión)
- Compartir snippets / ejemplos [ / ] (hay ejemplos cargables; falta compartir)
- Compilación del propio frontend a wASM junto a Emscripten [ ]
  (dejaría de hacer falta el servidor; no es necesario para que la página
  funcione)

> **Genéricos**: de función en la 0.3.0; en la 0.4.1, cotas, conceptos,
> métodos genéricos y **deducción** de los argumentos de tipo desde los
> argumentos de la llamada (`mayor(3, 9)`). No es inferencia: las variables
> se anotan siempre. Lo que no se puede deducir se escribe (`make<int>()`). Los **literales de arreglo** (`[1,2,3]`) siguen sin existir:
> el análisis de lo que cuestan está en `c_errorstfix.md`.

## Fase 9: Librerías nativas (libsrX)  

- Formato `.libsrx` y su resolución (`#import` / `#export as`) [x]
  (resolución real con caché adelantada a Fase 4, ver `src/linker_p/`)
- **Paquetes**: carpeta con padre `main.libsrx` (o `<carpeta>.libsrx`) +
  `#export package as <alias>`; imports punteados (`#import IO.print`,
  `#from IO.print #import __print__`) — anti-polución de namespaces [x]
  **El módulo se llama como su ALIAS, no como su archivo** (`lib/io/main.libsrx`
  con `#export package as IO` se importa `#import IO`)
- Tipos publicados por librerías: `const type int8;` (tipo nominal opaco) +
  uso cualificado desde el consumidor (`const dt.int8 x;`), y `type` como
  metatipo (`fn f() -> type`) [x]
- `.srcx` como librería permitido con NOTA en `log/notes.jsonl` [x]
-  Librería `IO` y manejo de metodos dunder [x] (`lib/io/`: `stdp` con
  print/println y `stdpf` con printf, y hooks `__print__`/`__len__` funcionando)
- Rutas de búsqueda (`libraries.libsrx_paths` en la config, relativas a la
  raíz del proyecto; default `./lib`) [x]
- Conjunto base de librerías estándar [ / ]: `io`, `array.vector`,
  `collections.dictionary`, `text`, `func`, `mem`, `excepciones`, `math`,
  `d_types` y `sistema` (archivos, proceso, entrada, comandos, tiempo,
  rutas). Qué llamadas al host tiene cada motor: `lib/LLAMADAS_AL_HOST.md`

## Fase 10: Tooling, tests y distribución  

- Paquete `config/` (raíz): dependencias, `.suriaX_config.yaml`, logs
  (`./log`, JSONL + espejo legible), volcados (`./dumps`) y verificador de
  caché (`./build/cache` — **entrada al runtime system y a suriniX**) [x]


- Runner propio de tests ([test/main.py](test/main.py)): descubre y ejecuta
  `test_*` en las categorías unit, grammar, negative_tests, snapshot, e2e y
  fuzz [x]
- Suite de tests por fase: lexer, parser y gramática regla a regla, semántica,
  HIR, intérprete (incluida la memoria nativa contra la de Python) y target
  web, más una prueba **diferencial** que ejecuta el mismo programa en el
  intérprete y en WebAssembly y compara salida y valor de retorno [x]

- Comando `suri` (envoltorio de la CLI, instalable con `pip install -e .`) [x]
- La suite no cuenta como pasado lo que no ejecutó: las omisiones son
  explícitas y visibles en consola, `--json`, informe de la CI y medalla [x]
- Build system **suriniX**[ ]

- Empaquetado del binario `suriaX` (depdencias resueltas para el usuario final) [ ]

- Documentación web: sitio de Sphinx publicado en GitHub Pages [x]

- Canales del editor en el compilador: `--emit-diagnostics` (en vivo, con
  rango), `--emit-index` (hover, ir a la definición, completar),
  `--emit-lang-info` v4 (sintaxis para colorear y snippets),
  `--emit-stage` (incluida la vista `desugar`) [x]
- Extensión de VS Code (la anterior se perdió con el computador viejo; se
  recreó DENTRO de suriaX, en `tooling/vscode`): gramática generada del
  lang-info, cliente LSP sin dependencias de npm, depurador y banderas
  configurables; se empaqueta en un `.vsix` [x]. Falta publicarla y probarla
  dentro del editor [ ]
- Servidor de lenguaje (`--lsp`) y depurador (`--dap`, sobre el intérprete) [x]

## Fase 11: Bootstrap (V1, el compilador escrito en suriaX)

> Meta: el **punto fijo**. La V1 compila su propio fuente y el `.phir` que
> produce es idéntico, byte a byte, al de la V0; compilada por sí misma, da
> otra vez lo mismo. Se avanza por rebanadas verticales: cada una lleva un
> subconjunto del lenguaje de punta a punta (`.phir` idéntico y corriendo en
> la VM) y la siguiente lo ensancha.

- Lexer y parser, idénticos a la V0 (`src/frontend/`) [x]
- Subconjunto mínimo de punta a punta: funciones, escalares, control de
  flujo, llamadas y variables del módulo (tipos en un pool, tabla de
  símbolos, emisor del HIR y su codec) [x]
- Structs, enums, `match`, punteros, `move`/`free`, cadenas y la propiedad
  (drops y temporales) [x] — la verificación de memoria de la V0 solo
  diagnostica: pasa a los diagnósticos
- Linker: librerías, paquetes, una unidad por `.phir` [x]
- Genéricos: structs y funciones con parámetros de tipo, la propiedad
  dentro de un genérico [x]
- Hooks con receptor genérico, `@impl`, excepciones, `with`: la V1 compila
  idénticas todas las librerías que importa [x] — traits, `const type`,
  `sizeof`, `__cast__` y `#extern` quedan fuera (la V1 no los usa)
- Punto fijo: la V1 se compila a sí misma [x] — las 30 unidades, idénticas a
  las de la V0 y estables al compilarse otra vez
  (`test/bootstrap/test_punto_fijo.py`). Alcanzado en la 0.4.0; hoy está
  roto hasta que la V1 se ponga al día con la 0.4.1 (último punto). Se adelantó a los diagnósticos
  (decidido por el mantenedor): el punto fijo no los necesita
- Diagnósticos (los mismos códigos y posiciones que la V0) [x] — en la 0.3.0
- Ponerse al día con la V0 de la 0.4.1 (sintaxis, semántica y diagnósticos
  nuevos) y regenerar la semilla [ ]

Después del punto fijo:

- Base para que el usuario final cree hooks y azúcar sintáctica, sobre la
  que se definirá la segunda versión de HTIMS [ ]
- Prueba de usabilidad: un programa complejo escrito leyendo solo la
  documentación [ ]

---

> Este roadmap es vivo: refleja la intención de diseño, no compromisos de fecha
