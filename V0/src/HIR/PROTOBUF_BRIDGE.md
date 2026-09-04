# El puente protobuf: Semántica (Python) → HIR → MIR (C++) / intérprete

> Documento de diseño de la **Fase 5** (HIR). Define QUÉ se serializa, CÓMO
> se mapea cada estructura de Python a protobuf, el plan de versionado y el
> orden de implementación. El esquema vive en [`proto/hir.proto`](proto/hir.proto)
> (**v1, compila con `protoc`; emisor implementado en `emmit_IR.py`**).
> Mismo rigor que `parser/ARQUITECTURA.md` y `semantic/ARQUITECTURA.md`.

## Alcance de v1 — qué NO viaja (deliberado)

- **Regiones**: `region`/`shrd`, `make T in r` y `x at r` se RETIRARON del
  lenguaje en v0.2.0 y nunca se serializaron. El
  emisor los **rechaza fail-fast** (`HIR005`,
  `HIRUnsupportedInstructionError`) con su posición — nunca degradación
  silenciosa (perder semántica de memoria sin avisar contradice el objetivo
  educativo). Sus tags (`Expr` 16/20/21, `Stmt` 12, `Symbol` 7/13,
  `SymbolKind.REGION` 9, `HookKind.MAKE` 2) quedan **`reserved`**: reintroducirlos en una
  versión futura es aditivo, sin romper el esquema.
- **move-semantics SÍ viaja** (`MoveStmt`, `Symbol.moved_at`): el
  intérprete la hace cumplir EN RUNTIME (los caminos por ramas/iteraciones
  que `memory_check` estático deja pasar a propósito), igual que hará el MIR.
- **`alloc`**: eliminado del LENGUAJE (no solo del HIR) — la reserva cruda
  la aporta una librería. Su tag quedó `reserved` junto a los de las regiones.

## Unidades separadas (Module.libraries)

Cada `.srcx`/`.libsrx` compila a **su propio `.phir`**: el módulo principal
NO re-embebe los exports de sus imports (el `Symbol` IMPORT viaja **opaco**,
sin `members`) — solo lista `LibraryRef {alias, phir}` con rutas relativas.
Beneficios medidos: `.phir` principal más chico (360 vs 644 bytes en el
ejemplo IO), debugging por unidad (`IO.phir.txt` aparte) y una librería
compartida no se re-serializa en cada consumidor. El consumidor (module
linker del intérprete, `runtime/interpreter/loader.load_image`; lector C++
futuro) resuelve y liga las N unidades — transitivamente, con vistos.

## Tabla de conversiones (SymbolTable.casts)

`__cast__` NO usa el registro `(owner, kind)` de los demás hooks: un tipo
puede declarar **varias** conversiones (`int->int8`, `int8->int`,
`str->Estado`, `Estado->vec`...). Viajan como `repeated Symbol casts`; la
clave del par es DERIVABLE de la firma (`origen = param_types[0]`,
`destino = type`) y cada lector reconstruye su índice
`{(origen,destino): hook}` en O(n). El encadenamiento es EXPLÍCITO
(`cast<vec>(cast<Estado>(s))`): nunca se buscan caminos intermedios.

## Reglas de punteros — qué SÍ viaja

- `Type.mut` en cada tipo `POINTER`: `ptr mutable T` (escritura a través
  del puntero) vs `ptr T` (solo lectura). Participa de la identidad del
  tipo; la única coerción segura es SOLTAR mutabilidad.
- `AddrOf` como mensaje **dedicado** (no un `UnaryOp` con string): `&x`
  viaja con `mut` ya resuelto por la Semántica (binding `var` → `true`,
  `const` → `false`) y su `Expr.restype` lleva el tipo puntero completo.
  Los consumidores despachan por caso del `oneof`.
- `FreeStmt` con su `HookRef` a `__free__` (SEM014 ya verificó que el
  target es `ptr T`).
