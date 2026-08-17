# Roadmap de suriaX

> Estado global: **V.0.1.0 (Pre-Alpha)**
> interprete funcional, RBMM incompleto y llamadas a c++(pybind11) para memoria

---

## Fase 0: Diseño del lenguaje 

- Filosofía libsrX (pocos tokens, librerías nativas)[x]
- Sintaxis base y conjunto de tokens. [x]
- Gramática EBNF objetivo ([docs/gramar/grammar.ebnf](grammar.ebnf))[x]
- Modelo de memoria definido: **region-based + move-semantics** [/]
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

> **Type-system óptimo para region-based + move-semantics:***`todavia no definido `*
> No se usara Hindley-Milner(HM) debido a la complejidad del sistema de tipado, choques con el futuro manejo de memoria y choque con el enfoque educativo 

## Fase 4: Semántica y modelo de memoria  

- Resolución de símbolos y scopes [x]
-  Verificación de **regiones**: pertenencia, anidamiento, no-escape de
  referencias fuera de su región [/] (pertenencia y escape obvio por scopes;
  escapes inter-función se difieren al MIR — `semantic/ARQUITECTURA.md` secc. 4)
-  Verificación de **move-semantics**: uso-tras-move, doble move [/]
  (lineal, intra-función, sin punto fijo — deliberado, ídem secc. 4)
- Reglas de `mutable`/`const`, `null`/nullable (`?`), punteros (`ptr`/`&`) [x]
- Hooks de tipo dunder con despacho enlazado: `__free__`/`__make__`/
  `__sizeof__`/`__print__`/`__len__` [x]
- `#test sem` (visualización de símbolos/diagnósticos) [x]

## Fase 5: HIR (protobuf)

> Alcance v1 (deliberado): **sin RBMM** — `region`/`shrd`, `make T in r` y
> `x at r` se RECHAZAN fail-fast (`HIR005`) y sus tags quedan `reserved`
> para reintroducirlos sin romper el esquema. **move-semantics SÍ viaja**
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
> C++/LLVM. Consume el mismo contrato que el backend nativo — el HIR es la
> costura de desacople (regla no negociable de `docs/propuesta_vm_bytecode.md`).
> Queda como oráculo de *differential testing*. Diseño completo y orden de
> implementación en
> [`runtime/interpreter/ARQUITECTURA.md`](interpreter_internals.md).
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
- Modelo de memoria en runtime SIN RBMM: celdas, `&`/deref implícito,
  `move` con invalidación (RT001/RT002), `free`/use-after-free (RT003),
  `--trace-memory` (`memory/pointer.py`) [x]
- Arenas por región (RBMM) — requiere HIR v2 [ ]
- Target `interp` en `compilerconfig` + CLI `--run` (V0/main.py llama a
  `runtime/interpreter/main.py --exec` en proceso) [x]
- Structs ejecutables (`__make__`/instanciación), vectores, `#extern` [ / ]

## Fase 6: Backend C++ 

- Lector de HIR en C++ [ ]
- **MIR lowering**: control de flujo explícito; verificación final de
  regiones/move sobre el MIR [ ]
- Generación de **LLVM IR** [ ]
- Targets por `compilerconfig`: `IS_WEB`→wASM, `IS_WIN32`→.exe, `IS_LINUX`→.o [ ]
- **Linker** por plataforma (Linux web y Windows) [ ]
- Integración del C++ de `#extern cpp{}` vía bindings (pybind11) [ ]
- `#test mir` / `#test llvm` (volcado de cada IR) [ ]

## Fase 7: Visualizaciones integradas  

>para debugging se desarrollaran algunas visualizaciones pero la version final y pulida espera a la version web

- Volcado por etapa: **tokens, AST, HIR, MIR, LLVM-IR** [ / ]
- Formatos: texto, **JSON** (consumible por herramientas) y **DOT/Graphviz**
  (árboles y CFG) [ / ]
- Visualización del **CFG** del MIR y del flujo de regiones/move [ ]
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


- Runner propio de tests ([test/main.py](https://github.com/samue1-pineda/suriaX/blob/main/test/main.py)): descubre y ejecuta
  `test_*` en las categorías unit, e2e, negative, snapshot, fuzz [/]
- Suite de tests por fase (ver [test/tests_to_add.txt](https://github.com/samue1-pineda/suriaX/blob/main/test/tests_to_add.txt))[ / ]

- Build system **suriniX**[ ]

- Empaquetado del binario `suriaX` (depdencias resueltas para el usuario final) [ ]

- Documentación web [ ]

---

> Este roadmap es vivo: refleja la intención de diseño, no compromisos de fecha
