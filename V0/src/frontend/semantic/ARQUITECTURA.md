# Arquitectura de la fase Semántica de suriaX

> Documento de diseño. **No** contiene código: define la estructura de
> carpetas/archivos propuesta, la responsabilidad de cada módulo, el diseño
> de la tabla de símbolos y el mapeo de **todo tipo de nodo del AST** a su
> módulo responsable. Mismo rigor que
> [`parser/ARQUITECTURA.md`](../parser/ARQUITECTURA.md), objetivo rector
> idéntico: **modularidad y sostenibilidad**, con **rendimiento** como
> restricción de diseño explícita (ver secc. 4).

---

## 0. Entrada y salida de la fase

```
AST-tipado (Program, con restype/return_restype ya resueltos)
      │
      ▼
   SEMÁNTICA
      │
      ├─▶ AST validado (mismo Program; los diagnósticos NO mutan su forma)
      └─▶ SymbolTable (nueva; persiste y viaja serializada al HIR — Fase 5)
```

Según [`ARCHITECTURE.md`](../../../../ARCHITECTURE.md): `AST-tipado → Semántica →
AST validado`, y la salida real y persistente es la **tabla de símbolos**
(`DESIGN_PRINCIPLES.md` secc. 7: *"la tabla de símbolos es un estado
persistente del compilador, no de una sola fase"*). Esta fase la **crea**; el
HIR la **serializa** (protobuf, Fase 5 — fuera de alcance aquí).

---

## 1. Estrategia de análisis: multi-pasada, cada pasada O(n)

A diferencia del parser (una sola pasada sobre los tokens), la Semántica
necesita conocer **declaraciones futuras** antes de poder resolver usos
anteriores en el archivo (p. ej. `main()` puede llamar a una función
declarada más abajo). Esto exige **varias pasadas sobre el AST**, cada una
con una responsabilidad cerrada:

| # | Pasada | Módulo | Qué resuelve |
|---|--------|--------|---------------|
| 1 | **Recolección** | `collect.py` | Registra todo símbolo de nivel superior (`fn`, `struct`, `enum`, imports) en el scope global, **antes** de mirar ningún cuerpo. |
| 2 | **Resolución de scopes** | `scope_resolver.py` | Recorre cuerpos de función; scope por bloque; resuelve cada `Identifier`/`Assignment`/`MemberAccess`; valida mutabilidad (`const`); y **enlaza los tipos nominales** con `TypeBinder` (`type_resolver.py`). |
| 3 | **Memoria ligera** | `memory_check.py` | Move-semantics y pertenencia a región — **deliberadamente no exhaustivo**, ver secc. 4. |

**Fueron cuatro.** El enlace de tipos era una pasada aparte con su propio
recorrido PLANO, y ahí estaba el problema: validar un tipo exige saber qué
scope se está mirando, y un recorrido sin scopes no puede. Un `type`
declarado dentro de una función no lo veía nadie —la declaración se
descartaba en silencio y el fallo salía lejos, como un `AST005` en el primer
uso—. Su lógica no se duplicó ni se tiró: vive en `type_resolver.TypeBinder`
y la invoca `scope_resolver` en el punto donde cada anotación entra en juego.
El frontend hace un recorrido menos (~25% menos de tiempo en la fase) y los
tipos anidados existen.

**Por qué 3 pasadas y no 1**: cada pasada es **O(n)** en el número de nodos
del AST; 3 pasadas siguen siendo **O(n)** (una constante, no crece con el
tamaño del programa). Intentar resolver todo en una sola pasada obligaría a
soportar *forward references* con retrocesos (revisar nodos ya visitados) o
a prohibir declarar `fn`/`struct` fuera de orden — ninguna de las dos es
aceptable (la segunda contradice el estilo de todos los ejemplos reales, ver
`docs/examples/structs_and_control.md`). 4 pasadas simples y predecibles es
más barato que 1 pasada con retrocesos.

> Mismo principio de rendimiento que el parser (secc. 1 de su ARQUITECTURA):
> **nunca reprocesar trabajo ya hecho**. Aquí el equivalente a "cero
> backtracking" es "cero pasadas redundantes": cada pasada visita cada nodo
> relevante **una sola vez**.

---

## 2. Contexto: qué ya existe y no se duplica

- **AST y AST-tipado** → [`include/ast_nodes.py`](../../../include/ast_nodes.py):
  la Semántica **consume** `Program` tal como lo deja `parser/typed_ast.py`
  (con `restype`/`return_restype` ya resueltos desde anotaciones explícitas).
  No reconstruye nodos; **anota** (mismo patrón mutable-en-sitio que
  `typed_ast.py`, ver secc. 4.4).
- **Sistema de tipos resuelto** → [`include/types_ast.py`](../../../include/types_ast.py):
  `Type`, `PRIMITIVE_TYPES`, `pointer_of`/`nullable_of`/`nominal`. La
  Semántica **extiende** este contrato, no lo reemplaza: un tipo nominal
  pasa de "solo un nombre" (`Type(NOMINAL, name="Punto")`) a tener, además,
  un `Symbol` enlazado (secc. 5).
- **Errores de tipos** → [`error_handler/ASTError.py`](../../../error_handler/ASTError.py):
  ya tiene `UnknownTypeError` (AST005), `TypeMismatchError` (AST006),
  `CannotInferTypeError` (AST007), `InvalidCastError` (AST008),
  `AmbiguousTypeError` (AST009), `InvalidReturnTypeError` (AST012).
  **Decisión**: la Semántica **reutiliza esta taxonomía** para todo
  diagnóstico de *tipos* — son exactamente las categorías que necesita el
  `TypeService` (secc. 5) y ya existen con código estable. **No** se
  duplica una jerarquía paralela `SEM-tipos`.
- **Errores nuevos** → `error_handler/SemanticError.py` (a crear, secc. 6):
  cubre lo que ASTError **no** cubre: símbolos (no declarado, duplicado),
  mutabilidad (`const` reasignado), y memoria (move/región). Estas
  categorías no existen hoy en ningún archivo de `error_handler/`.
- **Patrón de referencia** → el **parser**
  ([`parser/parser.py`](../parser/parser.py) + [`parser/grammar/`](../parser/grammar/)):
  orquestador padre + subpaquete con un archivo por responsabilidad, cursor
  (aquí: tabla de símbolos) compartido por referencia entre todas las
  pasadas. La Semántica replica esta filosofía.

---

## 3. Árbol de carpetas/archivos propuesto

```
V0/src/frontend/semantic/
├── ARQUITECTURA.md          # este documento
├── __init__.py              # API pública: analyze(program) -> (SymbolTable, errors)  [IMPLEMENTADO]
│
├── semantic.py               # ORQUESTADOR: corre las pasadas en orden,
│                              #   atiende '#test sem' (vuelca símbolos/diagnósticos)  [IMPLEMENTADO — parcial, secc. 12]
├── context.py                # Estado compartido entre pasadas (scope actual,
│                              #   función actual, acumulador de errores)  [IMPLEMENTADO]
│
├── symbol_table.py           # Estructura CENTRAL: Symbol, Scope, SymbolTable  [IMPLEMENTADO]
├── hooks.py                   # Vocabulario y lógica de métodos "dunder" como
│                              #   HOOKS de tipo (__free__/__make__/__sizeof__/
│                              #   __print__/__len__), firma COMPLETA  [IMPLEMENTADO, secc. 12–13]
├── type_service.py           # Interfaz de consulta de tipos (secc. 5) — la
│                              #   pieza que la futura Fase 3 (sistema de tipos)
│                              #   extenderá sin tocar sus llamadores  [IMPLEMENTADO]
│                              # (la resolución REAL de .libsrx vive FUERA de
│                              #  esta fase: `src/linker_p/`, el linker de
│                              #  librerías nativas — secc. 13.2)
│
├── collect.py                 # Pasada 1: símbolos de nivel superior + hooks + imports  [IMPLEMENTADO]
├── type_resolver.py           # TypeBinder: enlace de tipos nominales (+ __sizeof__), lo usa scope_resolver  [IMPLEMENTADO]
├── scope_resolver.py          # Pasada 3: scopes de bloque + resolución de
│                              #   nombres + mutabilidad (inline, ver secc. 4.3)
│                              #   + despacho de hooks (secc. 13.3)  [IMPLEMENTADO]
└── memory_check.py            # Pasada 4: move (ligero, ver secc. 4)  [IMPLEMENTADO]
```

Se sumó `hooks.py`, no previsto en el plan original (ver secc. 12–13); la
resolución de `.libsrx`, que también empezó aquí, se extrajo a `src/linker_p/`
(secc. 13.2). Cada archivo tiene una pasada o una estructura de
datos — misma proporción de modularidad que el parser (11 archivos en
`grammar/` + 4 de infraestructura). Además, el recorrido genérico del árbol
se extrajo a **`include/ast_walk.py`** (iterativo, con caché de campos por
clase, compartido con `parser/typed_ast.py`): es la pieza de rendimiento
central del recorrido — cero llamadas a `dataclasses.fields()` por nodo y
cero recursión de Python en los recorridos genéricos. Detalle as-built en
secc. 12–13.

---

## 4. La decisión de diseño central: profundidad de la verificación de memoria

`DESIGN_PRINCIPLES.md` (secc. 5) dice que la verificación de la propiedad
ocurre *"sobre todo"* en el lowering a MIR (C++). Delegar el **100%** de la
responsabilidad al MIR sería contraproducente por tres motivos, y hacer
**todo** el análisis en Python (un solver de flujo de datos completo, con
punto fijo sobre ramas y bucles) sería igual de contraproducente por otros
tres. La decisión adoptada es un **punto intermedio deliberado**, elegido por
rendimiento y por no acoplarse a un sistema de tipos que todavía no existe:

### 4.1 Qué SÍ hace `memory_check.py` (Semántica, Python)

Una pasada **lineal, O(n), de una sola pasada, conservadora e intra-función**:

- Recorre el cuerpo de cada función **una vez**, manteniendo un conjunto
  `moved: set[Symbol]` por scope.
- `move x;` → añade `x` a `moved`. Un uso posterior de `x` en el **mismo
  camino lineal** → `UseAfterMoveError`. Otro `move x;` → `DoubleMoveError`.
- En `if`/`else`, cada rama se analiza con una **copia** de `moved`; al
  cerrar el `if`, el `moved` resultante es la **unión conservadora** de
  ambas ramas (si se movió en *alguna* rama, se trata como movido después —
  nunca al revés). Un `while` se analiza con una sola pasada de su cuerpo
  (no se itera hasta punto fijo).
- Alcance de un valor con dueño: **gratis** a partir del scope de bloque que
  ya construye `scope_resolver.py` — un símbolo vive en el scope donde se
  declara y al cerrarse el scope se descarta como cualquier otro. Ese cierre
  es, además, el punto donde el drop tendrá que invocar el `__free__` del
  tipo: la información de *cuándo muere un valor* ya está en la estructura de
  scopes, no hace falta calcularla.

### 4.2 Qué NO hace (se defiere al MIR lowering, C++)

- Punto fijo sobre bucles (¿se movió `x` en **alguna** iteración anterior?).
- Escapes de región **entre funciones** (una región pasada por puntero a
  otra función que la retiene más allá de su cierre).
- Move condicionado por valor en tiempo de ejecución (fuera del alcance de
  cualquier análisis estático razonable en esta fase).
- **Nunca rechaza un programa válido** (cero falsos positivos): ante duda,
  `memory_check.py` deja pasar y confía en el MIR. Sí puede tener falsos
  **negativos** (dejar pasar algo que el MIR rechazará después) — es
  aceptable y esperado, se documenta como tal en el propio módulo.

### 4.3 Por qué este punto intermedio (rendimiento + futuro sistema de tipos)

1. **Evita trabajo duplicado y desechable.** Un solver de flujo de datos
   con punto fijo (CFG + iteración hasta convergencia) es exactamente lo que
   el MIR en C++ debe hacer de todos modos, **y lo hace mejor**: C++ sin el
   overhead del intérprete de Python, con estructuras de compilador reales.
   Construir esa maquinaria dos veces (una vez "aproximada" en Python, otra
   "definitiva" en C++) es precisamente el riesgo de *"meses reescribiendo"*
   que se quiere evitar: si el diseño del CFG en Python no coincide con el
   que se necesita en C++, se reescribe igual.
2. **Sigue aportando valor real.** La mayoría de errores de un estudiante
   (público objetivo declarado en `DESIGN_PRINCIPLES.md` secc. 1) son
   **lineales y obvios** (usar `x` justo después de moverlo). Detectarlos en
   Python, en la fase que ya se visualiza con `#test sem`, da
   retroalimentación inmediata sin esperar a un pipeline C++ que en Fase 4
   ni siquiera existe todavía.
3. **No se acopla al sistema de tipos aún no diseñado (Fase 3).** El
   chequeo de move/región aquí solo necesita **identidad de símbolos**
   (¿es esta variable la misma que se movió?), no información de tipos fina.
   Es independiente de cómo termine luciendo el *type system* real, así que
   no hay riesgo de reescritura cuando ese sistema llegue. Si en cambio se
   hubiera construido un analizador de flujo acoplado a reglas de tipos
   específicas *ahora*, sería el primer código a tirar cuando el sistema de
   tipos real aterrice.
4. **Costo proporcional al tamaño real del lenguaje hoy.** El modelo de
   memoria son 2 sentencias (`move`, `free`, ver `t_types.md` secc. 7)
   sobre un lenguaje sin genéricos, sin
   herencia y sin closures. Un solver de punto fijo es una inversión de
   ingeniería que **hoy** no tiene suficiente superficie de lenguaje para
   justificarse; si el lenguaje crece (bucles con move complejos, closures),
   esta pasada se puede **ampliar sin romper su interfaz** (sigue siendo "una
   pasada sobre el cuerpo de la función que produce diagnósticos").

### 4.4 Mutación en sitio, igual que `typed_ast.py`

`memory_check.py` no reconstruye nada: añade una anotación `moved_at: Optional[int]`
(número de nodo o posición) a cada `Symbol` cuando corresponde, reutilizando el
mismo principio de rendimiento que la fase AST-tipado (evitar duplicar
estructuras solo para adjuntar un dato).

---

## 5. `type_service.py`: el punto de enganche del futuro sistema de tipos

`DESIGN_PRINCIPLES.md` (secc. 7) es explícito: *"el sistema de tipos no es
una fase, es un servicio"*. Para que la Fase 3 (sistema de tipos, hoy **sin
definir**) no obligue a reescribir `type_resolver.py` ni `scope_resolver.py`,
estos módulos **nunca comparan `Type` a mano**: consultan una interfaz
mínima, implementada de forma simple hoy y **reemplazable** después:

```
TypeService (interfaz, implementación mínima hoy):
    resolve_nominal(name: str, scope: Scope) -> Optional[Symbol]
        # busca 'name' entre los StructDecl/EnumDecl registrados por collect.py

    is_assignable(target: Type, value: Type) -> bool
        # HOY: identidad estructural estricta (Type == Type), sin coerciones.
        # FUTURO (Fase 3): reglas de coerción, genéricos, nullable-unification.

    unify_literal_null(target: Type) -> Type
        # HOY: 'null' es asignable a cualquier NullableType, sin más regla.
        # FUTURO: matiz de nulabilidad más fino si el sistema de tipos lo pide.
```

**Por qué esto importa para el rendimiento y para no perder meses**: el
*costo de una interfaz mal anticipada* es bajo (son 3 funciones puras, sin
estado propio) comparado con el *costo de 200 comparaciones `Type ==`
dispersas por `scope_resolver.py`/`memory_check.py`* que habría que
localizar y reescribir una por una cuando la Fase 3 llegue. Centralizar el
punto de contacto es la misma lógica que ya usa el proyecto para
`error_handler` (un solo lugar, muchos consumidores).

---

## 6. Tabla de símbolos (`symbol_table.py`)

Estructura de datos central, viva durante toda la fase y **persistente**
hacia el HIR (Fase 5, fuera de alcance):

```
SymbolKind: FUNCTION | STRUCT | ENUM | ENUM_ITEM | PARAM | VAR | IMPORT

Symbol:
    name: str
    kind: SymbolKind           # ... | HOOK (ver secc. 12)
    ln: int, col: int          # posición del nodo que lo declaró (para diagnósticos;
                                #   IMPLEMENTADO así, no como 'decl_node: ASTNode' — evita
                                #   que el volcado JSON de '#test sem' incruste el sub-árbol
                                #   completo de cada función detrás de cada símbolo)
    type: Optional[Type]      # desde include/types_ast.py
    mutable: bool             # 'mutable' vs 'const'; N/A para FUNCTION/STRUCT/ENUM
    moved_at: Optional[int]   # anotado por memory_check.py (secc. 4.4)
    hook_kind: Optional[HookKind]   # solo si kind is HOOK (secc. 12)
    hook_owner: Optional[str]       # idem

Scope:
    kind: GLOBAL | FUNCTION | BLOCK
    parent: Optional[Scope]
    types: dict[str, Symbol]   # namespace de TIPOS (struct/enum)
    values: dict[str, Symbol]  # namespace de VALORES (fn/var/param/import)

    define_value(symbol) -> bool   # False si ya existe EN ESTE scope (shadowing
    define_type(symbol)  -> bool   # de un scope padre sí esta permitido)
    resolve_value(name) -> Optional[Symbol]   # camina 'parent' — O(profundidad)
    resolve_type(name)  -> Optional[Symbol]

SymbolTable:
    global_scope: Scope
    hooks: dict[tuple[str, HookKind], Symbol]   # ver secc. 12; namespace propio,
                                                  #  NO vive dentro de 'global_scope.values'
```

**Namespaces separados (`types` vs `values`)**: decisión deliberada, mismo
patrón que C/C++ (un `struct Punto` y una `fn Punto` no colisionan porque
vive cada uno en su propio espacio). Evita comparar contra dos veces más
entradas en cada búsqueda y elimina una clase entera de colisiones
accidentales sin lógica de desambiguación adicional.

**Lookups O(profundidad de scope), no O(símbolos totales)**: cada `Scope` es
un `dict` (O(1) por nivel); resolver un nombre camina como máximo tantos
scopes como bloques anidados tenga el código en ese punto — típicamente una
constante pequeña, nunca proporcional al tamaño del programa.

---

## 7. Responsabilidad de cada archivo

#### `__init__.py` — API pública
`analyze(program: ast.Program) -> tuple[SymbolTable, list]`. Igual que
`parser/__init__.py`: el resto del compilador (HIR) no debe conocer las 4
pasadas internas, solo el resultado.

#### `semantic.py` — Orquestador
Corre las 4 pasadas en orden fijo (secc. 1), pasándoles la misma
`SymbolTable`/`SemanticContext`. Atiende `#test sem`: vuelca la tabla de
símbolos y los diagnósticos acumulados en JSON, reutilizando
[`include/ast_json.py`](../../../include/ast_json.py) (mismo serializador
genérico por reflexión que ya usa el parser — cero código nuevo de
serialización).

#### `context.py` — Estado compartido
`SemanticContext`: scope actual (pila), función actual (para validar
`return <expr>;` contra `return_restype` vía `TypeService`), y
`errors: list` acumulado (mismo patrón que `ParserContext.errors`).

#### `symbol_table.py` — Estructura de datos
`Symbol`, `Scope`, `SymbolTable` (secc. 6). Sin lógica de análisis: solo la
estructura y sus operaciones O(1)/O(profundidad).

#### `type_service.py` — Servicio de tipos
La interfaz de la secc. 5. Implementación mínima hoy (identidad estructural);
punto único de extensión para la Fase 3.

#### `collect.py` — Pasada 1
Recorre `Program.items` (una sola vez, sin recursión a cuerpos de función) y
registra en el scope global: `FunctionDecl`, `StructDecl` (+ sus `Field` en
un scope propio del tipo), `EnumDecl` (+ sus `EnumItem`), `ImportBinding`,
`ImportDirective`, `FromDirective`. Detecta `DuplicateSymbolError` si un
nombre colisiona en el mismo namespace del mismo scope.

#### `type_resolver.py` — `TypeBinder` (colaborador de la pasada 2)
Enlaza cada `Type` que dejó `typed_ast.py` contra el símbolo del tipo, vía
`TypeService`. Ausente → `ASTError.UnknownTypeError` (reutilizado, ver
secc. 2). Ya **no es una pasada**: lo llama `scope_resolver` contra el scope
actual, en el punto exacto en que cada anotación importa (la firma de una
`fn` antes de su cuerpo, el tipo de un `VarDecl` antes de comparar su
inicializador, el destino de un `cast<T>` antes de buscar la conversión).

Su caché de nombres es **por scope**: cuando el recorrido era plano un nombre
resolvía siempre a lo mismo, pero con scopes un tipo local puede sombrear a
uno global y recordar el primero daría el tipo equivocado dentro del bloque.
`scope_resolver._pop_scope()` la invalida al cerrar un scope que declaró
tipos.

#### `scope_resolver.py` — Pasada 2
Recorre el cuerpo de cada `FunctionDecl` (y expresiones a nivel de
`Program.items` si las hay). Empuja un scope `BLOCK` por cada `Block`.
Resuelve `Identifier` (uso), valida
`Assignment.target` contra `Symbol.mutable` (reasignar un `const` →
`SemanticError.ImmutableAssignmentError` — **sin pasada separada**: se
comprueba en el mismo punto donde ya se resuelve el símbolo del target, cero
costo adicional, ver justificación de rendimiento en secc. 4.3 punto 1
aplicada aquí también). Valida aridad de `Call` contra los `Parameter` de la
`FunctionDecl` resuelta.

#### `memory_check.py` — Pasada 4
Ver secc. 4 completa.

---

## 8. Mapeo de nodos del AST → módulo responsable

| Nodo (`include/ast_nodes.py`) | Módulo | Rol |
|---|---|---|
| `Program` | `semantic.py` | orquesta las 4 pasadas |
| `FunctionDecl`, `StructDecl`, `EnumDecl` | `collect.py` | registro en scope global |
| `ImportBinding`, `ImportDirective`, `FromDirective` | `collect.py` | registro como símbolo VALUE opaco (ver secc. 9) |
| `ExternBlock`, `DecoratorDecl` | `collect.py` | registrados sin validación adicional (fuera de alcance, ver secc. 9) |
| `Parameter`, `Field`, `EnumItem` | `collect.py` | registro en el scope de su dueño (función/struct/enum) |
| `PrimitiveTypeExpr`, `NominalTypeExpr`, `PointerTypeExpr`, `NullableTypeExpr` | `type_resolver.py` | enlace nominal vía `TypeService` |
| `Block` | `scope_resolver.py` | push/pop de scope |
| `VarDecl` | `scope_resolver.py` | registro de símbolo local + chequeo de tipo del inicializador (vía `TypeService`) |
| `Identifier` | `scope_resolver.py` | resolución de uso (`UndefinedSymbolError` si no existe) |
| `Assignment` | `scope_resolver.py` | resolución de target + chequeo de mutabilidad |
| `MemberAccess`, `Index`, `Call` | `scope_resolver.py` | resolución de la base / aridad de argumentos |
| `IfStmt`, `WhileStmt`, `MatchStmt`, `CaseArm` | `scope_resolver.py` (scopes) + `memory_check.py` (ramas para `moved`) | ambos, ver secc. 4.1 |
| `ReturnStmt` | `scope_resolver.py` | chequeo contra `return_restype` de la función actual (vía `TypeService`) |
| `BreakStmt`, `ContinueStmt` | — | ya validados por el parser (posición dentro de un bucle); Semántica no repite el chequeo |
| `MoveStmt`, `FreeStmt` | `memory_check.py` | `moved`/uso-tras-move, doble-move |
| `MakeExpr`, `Placement` | `memory_check.py` | asociación a región |
| `SizeofExpr` | `type_resolver.py` | resuelve el `type` interno; sin verificación adicional |
| `Literal`, `InterpolatedString`, `UnaryOp`, `BinaryOp` | `scope_resolver.py` (visita para recursión) | sin lógica propia — el tipo ya viene de `typed_ast.py`/`TypeService` |

---

## 9. Explícitamente fuera de alcance de esta fase

Alineado con `ROADMAP.md` (Fase 4 vs. Fase 9). **Actualización as-built
(secc. 13):** dos puntos que este documento declaraba fuera de alcance se
implementaron después a petición explícita del usuario — la resolución real
de `.libsrx` (secc. 13.2) y los dunder de biblioteca como hooks
(`__print__`/`__len__`, secc. 13.1). Sigue fuera de alcance:

- **Contenido de `#extern cpp{}`**: el C++ crudo no se analiza (es tarea del
  backend C++, `DESIGN_PRINCIPLES.md` secc. 6).
- **`type` (alias de tipos)**: sigue sin sintaxis fijada (igual que en el
  parser); no hay nodo que resolver.
- **Inferencia de tipos real**: el visitor de expresiones de
  `scope_resolver.py` devuelve el tipo solo cuando es gratis conocerlo
  (literales, símbolos anotados, retornos); ante desconocido NUNCA reporta
  error (cero falsos positivos). La inferencia completa es Fase 3.

---

## 10. Cómo cumple modularidad, sostenibilidad y rendimiento

- **Un archivo, una pasada** (o una estructura de datos): igual disciplina
  que `grammar/` en el parser.
- **Cero pasadas redundantes**: 4 recorridos O(n) fijos, ninguno repite el
  trabajo de otro (secc. 1).
- **Punto de enganche único para el sistema de tipos futuro** (`type_service.py`,
  secc. 5): evita el riesgo de reescritura masiva que motivó esta decisión.
- **Verificación de memoria dimensionada al lenguaje actual, no al lenguaje
  imaginado**: secc. 4, con criterio de cuándo ampliarla.
- **Reutilización explícita**: `include/ast_json.py` para el volcado JSON,
  `error_handler/ASTError.py` para diagnósticos de tipos — cero código
  duplicado frente al trabajo ya hecho en la fase Parser.

---

## 11. Orden de implementación sugerido

1. `symbol_table.py` + `context.py` — la base de datos, sin lógica.
2. `collect.py` — primera pasada, verificable de forma aislada (`#test sem`
   ya puede volcar el scope global tras esta pasada).
3. `type_service.py` + `type_resolver.py` — enlace nominal.
4. `scope_resolver.py` — la pasada más grande; cubre la mayoría de
   `SemanticError`/`ASTError` reales.
5. `memory_check.py` — última, depende de que los scopes ya estén resueltos.
6. `semantic.py` + `__init__.py` — orquestador y API pública, igual que se
   hizo con `parser.py` al final en la implementación real del parser.

Cada paso deja la fase en un estado ejecutable y testeable contra
`docs/examples/*.md`, igual que se validó el parser.

---

## 12. Estado de implementación (as-built): métodos "dunder" como *hooks* de tipo

Primera porción implementada de esta fase (a petición explícita del
usuario): **no** las 4 pasadas completas de la secc. 1, sino el soporte de
extremo a extremo para que `__foo__` funcione como *hook* de tipo —
liberación, constructor y tamaño/layout personalizado — atravesando lexer,
AST, parser y esta fase. Motivación del usuario: en `.libsrx` (y también en
`.srcx` — la idea se mantiene en ambas extensiones) escribir un hook es
**opcional**, y quien lo **consume** nunca escribe `__foo__` explícitamente.

### 12.1 Vocabulario y convención de asociación (`hooks.py`)

| Hook | Dispara con | Convención de firma | Se asocia a su tipo por |
|---|---|---|---|
| `__free__` | (futuro: `free x;`, `memory_check.py`) | `fn __free__(T ptr x) -> void` | primer parámetro `ptr T` |
| `__make__` | (futuro: `make T in r`, `memory_check.py`) | `fn __make__(...) -> T ptr` | tipo de **retorno** `ptr T` |
| `__sizeof__` | (futuro: `sizeof(T)`, `type_resolver.py`) | `fn __sizeof__(T ptr x) -> int` | primer parámetro `ptr T` |
| `__cast__` | `cast<T>(x)` (resuelto en `scope_resolver.py` contra la TABLA DE CONVERSIONES) | `fn __cast__(X x) -> T` | registro por PAR `(origen, destino)` en `SymbolTable.casts` — un tipo declara VARIAS conversiones (`int->int8`, `int8->int`, `str->Estado`...); duplicado = mismo par exacto. El "dueño" nominal (retorno con prioridad, si no el primer parámetro) solo identifica al hook en diagnósticos/HIR |

`__make__` es asimétrico a propósito: `__free__`/`__sizeof__` operan
**sobre** una instancia ya existente (primer parámetro). `__make__` era la
excepción —se asociaba por su tipo de retorno, porque cuando se llamaba no
había nada a lo que apuntar—, pero su único disparador era `make T in r`:
se retiró en v0.2.0 con el modelo por regiones, sin haber ejecutado nunca.
Hoy la única excepción es `__cast__`, que se asocia por el lado NOMINAL de su
firma. La reserva "cruda" (`alloc`) tampoco es del lenguaje: la aporta una
librería.

`__print__`/`__len__` (ya usados en `docs/examples/io.libsrx` con **otro**
significado: formato/longitud lógica) se dejaron **fuera** de
`KNOWN_HOOKS` a propósito, para no reinterpretar código ya escrito.

### 12.2 Validación permisiva: lexer no valida nombres (decisión de usuario)

- **Lexer** (`scanners/ident.py`): reconoce la FORMA `__x__` (empieza y
  termina en `__`, ≥1 carácter dentro) para **cualquier** nombre y emite
  `TokenType.DUNDER` (`Token.value` = nombre sin guiones). No valida contra
  una lista cerrada — a diferencia de `DIRECTIVES` en `c_dir.py`. Añadir un
  hook nuevo a futuro solo toca `hooks.py`.
- **Parser** (`grammar/functions.py`): acepta `DUNDER` además de
  `IDENTIFIER` como nombre de `fn`; transporta el hecho estructural
  (`FunctionDecl.dunder: Optional[str]`, el nombre sin guiones) sin juzgar
  si es un hook reconocido.
- **Semántica** (`hooks.py::classify_hook`): único lugar que decide qué
  nombres son hooks. Un `__foo__` no reconocido (p. ej. `__print__`,
  `__len__`, o cualquier otro) se **ignora silenciosamente** — sigue siendo
  una función normal. Cero errores por convención no usada: coherente con
  "escribir un dunder no es obligatorio".

### 12.3 Registro de hooks: namespace propio, no dentro de `global_scope`

Un hook está **sobrecargado por tipo dueño** (`__free__` puede existir una
vez por cada `struct`/`enum` distinto) — no encaja en `Scope.values`
(namespace plano de una sola entrada por nombre). Se añadió
`SymbolTable.hooks: dict[(str, HookKind, str), Symbol]`, con su propia
detección de colisión: **mismo** tipo + mismo `HookKind` →
`DuplicateHookError`; mismo `HookKind` en **tipos distintos** → coexisten sin
conflicto (probado: `__free__(Punto ptr)` y `__free__(Texto ptr)` a la vez,
dos entradas).

El dueño es el nombre **canónico** del tipo, calificado con su unidad
(`a.Node`), no el nombre corto. Es lo que hace que "tipos distintos" incluya
el caso de dos librerías que declaran un `Node` cada una: con el nombre
corto compartían entrada y el hook que corría lo decidía el orden de carga,
en silencio. Ver `linker_p/readme.md`, *Identidad de un tipo*.

Por lo mismo, un hook cuyo dueño pertenece a **otra unidad** se rechaza
(`SEM006`): la tabla de despacho es una sola, y dos librerías extendiendo el
mismo tipo ajeno volverían a dejar la elección al orden de carga.

### 12.4 Errores nuevos (`error_handler/SemanticError.py`, creado en esta
misma entrega junto con el resto de la taxonomía prevista en la secc. 2)

