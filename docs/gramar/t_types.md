# Tipos y tokens de suriaX

Documento de referencia de los **tipos del lenguaje** y de los **tokens** que el
lexer produce, con su forma de uso. La fuente de verdad del enum es [`V0/include/t_types.py`](../../V0/include/t_types.py), la gramática completa está
en [`grammar.ebnf`](grammar.ebnf).

> Convención de este documento: cada construcción se documenta como
> `nombre definition: <forma de uso>`, p. ej.
> `while definition: while ( <condition> ) { <block> };`

---

## 1. Tipos primitivos

| Tipo   | Token  | Descripción                          |
|--------|--------|--------------------------------------|
| `int`  | `INT`  | Entero.                              |
| `float`| `FLOAT`| Coma flotante.                       |
| `bool` | `BOOL` | Lógico (`true` / `false`).           |
| `char` | `CHAR` | Un único code point Unicode.         |
| `str`  | `STR`  | Cadena Unicode (con interpolación).  |
| `void` | `VOID` | Ausencia de valor (retorno de fn).   |
| `byte` | `BYTE` | Entero SIN signo de 8 bits (0..255). |

> **Palabra clave de tipo ≠ literal.** El token de *tipo* es distinto del token
> del *literal* correspondiente, para que el parser nunca los confunda (p. ej.
> el tipo `str` frente a una cadena `"..."`):
>
> | Tipo (keyword) | Literal    | Ejemplo                    |
> |----------------|------------|----------------------------|
> | `INT`          | `INT_LIT`  | `int` vs `10`              |
> | `FLOAT`        | `FLOAT_LIT`| `float` vs `3.14`          |
> | `CHAR`         | `CHAR_LIT` | `char` vs `'A'`            |
> | `STR`          | `STRING_LIT`| `str` vs `"hola"`         |

Formas de uso:

```
int definition:    int <name> = <int_literal>;           // int edad = 25;
float definition:  float <name> = <float_literal>;        // float pi = 3.14;
bool definition:   bool <name> = ( true | false );        // bool ok = true;
char definition:   char <name> = '<code_point>';          // char c = 'A';
str definition:    str <name> = "<text>";                 // str s = "hola";
void definition:   fn <name>() -> void { <block> }        // tipo de retorno
```

### Literales especiales

```
null definition:   <type>? <name> = null;                 // int? x = null;
true/false:        bool <name> = true;  bool <name> = false;
```

| Token   | Lexema  |
|---------|---------|
| `TRUE`  | `true`  |
| `FALSE` | `false` |
| `NULL`  | `null`  |

---

## 2. Tipos compuestos / definidos por el usuario

### struct (nombre al final, estilo C)

```
struct definition:
    struct {
        <type> <field>;
        <type> <field>;
    } <Name>;

// ejemplo 
struct {
    int len;
    str str;
} __str__;
```

### enum 

```
enum definition:
    enum <Name> { <ITEM> [ = <expr> ] , <ITEM> , ... };

// ejemplo:
enum Color { Rojo, Verde, Azul };
enum Forma { Circulo(float), Rect(float, float), Nada };   // con payload
```

Un `struct` puede ser **genérico**: sus parámetros van con el nombre
(`struct { T valor; } Caja<T>;`) y se usa con sus argumentos
(`Caja<int>`, `Caja<int>{ valor: 7 }`). Una `fn` también (`fn make<T>(...)`).

| Token    | Lexema   |
|----------|----------|
| `STRUCT` | `struct` |
| `ENUM`   | `enum`   |
| `TYPE`   | `type`   |

### type (tipo nominal opaco + metatipo)

`type` declara un **tipo nominal opaco**: un tipo con nombre y **sin
representación escrita en suriaX** (no tiene campos como un `struct`). Su
layout lo aportan el backend o sus hooks (`__sizeof__`, `__min__`, `__max__`...).

```
type definition:   [const | var] type <Name> [ = <expr> ];   // const type int8;
```

Es la forma en que una **librería publica tipos no nativos** del lenguaje, y
el consumidor los usa igual que cualquier otro tipo:

```srcx
// lib/d_types/dt_variables.libsrx
const type int8;
const type float16;
#export as dt_variables
```

```srcx
// consumidor
#from d_types #import dt_variables as dt;
const dt.int8 abc = 5;      // tipo cualificado: 'int8' lo declara la librería
```

| Forma        | Significado                                                  |
|--------------|--------------------------------------------------------------|
| `const type T;` | El nombre `T` queda ligado a **ese** tipo para siempre.   |
| `type T;` / `var type T;` | `T` es redefinible (mismo modelo que las variables). |

#### `type` como metatipo (tipo de primera clase)

`type` también es un **tipo usable en una anotación**: es *el tipo de un
tipo*. Eso permite que una función devuelva un tipo como valor, y que un tipo
se calcule:

```srcx
fn _block_def(int len, int ptr cursor) -> type {
    return Opaco;                       // un tipo ES un valor de tipo 'type'
}

const type Blk = _block_def(4, cursor); // ...y puede calcularse
```

Por eso un nombre declarado con `type` vive en **los dos namespaces**: en el
de tipos (`const Opaco x;`) y en el de valores con tipo `type`
(`return Opaco;`) — mismo patrón que los items de un `enum`.

---

## 3. Modificadores de tipo (memoria)

Modelo de memoria: **ownership + move-semantics** (ver secc. 7).

`ptr` es un sufijo **POSTFIJO** (el tipo va primero): `char ptr` es "puntero
a char" — el `char *text` de C se escribe `char ptr text`. La forma prefija
`ptr char` **ya no es válida** (el parser sugiere la migración).

```
ptr definition:    <type> ptr <name> = <expr>;            // int ptr p = &x;
ptr mutable:       <type> ptr mutable <name> = <expr>;    // int ptr mutable q = &x;
address (&):       & <name>                                // &x  -> dirección
nullable (?):      <type>? <name> = null;                 // int? opt = null;
```

Los sufijos se aplican de izquierda a derecha, así que el orden desambigua
algo que en prefijo no se podía escribir:

| Escrito        | Significa                          |
|----------------|------------------------------------|
| `char ptr`     | puntero a char                     |
| `char ptr?`    | puntero **nullable** a char        |
| `char? ptr`    | puntero a (char nullable)          |
| `char ptr ptr` | puntero a puntero a char           |

| Token     | Lexema | Uso                                            |
|-----------|--------|------------------------------------------------|
| `POINTER` | `ptr`  | Tipo puntero POSTFIJO: `int ptr` (solo lectura a través de él) / `int ptr mutable` (escritura permitida). |
| `ADDRESS` | `&`    | Operador de dirección: `&x`. Es un operador **de expresión** (`&nombre`), no un modificador de tipo — `int &x` en un parámetro es un error. |
| `NULLABLE`| `?`    | Tipo nullable: `int?` (admite `null`).         |

---

## 4. Bindings (declaración de variables)

```
variable definition:  [const | var] <type> <name> = <expr>;

const definition:      const <type> <name> = <expr>;   // const int x = 10;  (inmutable)
var definition:        var <type> <name> = <expr>;     // var int y = 0;     (mutable)
implicit definition:   <type> <name> = <expr>;         // int z = 30;        (= var, estilo C)
```

`const` produce un binding inmutable; `var` uno mutable; **sin cualificador
equivale a `var`** (estilo C). El `;` final es **obligatorio**.

| Token     | Lexema    |
|-----------|-----------|
| `CONST`   | `const`   |
| `VAR`     | `var`     |
| `MUTABLE` | `mutable` |

> **`mutable` ya NO califica variables** (cambio de diseño): quedó
> reservado para los tipos puntero — `T ptr mutable` permite escribir a
> través del puntero, `T ptr` es de solo lectura a través de él (ver
> secc. 3 y `grammar.ebnf` regla `type`). Un `mutable int x` produce un
> error de sintaxis con la sugerencia de usar `var`.

---

## 5. Funciones

