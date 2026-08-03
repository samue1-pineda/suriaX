# El puente protobuf: Semántica (Python) → HIR → MIR (C++) / intérprete

> Documento de diseño de la **Fase 5** (HIR). Define QUÉ se serializa, CÓMO
> se mapea cada estructura de Python a protobuf, el plan de versionado y el
> orden de implementación. El esquema vive en [`proto/hir.proto`](proto/hir.proto)
> (**v1, compila con `protoc`; emisor implementado en `emmit_IR.py`**).
> Mismo rigor que `parser/ARQUITECTURA.md` y `semantic/ARQUITECTURA.md`.

## Alcance de v1 — qué NO viaja (deliberado)

- **RBMM**: `region`/`shrd`, `make T in r` y `x at r` NO se serializan. El
  emisor los **rechaza fail-fast** (`HIR005`,
  `HIRUnsupportedInstructionError`) con su posición — nunca degradación
  silenciosa (perder semántica de memoria sin avisar contradice el objetivo
  educativo). Sus tags (`Expr` 16/20/21, `Stmt` 12, `Symbol` 7/13,
  `SymbolKind.REGION` 9) quedan **`reserved`**: reintroducirlos en una
  versión futura es aditivo, sin romper el esquema.
- **move-semantics SÍ viaja** (`MoveStmt`, `Symbol.moved_at`): el
  intérprete la hace cumplir EN RUNTIME (los caminos por ramas/iteraciones
  que `memory_check` estático deja pasar a propósito), igual que hará el MIR.
- **`alloc`**: eliminado del LENGUAJE (no solo del HIR) — la reserva cruda
  la aporta una librería. Su tag quedó `reserved` junto a los de RBMM.

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
  es información que ya calculaba y descartaba.

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
│  (global + hooks)   │            │    regiones/move     │
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
| `Expression` (las de v1) | `Expr` con `oneof node` | ver abajo; `MakeExpr`/`Placement` se rechazan (RBMM) |
| `Statement` (las de v1) | `Stmt` con `oneof node` | idem; `RegionStmt`/`MoveStmt` se rechazan |
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
- Generación de stubs (**implementada en `stubs.py`**): `protoc
  --python_out=gen proto/hir.proto` se ejecuta en build, de forma perezosa y
  con detección de staleness por mtime (un `stat`, no re-generación ciega).
  Los stubs generados **no se commitean** (`V0/src/HIR/gen/` está en
  `.gitignore`); regenerarlos es parte del build, no del repo. El `--cpp_out`
  del backend queda para la fase del lector C++.

## 3. Versionado del esquema

- `Module.schema_version` (uint32) empieza en `1`. El lector C++ compara
  contra las versiones que soporta y **rechaza** lo demás con error claro
  (fail-fast; nunca interpretar bytes con un layout que no conoce).
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

1. ~~Fijar `hir.proto`~~ **hecho** (v1 con tags `reserved` para RBMM/move).
2. ~~`emmit_IR.py` + `#test hir`~~ **hecho** (`emit`/`emit_text`, más
   `--emit-hir` en `V0/main.py` → binario `.hir` en `./dumps`).
3. Lector C++ mínimo que valide `schema_version` y reconstruya
   `SymbolTable` + un `switch` exhaustivo por `oneof` (aunque el lowering
   sea un stub): eso congela el contrato de la frontera. **Pendiente.**
4. Round-trip test: `.srcx` → HIR → texto → comparación golden, por cada
   ejemplo de `docs/examples/`. **Pendiente** (verificado hoy a mano:
   emisión + deserialización + inspección de símbolos/AddrOf/nullable).