- `SEM006 InvalidHookSignatureError`: el nombre es un hook reconocido pero
  la firma no encaja (p. ej. `__free__` sin parámetros, `__make__` que no
  devuelve `ptr T`).
- `SEM007 DuplicateHookError`: ya existe un hook del mismo tipo para el
  mismo dueño.

### 12.5 `#test sem`

Añadido a `Parser.run_test_directive` (`parser/parser.py`) igual que
`lexer`/`parser`/`ast`, con una diferencia deliberada: el import de
`semantic` es **diferido** (dentro del método, no al tope del módulo) para
que el paquete `parser` no dependa de `semantic` en tiempo de carga — son
fases separadas; la dependencia es solo de esta directiva de depuración.
Vuelca `SymbolTable.hooks` en JSON vía `symbol_table.to_debug_dict` (las
claves tupla no son válidas como clave JSON directa, se proyectan a lista) +
`include/ast_json.py` (mismo serializador genérico ya usado por
`parser`/`ast`, cero código de serialización nuevo).

### 12.6 Validado contra

- `docs/examples/io.libsrx`: `__print__`/`__len__` no generan hooks ni
  errores (0 hooks, 0 errores) — confirma que la convención existente sigue
  intacta.
- 3 hooks válidos (`__free__`/`__make__`/`__sizeof__`) sobre un mismo
  `struct`: registrados correctamente con su `hook_owner`.