- El `restype` de **toda expresión** viaja en el contenedor `Expr`: la
  Semántica lo anota en sitio (`scope_resolver.visit_expr`) — costo cero,
  es información que ya calculaba y descartaba. Desde **v2** viaja como
  `type_id`, un índice en el POOL `Module.types`, en vez del mensaje `Type`
  completo: había 21 065 copias de 43 formas distintas (490x), un 20 % del
  artefacto y un 16 % del tiempo de emisión. La `SymbolTable` conserva sus
  tipos inline a propósito. Ver [../../../docs/plan_hir_v2.md](../../../docs/plan_hir_v2.md).

---

## 0. Qué cruza la frontera

La fase Semántica ya produce exactamente las dos cosas que el backend C++
necesita (`semantic.analyze()` → `(SymbolTable, errors)` + el `Program`
anotado en sitio):

```
  Python (frontend)                      C++ (backend)
┌─────────────────────┐   bytes    ┌──────────────────────┐
│ Program (AST        │  protobuf  │ lector HIR           │
│  validado + hooks   │ ─────────▶ │  → MIR lowering      │
│  enlazados)         │            │  → verificación      │
│ SymbolTable         │            │    definitiva de     │
│  (global + hooks)   │            │    propiedad/move    │
└─────────────────────┘            └──────────────────────┘
```

Un `.srcx` compilado = **un** mensaje `Module`:

| Campo de `Module` | Origen en Python | Notas |
|---|---|---|
| `schema_version` | constante del emisor | ver secc. 3 |
| `source_file` | `ctx.source_path` | solo diagnósticos |
| `symbols` | `SymbolTable.global_scope` + `SymbolTable.hooks` | scope global completo; los scopes de bloque **no** viajan (C++ los reconstruye al recorrer cuerpos — son derivables, serializarlos sería redundancia) |
| `items` | `Program.items` | en orden de declaración |

Los **diagnósticos NO viajan**: si la Semántica acumuló errores, el emisor
HIR ni siquiera se ejecuta (no se cruza la frontera con un programa
inválido). Los falsos negativos deliberados de `memory_check` (ver
`semantic/ARQUITECTURA.md` secc. 4.2) los atrapa el MIR en C++.

## 1. Mapeo estructura a estructura

Regla general: **cada dataclass de Python tiene un message espejo**, con el
mismo nombre y los mismos campos. Cero traducción conceptual — quien lee
`ast_nodes.py` puede leer `hir.proto` sin tabla de equivalencias.

| Python | protobuf | Decisión |
|---|---|---|
| `types_ast.Type` (`kind`+`name`+`inner`) | `Type` | espejo 1:1; recursivo para `ptr`/`?` |
| `symbol_table.Symbol` | `Symbol` | espejo 1:1; `members` es `map<string,Symbol>` (los namespaces ya son `dict` en Python) |
| `SymbolTable.hooks: dict[(owner,kind)]` | `repeated HookEntry` | protobuf no admite claves compuestas en `map`; una lista de tripletas conserva la clave y el lookup en C++ se reconstruye O(1) en un `unordered_map` |
| `Expression` | `Expr` con `oneof node` | ver abajo; un nodo sin handler se rechaza (`HIR005`) |
| `Statement` | `Stmt` con `oneof node` | idem; `MoveStmt`/`FreeStmt` SÍ viajan |
| `Block.drops` | `repeated Drop` | destrucciones que el compilador INSERTA al cerrar el bloque; nadie las escribe |
| `Declaration` (8 clases) | `Decl` con `oneof node` | incluye `FromDirective`; statements sueltos van en `Decl.statement` |
| `AddrOf` (`&x`) | `AddrOf {operand, mut}` | nodo dedicado con la regla de mutabilidad resuelta (ver arriba) |
| `CastExpr` (`cast<T>(x)`) | `CastExpr {type, value, hook}` | única vía de conversión; `hook` = `__cast__` (`HookKind.CAST`) si hay nominal involucrado |
| `TypeDecl` (`const type int8;`) | `TypeDecl` en `Stmt` | el binding es de metatipo `type` (`TypeKind.META`) |
| `ImportBinding.source` (`Import\|From`) | campos aplanados `lib` + `member` | `member` != "" solo en la forma `#from lib #import member` |
| anotación `.hook` (Call/Sizeof/Free) | `HookRef {owner, kind}` | referencia por CLAVE, no el `Symbol` completo: evita duplicarlo N veces y el lector lo resuelve O(1) contra `SymbolTable.hooks` |
| `DecoratorDecl(target=fn)` | `FunctionDecl.decorator` | el wrapper se aplana: un campo string en vez de un nodo contenedor (el MIR no necesita la indirección) |
| `InterpolatedString.parts: [str\|Expr]` | `repeated Part` con `oneof` | los `Union` de Python se vuelven `oneof` por elemento |

