# Arquitectura del Parser de suriaX

> Documento de diseño. **No** contiene código: define la estructura de
> carpetas/archivos propuesta, la responsabilidad de cada módulo y el mapeo de
> **todos** los tokens a su módulo responsable. Objetivo rector: **modularidad y
> sostenibilidad** — un archivo, una responsabilidad; un token, un dueño claro.

---

## 1. Estrategia de análisis

El parser es **híbrido**, la combinación estándar para lenguajes con expresiones
ricas y estructura estática:

| Capa | Técnica | Alcance |
|------|---------|---------|
| **Sentencias / declaraciones** | Descenso recursivo **LL(k) predictivo** | Estructura del programa: `fn`, `struct`, `if`, `while`, `region`, directivas… |
| **Expresiones** | **Pratt** (TDOP / precedence-climbing) | Operadores con precedencia y asociatividad: `+ - * /`, comparaciones, `and/or`, llamadas, acceso, indexado… |

### Decisión de rendimiento: `k` fija, sin backtracking

Se adopta **LL(k) predictivo con `k` acotada (k ≤ 2) y sin backtracking**:

- El dispatch de cada regla se resuelve mirando a lo sumo 1–2 tokens contra
  **tablas FIRST precomputadas O(1)** (mismo principio que la tabla `KEYWORDS`
  del lexer: se construyen una vez al importar, no por token en caliente).
- Se **descarta** el backtracking especulativo: reparsear tokens es trabajo
  desperdiciado y rompe la linealidad. Las colisiones aparentes (p. ej.
  distinguir una anotación de tipo de una expresión, o `make T in r` de una
  llamada) se resuelven con lookahead acotado + tablas de decisión, **no**
  reintentando.
- Resultado: coste **lineal** en el número de tokens. Esto es deliberado: una
  implementación vaga aquí se paga cara en HIR/MIR aguas abajo.

> Regla de diseño de la gramática: cada punto de decisión debe ser predecible
> con ≤2 tokens de lookahead. Si una construcción futura lo exige, se refactoriza
> la gramática (o se introduce un token/keyword desambiguador en el lexer) antes
> que caer en backtracking.

---

## 2. Contexto: qué ya existe y no se duplica

- **Tokens y tipos** → [`include/t_types.py`](../../../include/t_types.py):
  `TokenType`, `Token`, `StringValue`/`Interp`, tablas `KEYWORDS`/`DIRECTIVES`.
- **Nodos del AST** → [`include/ast_nodes.py`](../../../include/ast_nodes.py).
  **Decisión tomada:** el AST permanece como contrato compartido en `include/`
  (junto a `t_types`); el parser lo **importa** y construye instancias
  directamente. El parser *no* redefine ni re-empaqueta nodos.
- **Errores** → [`error_handler/ParseError.py`](../../../error_handler/ParseError.py):
  taxonomía completa `PAR000`–`PAR024` (sintaxis, tipos, funciones, `match`,
  memoria/regiones, directivas, `extern`…). El parser **lanza** estos errores;
  no crea clases nuevas salvo que aparezca una categoría no cubierta.
- **Patrón de referencia** → el **lexer**
  ([`lexer/lexer.py`](../lexer/lexer.py) + [`lexer/scanners/`](../lexer/scanners/)):
  orquestador padre con estado compartido + subpaquete con un archivo por clase.
  El parser replica exactamente esta filosofía.

---

## 3. Árbol de carpetas/archivos propuesto

```
V0/src/frontend/parser/
├── ARQUITECTURA.md          # este documento
├── __init__.py              # API pública del paquete (parse(tokens) -> AST)
│
├── parser.py                # ORQUESTADOR padre (ya existe: se reencuadra)
├── cursor.py                # Primitivas de cursor sobre list[Token] (+ expect_name)
├── context.py               # Estado sintáctico compartido durante el parseo
├── recovery.py              # Recuperación de errores (modo pánico consciente de
│                            #   profundidad de llaves — ver secc. 9.7; el
│                            #   'firstsets.py' original se eliminó, sin consumidores)
│
├── pratt.py                 # MOTOR Pratt (algoritmo de precedencia)
├── precedence.py            # Fuente única de binding power + asociatividad
│
├── expressions/             # Capa Pratt: handlers por rol del token
│   ├── __init__.py
│   ├── registry.py          # TokenType -> (nud, led) enlazado a precedence
│   ├── nud.py               # Null denotation: átomos y operadores prefijos
│   └── led.py               # Left denotation: operadores infijos y postfijos
│
└── grammar/                 # Capa LL(k): descenso recursivo por dominio
    ├── __init__.py
    ├── program.py           # Punto de entrada gramatical (items top-level)
    ├── declarations.py      # const/mutable, fn, struct, enum, type
    ├── statements.py        # bloques, expr-stmt, asignación, return
    ├── control_flow.py      # if/else, while, match/case, break/continue
    ├── memory.py            # region, in/at, move, make/free, ptr, &, ?
    ├── types.py             # anotaciones de tipo
    ├── patterns.py          # patrones de match/case
    └── directives.py        # #import/#export/#extern/#test/#from, RAW_BLOCK
```

