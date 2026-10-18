# El contrato de la V0: qué emite en el HIR y por qué

Lo que la V1 tiene que reproducir para que su `.phir` sea idéntico, byte a
byte, al de la V0. Cada regla está **verificada**: contra el `.phir` real de
un programa de sonda (los de [`test/bootstrap/v1/`](../../test/bootstrap/v1/))
y contra el código de la V0 que la produce (citado en cada sección).

Cómo se verificó:

1. programas de sonda que tocan cada construcción;
2. un recorrido del `.phir` que lista **cada campo presente** de cada mensaje,
   con ejemplos (el catálogo de la sección 9);
3. la lectura del código de la V0 que escribe cada campo;
4. el árbol del parser de la V1 sobre las mismas sondas: que tenga todo lo que
   la regla necesita.

Cubre lo que la V1 ya implementa (lotes 14 a 17b): funciones, escalares,
control de flujo, `struct`, `enum`, `match`, punteros, `move`/`free`, cadenas
y f-strings, la propiedad (drops y temporales), el linker (sección 10), los
genéricos (sección 11) y los métodos, las excepciones y el `with` (sección
12). La sección 13 es el contrato de los diagnósticos.

---

## 1. La tabla de símbolos (`SymbolTable`)

Solo viaja el scope GLOBAL (`collect.py`). Los locales y los parámetros no.

| Qué | Dónde | Campos |
|---|---|---|
| función | `values` | `FUNCTION`, `type` = retorno, `param_types`, `mutable` falso |
| variable del módulo | `values` | `VAR`, `mutable` = no es `const` |
| struct | `types` | `STRUCT`, `type` = `NOMINAL` con su nombre, `members` = sus campos |
| campo | `members` del struct | `FIELD`, su tipo, **`mutable` = true** |
| enum | `types` | `ENUM`, `type` = `NOMINAL`, `members` = sus variantes |
| variante | `members` del enum **y también** `values` | `ENUM_ITEM`, `type` = el enum, `param_types` = el payload; sin `mutable`; el valor (`= 200`) NO viaja aquí |
| `hook fn` | `hooks` (una `HookEntry`), NO en `values` | `owner_type`, `kind`; su `symbol`: `HOOK`, `hook_kind`, `hook_owner`, `type` = retorno, `param_types` |

- Los mapas (`types`, `values`, `members`) se escriben ordenados por clave.
- `hooks` es una lista, en orden de declaración.
- La posición de una función es la de `fn`, también en `hook fn` (col 6).

## 2. El orden del pool de tipos (`Module.types`)

Un tipo entra al pool la primera vez que la V0 lo encuentra recorriendo los
items **en orden** (`emmit_IR.py`):

- `struct`: el tipo de cada campo;
- `enum`: por cada variante, su valor (`= 200` es una expresión, con su
  tipo) y después sus tipos de payload;
- función: parámetros, retorno, cuerpo;
- sentencia `var`: su tipo, después su valor;
- expresión: su tipo, después sus hijos en el orden del emisor:
  - binaria: izquierda, derecha;
  - llamada: callee, argumentos;
  - asignación: destino, valor;
  - miembro: objeto;
  - índice: objeto, índice;
  - `&`, `move`, unaria: su operando;
  - literal de struct: los valores;
  - `cast`: su valor;
  - f-string: cada parte expresión;
- `match`: el sujeto; por rama, el patrón y después el cuerpo.

El tipo de un `cast` viaja DOS veces: `type_id` (pool) y un `Type` completo
dentro de `CastExpr.type` (ese no entra al pool).

## 3. Qué nodo lleva tipo (`Expr.type_id`)

La V0 anota `restype` solo en lo que **visita como expresión**
(`scope_resolver.visit_expr`). Lo que no visita queda en 0:

| No lleva tipo | Por qué |
|---|---|
| el `callee` de una llamada (un nombre, `Forma.Rect`, `io.f`) | se resuelve como símbolo, no se evalúa |
| el destino de una asignación | ídem |
| el objeto NOMBRE de un acceso a miembro (`p` en `p.x`, `Color` en `Color.VERDE`) | `_expr_member` resuelve el nombre sin visitarlo |
| el patrón de un `case` con payload (`Forma.Circulo(r)`) y su callee | se liga, no se evalúa |