**Por qué `oneof` y no `google.protobuf.Any`**: `Any` obliga a reflexión y
registry de tipos en C++ (lento, frágil, y rompe el fail-fast del
versionado). Con `oneof`, el lector C++ es un `switch (expr.node_case())` —
despacho O(1), exhaustivo verificable por el compilador, mismo patrón de
tabla-de-despacho que ya usa todo el frontend.

**Por qué los primitivos de posición (`ln`/`col`) van en `Expr`/`Stmt`/`Decl`
y no en cada variante**: todos los nodos los tienen (herencia de `ASTNode`);
subirlos al contenedor evita repetir 2 campos × 33 messages.

## 2. El emisor Python (`emmit_IR.py`, **implementado**)

```python
def emit(program, table, *, source_file="") -> tuple[bytes | None, list[HIRError]]
def emit_text(...)  # formato texto de protobuf, para '#test hir'
```

Contrato: **acumula** `HIRError` en vez de lanzar (mismo patrón que
`semantic.analyze`); devuelve bytes SOLO con cero errores — un HIR parcial
no cruza la frontera. Cada hijo se escribe DENTRO del message de su padre
(cero copias intermedias); despacho por `type(node)` con tablas por
categoría, un solo recorrido O(n).

- **Un solo recorrido O(n)** del árbol (mismo contrato de rendimiento que
  cada pasada semántica), con despacho por `type(node)` — reutilizar el
  patrón de `include/ast_walk.py` no aplica aquí porque el emisor necesita
  recursión estructural (cada hijo se escribe DENTRO de su message padre),
  pero sí su tabla `child_fields` si se opta por un emisor reflexivo.
  **Recomendación: emisor explícito por clase** (como `scope_resolver`), no
  reflexivo: el mapeo tiene casos especiales (DecoratorDecl aplanado,
  HookRef, oneof de Literal) que la reflexión complica más de lo que ahorra.
- La dependencia `protobuf` la exige `V0/main.py` **solo si se pide la fase
  HIR** (`--emit-hir` / `#test hir`); el frontend puro sigue sin necesitarla
  (no imponer dependencias por adelantado).
- **El lado Python NO usa `protoc` ni `google.protobuf`** (`stubs.py` +
  `schema.py` + `wire.py`). Los mensajes se construyen leyendo el propio
  `hir.proto` y se serializan a mano.

  Antes se generaban stubs con `protoc` y se cargaban con la librería. Eso
  ataba la compilación a DOS instalaciones que se hacen por vías distintas
  —un binario del sistema y un paquete de pip— y que además tienen que ser
  compatibles entre sí: el stub generado lleva dentro su versión de gencode
  y el runtime se niega a cargar uno más nuevo que él. Un `protoc` 36 con un
  `protobuf` 7.35 es una combinación perfectamente normal, y rompía la
  compilación entera —con un `VersionError` en bruto— en cuanto alguien
  tocaba el `.proto`.

  Es la misma decisión que ya había tomado el target web por las mismas
  razones (ver la cabecera de `web/src/hir/wire.ts`), y devuelve al proyecto
  la propiedad que esta sección prometía: el frontend no necesita nada
  instalado.

  El `.proto` sigue siendo la **fuente única**: no hay un esquema
  transcrito a mano que mantener sincronizado, se lee de él. Y que los bytes
  sean protobuf DE VERDAD lo comprueba
  `test_hir_reproducible.test_el_codec_propio_coincide_con_google_protobuf`,
  que sí usa la librería **cuando está instalada** y se salta cuando no.