---

## 4. Responsabilidad de cada archivo

### Núcleo (raíz del paquete)

#### `__init__.py` — API pública
Expone la única función que el resto del compilador consume:
`parse(tokens: list[Token]) -> ASTNode`. Oculta la estructura interna: `main.py`
y fases posteriores no deben conocer `pratt`, `grammar` ni `cursor`.

#### `parser.py` — Orquestador padre
El equivalente a `lexer.py`. **No** contiene reglas gramaticales: coordina.
- Construye el `Cursor` y el `Context` a partir de la `list[Token]`.
- Atiende las **directivas de prueba** ya implementadas (`#test lexer`) y su
  volcado de tokens (código actual conservado).
- Llama al punto de entrada gramatical (`grammar/program.py`) y devuelve el AST.
- Acumula errores recuperados y decide el corte final (fail-fast vs. reporte
  agregado, igual que `Lexer.errors`).

#### `cursor.py` — Primitivas de cursor
Extrae de `parser.py` el cursor puro sobre `list[Token]`:
`peek(offset)`, `advance`, `check`, `match`, `expect`, y `expect_name`
(`IDENTIFIER` **o** `DUNDER` — ver secc. 9.7: usar `expect(IDENTIFIER)`
directo en una posición de nombre fue la causa de un bug real). Punto
**único** de acceso a la secuencia de tokens; todas las capas (Pratt y
LL(k)) dependen de él. Aislar el cursor permite optimizarlo (índices,
`__slots__`) sin tocar la gramática.

#### `context.py` — Estado sintáctico
Estado **puramente sintáctico** que las reglas comparten sin pasarse mil
argumentos:
- profundidad de bucle (para validar la *posición* de `break`/`continue`);
- si se está dentro de un cuerpo de `region` / firma de `fn` / cuerpo de `match`;
- modificadores/decoradores pendientes acumulados antes de una declaración
  (`@deco`, `const`, `mutable`).

> Frontera clara: aquí solo vive contexto **sintáctico**. La validación semántica
> profunda (propiedad/lifetimes de regiones, resolución de nombres, chequeo de
> tipos) pertenece a la fase de semántica, no al parser.

#### `recovery.py` — Recuperación de errores
**Rediseñado tras la revisión de calidad (secc. 9.7); la propuesta original
de esta sección (tablas `firstsets.py` con conjuntos FIRST/SYNC) se abandonó
por un bug real que encontró y explica esa sección.** Estrategia de **modo
pánico consciente de profundidad de llaves**: ante un `ParseError`, rebobina
al inicio del item de nivel superior que falló y descarta ese item
**completo** contando anidamiento de `{`/`}` desde cero, para reportar un
diagnóstico por error real en vez de una cascada. Centralizar la
recuperación evita esparcir lógica de "saltar hasta `;`" por toda la
gramática.

### Capa de expresiones (Pratt)

#### `pratt.py` — Motor Pratt
El **algoritmo**, agnóstico de operadores concretos: el bucle
`parse_expression(min_bp)` que pide un `nud` (denotación nula) al token actual y
luego encadena `led`s (denotación izquierda) mientras el binding power lo
permita. No conoce tokens específicos: los obtiene de `expressions/registry.py`.

#### `precedence.py` — Binding power y asociatividad
**Fuente única de verdad** de la precedencia: a qué binding power liga cada
operador y su asociatividad (izq./der.; p. ej. `=` es derecha, los aritméticos
izquierda). Aislarlo permite ajustar/expandir la tabla de precedencia en un solo
lugar sin tocar los handlers.

#### `expressions/registry.py` — Tablas de dispatch
Mapea `TokenType -> (nud_handler, led_handler)` y enlaza cada operador con su
binding power de `precedence.py`. Es la "tabla de despacho" que consulta
`pratt.py`. Registrar un operador nuevo = una entrada aquí (extensibilidad).