| Sí lleva tipo | Cuál |
|---|---|
| el objeto de un miembro que NO es un nombre (`s.a` en `s.a.x`) | el de `s.a` |
| el objeto de un DESTINO compuesto (`p` en `p.x = v`) | se visita para comprobar la escritura |
| un binding de patrón (`r` en `case Forma.Circulo(r)`) | el tipo del payload |
| un patrón sin payload (`case Forma.Nada`) | el enum: se visita como expresión |
| `Color.VERDE` | el enum |
| `Forma.Rect(2.0, 3.0)` | el enum (la llamada; el callee no) |
| `x.campo` | el tipo del campo; a través de un `ptr` también (se desenvuelve) |
| `&x` | `ptr T`, con `mut` (ver 4) |
| `s[i]` | `char` si `s` es `str`; `T` si es un `T ptr` |
| `cast<T>(x)` | `T` |
| `move x` | el de `x` |
| f-string | `str` |
| `len(s)` | `int` |
| literal de struct | su `NOMINAL` |

`Color.ROJO.name` no es un acceso: se reemplaza por el literal `"ROJO"`
(`str`), en la posición del acceso (`MemberAccess.nombre_de_item`).

## 4. Expresiones

- **`&x`** (`_expr_addrof`): `AddrOf.mut` es la mutabilidad del símbolo:
  - `var` y parámetros: `true`;
  - `const` y bindings de patrón: `false`;
  - sobre un campo o un índice: siempre `true`.

  El tipo es `ptr` de lo apuntado, con ese `mut`. `mut=false` también se
  escribe: `AddrOf` se marca presente con `SetInParent`.
- **Llamada a variante** (`_construir_variante`): una `Call` normal.
- **`len(s)`** sobre `str`: `Call.hook` = `{owner_type: "str", kind: LEN}`
  (`_LEN_DE_STR`).
- **Literal de struct**: `type_name` como se escribió, `field_names` en el
  orden escrito, y `values` en el mismo orden.
- **f-string**: `InterpolatedString.parts`, cada una `text` (un trozo) o
  `expr` (con `repr` si `!r` y `spec` si `:...`).
- **`+` entre `str`**: una `BinaryOp` como cualquier otra (tipo `str`).

## 5. Sentencias

- **`match`**: `subject` y `cases`; cada `CaseArm` lleva `pattern` (una `Expr`)
  y `body` (una `Stmt`, el bloque). Una rama con payload abre su propio scope
  y liga cada nombre como `VAR` no mutable del tipo del payload.
- **`move x;`**: `MoveStmt.target`, visitado (con tipo).
- **`free e;`**: `FreeStmt.target` y `hook` si el tipo nominal de `e` tiene
  `__free__` (si no, sin `hook`).
- **`return`**: `transfers = true` si el valor POSEE (sección 6).

### 5.1 Cuánto anida un módulo

El HIR guarda el árbol como mensajes dentro de mensajes, y quien lo lee
recorre esa anidación con su propia pila. Para que ningún lector tenga que
adivinar cuánta necesita, el **productor** la acota:

- la V0 rechaza (`PAR025`) una declaración cuyo árbol anide más de **500**
  niveles (`MAX_NESTING`, en `grammar/program.py`);
- cada nivel del árbol son como mucho **dos** mensajes en el HIR (el
  envoltorio `Expr`/`Stmt` y su variante). Medido en el peor caso —una
  cadena de 496 operadores—: 1000 mensajes anidados;
- un lector debe admitir al menos esos 1000. El del target web admite 1024
  (`MAX_NESTING_DEPTH`, en `web/src/hir/wire.ts`) y una prueba compara los
  dos números.

La V1 no tiene este límite: su parser corre en suriaX y un anidamiento
extremo agota su pila (`RT019`). Es una diferencia conocida con la V0.

## 6. La propiedad: drops y temporales

**Quién posee** (`type_service.owns_resources`):

1. un `ptr T` no posee;
2. un nominal con `__free__` posee;
3. un struct posee si posee algún campo por valor;
4. un CAMPO `R ptr` posee si `R` posee;
5. un enum posee si posee el payload de alguna variante (un payload puntero
   no).

`T?` y `error T` poseen si lo envuelto posee. Los primitivos (`str`
incluido) nunca.

**Drops de un bloque** (`_anotar_drops`), al cerrar cada scope (el del cuerpo
de una función incluye los parámetros):

- entran los `VAR` que poseen y los parámetros por valor que poseen. No
  entran los de un `hook fn`, ni el primer parámetro de un `dunder`;
- en orden INVERSO de declaración;
- cada uno se aplana (`_aplanar_drops`):
  - si su tipo tiene `__free__`: un drop con `hook`;
  - si es un enum, un puntero o un genérico: un drop `by_type`;
  - si no, se baja a sus campos que poseen, con la ruta (`c.dentro`);
- la lista entera se invierte al final. Por eso los campos salen en orden
  inverso (`c.otro` antes que `c.dentro`).

**Temporales** (`visit_expr`). Una `Call` o un literal de struct cuyo tipo
posee se marca:

- `temp_drop` con el `__free__` del tipo, si lo tiene;
- `temp_by_type` si posee sin `__free__`.

La marca se QUITA (`_tiene_dueno`) cuando el valor tiene dueño:

- el valor de un `var`;
- el valor de una asignación;
- el valor de un `return`;
- un campo de un literal de struct;
- el operando de un `move`;
- un argumento de un constructor de variante;
- un argumento hacia un parámetro por valor que posee.

**`drops_old`** en una asignación, si el destino posee y no es puntero.

**`transfers`** en un `return`, si el valor posee.

## 7. Lo que NO llega al HIR

- **`memory_check`**: solo diagnostica. Lo único que escribe es
  `Symbol.moved_at`, sobre símbolos LOCALES, que el HIR no lleva. Para un
  programa válido, la V1 no lo necesita: va con los diagnósticos.
- Los símbolos locales y los parámetros; `ctx.uses` (lo que usa el índice
  del LSP); las marcas de azúcar (`azucar`).

## 8. Lo que usa la V1 (el censo)

El fuente de la V1 (23 archivos, parseados con la V0) es lo que decide qué
hace falta para el punto fijo:

- **Mucho:**
  - acceso a miembro (3054);
  - `&` (228);
  - `Index` (121);
  - `CaseArm` (143);
  - f-strings (40, sin formatos);
  - literales de struct (19);
  - `cast` (27);
  - `break` y `continue` (18);
  - `try`/`catch` (6).
- **Poco:** un `enum`, 2 `match`, 3 `move`.
- **Nada:** nullables, `hook fn`, `free`, `sizeof`, genéricos propios.

Su propiedad viene de `Vector` y `Dictionary`, que son de LIBRERÍA: los drops,
`transfers`, `drops_old` y los temporales se ejercitan de verdad cuando
exista el linker (lote 16).

## 9. El catálogo de campos

Cada `(mensaje, campo)` presente en las sondas (`campos.py` sobre los
`.phir`), además de los del lote 14:

`AddrOf.{operand, mut}` · `Assignment.drops_old` · `Block.drops` ·
`Call.{hook, temp_drop, temp_by_type}` · `CaseArm.{pattern, body}` ·
`CastExpr.{type, value}` · `Decl.{struct_decl, enum_decl}` ·
`Drop.{path, hook, by_type}` · `EnumDecl.{name, items}` ·
`EnumItem.{name, value, payload_type_ids}` ·
`Expr.{addr_of, cast_expr, index, interp, member, move_expr, struct_literal}` ·
`Field.{name, type_id}` · `FreeStmt.target` · `FunctionDecl.dunder` ·
`HookEntry.{owner_type, kind, symbol}` · `HookRef.{owner_type, kind}` ·
`Index.{obj, index}` · `InterpolatedString.parts` ·
`MatchStmt.{subject, cases}` · `MemberAccess.{obj, member}` ·
`MoveExpr.operand` · `MoveStmt.target` · `Part.{text, expr, repr, spec}` ·
`ReturnStmt.transfers` · `Stmt.{match_stmt, move_stmt, block}` ·
`StructDecl.{name, fields}` ·
`StructLiteral.{type_name, field_names, values}` ·
`Symbol.{members, hook_kind, hook_owner}` · `SymbolTable.{types, hooks}` ·
`Type.{name, inner, mut}`

---

## 10. El linker: varias unidades (lote 16)

Verificado con un proyecto de sonda (una librería de un archivo, un paquete
con dos submódulos, una librería que importa a otras y la stdlib) y con el
código de `V0/src/linker_p/`, `collect.define_import`, `type_service` y
`driver/pipeline.py`.

### 10.1 Una unidad por `.phir`

- El programa y CADA librería que carga son unidades distintas: la V0 emite
  `<unidad>.phir` para cada una (`pipeline.build_library_units`), junto al
  del programa.
- La unidad de una librería es su alias de `#export`. La de un submódulo es
  `<alias del paquete>.<alias del submódulo>` (`IO.stdp`, `geo.punto`). Un
  paquete importado entero (`#import io`, `#from io #import stdp`) emite su
  padre (`IO.phir`: solo su `export package`). Uno del que solo se importan
  submódulos (`#import geo.punto`) no lo emite.
- Cada librería se ANALIZA OTRA VEZ como un programa propio (con su unidad) y
  se emite con `source_file` = su ruta PÚBLICA (10.7). El programa lleva la
  ruta como se la pasaron al compilador.

### 10.2 Dónde se busca (`linker_p/resolver.py`)

