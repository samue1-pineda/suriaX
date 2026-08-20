# HIR (High-level Intermediate Representation)

El HIR es la **frontera entre el frontend (Python) y sus consumidores**: el
backend C++ (MIR → VM de bytecode), el intérprete tree-walk y el target web
(TypeScript → WIR → JS/WASM). Se serializa en
**protobuf**, lo que permite desacoplamiento y mantener un contexto
semántico persistente. Ver [ARCHITECTURE.md](../ARCHITECTURE.md).

> Estado: **emisor Python implementado** (Fase 5 del lado frontend
> completa). Falta el lector C++ (entrada del lowering a MIR).

## Propósito

- Representación intermedia de alto nivel, ya con tipos resueltos y símbolos.
- Serialización en protobuf: puente Python → C++ e intérprete.
- Transporta la tabla de símbolos enriquecida (tipos, mutabilidad, hooks) y
  el AST-tipado con el `restype` de **cada expresión** anotado por la
  Semántica — la semántica rica que el MIR, el intérprete y el target web
  necesitan.

## Alcance de v2 (`schema_version == 2`)

El v2 añadió un **pool de tipos** en el `Module`: los tipos se escriben una
vez y los nodos los referencian por índice. Lo demás de esta lista viene del
v1 y no cambió.

- **Sin regiones**: retiradas del lenguaje en v0.2.0; sus tags siguen `reserved`
  (rechazo fail-fast, nunca degradación silenciosa); sus tags quedan
  `reserved` en el esquema para reintroducirlos sin romperlo.
- **move-semantics SÍ viaja** (`MoveStmt` + `Symbol.moved_at`): el
  intérprete la hace cumplir en runtime (RT001/RT002 en los caminos que el
  análisis estático conservador no ve).
- **Unidades separadas**: cada `.libsrx` emite SU propio `.phir`; el módulo
  principal las referencia (`Module.libraries`) con el IMPORT opaco. El
  module-linker del intérprete liga las N unidades al cargar.
- **Tabla de conversiones**: los `__cast__` viajan en `SymbolTable.casts`
  (varios por tipo, clave derivable de la firma origen→destino).
- **`alloc` no existe**: dejó de ser keyword del lenguaje (la reserva cruda
  la aporta una librería); su tag también quedó `reserved`.
- **Reglas de punteros SÍ viajan**, en dos lugares:
  - en el **tipo**: `Type.mut` distingue `ptr mutable T` (escritura a través
    del puntero) de `ptr T` (solo lectura);
  - en el **nodo**: `&x` es el mensaje dedicado `AddrOf` con la mutabilidad
    ya resuelta (`var` → mut, `const` → no-mut). Los consumidores despachan
    por caso del `oneof`, sin comparar strings de operadores.
- **`cast<T>(x)` viaja como `CastExpr`** (`type` + `value` + `HookRef`): la
  única vía de conversión del lenguaje. Entre primitivos el consumidor
  ejecuta la conversión nativa; con nominal involucrado, el `hook`
  referencia el `__cast__` que la implementa (`HookKind.CAST`).

## Cómo se usa

```
python V0/main.py programa.srcx --emit-hir
#   binario -> ./dumps/programa.srcx.phir   ("protohir": el artefacto real)
#   texto   -> ./dumps/programa.srcx.phir.txt (mismo Module, debugging)

#test hir            # (en el fuente) volcado en texto protobuf a consola
#   los objetivos de #test son case-insensitive (#test HIR == #test hir) y
#   cada fase corre sus prerequisitos; un objetivo desconocido lista los
#   disponibles en vez de intentar parsear el archivo como código.

python runtime/interpreter/main.py dumps/programa.srcx.phir
#   punto de entrada del intérprete: valida el esquema fail-fast, indexa
#   los hooks y resume el módulo (el tree-walk llega en la Fase 5.5).
```

La dependencia `protobuf` solo se exige si se pide la fase HIR; el frontend
(lexer → Semántica) funciona sin ella. Los stubs `hir_pb2.py` **no se
commitean**: `V0/src/HIR/stubs.py` los genera con `protoc` en build (carpeta
`gen/`, ignorada por git) y los regenera si el `.proto` cambió.

## Módulos

| Archivo | Responsabilidad |
|---|---|
| [`proto/hir.proto`](../V0/src/HIR/proto/hir.proto) | esquema v1 (compila con `protoc`) |
| [`emmit_IR.py`](../V0/src/HIR/emmit_IR.py) | emisor explícito por clase: `(Program, SymbolTable)` → bytes; acumula `HIRError`, solo emite con cero errores |
| [`stubs.py`](../V0/src/HIR/stubs.py) | generación en build + carga perezosa de `hir_pb2` |
| [`PROTOBUF_BRIDGE.md`](../V0/src/HIR/PROTOBUF_BRIDGE.md) | diseño completo del puente (mapeos, decisiones, versionado) |

## TODO

- [x] Esquema `.proto` v2 (pool de tipos) con tags reservados para las
  regiones retiradas.
- [x] Emisor Python (`emit`/`emit_text`) + `#test hir` + `--emit-hir`.
- [x] Versionado de esquema (`schema_version` fail-fast, paquete `v0`).
- [x] Lector de HIR en TypeScript (target web): valida `schema_version`,
  reconstruye la `SymbolTable` y baja a WIR → JS/WASM.
- [ ] Lector de HIR en C++ (valida `schema_version`, reconstruye
  `SymbolTable`, `switch` exhaustivo por `oneof`).
- [ ] Round-trip golden tests por cada ejemplo de `docs/examples/`.