```
fn definition:     fn <name> ( <type> <param>, ... ) -> <return_type> { <block> };
fn (sin retorno):  fn <name> ( ... ) { <block> };          // '->' opcional = void
fn prototipo:      fn <name> ( ... ) -> <return_type>;      // ';' = solo firma

// ejemplo:
fn suma(int a, int b) -> int {
    return a + b;
};

// prototipo: la firma se publica, la implementa el backend / #extern
fn put_char(char c) -> void;

//decorator definition:  @<name>  (sobre la línea de la función, estilo  tomado de Python)
    @test
    fn caso() -> void { ... }
```

El `->` es **opcional** (sin él, el retorno es `void`); un `;` en lugar del
cuerpo declara un **prototipo** (solo la firma).

| Token       | Lexema   | Uso                                         |
|-------------|----------|---------------------------------------------|
| `FUNCTION`  | `fn`     | Declara una función.                        |
| `LAMBDA`    | `lambda` | Una función sin nombre como argumento: `lambda (int x) -> bool: x > 3` o `lambda (int x) -> bool { ... }`. El `->` es obligatorio. |
| `ARROW`     | `->`     | Tipo de retorno (opcional): `fn f() -> int`. |
| `RETURN`    | `return` | `return <expr>;`                            |
| `SIZEOF`    | `sizeof` | `sizeof(<type>)`                            |
| `DECORATOR` | `@`      | `@<name>` sobre la función.                 |
| `TEST`      | `test`   | Una prueba: `test "nombre" { ... }` ≠ `#test`. |
| `EXPECT`    | `expect` | La comprobación de un `test`: `expect (cond);`. Solo dentro de su cuerpo. |
| `ERRFINALLY` | `errfinally` | Cláusula de un `test`: corre solo si la prueba falló. |
| `HOOK`      | `hook`   | Antes de `fn`: método del set fijo de hooks (`hook fn __free__(...)`). |
| `DUNDER_KW` | `dunder` | Antes de `fn`: método especial LIBRE (`dunder fn __x__(...)`), sin significado especial. |

### 5.1 Reservas de visibilidad (`public` / `private` / `internal`)

Prefijo **opcional** de una declaración de nivel superior (`fn`, `struct`,
`enum`, `type`, bindings; **no** directivas). Sin token = **`public`**.

```
public fn api() -> void { ... }          // usable al importar el archivo/librería
private fn helper() -> void { ... }       // solo entre archivos del MISMO paquete
internal fn secreto() -> void { ... }     // exclusivo de ESTE archivo
```

| Token      | Lexema     | Uso                                        |
|------------|------------|--------------------------------------------|
| `PUBLIC`   | `public`   | Visibilidad global (el default sin token). |
| `PRIVATE`  | `private`  | Visible solo dentro del mismo paquete.     |
| `INTERNAL` | `internal` | Visible solo dentro del mismo archivo.     |

El enforcement es de la Semántica + `linker_p`: `internal` nunca se exporta;
`private` solo se ve entre archivos del mismo paquete; `public` siempre.

> Los métodos especiales `__x__` **ya no se adivinan por la forma**: un `hook`
> debe pertenecer al set fijo (`semantic/hooks.py`, si no → `SEM018`); un
> `dunder fn __x__(T ptr self)` es un **método libre del usuario** indexado por
> su tipo dueño (un "hook del usuario", despachado con `x.__x__()`); un `fn
> __x__` a secas es una función corriente. La visibilidad va **antes** del
> especificador: `private hook fn __free__(...)`.

### 5.2 Traits (`@trait` / `@impl`) y decoradores generalizados

Un **trait** es un contrato con nombre = conjunto de firmas de método dunder,
definido por el usuario y **verificado por el compilador** (no cableado en él):

```
@trait struct { fn __next__(self ptr) -> int?; } iterable;   // el contrato
dunder fn __next__(Lista ptr self) -> int? { ... }            // el metodo real
@impl(iterable) struct { int pos; } Lista;                    // se VERIFICA (SEM021)
```

`self` en un prototipo de trait es el tipo que hará `@impl` (no es keyword).

Un bloque `@impl Tipo { ... }` (sin argumentos) declara MÉTODOS de nombre
llano, con el receptor explícito como primer parámetro:

```
@impl Vector<T> {
    fn push(Vector<T> ptr mutable self, T x) -> void { ... }   // v.push(x)
}
```
Los **decoradores** se generalizaron: admiten argumentos (`@impl(iterable)`),
aplican a `fn`/`struct`/`enum`, y van **antes** de la visibilidad/especificador
(`@impl(x) public struct ...`). Ver `grammar.ebnf` (`decorator_decl`,
`trait_body`) y [lib/HOOKS.md](../../lib/HOOKS.md).

---

## 6. Control de flujo

```
if definition:        if ( <condition> ) { <block> }; [ else { <block> }; ]
while definition:      while ( <condition> ) { <block> };
match definition:      match ( <expr> ) { case <pattern>: <stmt> ... };
case definition:       case <pattern>: ( <stmt> | { <block> } );
return definition:     return [ <expr> ];
break definition:      break;
continue definition:   continue;
```

| Token      | Lexema     |
|------------|------------|
| `IF`/`ELSE`| `if`/`else`|
| `WHILE`    | `while`    |
| `MATCH`    | `match`    |
| `CASE`     | `case`     |
| `BREAK`    | `break`    |
| `CONTINUE` | `continue` |

### Excepciones y `with`

```
throw definition:     throw <expr>;
try definition:       try { <block> } catch ( [<type>] <name> ) { <block> } ... [ finally { <block> } ]
with definition:      with ( <recurso o valor> ) { <block> }    // RAII: se destruye al salir
```

| Token       | Lexema    | Uso                                                      |
|-------------|-----------|----------------------------------------------------------|
| `THROW`     | `throw`   | Lanza un valor (cede su propiedad).                      |
| `TRY`       | `try`     | Bloque protegido.                                        |
| `CATCH`     | `catch`   | Rama que atrapa (con tipo, solo ese tipo).               |
| `FINALLY`   | `finally` | Corre al salir del `try` por cualquier camino; tras un `test`, siempre. |
| `ERRORTYPE` | `error`   | Tipo `error T`: un valor o un error.                     |
| `WITH`      | `with`    | Recurso, guardián o receptor con ámbito (`.campo`).      |

---

## 7. Memoria: ownership y move-semantics

Cada valor con recursos tiene **un dueño**; la destrucción ocurre al cerrar el
ámbito que lo posee, invocando el `__free__` de su tipo. Eso no tiene
sintaxis: la llave que cierra ES el punto de destrucción. Solo dos sentencias
escriben algo:

```
move definition:      move <expr>;    // transfiere la propiedad; invalida el origen
free definition:      free <expr>;    // destruye ANTES del cierre del ámbito
```

| Token  | Lexema | Uso                                              |
|--------|--------|--------------------------------------------------|
| `MOVE` | `move` | Transferencia de propiedad de un valor.          |
| `FREE` | `free` | Destrucción anticipada (exige un puntero).       |

> **Retirados en v0.2.0 con el modelo por regiones**: `REGION` (`region`),
> `SHRD` (`shrd`), `NA` (`na`), `IN` (`in`), `AT` (`at`), `NEW` (`new`),
> `DELETE` (`delete`) y `MAKE` (`make`) — 8 de las 50 palabras reservadas que
> tenía el lenguaje, el 16 %. `MUTABLE` sigue, pero solo calificando punteros
> (`ptr mutable T`). Los valores 40-42, 44-45, 47-48 y 57-58 de `TokenType`
> quedan retirados y **no se reutilizan**: un volcado de tokens viejo mostraría
> un nombre distinto para el mismo número y no habría cómo notarlo. El
> razonamiento del retiro está en
> [memory_decision.rst](../../documentation/source/memory_decision.rst).

> `alloc` tampoco es keyword: la reserva "cruda" la aporta una librería
> (p. ej. una `fn alloc(...)` publicada por un `.libsrx`).

### Conversión explícita: `cast`

```
cast definition:      cast<type>(expr)        // int8 b = cast<int8>(10);
```

| Token  | Lexema | Uso                                                        |
|--------|--------|------------------------------------------------------------|
| `CAST` | `cast` | Conversión explícita — la ÚNICA vía de cambio de tipo (el lenguaje no tiene coerciones implícitas). Nativa entre primitivos numéricos (`int`↔`float`, `int`↔`char`, `bool`→`int`); con un tipo nominal involucrado despacha al hook `__cast__` de ese tipo. |