- Las rutas de búsqueda, en orden:
  1. la carpeta del fuente;
  2. la carpeta que contiene al paquete que lo envuelve, si está dentro de
     uno;
  3. las `libsrx_paths` de la configuración (por defecto `./lib`, resuelta
     contra la raíz del proyecto);
  4. la stdlib (`SURIAX_STDLIB`, o `<raíz del compilador>/lib`).

  No se repiten.
- En cada ruta se prueba el nombre como está y en minúsculas. Gana un archivo
  `.libsrx`, después un paquete (una carpeta con `main.libsrx`, o con
  `<carpeta>.libsrx`) y después un `.srcx`. Un import punteado (`geo.punto`)
  solo lo satisface un paquete.
- Los submódulos de un paquete son los otros `.libsrx` de su carpeta, en
  orden `sorted()`.

### 10.3 La tabla del importador (`collect.define_import`)

- `#import lib [as x]`: un `IMPORT` con el nombre del alias (o el último
  tramo de `lib`), `type` = `NOMINAL` con `lib` TAL COMO SE ESCRIBIÓ, y la
  posición de la directiva.
- `#from lib #import y [as z]`: el símbolo de `y` COPIADO (clase, tipo,
  parámetros, miembros, parámetros de tipo) con la posición de la
  DIRECTIVA. Si `y` es un submódulo, la copia es un `IMPORT` sin tipo. Si es
  un struct o un enum, la copia va al espacio de TIPOS (no al de valores),
  bajo el nombre local y bajo el canónico (`cosa.Plano`), como un tipo
  propio (lote 17a: antes no se podía usar como tipo).
- Los HOOKS de la librería se fusionan en la tabla del importador (por eso
  `SymbolTable.hooks` del programa lista el `__free__` de `punto.Punto`).
  Una librería ya trae fusionados los de las que ella importa, y un paquete
  los de sus submódulos. Visibilidad:
  - `internal` no sale nunca de su archivo;
  - `private` solo se fusiona dentro del mismo paquete (los `private hook` de
    `stdp` no llegan al programa).
- `Module.libraries`: las unidades que ESTE módulo importa (y los submódulos
  de un paquete que importa), en orden de import, sin repetir.
- En el HIR:
  - `ImportDirective` lleva `lib`, `alias` (si se escribió), `unit` y
    `binding`;
  - `FromDirective` lleva `lib`, `name`, `alias` y `unit`.

### 10.4 Los nombres canónicos de los tipos

- Un tipo declarado en una librería se llama `<unidad>.<nombre>` (el alias
  del `#export`: `calc.Par`, `punto.Punto`), también DENTRO de su librería
  (`SemanticContext.qualify`). El programa no tiene unidad: sus tipos van sin
  calificar.
- Dentro de su librería, cada tipo está en `SymbolTable.types` DOS veces: por
  su nombre (`Par`) y por el canónico (`calc.Par`), el mismo símbolo
  (`collect._registrar_tipo`). La declaración conserva el nombre corto
  (`struct Par`).
- Toda anotación se reescribe con el nombre canónico (`pt.Punto` →
  `punto.Punto`), y también el `type_name` de un literal de struct
  (`Par{...}` → `calc.Par{...}` en el HIR).

### 10.5 Qué nodo lleva tipo, a través de un import

- `calc.BASE`: el tipo de la constante; `calc` no.
- `calc.Signo.NEG`: la del medio (`calc.Signo`) sí lleva tipo (se visita,
  no es un nombre); la de afuera, el enum.
- `pt.crea(...)`: la llamada, el retorno; el callee y el nombre del import,
  no.

### 10.6 Implementación en la V1

- `semantica/enlazador.libsrx`: rutas de búsqueda, `busca` (`find_library`),
  submódulos, la caché por ruta y el estado compartido (`Contexto`).
- `semantica/resolver.libsrx`: `carga` (con el paquete entero para un import
  punteado y el caso del HERMANO), `importa` (`define_import`),
  `fusiona_hooks`, `canonico_escrito` (`lookup_type_path`) y las cadenas de
  imports en miembros y llamadas.
- `src/main.srcx`: el programa y después cada unidad pendiente, analizada con
  su unidad y emitida como `<unidad>.phir`.

### 10.7 Las rutas

El `source_file` de cada librería es su ruta PÚBLICA, REPRODUCIBLE (fase V2,
decidido por el mantenedor; antes era la absoluta y el `.phir` cambiaba con la
carpeta y la máquina): dentro de la stdlib, `<stdlib>/` + la ruta relativa a
ella; dentro del proyecto, relativa a su raíz (la carpeta del
`.suriaX_config.yaml`, o la del fuente); fuera de los dos, la absoluta. Siempre
con `/`, y en Windows la comparación del prefijo no distingue mayúsculas. La
stdlib se mira PRIMERO. V0: `linker_p.resolver.ruta_publica`; V1:
`semantica.enlazador.ruta_publica`, sobre las rutas del host (`sistema.rutas`,
que calcula lo mismo que `os.path`).