#### `expressions/nud.py` — Null denotation (prefijos / átomos)
Handlers para tokens que **abren** una expresión sin operando izquierdo:
- literales (`INT_LIT`, `FLOAT_LIT`, `STRING_LIT` con interpolación, `CHAR_LIT`,
  `TRUE`, `FALSE`, `NULL`), `IDENTIFIER`, `DUNDER`;
- prefijos: unario `+`/`-`, `not`, `&` (address-of), `move`, `ptr`;
- agrupación `( … )`; `sizeof`; llamada a la función nativa `test`.

#### `expressions/led.py` — Left denotation (infijos / postfijos)
Handlers para tokens que **continúan** una expresión con un operando izquierdo:
- binarios aritméticos (`+ - * /`) y de comparación (`== != < <= > >=`);
- lógicos `and`/`or`;
- asignación `=` (asociativa a derecha);
- llamada `f(...)` (`L_PAREN` como infijo), indexado `a[i]` (`L_BRACKET`),
  acceso a miembro `a.b` (`DOT`), postfijo nullable `?`.

### Capa de sentencias/declaraciones (LL(k))

#### `grammar/program.py` — Punto de entrada gramatical
Regla raíz: itera los **items top-level** hasta `EOF`, despachando por FIRST
hacia declaraciones, directivas o decoradores. Devuelve el nodo raíz del AST.

#### `grammar/declarations.py` — Declaraciones
Bindings (`const`/`mutable`), funciones (`fn`, firma con `->` y tipo de retorno),
`struct`, `enum` y `type`. Emite `PAR016`/`PAR017` ante firmas o cuerpos mal
formados. Consume los modificadores/decoradores pendientes de `context.py`.

#### `grammar/statements.py` — Sentencias
Bloques `{ … }`, sentencia-expresión (delega en `pratt.py`), asignaciones a nivel
de sentencia, `return`, y el terminador `;` (`PAR004`). Es el despachador de
sentencias dentro de un bloque.

#### `grammar/control_flow.py` — Control de flujo
`if`/`else`, `while`, `match`/`case`, `break`, `continue`. Coordina con
`patterns.py` para las ramas de `match` (`PAR018`) y con `context.py` para la
posición válida de `break`/`continue`.

#### `grammar/memory.py` — Modelo de memoria
Modelo *region-based + move-semantics*: declaración de `region`, asociación
`in`/`at`, `move`, `make`/`free`, `ptr`, `&`, `?`. Define la **forma
sintáctica**; la validación de propiedad/lifetimes es semántica.
Emite `PAR021`/`PAR022`.

#### `grammar/types.py` — Anotaciones de tipo
Analiza posiciones de tipo (`name: T`, retorno `-> T`, campos de `struct`):
tipos primitivos (`int float char str bool void`), nominales (`IDENTIFIER`),
`ptr T`, `T?` (nullable), tipo de función. Exige la anotación donde el lenguaje
la requiere (`PAR023`). Es reutilizado por declaraciones, memoria y patrones.

#### `grammar/patterns.py` — Patrones de `match`
Analiza los patrones de cada `case` (literales, nombres, comodines, patrones de
`enum`). Aislado porque los patrones son una mini-gramática propia reutilizable.

#### `grammar/directives.py` — Directivas y bloques crudos
Semántica sintáctica de las directivas `#` (`import`, `export`, `extern`, `test`,
`from`) y del `RAW_BLOCK` de `#extern cpp{ … }`. Valida el **uso** de la
directiva (el lexer solo validó que el nombre exista): `PAR020` (directiva
desconocida/mal ubicada), `PAR024` (bloque `extern` inválido).

---

## 5. Cobertura de **todos** los tokens → módulo responsable

Cada `TokenType` de [`t_types.py`](../../../include/t_types.py) tiene un dueño.
Algunos tokens aparecen en dos roles (p. ej. un keyword de tipo que también
inicia una declaración): se anota el matiz.