- Firma inválida (`__free__` sin parámetros; `__make__` sin retornar
  `ptr T`): `SEM006` en ambos casos, sin registrar el hook.
- Duplicado (`__free__` dos veces para el mismo tipo): `SEM007`, se
  conserva el primero.
- Dos structs con el mismo `HookKind` (`__free__`): ambos registrados, sin
  colisión falsa.
- `__foo__` no reconocido (p. ej. `__banana__`): 0 hooks, 0 errores.
- Regresión completa de la suite de la fase Parser (todos los ejemplos de
  `docs/examples/*.md`, `docs/syntax.md`, stress test de rendimiento):
  sigue en verde, sin cambios de comportamiento fuera de lo descrito aquí.

---

## 13. Estado de implementación (as-built, 2ª entrega): fase completa

Segunda porción implementada (a petición explícita del usuario): las **4
pasadas completas** de la secc. 1 más tres extensiones decididas en esa
conversación. La secc. 12 se conserva como registro histórico; donde
contradiga a esta sección, vale esta.

### 13.1 Hooks: vocabulario ampliado y firma completa

- `__print__` y `__len__` se **promovieron** a hooks reconocidos (revierte
  la decisión de la secc. 12.1 de dejarlos fuera — decisión de usuario).
  Vocabulario completo en `hooks.py::HOOK_SPECS`:
  `__free__(T ptr)->void`, `__make__(...)->T ptr`, `__sizeof__(T ptr)->int`,
  `__print__(T ptr)->void`, `__len__(T ptr)->int`.