---

## 11. Los genéricos (lote 17a)

Verificado con cuatro sondas (structs genéricos y anidados; funciones
genéricas con argumentos escritos y deducidos; la propiedad con `T`; un
proyecto con una librería genérica y `mem`) y con el código de
`collect._declarar_parametros`, `scope_resolver` (`_ligar_generico`,
`_check_call`, `_genericos`, `_anotar_drops`, `_aplanar_drops`,
`_argumento_transferido`, `_stmt_return`, `visit_expr`) y `type_service`
(`substitute`, `bindings`, `owns_resources`, `mentions_param`).

### 11.1 En el HIR

Solo tres campos nuevos:

- `FunctionDecl.type_params` y `StructDecl.type_params`: los nombres, en el
  orden escrito;
- `Type.args`: los argumentos de un `NOMINAL` (`Caja<int>`), DENTRO del
  `Type` del pool. Los argumentos no entran al pool por su cuenta: `#9
  Caja<Caja<float>>` no agrega `Caja<float>` ni `float`.

Lo que NO viaja: los argumentos de tipo de una llamada (`make<int>(4)` es
una `Call` corriente; la instancia está en su `type_id`), los de un literal
(`Caja<int>{...}` lleva `type_name = "Caja"`, canónico y sin argumentos, y
el tipo completo en `type_id`) y `Symbol.type_params`.

### 11.2 Los parámetros de tipo en la tabla

- Cada parámetro (`T`, `A`, `K`...) es un símbolo `TYPE` del espacio de
  TIPOS global: `type` = `NOMINAL` con su nombre, SIN calificar (también en
  una librería), sin `mutable`, visibilidad `internal` (no se exporta).
- Lo declara la PRIMERA declaración que lo nombra, en el orden del archivo
  (un `struct` o una `fn`), con la posición de esa declaración (la de `fn`,
  la de `struct`). Otro genérico que reusa `T` no lo vuelve a declarar.
- En un struct, sus campos se declaran con el parámetro (`T valor`); el
  símbolo de una función genérica, con su firma sin sustituir (`T`,
  `caja.Bolsa<T>`).

### 11.3 Usar un genérico: la sustitución

- Un campo visto desde una instancia vale su sustitución: `a.valor` con `a:
  Caja<int>` es `int`; `c.valor.valor` con `Caja<Caja<float>>` es `float`.
  También a través de un `ptr` y en `l.datos[i]` (`T ptr mutable` → `int ptr
  mutable` → `int`).
- Una llamada a una función genérica (`_ligar_generico`):
  - si trae argumentos de tipo (`primero<int>(...)`), esos;
  - si no, se DEDUCEN solo de los parámetros declarados exactamente como un
    parámetro de tipo (`T a` con un `int` liga `T=int`), el primero que lo
    liga gana. La deducción es literal a propósito: no unifica dentro de
    `Caja<T>` ni de `T ptr` (ahí se escriben los argumentos).
  - el tipo de la llamada es el retorno SUSTITUIDO (`envuelve<int>(5)` es
    `Caja<int>`); los parámetros también se sustituyen antes de decidir si un
    argumento pasa a tener dueño.
- Dentro de un genérico, una llamada con los parámetros del llamador
  (`primero<T>(x, x)`) da `T`: la sustitución liga a OTRO `T` (el del
  llamador), que sigue siendo un parámetro.

### 11.4 La propiedad con genéricos

Los "genéricos en curso" de un cuerpo son los `type_params` de la función (y,
en el lote 17b, los de su `@impl` y los de un receptor genérico). Un tipo
"habla de un genérico" si nombra alguno (`T`, `Caja<T>`, `T ptr`).

- **Quién posee** (`owns_resources`) se calcula sobre el tipo CONCRETO: los
  campos de un struct genérico se sustituyen con los argumentos de la
  instancia (`Caja<R>` posee si `R` posee; `Caja<int>` no). Un `T` solo no
  posee (es un `TYPE`); lo que hace que se destruya es la regla siguiente.
- **Drops** (`_anotar_drops`): un local o un parámetro propio cuyo tipo habla
  de un genérico y NO es puntero se destruye POR SU TIPO (`drop x ⟨por su
  tipo⟩`), sin mirar si posee. Un `T ptr` no.
- **Aplanar** (`_aplanar_drops`): un valor cuyo tipo habla de un genérico se
  destruye por su tipo; si no, los campos se bajan SUSTITUIDOS (`drop
  dentro.valor ⟨hook __free__ de R⟩` para un `Caja<R>`; `drop q.valor ⟨por
  su tipo⟩` para un `Caja<Quizas>`, porque el campo es un enum).