| Token(s) | Módulo responsable | Rol |
|----------|--------------------|-----|
| `IDENTIFIER` | `expressions/nud.py` · `grammar/types.py` | átomo de expresión / nombre de tipo nominal |
| `INT_LIT` `FLOAT_LIT` `CHAR_LIT` `STRING_LIT` | `expressions/nud.py` | literales (string resuelve `Interp` recursivamente) |
| `TRUE` `FALSE` `NULL` | `expressions/nud.py` | literales atómicos |
| `DUNDER` | `expressions/nud.py` · `grammar/declarations.py` | identificador especial `__x__` |
| `VOID` `BOOL` `INT` `FLOAT` `CHAR` `STR` | `grammar/types.py` | tipos primitivos en posición de tipo |
| `TYPE` | `grammar/declarations.py` | keyword `type` que declara un tipo |
| `CONST` `MUTABLE` | `grammar/declarations.py` (+ `context.py`) | modificadores de binding |
| `FUNCTION` | `grammar/declarations.py` | `fn` + firma |
| `STRUCT` `ENUM` | `grammar/declarations.py` | declaración de tipos compuestos |
| `SIZEOF` | `expressions/nud.py` | `sizeof(T)` como expresión |
| `IF` `ELSE` `WHILE` `RETURN` `BREAK` `CONTINUE` | `grammar/control_flow.py` | sentencias de control |
| `MATCH` `CASE` | `grammar/control_flow.py` (+ `grammar/patterns.py`) | selección + patrones |
| `TEST` | `expressions/nud.py` | función nativa `test(...)` (≠ directiva `#test`) |
| `REGION` `IN` `AT` `MOVE` `FREE` `ALLOC` `MAKE` | `grammar/memory.py` | modelo region-based + move |
| `POINTER` (`ptr`) | `grammar/types.py` · `grammar/memory.py` | tipo puntero / expresión |
| `ADDRESS` (`&`) | `expressions/nud.py` (memoria) | prefijo address-of |
| `NULLABLE` (`?`) | `grammar/types.py` · `expressions/led.py` | tipo `T?` / postfijo |
| `ASSIGN` (`=`) | `expressions/led.py` | asignación (asoc. derecha) |
| `PLUS` `MINUS` | `expressions/led.py` (binario) · `nud.py` (unario) | aritmético / signo |
| `MULTIPLY` `DIVIDE` | `expressions/led.py` | aritmético binario |
| `EQUAL` `NOT_EQUAL` `LESS` `LESS_EQUAL` `GREATER` `GREATER_EQUAL` | `expressions/led.py` | comparación |
| `AND` `OR` | `expressions/led.py` | lógicos binarios |
| `NOT` | `expressions/nud.py` | lógico prefijo |
| `ARROW` (`->`) | `grammar/declarations.py` · `grammar/types.py` | retorno de firma / tipo función |
| `L_PAREN` | `expressions/nud.py` (grupo) · `led.py` (llamada) | agrupación / llamada |
| `L_BRACKET` | `expressions/led.py` (indexado) · `nud.py` (literal) | índice / literal de arreglo |
| `L_BRACE` | `grammar/statements.py` · `declarations.py` · `control_flow.py` | bloque / cuerpo |
| `R_PAREN` `R_BRACKET` `R_BRACE` | consumidos vía `cursor.expect` por su apertura | cierre de delimitador |
| `DOT` | `expressions/led.py` | acceso a miembro |
| `COMMA` | parsers de listas (args/params/campos) vía `cursor` | separador |
| `SEMICOLON` | `grammar/statements.py` | terminador de sentencia |
| `COLON` | `grammar/types.py` · `patterns.py` · `control_flow.py` | anotación / `case X:` |
| `DECORATOR` (`@`) | `grammar/program.py` · `declarations.py` (+ `context.py`) | decorador sobre declaración |
| `DIRECTIVE` (`#`) | `grammar/directives.py` | directivas del compilador |
| `RAW_BLOCK` | `grammar/directives.py` | cuerpo crudo de `#extern cpp{}` |
| `ERROR` | `recovery.py` | token sintético de error léxico |
| `EOF` | `cursor.py` · `grammar/program.py` | fin de flujo / centinela |

---

## 6. Flujo de datos entre capas

```
main.py
  └─ parser.parse(tokens)
        └─ parser.py (orquestador)
              ├─ crea cursor.Cursor + context.Context
              ├─ [conservado] atiende #test lexer
              └─ grammar/program.py  ── dispatch por firstsets ──┐
                    ├─ declarations / control_flow / memory / …  │
                    │      └─ al necesitar una expresión:        │
                    │            pratt.parse_expression()  ──────┤
                    │                  ├─ registry (nud/led)     │
                    │                  └─ precedence             │
                    │      └─ al necesitar un tipo/patrón:       │
                    │            grammar/types.py · patterns.py  │
                    └─ ante error: recovery.py (sync) ───────────┘
        ↓
  AST (nodos de include/ast_nodes.py)
```