- El `--cpp_out` lo sigue invocando CMake (`CMake/SuriaXBackend.cmake`): el
  backend C++ enlaza `libprotobuf` de verdad, y ahí es una dependencia de
  BUILD del backend, resuelta por el mismo sistema que lo compila. Quien
  descarga un binario no la ve.

## 3. Versionado del esquema

- `Module.schema_version` (uint32) va por **2** (v1: inicial; v2: pool de
  tipos). El lector C++ compara contra las versiones que soporta y **rechaza**
  lo demás con error claro (fail-fast; nunca interpretar bytes con un layout
  que no conoce). Los lectores vivos hoy son
  `runtime/interpreter/loader.SUPPORTED_SCHEMA_VERSIONS` y
  `web/src/hir/decode.SUPPORTED_SCHEMA_VERSIONS`: se actualizan a la vez, y
  un test del repo lo recuerda si alguien cambia la constante del emisor.

- **Serialización determinista.** El `.phir` se escribe SIEMPRE por
  `emmit_IR.serialize`, que usa `deterministic=True`. Sin eso el orden de las
  entradas de un `map<>` lo decide la tabla hash del proceso, y el mismo
  programa compilado dos veces daba artefactos distintos — lo que invalida
  golden fixtures, cachés por hash y cualquier diferencial de artefactos.
- Cambios **aditivos** (campo nuevo con tag nuevo) no rompen: proto3 ignora
  campos desconocidos al leer con un esquema viejo y los deja en default al
  leer datos viejos con esquema nuevo. `schema_version` NO se incrementa.
- Cambios **incompatibles** (renumerar tags, cambiar tipo de un campo,
  eliminar un campo sin `reserved`) exigen incrementar `schema_version` y
  marcar los tags viejos como `reserved` para que nunca se reutilicen.
- El paquete es `suriax.hir.v0`: si algún día hace falta un rediseño total,
  se crea `suriax.hir.v1` en paralelo y ambos coexisten durante la
  transición (patrón estándar de gRPC/protobuf).

## 4. Orden de implementación

1. ~~Fijar `hir.proto`~~ **hecho** (tags `reserved` para las regiones retiradas).
2. ~~`emmit_IR.py` + `#test hir`~~ **hecho** (`emit`/`emit_text`, más
   `--emit-hir` en `V0/main.py` → binario `.hir` en `./dumps`).
3. ~~Lector C++ mínimo que valide `schema_version` y reconstruya
   `SymbolTable` + un `switch` exhaustivo por `oneof`~~ **hecho**
   ([`backend/`](../../../backend/README.md)). El contrato de la frontera
   queda congelado: sus vistas (`--pretty`, `--summary`) son **byte-idénticas**
   a las de Python, y `test/e2e/test_backend_cpp.py` las compara sobre un
   programa de referencia que toca cada forma del esquema. El `switch` va
   **sin rama `default`**, así que añadir un caso al `oneof` rompe la
   compilación del lector — la exhaustividad verificable por el compilador que
   esta sección prometía.
4. Round-trip test: `.srcx` → HIR → texto → comparación golden, por cada
   ejemplo de `docs/examples/`. **Pendiente** (verificado hoy a mano:
   emisión + deserialización + inspección de símbolos/AddrOf/nullable).