- **Temporales** (`visit_expr`): una llamada o un literal cuyo tipo habla de
  un genérico (y no es puntero ni tiene `__free__`) es `temp_by_type`.
- **`return`**: `transfers` si posee o si habla de un genérico (y no es
  puntero).
- **Argumentos**: hacia un parámetro (ya sustituido) que habla de un
  genérico, el argumento TIENE DUEÑO (se le quita la marca de temporal),
  posea o no.
- `drops_old` en una asignación (`_asignacion_de_dueno`): si el destino posee
  O habla de un genérico (y no es puntero). `p[0] = move x` con `p: T ptr
  mutable` destruye el viejo.
- Copiar un `T` con destructor (SEM038) es un diagnóstico: no llega al HIR.

### 11.5 Implementación en la V1

- `semantica/simbolos.libsrx`: los parámetros de tipo de un símbolo
  (`pon_tparams`, `tparams_de`), copiados con él (`copia`: un genérico
  importado, también con `#from`, los conserva).
- `semantica/tipos.libsrx`: `sustituye` (`substitute`) y `menciona`
  (`mentions_param`).
- `semantica/propiedad.libsrx`: `instancia_de` (`bindings` + `substitute`)
  en `posee` y en `aplana`; `aplana` recibe los genéricos en curso.
- `semantica/resolver.libsrx`: `declara_parametros`
  (`_declarar_parametros`), `Analisis.genericos` (`_genericos`), `campo_de`
  sustituido, `llama_a` + `liga` (`_check_call` + `_ligar_generico`) y las
  reglas de 11.4.
- `hir/emisor.libsrx`: `FunctionDecl.type_params` y `StructDecl.type_params`
  (`Type.args` ya se escribía).

### 11.6 Lo que queda fuera de 17a

- `@impl` (métodos), los hooks con receptor genérico (`__index__(Vector<T>
  ptr self, ...)`), `throw`/`try` y `with`: lote 17b. Por eso
  `array.vector` y `collections.dictionary` se verifican en 17b; `mem` (solo
  funciones genéricas) ya en 17a.
- `const type Caja<T>;` (el tipo opaco genérico): la V1 no usa `type` ni
  importa `d_types`.

---

## 12. Métodos, hooks con receptor genérico, excepciones y `with` (lote 17b)

Verificado con cuatro sondas (métodos de `@impl` y `dunder fn`; un `@impl`
genérico con `__index__`/`__index_set__`; `throw`/`try`/`catch`/`finally`;
las formas de `with`) y un proyecto que importa LAS MISMAS librerías que la
V1 (`array.vector`, `collections.dictionary`, `sistema.*`, `text`,
`excepciones`, `io`), y con el código de `collect._collect_dunder`,
`scope_resolver` (`_call_member`, `_mapa_de`, `_expr_index`, `_hash_de`,
`_stmt_throw`, `_stmt_try`, `_stmt_catch`, `_check_var_init`) y el emisor.

### 12.1 En el HIR

- `ThrowStmt.value`; `TryStmt.{try_block, catches, finally_block}`;
  `CatchClause.{name, block, type}`. El `type` de una rama viaja INLINE (un
  `Type` completo, como el de `CastExpr`): no entra al pool. Sin tipo
  escrito, `type` está ausente.
- Un método no tiene nodo propio: es una `Call` cuyo `hook` es `{owner_type
  = el dueño canónico, kind = 0}` (`HOOK_UNSPECIFIED`). El callee sigue
  siendo un `MemberAccess`.
- `hash(x)`: una `Call` con `hook = {owner_type, HASH}`. El dueño es el
  nominal del argumento; sobre un primitivo, su nombre (`int`, `bool`,
  `char`, `str`; un `byte` cuenta como `int`); sobre un parámetro de tipo
  (`hash(key)` con `key: K`), `K`; sobre un enum sin payload, el enum.
- `v[i]` sobre un nominal con `__index__` NO lleva hook en el HIR: el
  consumidor lo busca por el tipo. Su tipo es el retorno del hook,
  sustituido.

### 12.2 Los métodos (`@impl` y `dunder fn`)

- El parser APLANA `@impl T { ... }` en funciones con `specifier =
  "dunder"`, `dunder` = su nombre (`push`) e `impl_type_params`. Un `dunder
  fn __doble__` lleva `dunder = "doble"`.
- `FunctionDecl.type_params` de un método: los del `@impl` PRIMERO y
  después los propios.