Puntos clave de la interacción:
- **La gramática LL(k) llama a Pratt**, no al revés: cuando una regla necesita
  una expresión, delega en `pratt.parse_expression()`. Pratt a su vez puede
  llamar de vuelta a la gramática para sub-construcciones (p. ej. el cuerpo de
  una lambda o argumentos), siempre a través del `cursor` compartido.
- **Un solo `cursor` y un solo `context`** atraviesan todas las capas: no hay
  copias del flujo de tokens ni estados divergentes.
- **Los errores fluyen a la taxonomía existente** (`error_handler`) y la
  recuperación se concentra en `recovery.py`.

---

## 7. Cómo esta estructura cumple modularidad y sostenibilidad

- **Un archivo, una responsabilidad**: agregar un operador toca solo
  `precedence.py` + `registry.py` + un handler; agregar una sentencia toca solo
  su archivo de dominio en `grammar/`.
- **Frontera dato/lógica respetada**: el AST (dato) vive en `include/`; el parser
  (lógica) lo consume. Los errores (contrato) viven en `error_handler/`.
- **Espejo del lexer**: mismo patrón "orquestador padre + subpaquete por clase",
  reduciendo la carga cognitiva para quien ya conoce el lexer.
- **Rendimiento explícito**: tablas O(1) precomputadas, cero backtracking, un
  único recorrido lineal del flujo de tokens — coherente con no penalizar
  HIR/MIR aguas abajo.
- **Extensible sin refactors**: nuevas directivas → `directives.py`; nuevos
  tipos → `types.py`; nuevas sentencias → un archivo de dominio en `grammar/`,
  sin tocar el motor.

---

## 8. Orden de implementación sugerido

1. `cursor.py` (extraer de `parser.py`) + `context.py` — la base.
2. `precedence.py` + `pratt.py` + `expressions/` — expresiones aritméticas y de
   comparación (verificables de forma aislada, p. ej. vía una directiva
   `#test parser expr`).
3. `firstsets.py` + `grammar/statements.py` + `grammar/types.py` — sentencias y
   anotaciones.
4. `grammar/functions.py` + `control_flow.py` — funciones y flujo.
5. `grammar/memory.py` + `directives.py` — dominios avanzados.
6. `recovery.py` — endurecer la recuperación una vez estabilizada la gramática.

Cada paso deja el parser en un estado ejecutable y testeable, sin big-bang.

---

## 9. Estado de implementación (as-built)

El parser, el AST, el AST-tipado y el volcado JSON están **implementados y
probados** contra los ejemplos reales de `docs/examples/*.md` y `docs/syntax.md`,
más pruebas de estrés de rendimiento. Esta sección documenta los ajustes que
surgieron al confrontar el diseño (secciones 1–8) con el EBNF formal
(`docs/gramar/grammar.ebnf`) y con la implementación real.

### 9.1 Árbol final

Igual al propuesto en la secc. 3, con dos diferencias:

- **No existe `grammar/patterns.py`**: el EBNF formal define
  `case_arm = "case" expression ":" ( statement | block )` — el patrón de
  cada rama de `match` **es una expresión**, no una mini-gramática de
  patrones aparte. `control_flow.py` reutiliza `pratt.parse_expression`
  directamente para el patrón.
- **`grammar/declarations.py` se dividió** en `functions.py`, `structs.py`,
  `enums.py` y `decorators.py` (más módulos, cada uno más pequeño y con una
  única responsabilidad — más modular que el archivo único original).

### 9.2 Ajustes de gramática frente al EBNF formal

El EBNF es la fuente de verdad, pero tres construcciones reales del corpus
(`docs/examples/*.md`, `docs/syntax.md`) no encajaban literalmente en él.
Cada ajuste está documentado en el docstring del módulo que lo implementa:

1. **`;` opcional tras un `block`** (decisión de usuario): `fn`/`if`-`else`/
   `while`/`region`/cuerpos `{ }` de `case` toleran un `;` final opcional
   (`grammar/block.py`, un único punto: `parse_block` lo consume). `enum`
   y `struct` lo exigen **siempre** (decisión explícita de usuario para
   `enum`; `struct` ya lo exigía el EBNF).
2. **`case` sin `:` antes de un bloque** (`grammar/control_flow.py`): el
   corpus real omite `:` cuando la rama es `{ ... }` y solo lo usa antes de
   una sentencia suelta (`case X: stmt;` vs `case X { ... };`). Se
   implementó esa forma tolerante.
