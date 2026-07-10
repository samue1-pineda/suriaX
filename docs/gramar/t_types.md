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
```

### type (token reservado, sintaxis pendiente)

El token `TYPE` (`type`) existe y se reserva para definir alias/tipos a partir de
un `struct`, pero **su gramática aún no está fijada**. es decir aun no tiene una funcion especifica.

```
type definition:   (pendiente de diseño)
```

---

## 3. Modificadores de tipo (memoria)

Modelo de memoria: **region-based + move-semantics**.

```
ptr definition:    ptr <type> <name> = <expr>;            // ptr int p = &x;
address (&):       & <name>                                // &x  -> dirección
nullable (?):      <type>? <name> = null;                 // int? opt = null;
```

| Token     | Lexema | Uso                                            |
|-----------|--------|------------------------------------------------|
| `POINTER` | `ptr`  | Tipo puntero: `ptr int`.                       |
| `ADDRESS` | `&`    | Operador de dirección: `&x`.                   |
| `NULLABLE`| `?`    | Tipo nullable: `int?` (admite `null`).         |

---

## 4. Bindings (declaración de variables)

```
variable definition:  [const | mutable] <type> <name> = <expr>;

const definition:      const <type> <name> = <expr>;      // const int x = 10;
mutable definition:    mutable <type> <name> = <expr>;     // mutable int y = 0;
```

`const` produce un binding inmutable; `mutable` permite reasignación. El `;`
final es **obligatorio**.

---

## 5. Funciones

```
fn definition:     fn <name> ( <type> <param>, ... ) -> <return_type> { <block> };

// ejemplo:
fn suma(int a, int b) -> int {
    return a + b;
};

//decorator definition:  @<name>  (sobre la línea de la función, estilo  tomado de Python)
    @test
    fn caso() -> void { ... }
```

| Token       | Lexema   | Uso                                         |
|-------------|----------|---------------------------------------------|
| `FUNCTION`  | `fn`     | Declara una función.                        |
| `ARROW`     | `->`     | Tipo de retorno: `fn f() -> int`.           |
| `RETURN`    | `return` | `return <expr>;`                            |
| `SIZEOF`    | `sizeof` | `sizeof(<type>)`                            |
| `DECORATOR` | `@`      | `@<name>` sobre la función.                 |
| `TEST`      | `test`   | Función nativa de prueba ≠ `#test`.         |

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

---

## 7. Memoria: regiones y move-semantics

```
region definition:    region <name> { <block> };      // libera todo al cerrar
make ... in:          make <type> in <region>         // make int in scratch
at definition:        <expr> at <region>              // z = promedio(...) at scratch
move definition:      move <expr>;                    // transfiere la propiedad
alloc definition:     alloc <type>;
free definition:      free <expr>;
```

Ejemplo:

```
region scratch {
    ptr int y = make int in scratch;
    int z = compute(y) at scratch;
    move y;
}   // aquí se libera toda la región 'scratch'
```

| Token    | Lexema   | Uso                                        |
|----------|----------|--------------------------------------------|
| `REGION` | `region` | Declara una región de memoria.             |
| `IN`     | `in`     | Asocia a una región (`make T in r`).       |
| `AT`     | `at`     | Ubica un valor en una región (`x at r`).   |
| `MOVE`   | `move`   | Transferencia de propiedad.                |
| `MAKE`   | `make`   | Construye un valor (en una región).        |
| `ALLOC`  | `alloc`  | Reserva explícita.                         |
| `FREE`   | `free`   | Liberación explícita puntual.              |

---

## 8. Operadores

```
arithmetic:   <expr> ( + | - | * | / ) <expr>
comparison:   <expr> ( == | != | < | <= | > | >= ) <expr>
logical:      <expr> ( and | or ) <expr>   |   not <expr>
assign:       <name> = <expr>;
```

| Categoría   | Tokens                                                        |
|-------------|---------------------------------------------------------------|
| Aritméticos | `PLUS +` `MINUS -` `MULTIPLY *` `DIVIDE /`                     |
| Comparación | `EQUAL ==` `NOT_EQUAL !=` `LESS <` `LESS_EQUAL <=` `GREATER >` `GREATER_EQUAL >=` |
| Lógicos     | `AND and` `OR or` `NOT not`                                    |
| Asignación  | `ASSIGN =`                                                    |

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

## 10. Strings con interpolación

```
string definition:    "<text>{<expr>}<text>"
llave literal:        "{{"  ->  {        "}}"  ->  }
```

El `value` del token `STRING_LIT` es un `StringValue` con segmentos en orden
(texto literal e `Interp`):

```
"hola{a}"     ->  Str(['hola', Interp('a')])
"{x} y {z}"   ->  Str([Interp('x'), ' y ', Interp('z')])
"{{ }}"       ->  Str(['{ }'])
```

Los literales de **carácter** (`'x'`) **no** interpolan.

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
| `DUNDER`| **Reservado, aún no emitido.** Pensado para `__foo__` (p. ej. `__str__`), pero hoy el lexer los tokeniza como `IDENTIFIER`. |

---

## Estado de implementación

Casi todos los tokens de este documento **ya los produce el lexer** (verificable
con `#test lexer`). La única excepción es `DUNDER`, que está **reservado en el
enum pero aún no se emite** (los `__foo__` salen como `IDENTIFIER`). El **parser**
que combina estos tokens según la
[gramática](grammar.ebnf) **aún no está implementado**, por eso la semántica de
cada construcción (tipado nominal, regiones, move) es trabajo de fases
posteriores. 

observe [how_to_run.md](../../how_to_run.md) para probar.