- La validación ahora es de **firma completa** (`hooks.validate_hook`):
  número exacto de parámetros Y tipo de retorno (antes `__free__` sin
  retorno `void` pasaba sin queja). `SEM006` con mensaje específico.
- **Despacho enlazado en el AST** (anotación `.hook` en el nodo, mismo
  patrón mutable-en-sitio que `restype`; viaja al HIR como `HookRef`, ver
  `HIR/PROTOBUF_BRIDGE.md`):

  | Dispara | Nodo anotado | Pasada |
  |---|---|---|
  | `free x;` | `FreeStmt.hook` | 3 (`scope_resolver`) |
  | `make T in r` | `MakeExpr.hook` | 3 (`scope_resolver`) |
  | `sizeof(T)` | `SizeofExpr.hook` | 2 (`type_resolver`) |
  | `print(x)` / `x.print()` | `Call.hook` | 3 (`scope_resolver`) |
  | `len(x)` / `x.len()` | `Call.hook` | 3 (`scope_resolver`) |

  **Desviación deliberada de la secc. 8**: el despacho de `__free__` se
  hace en `scope_resolver` (donde el tipo del target ya está resuelto), no
  en `memory_check` — mismo argumento de costo cero que la mutabilidad
  (secc. 4.3.1). `memory_check` queda puro: solo identidad de símbolos.
  `print`/`len` NO son keywords: si el nombre resuelve a una función
  declarada, esa gana; el hook solo aplica cuando no hay símbolo y el tipo
  del primer argumento se conoce (tipo desconocido → pasa en silencio).