3. **`const NAME = #import lib;` / `#from lib #import name;`**: patrón
   presente en **todos** los ejemplos del lenguaje pero no cubierto por
   `var_decl` (exige tipo) ni por `import_dir`/`from_dir` (sentencias
   standalone, no expresiones). Se añadió el nodo
   `ast_nodes.ImportBinding` y detección por lookahead puro
   (`IDENTIFIER ASSIGN DIRECTIVE`) en `grammar/statements.py`, sin tocar
   `var_decl` ni la gramática de expresiones.

### 9.3 Bug crítico corregido: progreso garantizado en `recovery.py`

Al probar contra un archivo con una directiva `#test`/`#<nombre-desconocido>`
en posición de declaración, `synchronize()` podía quedarse en **bucle
infinito**: `SYNC_TOKENS` incluye `DIRECTIVE` (porque es el FIRST de
`import_dir`/`export_dir`/`from_dir`/`extern_block`), así que si el error
ocurría *sobre* un `DIRECTIVE`, la condición de sincronización se cumplía en
la primera iteración **sin avanzar el cursor** — `grammar/program.py`
reintentaba el mismo token para siempre, agotando memoria (causa raíz de un
cierre forzado de VSCode durante el desarrollo). Corregido garantizando que
`synchronize()` **siempre** descarta al menos el token que causó el error
antes de buscar el punto de sincronización. Regla general para cualquier
recuperación de errores: un `SYNC_TOKENS` construido a partir de conjuntos
FIRST puede coincidir con el token que disparó el error, así que la
recuperación nunca debe verificar la condición de parada antes de garantizar
al menos un avance.

### 9.4 AST-tipado: mutación en sitio, no árbol paralelo

Por rendimiento (evitar duplicar el árbol completo), `parser/typed_ast.py`
**muta el mismo `Program`** devuelto por el parser: recorre el árbol una vez
por reflexión (`dataclasses.fields()`) y rellena `restype`/`return_restype`
donde el código ya trae una anotación de tipo explícita (`Parameter`,
`VarDecl`, `Field`, `FunctionDecl.return_type`, literales por su
`literal_kind`, `MakeExpr` como `ptr T`, `SizeofExpr` como
`int`). No resuelve símbolos ni hace inferencia (eso es Semántica, Fase 4);
un tipo nominal se resuelve solo hasta su nombre
(`include/types_ast.py::nominal`).

### 9.5 Interpolación de strings: re-lexing aislado

`"...{expr}..."` produce un `Literal` plano (`literal_kind='str'`) cuando no
hay interpolación (camino rápido, mismo que ya optimizaba el lexer con
`StringValue.is_interpolated`). Con interpolación, produce
`ast_nodes.InterpolatedString`: cada `{expr}` se re-tokeniza y re-parsea de
forma aislada (`expressions/nud.py::_parse_interp`, vía
`src/frontend/lexer/lexer.tokenize`) — el EBNF es explícito en que el lexer
solo delimita el texto crudo y el análisis es responsabilidad del parser. Las
posiciones (`ln`/`col`) del sub-árbol resultante se reubican a la posición
real en el archivo tras el re-parseo.

### 9.6 Validado contra

- Los 10 bloques `srcx` de `docs/examples/helloworld.md`,
  `docs/examples/regions.md`, `docs/examples/structs_and_control.md` y
  `docs/syntax.md` (parsean sin errores).
- Casos negativos: `break`/`continue` fuera de un bucle (`PAR013`), `enum`
  sin `;` final — ambos recuperan y reportan sin colgarse ni crashear.
- Rendimiento: 183k / 366k / 732k tokens (fn con expresiones aritméticas +
  `if`/`else` anidado) escalan aproximadamente lineal (~571ms / ~1174ms /
  ~2910ms de parseo), sin señales de comportamiento cuadrático.

### 9.7 Revisión de calidad posterior: 3 bugs reales corregidos

Una revisión de calidad dedicada (8 ángulos: correctitud, comportamiento
eliminado, trazador cruzado, reuso, simplificación, eficiencia, altitud)
sobre todo lo construido en la sesión encontró y corrigió 3 defectos reales
(no solo advertencias de estilo):