- Un método NO es un valor: va a una tabla propia, por `(dueño, nombre
  escrito)` (`register_dunder`), con el dueño = el nominal CANÓNICO de su
  receptor (el primer parámetro). Esa tabla NO viaja en `SymbolTable`.
  Los de una librería se fusionan en el importador como los hooks (`private`
  solo dentro del paquete).
- `x.m(args)` (`_call_member`): el receptor `x` SÍ se visita (lleva tipo),
  después los argumentos. Se busca `(dueño de x, m)`; el `hook` de la `Call`
  es el del método. El mapa de sustitución sale de los argumentos de tipo
  del receptor (`Lista<int>` liga la `T` de `Lista`); si el tipo no resuelve
  por su nombre (una librería vista desde su consumidor), de los del
  receptor DECLARADO del método (`_mapa_por_receptor`). Cada argumento se
  transfiere contra su parámetro declarado SUSTITUIDO (sin contar el
  receptor). El tipo de la llamada es el retorno sustituido.
- Dentro de un método, los genéricos en curso son sus `type_params`, los
  `impl_type_params` y los argumentos del receptor que son parámetros de
  tipo (`__index__(Vector<T> ptr self)` nombra la `T` de `Vector`). El
  receptor no es de la función: no se destruye.

### 12.3 Excepciones

- `throw v` (`_stmt_throw`): `v` se visita. Si es un local (o un parámetro
  por valor, o un campo propio suyo) cuyo tipo posee, se ENVUELVE en un
  `MoveExpr` sintético (misma posición, mismo tipo): `throw move r`. Después
  el valor tiene dueño (no es un temporal).
- `try` (`_stmt_try`): el bloque protegido es un bloque corriente (scope y
  drops propios); cada `catch` abre un scope con su binding —`VAR` no
  mutable, del tipo escrito o, sin tipo, `error` sin envolver
  (DESCONOCIDO)— y anota los drops de su bloque, binding incluido: con tipo,
  como cualquier local; sin tipo, POR SU TIPO (`es_desconocido`). `finally`
  es un bloque corriente.

### 12.4 `with`

Es azúcar del PARSER (un `Block` con las declaraciones y el cuerpo): la
Semántica no ve un `with`. Lo único propio es el GUARDIÁN sin nombre (`with
(abre("x")) {...}`): un `VarDecl` sin tipo escrito (`inferido`) cuyo tipo es
el de su valor, y el valor tiene dueño (`_check_var_init`).

### 12.5 Implementación en la V1

- `semantica/simbolos.libsrx`: la tabla de métodos (`define_dunder`,
  `busca_dunder`; clase `DUNDER`, que no viaja).
- `semantica/tipos.libsrx`: `error_suelto` y `es_desconocido`.
- `semantica/resolver.libsrx`: `recoge_funcion` (un método va a la tabla
  de métodos), `exporta`/`fusiona_hooks` (los métodos de una librería, en
  el tramo de sus hooks), `genericos_de`, `metodo` + `mapa_de`
  (`_call_member` + `_mapa_de`), `hook_de_llamada` y `hash_de`, `leido_de`
  y `hook_de_escritura` (`v[i]`, `v[i] = x`), `atrapa` y `local_con_dueno`
  (excepciones) y el `VarDecl` `inferido`.
- `hir/emisor.libsrx`: `ThrowStmt` (con el `move` implícito), `TryStmt` y
  `CatchClause`; los `type_params` de un método (`@impl` primero).

## 13. Los diagnósticos (lote 18a)

No es parte del HIR, pero es el otro contrato de la V1: con un programa con
errores, la MISMA lista que `driver/inspect.emit_diagnostics` de la V0, en el
mismo orden, con el mismo código, línea y columna (el texto es de cada una).
Verificado con `test/bootstrap/test_diagnosticos_v1.py` (el corpus de las
pruebas negativas y de gramática, y las sondas de
`test/bootstrap/v1_diagnosticos/`) y con el código de `collect.py`,
`scope_resolver.py`, `type_resolver.py` y `type_service.py`.

### 13.1 El canal

- Orden: los léxicos, los de sintaxis y —solo si el parseo fue limpio— los
  semánticos (`collect`, después `scope_resolver`). No se ordenan: salen en
  el orden en que se encuentran.
- Severidad: todos detienen la compilación salvo `SEM030` (aviso) y
  `NOTE001` (nota). Con uno que detiene no hay `.phir`; con solo avisos, el
  `.phir` es el mismo que sin ellos.
- Nunca se emiten: `AST001`-`AST004`, `AST007`-`AST011` (`AST008` incluido).
  `SEM017` es el límite de recursión de Python: la V1 no lo reproduce.

### 13.2 El orden de la Semántica