### 13.2 Resolución real de `.libsrx` (`src/linker_p/`, adelanto de Fase 9)

> **Dónde vive**: empezó como `semantic/libsrx.py` y hoy es el paquete
> `V0/src/linker_p/` — el *linker de librerías nativas*, separado de esta
> fase (`resolver` → `loader` → `packages` + `cache`). La Semántica lo
> consume desde `collect.define_import`; el contrato no cambió. Ver
> [`src/linker_p/readme.md`](../../linker_p/readme.md).

Decisión de usuario (revierte la secc. 9 original): `#import IO` carga de
verdad la librería. Búsqueda: dir del fuente → `libraries.libsrx_paths` de
la config (nombre exacto y minúsculas). Pipeline completo (lexer→parser→
tipos→collect) **una vez por archivo** — caché por ruta absoluta a nivel de
proceso, con guard de imports circulares. Contrato validado: el archivo
debe TERMINAR en `#export <alias>` y el alias debe coincidir con el nombre
importado. Los exports viajan en `Symbol.members` del símbolo IMPORT
(`IO.printf` se valida: existencia `SEM011` + aridad `SEM008`); los hooks
de la librería se **fusionan** en la tabla del consumidor (`print(x)` sobre
un tipo de la librería despacha). Los tipos de la librería NO se vuelcan al
namespace global del consumidor (viven detrás del alias — evita colisiones
entre librerías). Si la carga falla, el símbolo queda *opaco* (como la
secc. 9 original) para no producir cascadas de `SEM001`. Errores nuevos:
`SEM009` (no encontrada), `SEM010` (inválida/sin `#export`/errores internos),
`SEM011` (miembro no exportado). Reimportar la misma librería bajo el mismo
nombre es **idempotente** (los ejemplos de la documentación muestran las
formas `const IO = #import IO;` y `#import IO;` juntas).

