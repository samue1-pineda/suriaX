# Roadmap de suriaX

> Estado global: **V.0.0.1 (Pre-Alpha)**
> Frontend léxico funcional, el resto en diseño / implementación

---

## Fase 0: Diseño del lenguaje 

- Filosofía libsrX (pocos tokens, librerías nativas)[x]
- Sintaxis base y conjunto de tokens. [x]
- Gramática EBNF objetivo ([docs/gramar/grammar.ebnf](docs/gramar/grammar.ebnf))[x]
- Modelo de memoria definido: **region-based + move-semantics** [/]
- Definicion del ErrorHandler  y version preeliminar de los errores [x] 


## Fase 1: Frontend: análisis léxico  

- `source_reader`: UTF-8 → Unicode, normalización de saltos de línea[x]
-  Lexer modular (scanners + dispatch )[x]
-  Comentarios, interpolación de strings, `#extern cpp{}` (raw)[x]
-  Recuperación de errores [/]
-  Directiva orquestadora `#test lexer`[x]

## Fase 2 — Frontend: parser y AST 

-  Parser de **descenso recursivo + Pratt** [ / ]
-  Construcción del **AST** [ ]
-  Directivas en el parser: `#import` / `#export` / `#from` / `#extern` [ ]
-  Resolución de librerías `.libsrx` (verificar `#export <alias>`) [ ]
-  `#test parser` / `#test ast` (visualización de cada salida)[  ]

## Fase 3: Sistema de tipos  

> **Type-system óptimo para region-based + move-semantics:***`todavia no definido `*
> No se usara Hindley-Milner(HM) debido a la complejidad del sistema de tipado, choques con el futuro manejo de memoria y choque con el enfoque educativo 

## Fase 4: Semántica y modelo de memoria  

- Resolución de símbolos y scopes [ ]
-  Verificación de **regiones**: pertenencia, anidamiento, no-escape de
  referencias fuera de su región [ ]
-  Verificación de **move-semantics**: uso-tras-move, doble move [ ]
- Reglas de `mutable`/`const`, `null`/nullable (`?`), punteros (`ptr`/`&`) [ ]
- `#test sem` (visualización de símbolos/diagnósticos) [ ]

## Fase 5: HIR (protobuf)

- Esquema `.proto` del HIR [ ]
- Generador AST validado → HIR (Python) [ ]
- Serialización y versionado del esquema [ ]
- `#test hir` (volcado del HIR) [ ]

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

- Volcado por etapa: **tokens, AST, HIR, MIR, LLVM-IR** [ ]
- Formatos: texto, **JSON** (consumible por herramientas) y **DOT/Graphviz**
  (árboles y CFG) [ ]
- Visualización del **CFG** del MIR y del flujo de regiones/move [ ]
- `suriaX inspect <archivo> --stage <fase>`[ ]
- Vista interactiva paso a paso del pipeline[ ]

## Fase 8: Playground (web)  

- Compilación a **wASM** junto a Emscripten [ ]
- Editor web con ejecución del frontend en el navegador [ ]
- Visualizaciones integradas en el playground[ ]
- Compartir snippets / ejemplos [ ]

## Fase 9: Librerías nativas (libsrX)  

- Formato `.libsrx` y su resolución (`#import` / `#export as`)[ ]
-  Librería `IO` y manejo de metodos dunder [ ]
- Rutas de búsqueda (`libraries.libsrx_paths` en la config) [ ]
- Conjunto base de librerías estándar [ ]

## Fase 10: Tooling, tests y distribución  

- Runner propio de tests ([test/main.py](test/main.py)): descubre y ejecuta
  `test_*` en las categorías unit, e2e, negative, snapshot, fuzz [/]
- Suite de tests por fase (ver [test/tests_to_add.txt](test/tests_to_add.txt))[ ]

- Build system **suriniX**[ ]

- Empaquetado del binario `suriaX` (depdencias resueltas para el usuario final) [ ]

- Documentación web [ ]

---

> Este roadmap es vivo: refleja la intención de diseño, no compromisos de fecha
