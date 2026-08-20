# Roadmap de suriaX

> Estado global: **Pre-Alpha — "Dejando las arenas movedizas sin dueño"**
> (la version publicada es la medalla del [README](README.md), que sale de
> `version.py`)
> interprete funcional, modelo de memoria por **ownership** (las regiones se
> retiraron: ver [el registro de la decisión](documentation/source/memory_decision.rst))
> y llamadas a c++(pybind11) para memoria

---

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
  `__min__`/`__max__` [x]
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
- Lector de HIR en C++ (entrada del lowering a MIR) [ ]

## Fase 5.5: Intérprete tree-walk (consume HIR)

> Ejecuta el **HIR** para ver salidas reales y probar librerías sin el backend
> C++. Consume el mismo contrato que el backend nativo — el HIR es la
> costura de desacople (regla no negociable de `docs/propuesta_vm_bytecode.md`).
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
  sintaxis dedicada) — requiere structs ejecutables [ ]
- Target `interp` en `compilerconfig` + CLI `--run` (V0/main.py llama a
  `runtime/interpreter/main.py --exec` en proceso) [x]
- Structs ejecutables (instanciación por fábrica de librería), vectores,
  `#extern` [ / ]

## Fase 6: Backend C++ 

- Lector de HIR en C++ [ ]
- **MIR lowering**: control de flujo explícito; verificación final de
  propiedad y **préstamos** (tiempos de vida de `ptr`) sobre el MIR [ ]
- **VM de bytecode + JIT**: el target NATIVO estándar (LLVM queda fuera del
  plan: el MIR ya es un IR de registros con CFG, y meter LLVM en medio añadía
  una dependencia enorme y un segundo modelo de máquina antes de tener el
  primero funcionando) [ ]
- Targets por `compilerconfig`: `IS_WEB`→wASM, `IS_WIN32`→.exe, `IS_LINUX`→.o [ ]
- **Linker** por plataforma (Linux web y Windows) [ ]
- Integración del C++ de `#extern cpp{}` vía bindings (pybind11) [ ]
- `#test mir` / `#test bytecode` (volcado de cada IR) [ ]

## Fase 7: Visualizaciones integradas  

>para debugging se desarrollaran algunas visualizaciones pero la version final y pulida espera a la version web

- Volcado por etapa: **tokens, AST, HIR, MIR, bytecode** [ / ]
- Formatos: texto, **JSON** (consumible por herramientas) y **DOT/Graphviz**
  (árboles y CFG) [ / ]
- Visualización del **CFG** del MIR y del flujo de propiedad (`move`/drop) [ ]
- `suriaX inspect <archivo> --stage <fase>`[x]
- Vista interactiva paso a paso del pipeline[ ]

## Fase 8: Playground (web)  

- Compilación a **wASM** junto a Emscripten [ ]
- Editor web con ejecución del frontend en el navegador [ ]
- Visualizaciones integradas en el playground[ ]
- Compartir snippets / ejemplos [ ]

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
-  Librería `IO` y manejo de metodos dunder [/] (io.libsrx con
  print/printf/println y hooks `__print__`/`__len__` funcionando)
- Rutas de búsqueda (`libraries.libsrx_paths` en la config, relativas a la
  raíz del proyecto; default `./lib`) [x]
- Conjunto base de librerías estándar [ / ]

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

- Build system **suriniX**[ ]

- Empaquetado del binario `suriaX` (depdencias resueltas para el usuario final) [ ]

- Documentación web: sitio de Sphinx publicado en GitHub Pages [x]

---

> Este roadmap es vivo: refleja la intención de diseño, no compromisos de fecha