### 13.3 Decisiones tomadas durante la implementación de las 4 pasadas

- **Items de enum "pelados"** (modelo C): `collect` registra cada
  `EnumItem` también en el namespace de VALORES del scope global —
  `return Origen;` y `case Origen:` resuelven sin prefijo (es la forma de
  todos los ejemplos reales). Dos enums con un item homónimo colisionan
  (`SEM002`), documentado y deliberado.
- **Variables globales** se registran en la pasada 1 (no solo fn/struct/
  enum): un cuerpo puede usar una global declarada más abajo. La pasada 3
  valida su inicializador sin redefinirlas.
- **`memory_check` con identidad por nombre + "revivir"**: re-declarar
  (`int x = ...;`) o reasignar (`x = ...;`) un nombre lo saca del conjunto
  `moved` — elimina los falsos positivos por shadowing sin reconstruir
  scopes. La pasada 3 publica `ctx.fn_locals` (nombre→Symbol por función)
  para que la 4 anote `Symbol.moved_at` sin resolver nada de nuevo.
- **`return` validado** contra `return_restype` (AST012), asignaciones e
  inicializadores contra `type_service.is_assignable` (AST006), `null`
  contra nullable (`unify_literal_null`). `BinaryOp` aritmético entre tipos
  distintos conocidos → AST006 (tipado fuerte, sin coerciones).
- **Aridad de llamadas** (`SEM008`): se valida cuando el callee resuelve a
  una función con `param_types` conocidos (declaradas o exportadas por una
  librería). La compatibilidad de tipos argumento-a-parámetro queda para la
  Fase 3 (vía `type_service`, sin tocar llamadores).

### 13.4 Validado contra (2ª entrega)