Los ángulos `<...>` de `cast` son la posición de **argumentos de tipo**
(`type_args` en el EBNF), compartida: los genéricos de librería (`vec<int>`)
usarán la misma regla.

---

## 8. Operadores

```
arithmetic:   <expr> ( + | - | * | / | % ) <expr>
bits:         <expr> ( & | | | ^ | << | >> ) <expr>   |   ~ <expr>
comparison:   <expr> ( == | != | < | <= | > | >= ) <expr>
logical:      <expr> ( and | or ) <expr>   |   not <expr>
unwrap:       <expr> ?? <expr>          (x: T?, d: T -> T)
assign:       <name> ( = | += | -= | *= | /= | %= | &= | |= | ^= | <<= | >>= ) <expr>;
step:         <name>++;   <name>--;
```

| Categoría   | Tokens                                                        |
|-------------|---------------------------------------------------------------|
| Aritméticos | `PLUS +` `MINUS -` `MULTIPLY *` `DIVIDE /` `MODULO %`          |
| Bits        | `ADDRESS &` `PIPE \|` `CARET ^` `TILDE ~` `SHIFT_LEFT <<` `SHIFT_RIGHT >>` |
| Comparación | `EQUAL ==` `NOT_EQUAL !=` `LESS <` `LESS_EQUAL <=` `GREATER >` `GREATER_EQUAL >=` |
| Lógicos     | `AND and` `OR or` `NOT not`                                    |
| Opcional    | `NULL_COALESCE ??` (lo arma el parser: dos `NULLABLE` pegados) |
| Asignación  | `ASSIGN =` `PLUS_ASSIGN +=` `MINUS_ASSIGN -=` `STAR_ASSIGN *=` `SLASH_ASSIGN /=` `PERCENT_ASSIGN %=` `AMP_ASSIGN &=` `PIPE_ASSIGN \|=` `CARET_ASSIGN ^=` `SHIFT_LEFT_ASSIGN <<=` `SHIFT_RIGHT_ASSIGN >>=` |
| Paso        | `INCREMENT ++` `DECREMENT --` (solo como sentencia: `i++;`)    |

`&` es a la vez la dirección (`&x`, prefijo) y el y de bits (`a & b`, infijo).

Qué compara cada operador de comparación lo decide el tipo, no la gramática:
`==` es igualdad de **valor** (un `struct` campo a campo, un enum con datos
por variante y payload, un puntero por su dirección) salvo que el tipo declare
`__eq__`; `<`, `<=`, `>`, `>=` ordenan los números, `char`, `str`, `byte` y
los enums sin datos, y un tipo propio que declare `__cmp__`. Ver
`documentation/source/type_system.rst` (Igualdad y orden).
La precedencia, de menor a mayor: asignación, `??`, `or`, `and`, igualdad,
comparación, `|`, `^`, `&`, desplazamientos, suma, producto; los unarios y
los sufijos (`.`, `()`, `[]`) ligan más fuerte (ver `grammar.ebnf`). La
asignación y `??` asocian por la derecha (`a ?? b ?? c` es `a ?? (b ?? c)`).

`??` desenvuelve un `T?`: vale el contenido de `x` si no es `null` y, si lo
es, `d`, que solo entonces se evalúa. `d` tiene que ser exactamente el `T`.
Como `>>`, el lexer no lo emite: son dos `?` pegados que el parser junta en
posición de operador, así que `int??` sigue siendo un tipo con dos sufijos.
Ver `documentation/source/type_system.rst` (Desenvolver un `T?`).

---

## 9. Delimitadores

| Token        | Lexema | Uso                          |
|--------------|--------|------------------------------|
| `L_PAREN`/`R_PAREN`    | `(` `)` | Agrupación / argumentos.   |
| `L_BRACE`/`R_BRACE`    | `{` `}` | Bloques / cuerpos.         |
| `L_BRACKET`/`R_BRACKET`| `[` `]` | Indexación / colecciones. |
| `DOT`        | `.`    | Acceso a miembro: `IO.printf`.|
| `COMMA`      | `,`    | Separador.                   |
| `SEMICOLON`  | `;`    | Terminador de sentencia (obligatorio). |
| `COLON`      | `:`    | Asociación / rama de `case`. |