**a) `DUNDER` solo se aceptaba como nombre de función.** El diseño explícito
de `hooks.py` es "`DUNDER` es un `IDENTIFIER` para propósitos gramaticales;
Semántica decide el significado" — pero esa regla solo se aplicó en
`grammar/functions.py::_parse_function_name`. Cada otro sitio que esperaba
un nombre (`cursor.expect(TokenType.IDENTIFIER)`) rechazaba `DUNDER`
directamente: nombre de `struct`/campo, nombre de `enum`/item, parámetro de
función, nombre de variable, nombre de región, y el miembro de un
`MemberAccess` (`x.__free__()` fallaba). Corregido con un único método
nuevo, `Cursor.expect_name()` (acepta `IDENTIFIER` **o** `DUNDER`), aplicado
uniformemente en los 11 sitios afectados (`cursor.py`, `structs.py`,
`enums.py`, `functions.py`, `memory.py`, `statements.py`,
`expressions/nud.py`). Las posiciones de nombre de librería/alias en
`directives.py` (`#import`/`#export`/`#from`) se dejaron **sin cambiar** a
propósito: no son parte del sistema de hooks, son identificadores de
módulo.

**b) Recuperación de errores destruía funciones enteras.** `recovery.py`
escaneaba hacia adelante desde la posición del ERROR usando un conjunto
`SYNC_TOKENS` (en `firstsets.py`) que incluía casi todo `FIRST_EXPRESSION` —
la recuperación se detenía tras descartar un solo token en la mayoría de
casos reales. Verificado: un paréntesis faltante en un `if` dentro de una
función hacía que **toda la función** desapareciera del AST (sus `return`
internos reaparecían como items sueltos de nivel superior), con 3 errores en
cascada en vez de 1. Rediseñado (ver docstring de `recovery.py`): ahora se
**rebobina al inicio del item de nivel superior que falló** y se cuenta
profundidad de `{`/`}` desde cero, descartando el item roto **completo**
como unidad. Verificado con el mismo caso: 1 solo error, la función
siguiente se recupera intacta. `firstsets.py` quedó sin ningún consumidor
tras este cambio y se **eliminó** (22 de sus 24 conjuntos ya estaban
muertos antes de este fix; el rediseño mató también al único que se usaba).

**c) La forma sin *qualifier* de `ImportBinding` era inalcanzable.**
`ast_nodes.ImportBinding` documenta `[qualifier] IDENTIFIER "=" ...` como
válido sin `const`/`mutable`, pero `parse_statement` solo probaba el
lookahead de import-binding *dentro* de `parse_var_decl`, alcanzable
únicamente vía `const`/`mutable`/tipo-keyword. `IO = #import IO;` (sin
qualifier) cascadeaba a un `ParseError`. Corregido moviendo el chequeo de
`_looks_like_import_binding` al inicio de la rama `IDENTIFIER` de
`parse_statement`, antes del chequeo de tipo nominal.

Los 3 fixes se validaron contra la suite completa (los 10 bloques de
`docs/examples/*.md`/`docs/syntax.md`, `io.libsrx`, los hooks de
Semántica, y el stress test de rendimiento) sin regresiones.

---

## 10. Estado de implementación (as-built, 4ª entrega): reservas, hook/dunder y regiones

Tres features pedidas por el usuario, todas del lado sintáctico aquí (la
semántica en `semantic/ARQUITECTURA.md` secc. 15):

### 10.1 Prefijo de modificadores top-level — `grammar/modifiers.py` (nuevo)

Un item top-level admite, en **orden fijo**,
`[ visibility ] [ hook | dunder ] declaración`. En lugar de esparcir ese
lookahead por `program.py` y cada parser de declaración, se creó
**`grammar/modifiers.py`**: el único dueño de "qué inicia un item top-level y
con qué prefijo". `program.py` quedó reducido a bucle + recuperación (llama a
`modifiers.parse_top_level_item`). Es el equivalente top-level de
`statements.parse_statement`. La **visibilidad** (`public`/`private`/
`internal`; sin token = público) precede a todo, incluido un decorador; el
**especificador** (`hook`/`dunder`) solo precede a `fn` (si no → error
dirigido). Ambos se enhebran como parámetros `visibility`/`specifier` a los
parsers de declaración (nodos con default `None`, cero costo en el caso común).
Las directivas y `test` no admiten prefijo. Una visibilidad que recae sobre
algo que no es una declaración (`VarDecl`/`TypeDecl`/`ImportBinding` o
`fn`/`struct`/`enum`) es un error dirigido; dentro de un bloque, los tokens de
visibilidad/especificador tienen su propio handler de mal uso en
`_STATEMENT_DISPATCH`.