- `collect`, en el orden de los items. Un struct: campos repetidos (en el
  campo), parámetro de tipo que choca con un tipo de verdad (en el struct),
  nombre repetido (en el struct). Un enum: variante repetida en el mismo enum
  (en la variante, se salta), variante que choca con un valor (en la
  variante, queda como miembro), nombre repetido (en el enum). Una función:
  parámetro de tipo que choca, nombre repetido (en la función).
- `scope_resolver`: PRIMERO las firmas de todas las funciones (cada
  parámetro en su posición; el retorno en la de la función, donde `void`
  vale); DESPUÉS, en el orden de los items, los cuerpos, los campos de cada
  struct (en el campo), el payload de cada enum (en la variante) y las
  globales (en la declaración).
- La V1 resuelve los tipos ANTES (al recoger) y los VALIDA después, en el
  punto de la V0 (`valida_tipo`, `valida_declarado`): validar y resolver
  van separados para que el orden sea el de la V0.

### 13.3 Las posiciones

- Un tipo escrito se informa en la posición de quien lo escribe: la
  declaración (variable, parámetro, campo, `catch`), la función (su
  retorno), la variante (su payload), el literal de struct, el `cast`, la
  llamada (sus argumentos de tipo).
- `SEM001`: el identificador; el destino de una asignación; la llamada a un
  nombre que no existe; el miembro (`p.z`, `Color.MORADO`); el literal de
  struct (un campo que no tiene); el objeto de `noexiste.x`.
- `AST006`: la declaración (inicializar), la asignación, el VALOR (campo de
  un literal), el ARGUMENTO (llamada), la condición, el operando de un
  lógico, el literal (rango), el operador (aritmética, comparación);
  `AST012`: el `return`; `SEM008`: la llamada.
- Un tipo que no existe NO desaparece: queda como un nominal con el nombre
  escrito, y eso decide las cascadas (`AST005` y después `AST006`). Un tipo
  desconocido (sin tipo, o `error` sin envolver) nunca da un `AST006`.

### 13.4 Lo que la V0 inserta

El chequeo de tipos de la V0 REESCRIBE el árbol en dos casos: la conversión
implícita de un literal (`var byte b = 5;`, `var dt.int8 x = 5;`) y el
`hook` de un `cast` por un `__cast__` declarado. La V1 da los mismos
diagnósticos pero todavía no los emite: quedan marcados (`Analisis.no_emitible`)
y la compilación se detiene diciéndolo, como todo lo que queda fuera del
subconjunto.

### 13.5 El final de la Semántica

Después de recorrer todos los cuerpos, en este orden:

1. `verificar_copias` (`SEM038`): qué copia cada cuerpo genérico (pasar,
   ligar, asignar, devolver o poner en un campo un valor de un parámetro de
   tipo), propagado por las llamadas entre genéricos (con tope), y cada
   INSTANCIA con tipos concretos que copiaría un valor con destructor, en la
   llamada. Las copias de un genérico de librería salen de resolver sus
   cuerpos genéricos al cargarla (`run_generics`); lo que esa resolución dice
   se descarta.
2. `memory_check` (`SEM004`, `SEM005`, `SEM023`, `SEM024`): rutas estáticas
   movidas o liberadas, función por función (la V1: `semantica/muertos.libsrx`).
   El `throw r;` que cede con un `move` implícito cuenta como ese `move`.
3. Las NOTAS (`NOTE001`, `NOTE002`), después de todos los errores.

### 13.6 El linker

- Lo que dice un `#import`/`#from` va en su lugar del orden de los items,
  aunque la librería se cargue antes.
- No encontrada: `SEM009`. No compila: sus errores léxicos/de sintaxis con
  SU archivo y SU posición, y un `SEM010` en el import. Sin `#export`, o
  con el `package` que no corresponde: `SEM010` con el archivo de la
  librería y la posición del import. Alias distinto, ciclo, subpaquetes
  anidados: `SEM010` en el import. Los errores del `collect` de la librería
  (y de las que ella importa), con su archivo, UNA vez por compilación.
- Un submódulo de paquete que no compila no hace fallar al paquete: sus
  errores se dicen cuando un import lo pide (`pq.roto`, o `#import pq`).
- `#from lib #import x`: privado y de otro paquete, `SEM019`; interno o
  inexistente, `SEM011` (inexistente: el nombre se liga igual, opaco).
- Una librería que no carga deja el nombre como import OPACO: sus usos
  callan (ni `SEM011` ni `AST005`), pero un tipo escrito a través de él
  queda con su nombre y puede dar un `AST006`.
- `NOTE001` (un `.srcx` usado como librería): con el archivo del `.srcx` y
  la posición del import.