- **Todos** los bloques ```srcx de `docs/examples/*.md` y `docs/syntax.md`
  por `#test parser`/`ast`/`sem`: 0 regresiones de sintaxis, 0 diagnósticos
  semánticos falsos (los fragmentos que dependen de un bloque anterior se
  validaron combinados).
- 13 clases de error disparadas cada una en su punto exacto (SEM001–SEM012
  + AST005/AST006/AST012) en un archivo negativo dedicado.
- Los 5 hooks despachan y quedan anotados en el AST (verificado sobre el
  volcado `--emit-ast-json`).
- Escalado **lineal** del pipeline completo (lexer→sem): 3.4k/6.8k/13.6k/
  27.2k líneas → 0.27/0.63/0.76/1.47 s (incluye arranque de Python).
- Adversarial: 2000 paréntesis anidados, 300 `if` anidados, 500 binops
  encadenados, recuperación de errores con basura — sin crash, sin timeout,
  <0.2 s cada uno.

---

## 14. Estado de implementación (as-built): memoria, paquetes y salidas

### 14.1 Cambio de modelo de declaración (decisión de usuario)

- `var int x = 10;` / `const int x = 10;`; **sin cualificador = `var`**
  (estilo C). `mutable` YA NO califica variables: `mutable int x` es un
  ParseError dirigido que sugiere `var`.
- `mutable` quedó para los PUNTEROS: `ptr T` es solo lectura a través del
  puntero; `ptr mutable T` permite escribir a través de él
  (const-correctness estilo C). `Type` ganó el campo `mut` (participa de la
  igualdad); la coerción segura `ptr mutable T -> ptr T` vive SOLO en
  `type_service.is_assignable`. `&x` hereda la mutabilidad del binding
  (`var` -> `ptr mutable`, `const` -> `ptr`).

### 14.2 Punteros y memoria básica

Checks nuevos, todos en el punto donde el símbolo/tipo ya está resuelto
(costo cero adicional):

- `SEM013 InvalidAddressOfError`: `&(expr)` sobre un no-lvalue.
- `SEM014 InvalidFreeTargetError`: `free x;` con `x` que no es `ptr T`.
- `SEM015 ReadOnlyPointerWriteError`: `p.campo = v` / `p[i] = v` a través
  de un `ptr T` sin `mutable`.
- `SEM016 InvalidCastError`: `cast<T>(x)` sin conversión definida — ni
  identidad, ni par nativo entre primitivos (`int`↔`float`, `int`↔`char`,
  `bool`→`int`), ni entrada `(origen, destino)` en la tabla de conversiones
  (`SymbolTable.casts`). El mensaje lista las conversiones declaradas que
  tocan alguno de los dos tipos. El encadenamiento es explícito:
  `cast<vec>(cast<Estado>(s))` — nunca se buscan caminos intermedios.
- Todos permisivos ante tipo desconocido (cero falsos positivos).

### 14.3 Paquetes `.libsrx` (anti-polución de namespaces)

`src/linker_p/packages.py` resuelve carpetas-paquete: padre `main.libsrx`
(o `<carpeta>.libsrx`) con `#export package as <alias>`; cada otro `.libsrx`
de la carpeta es un submódulo (su `#export` da el nombre). **Regla central:
un módulo se llama como su alias, no como su archivo ni como su carpeta** —
el nombre de archivo solo localiza en disco.
`#from IO.print #import __print__` /
`#import IO.print` / `#import IO` (nombres punteados en `#import`/`#from`,
un nivel de anidamiento). Un nombre punteado solo lo satisface un paquete
(los archivos planos homónimos no lo bloquean); a la inversa, un archivo
plano gana sobre un paquete homónimo en un import NO punteado (orden de
búsqueda documentado). `.srcx` como librería se permite con **NOTA**
(`ctx.notes` -> `log/notes.jsonl`).

### 14.4 Rutas y salidas (fix de la búsqueda "extraña")

Causa raíz: la config fallaba en silencio sin `pyyaml` y las rutas
relativas se resolvían contra el CWD del proceso. Ahora: el
`.suriaX_config.yaml` se busca HACIA ARRIBA desde el dir del fuente y su
ubicación define la raíz del proyecto; TODA ruta relativa (libsrx_paths,
dumps, log, cache) se ancla ahí (sin yaml instalado, encontrar el archivo
sigue anclando la raíz). El antiguo `V0/compilerconfig.py` se dividió en el
paquete `config/` de la raíz (dependencies / yaml_config / logs / dumps /
cache + orquestador); el frontend NO lo importa — `V0/main.py` es el único
puente (incluye el canal `ctx.notes` de esta fase hacia `log/notes.jsonl`).

### 14.5 Validado contra (3ª entrega)

- Regresión completa de bloques ```srcx de `docs/` (0 fallos; los
  fragmentos y el ejemplo de paquetes validados en su entorno propio).
- 15 clases de error disparadas en su punto exacto (SEM002–SEM015,
  AST005/006/012) + NOTA001.
- Paquete `io/` real: `#from io.string #import printf`, `#import io.string`,
  `#import io` (miembros anidados validados), `.srcx` como lib con NOTA,
  compilación desde CWD ajeno con rutas correctas.
- Rendimiento SIN regresión: 27.2k líneas -> 1.17 s (lexer 40% / parser
  33% / semántica 18% / tipado 9%), idéntico al baseline previo a los
  checks nuevos; adversariales controlados <0.2 s.

---

## 15. Estado de implementación (as-built, 4ª entrega): reservas, hook/dunder y regiones

### 15.1 hook/dunder guiados por el especificador (no por la forma)

`collect._collect_function` ya **no** clasifica un hook por
`fn.dunder in HOOK_SPECS`, sino por `fn.specifier == "hook"` (decisión de
usuario: el compilador ya no adivina). Consecuencias, con la **lógica de hooks
intacta** (validación de firma, registro por `(owner, kind)`, tabla de casts,
despacho de `free`/`make`/`sizeof`/`print`/`len`/`cast`):

 - `hook fn __x__`: si `__x__` **no** está en `HOOK_SPECS` → `SEM018`
   (`UnknownHookError`); antes un `__foo__` desconocido se ignoraba en
   silencio. Si está, se valida la firma y se registra igual que antes.
 - `dunder fn __x__`: se registra como **función normal** (sin significado
   especial aún — decisión de usuario); no valida firma ni despacha.
 - `fn __x__` (sin especificador): función normal, aunque tenga forma `__x__`.

### 15.2 Reservas de visibilidad (`public`/`private`/`internal`)

`Symbol` ganó `visibility`; `collect` lo copia desde el AST a cada símbolo
top-level (fn/hook/struct/enum/type/global-var/import). El **enforcement** vive
en el linker (frontera real entre archivos):

 - **`internal`** se filtra en el ORIGEN (`linker_p/loader._without_internal`):
   nunca entra a `LoadedLibrary.values/types`, así que ningún consumidor lo ve
   (acceso → `SEM011`, "no exporta"). Correcto y sin ambigüedad.
 - **`private`** viaja en el export pero `collect.define_import` lo filtra según
   `_same_package(consumidor, librería)` — modelo simple coherente con
   `packages.py` (un paquete es una carpeta: mismo directorio o el consumidor
   dentro de la carpeta del paquete). Mismo paquete → visible; otro paquete →
   oculto (`all_members` filtrado; en `#from ... #import priv` → `SEM019`
   `VisibilityViolationError`, diagnóstico específico en vez del genérico).
 - **`public`/`None`**: siempre visible.

Dentro del propio archivo no hay filtro (todo es visible): la visibilidad es una
regla de FRONTERA, no de scope local.

### 15.3 Memoria — retirada del modelo por regiones (v0.2.0)

Lo que esta sección describía —`scope_resolver` resolviendo `RegionStmt`,
`NewStmt`, `DeleteStmt`, `InRegionStmt` y `MoveRegionStmt`, con `Symbol` de
kind `REGION` cargando `shared`/`region_mutable`/`region_na` hacia el HIR— se
retiró entero. El razonamiento está en
`documentation/source/memory_decision.rst`; el resumen es que las regiones
ocupaban el 16 % del vocabulario reservado del lenguaje y empujaban hacia los
hooks intrínsecos y los traits, y que su seguridad dependía de un análisis de
escape que exigía un sistema de tipos que nunca se definió.

Lo que la Semántica hace hoy con la memoria:

 - `MoveStmt`: `memory_check` (pasada 3) lo rastrea de forma lineal e
   intra-función — uso tras move (`SEM004`), doble move (`SEM005`).
 - `FreeStmt`: `scope_resolver` valida que el objetivo sea un puntero
   (`SEM014`) y enlaza el `__free__` del tipo apuntado.
 - `FreeStmt` en `memory_check`: `free` TERMINA una propiedad igual que
   `move`, así que las rastrea la misma pasada, con un solo conjunto de rutas
   muertas y el MOTIVO guardado. El motivo —no la operación— decide el
   diagnóstico: `SEM023` (uso tras free), `SEM024` (doble free), y liberar
   algo ya movido es `SEM004`, porque el problema no es liberarlo dos veces
   sino que ya no es tuyo.
 - `type_service.owns_resources(t, scope, table)`: qué tipos tienen una
   obligación de destrucción. Vive en el servicio de tipos, no en una pasada,
   porque es una pregunta SOBRE EL TIPO y la consultarán varias etapas. Tres
   reglas: lo declara (`__free__`), lo contiene (campo por valor, transitivo),
   y un `ptr` no (es un préstamo) — esta última es además lo que hace terminar
   la recursión, porque los tipos recursivos se cierran por puntero.
 - **Drop automático** (`scope_resolver._anotar_drops`): al cerrar cada scope,
   con el scope TODAVÍA ABIERTO, se anota en el `ast.Block` qué locales mueren
   ahí. Se hace en este punto por dos razones: el scope ES la lista de locales
   del bloque en orden de declaración, y es el último momento en que un tipo
   declarado dentro del bloque (`const type T;`) todavía resuelve — después de
   esta pasada los scopes se descartan y la pregunta ya no se puede hacer.
   El orden es inverso al de declaración. Los `PARAM` no entran: no los posee
   este ámbito.
 - El reparto con el runtime es la decisión de diseño: la lista es ESTÁTICA
   (qué puede necesitar destruirse lo dice el tipo) pero el drop NO es
   incondicional (si hace falta lo dice el estado de la celda, en ejecución).
   Eso es lo que hace que un `move` dentro de un `if` salga correcto sin punto
   fijo ni drop flags — el bit que haría falta ya existía.
 - **Temporales** (`Call.temp_drop` / `StructLiteral.temp_drop`): una llamada
   o un literal PRODUCEN un valor; si posee recursos y nadie se queda con él,
   no hay ningún ámbito que lo alcance. Se marca en `visit_expr` —el único
   punto por el que pasan todas las expresiones— y las cuatro posiciones que
   SÍ le dan dueño lo desmarcan: inicializador de `var`, lado derecho de una
   asignación, valor de `return` y **campo de un literal que lo envuelve**.
   Marcar de más y quitar es más seguro que enumerar dónde marcar (si aparece
   una posición nueva se destruye de más, no de menos), y por eso el
   desmarcado se prueba en vez de fiarse.
 - `_aplanar_drops` traduce "este valor posee" a destrucciones CONCRETAS: si
   el tipo declara `__free__`, ESE destructor se hace cargo de todo lo suyo y
   no se baja más; si no lo declara, se baja a sus campos que sí poseen, en
   rutas aplanadas (`e.c.b`). La recursión termina porque `owns_resources`
   solo es cierto si en algún punto del árbol POR VALOR hay un `__free__`, y
   los punteros —por donde se cierran los tipos recursivos— no poseen.

Diagnósticos retirados con el modelo, por quedarse sin productor: `SEM012`
(`UndefinedRegionError`), `SEM020` (`InvalidDeleteError`) y `PAR022`
(`InvalidRegionDeclarationError`).

Errores que esta entrega sí dejó: `SEM018` (`UnknownHookError`) y `SEM019`
(`VisibilityViolationError`).

### 15.4 Validado contra (4ª entrega)

Suite completa **281/281 verde** (tras migrar las fixtures y las `.libsrx`
reales —`io/stdp`, `d_types/dt_variables`— a `hook fn`, y regenerar los golden
por los campos aditivos de `Symbol`). `#test sem`: hook válido registra, `hook
fn __banana__` → `SEM018`, `delete()` fuera de región → `SEM020`, región
inexistente → `SEM012`. Enforcement e2e: `internal` oculto a un consumidor
(`SEM011`), `private` visible en el mismo paquete. El emisor HIR rechaza los
nodos de región nuevos con `HIR005` (sin crash).

---

## 16. Estado de implementación (as-built, 5ª entrega): dunders del usuario y traits

### 16.1 Dunders indexados por tipo — "hooks del usuario"

Cambio de modelo (decisión de usuario): un `dunder fn __x__(T ptr self, ...)`
ya **no** es una función global plana (colisionaba si dos tipos tenían
`__next__`). Se registra en `SymbolTable.dunders[(owner, __x__)]` — igual que
los hooks pero con **nombre abierto** —, con `owner` = nominal del primer
parámetro (`collect._collect_dunder`). Sin receptor nominal → `SEM022`
(`InvalidDunderSignatureError`). Se despacha con `x.__x__()`
(`scope_resolver._call_member`, anota `Call.hook`). `SymbolKind.DUNDER` es
solo-frontend (nunca se emite al HIR). La **ejecución** en runtime de dunders
del usuario está **diferida**: el frontend resuelve y
anota; el HIR emite una `HookRef` parcial (owner sin kind) que el runtime
completará.

### 16.2 Traits — contratos verificados, no cableados

`semantic/traits.py`: un `@trait` registra en `SymbolTable.traits[nombre]` una
tupla de `TraitSig` (nombre de método, tipos de parámetro con `SELF_TYPE`,
retorno). Un `@impl(trait)` sobre un struct se verifica **después** de
recolectar todo (dunders y traits en cualquier orden): por cada método del
trait se sustituye `self` -> el tipo que implementa (`subst_self`, recursivo
por `ptr`/`?`/`error`) y se compara la **firma completa** contra el dunder
`(tipo, nombre)`. Falta de método, firma que no coincide o trait no declarado
-> `SEM021` (`TraitNotSatisfiedError`). Los métodos de un trait deben tener
nombre dunder. **Filosofía**: el vocabulario de contratos (`iterable`,
`sumable`...) lo define el usuario; el compilador solo verifica — se extiende
el ecosistema sin tocar el compilador (mismo principio que los hooks, pero
abierto).

### 16.3 Validado contra (5ª entrega)

Suite **358/358 verde** (golden de símbolos regenerado por los campos aditivos
`dunders`/`traits`). `#test sem`: trait + dunder + `@impl` válido → 0 errores;
casos negativos disparan `SEM021` (método faltante / firma / trait
desconocido) y `SEM022` (dunder sin dueño) en su punto exacto.