### 10.2 hook/dunder: el compilador ya no adivina por la forma `__x__`

El lexer sigue emitiendo `DUNDER` para la FORMA `__x__` (sin validar), pero la
"hook-ness" ya **no** se deriva del nombre: la fija el especificador explícito
(`FunctionDecl.specifier ∈ {'hook','dunder',None}`). `fn __x__` a secas es una
función normal (el usuario puede usar `__` libremente). Con especificador, el
nombre DEBE tener forma `__x__` (si no → `ParseError`). El campo `dunder`
(nombre sin guiones) se conserva para la Semántica.

### 10.3 Regiones (modelo híbrido) — `grammar/memory.py`

`region_stmt` pasó a `region_mods "region" IDENTIFIER block` con
`region_mods = { shrd | mutable | na }` de **orden libre** (helper
`_parse_region_modifiers`, duplicado = error). Se añadieron `new_stmt`
(handle sin bloque), `delete_stmt` (externa `delete(region r)` / interna
`delete()`), `in_region_stmt` (`in region r: stmt | block`, espeja `case_arm`)
y la variante de región de `move_stmt` (`move region a -> region b`, 1 token de
lookahead). El dispatch de `statements.py` enruta `NA`/`NEW`/`DELETE`/`IN` a sus
parsers; `MUTABLE` desambigua con `starts_region` (lookahead puro) entre
`mutable region` y el mal uso histórico como qualifier de variable. Nodos
nuevos: `NewStmt`/`DeleteStmt`/`InRegionStmt`/`MoveRegionStmt`; `RegionStmt`
ganó `mutable`/`na` (ya tenía `shared`).

### 10.4 Validado contra

Suite completa **281/281 verde** tras regenerar los golden del AST-tipado y de
la tabla de símbolos (cambio de contrato aditivo: campos `visibility`/
`specifier` en el AST y `visibility`/`region_mutable`/`region_na` en `Symbol`).
`#test parser` sobre las tres features produce el AST esperado; el emisor HIR
rechaza los nodos de región nuevos con `HIR005` (sin crash), a la espera del
runtime RBMM.

---

## 11. Estado de implementación (as-built, 5ª entrega): traits y decoradores generalizados

### 11.1 Decoradores generalizados — `grammar/decorators.py`

El decorador dejó de ser `DECORATOR function_decl`: ahora va **primero** y es
dueño de su prefijo. Admite **argumentos** (`@impl(iterable)` -> `args`),
aplica a **fn/struct/enum**, y tras él van `[visibility] [specifier]`
(`@impl(x) public struct`). `DecoratorDecl.target` se amplió a
`fn|struct|enum` y ganó `args: List[str]`. El orden cambió de `[visibility]
@deco` a `@deco [visibility]` (decisión de usuario); `modifiers.py` chequea
`DECORATOR` **antes** que la visibilidad. Los helpers de prefijo
(`consume_visibility`/`consume_specifier`) se extrajeron a
**`grammar/prefixes.py`** (módulo neutro) para que `modifiers` y `decorators`
los compartan sin ciclo de imports.

### 11.2 Traits — `grammar/traits.py`

`@trait` es especial: tiene cuerpo propio (prototipos, no campos) y produce un
`TraitDecl` (no un `DecoratorDecl`). `decorators.py` desvía a
`traits.parse_trait_decl` al ver el nombre `trait`. Dos formas: **struct**
(`@trait struct { <prototipos> } Nombre;`) y **suelta**
(`@trait dunder fn __x__(...) ;`, nombre del trait = nombre del método). Un
`trait_method` es un prototipo cuyos parámetros son **tipos sin nombre**
(`trait_params`). El placeholder `self` es un `SelfTypeExpr` (nuevo nodo);
**no es keyword** — `types.py` lo reconoce solo cuando un tipo nominal se
llama `self`, así `self` sigue usable como nombre de variable/parámetro.
`typed_ast` lo resuelve a `include.types_ast.SELF_TYPE` (nuevo `TypeKind.SELF`).

### 11.3 Validado contra

Suite **358/358 verde**. `#test parser` sobre `@trait`/`@impl`/decoradores con
args produce el AST esperado. Dos crashes de emisión HIR (kinds `SELF` y
`DUNDER` inexistentes en el `.proto`) se corrigieron excluyéndolos del mapeo de
enums (son solo-frontend, nunca viajan al HIR v1; mismo tratamiento que
`REGION`).