---

## 10. Strings: planos y f-strings (interpolación opt-in)

La interpolación es **opt-in** con el prefijo `f` (decisión de diseño: así
`print` — texto plano — y `printf` — formateado — son operaciones distintas):

```
cadena plana:         "<text>"            // '{' y '}' son literales
f-string:             f"<text>{<expr>}<text>"
llave literal (solo f-string):  "{{"  ->  {        "}}"  ->  }
```

Ambas formas producen el mismo token `STRING_LIT`; su `value` es un
`StringValue` con segmentos en orden (texto literal e `Interp`). Las fases
posteriores distinguen por `StringValue.is_interpolated`:

```
"hola{a}"      ->  Str(['hola{a}'])                  // plano: sin Interp
f"hola{a}"     ->  Str(['hola', Interp('a')])
f"{x} y {z}"   ->  Str([Interp('x'), ' y ', Interp('z')])
f"{{ }}"       ->  Str(['{ }'])
```

Los literales de **carácter** (`'x'`) **no** interpolan y no admiten prefijo.

---

## 11. Directivas e interoperabilidad

```
import definition:    #import <lib> [ as <alias> ];      // #import IO as InputOutput
export definition:    #export <alias>;                   // cierra una .libsrx
from definition:      #from <lib> #import <name>;
test definition:      #test <fase>;                       // #test lexer  (orquestador)
extern definition:    #extern cpp{ <c++ crudo> };         // RAW_BLOCK, no se tokeniza
```

| Token       | Lexema     | Uso                                          |
|-------------|------------|----------------------------------------------|
| `DIRECTIVE` | `#<nombre>`| `import`/`export`/`extern`/`test`/`from`.    |
| `RAW_BLOCK` | `{ ... }`  | Cuerpo C++ crudo de `#extern cpp{...}`.      |

> Las funciones de librería (`printf`, etc.) **no** son tokens: son `IDENTIFIER`
> resueltos contra el alias importado y se invocan como `alias.fn(args)`.

---

## 12. Tokens internos

| Token   | Uso                                                          |
|---------|--------------------------------------------------------------|
| `EOF`   | Marca el fin del flujo de tokens. Siempre el último.         |
| `ERROR` | Token sintético emitido ante un error léxico (recuperación). |
| `DUNDER`| `__foo__` (empieza y termina en `__`, ≥1 caracter dentro). El lexer reconoce la FORMA para cualquier nombre, sin validar una lista cerrada; qué nombres son *hooks* de tipo reconocidos lo decide la fase Semántica (`semantic/hooks.py`), que valida la firma completa y enlaza el despacho: `free x;` y el cierre del ámbito→`__free__`, `sizeof(T)`→`__sizeof__`, `print(x)`/`x.print()`→`__print__`, `len(x)`/`x.len()`→`__len__`, `cast<T>(x)`→`__cast__`, `v[i]`→`__index__`, `v[i] = x`→`__index_set__`, `a == b`→`__eq__`, `a < b` (y `<=`, `>`, `>=`)→`__cmp__`, `hash(x)`→`__hash__`. `__min__`/`__max__` no los dispara ninguna sintaxis: los LEE el compilador para decidir si un literal cabe en un tipo numérico de librería. Un `__foo__` no reconocido se trata como una función normal, sin error. |

---

## Estado de implementación

Todos los tokens de este documento **los produce el lexer** (verificable con
`#test lexer`), y todas las construcciones las implementa el compilador de
punta a punta: parser, AST-tipado, Semántica (símbolos, tipos, propiedad,
hooks, genéricos, excepciones) y HIR. El compilador escrito en suriaX
(`src/`) reproduce el mismo lexer y el mismo parser. Lo que todavía falla está
en [c_errorstfix.md](../../c_errorstfix.md).

observe [how_to_run.md](../../how_to_run.md) para probar.
