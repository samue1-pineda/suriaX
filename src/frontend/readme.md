# `src/frontend/` — el frontend de suriaX, escrito en suriaX

Primer paso del **bootstrap** (ver [`src/readme.md`](../readme.md)): el
lexer y el parser del compilador, escritos en el propio lenguaje. Son una
traducción de los de la V0 (`V0/src/frontend/lexer/` y `parser/`), módulo
por módulo, y producen **la misma salida**: los mismos tokens y el mismo
árbol, nodo por nodo.

```bash
suri src/frontend/volcado.srcx      # un programa de ejemplo, token a token
suri src/frontend/sintaxis.srcx     # el mismo tipo de programa, como árbol
```

| archivo | qué es | en la V0 |
|---|---|---|
| `tokens.libsrx` | `enum TType` (con los mismos números que la V0), `struct Token`, palabras reservadas | `include/t_types.py` |
| `lexer.libsrx` | `tokenizar(fuente, &errores)` → `Vector<Token>` terminado en `EOF` | `lexer/` |
| `arbol.libsrx` | el árbol en una **arena** y su volcado canónico | `include/ast_nodes.py` |
| `cursor.libsrx` | el estado del parser, la lectura de tokens y `ErrorDeSintaxis` | `parser/cursor.py`, `context.py` |
| `tipos.libsrx` | las anotaciones de tipo | `grammar/types.py` |
| `expresiones.libsrx` | el motor Pratt, los literales y las f-strings | `pratt.py`, `expressions/` |
| `directivas.libsrx` | `#import`, `#from`, `#export` | `grammar/directives.py` |
| `sentencias.libsrx` | bloques, declaraciones, control de flujo, excepciones | `grammar/statements.py` y afines |
| `declaraciones.libsrx` | `fn`, `struct`, `enum`, decoradores, `@impl`, `@trait`, `test` | `grammar/modifiers.py` y afines |
| `parser.libsrx` | el programa entero y la recuperación de errores | `grammar/program.py`, `recovery.py` |
| `volcado.srcx`, `sintaxis.srcx` | los dos programas de ejemplo | — |

## Cómo está hecho

- **El árbol vive en una arena.** El lenguaje no tiene tipos recursivos
  (un nodo no puede contener a sus hijos), así que todos los nodos están en
  un solo `Vector` y se enlazan por índice. Cada nodo guarda su primer hijo,
  su último hijo y su siguiente hermano: es la representación "primer hijo /
  siguiente hermano" de los libros de estructuras de datos. Los nodos son
  uniformes: la clase es un texto (`"FunctionDecl"`) y cada hijo sabe en qué
  campo de su padre cuelga.
- **Los errores de sintaxis son excepciones**, como en la V0: se lanza un
  `ErrorDeSintaxis` con `throw`, y el bucle del programa lo atrapa, lo anota
  y descarta la declaración rota. Por eso el parser es también la prueba
  más grande de `try`/`catch`.
- **Las interpolaciones se parsean en una ventana.** El texto de un `{expr}`
  se tokeniza aparte, sus tokens se añaden al final del vector y se parsean
  moviendo la ventana `[pos, fin]` (ver "Qué le faltó").

## Cómo se sabe que está bien

Los dos lexers usan los mismos números de clase, y los dos parsers escriben
el mismo **volcado canónico** del árbol:

```
campo: Clase linea:col escalar=valor ...
```

- **Lexer:** [`test_bootstrap_lexer.py`](../../test/bootstrap/test_bootstrap_lexer.py)
  compara token a token. Leyendo su propio fuente, los dos dan los mismos
  3833 tokens.
- **Parser:** [`test_bootstrap_parser.py`](../../test/bootstrap/test_bootstrap_parser.py)
  compara el árbol entero en:
  - expresiones, sentencias y declaraciones de toda la gramática;
  - un programa real (`fuego/inventario.srcx`) y la librería del vector;
  - **el propio `expresiones.libsrx`**, leyéndose a sí mismo: 3260 líneas
    de árbol idénticas.

  En 33 programas inválidos compara además el primer error de sintaxis.

## Qué encontró

Escribirlo encontró fallos que ninguna prueba veía:

- **En la V0, un dígito no ASCII (`²`, `٣`) era un error interno (ICE000).**
  `str.isdigit()` lo aceptaba y `int()` no podía convertirlo. Corregido:
  ahora es `LEX001`.
- **Una librería con errores daba un diagnóstico que despistaba**: una
  posición que no existía, y un "no tiene un submódulo" en cascada.
  Corregido: cada error sale en su sitio.
- **Relanzar desde un `catch (e)` perdía el tipo del valor**: un
  `catch (T x)` de más arriba ya no lo reconocía. El parser lo necesitaba
  para "limpiar y relanzar". Corregido en los dos motores.
- **Una f-string partida en dos líneas** (`f"a{x}"` y en la línea siguiente
  `f"b{y}"`) ubica la `y` en la línea de la PRIMERA cadena con la columna
  de la segunda. Está en `c_errorstfix.md`.

Y lo que le faltó al lenguaje (lo marcado **ya existe**: el código de aquí
todavía no lo usa):

| falta | consecuencia aquí |
|---|---|
| **Tipos recursivos** | El árbol es una arena de nodos enlazados por índice (ver arriba). |
| **Sacar un valor de un campo y dejar otro** (`mem::replace` de Rust) | Mover el vector de tokens fuera del `Parser` es mover a través de un puntero (SEM036). Las interpolaciones se parsean en una ventana al final del mismo vector. |
| **`finally`** (ya existe) | Restaurar el contexto pase lo que pase se escribe como `catch (e) { restaura; throw e; }`. |
| **Subcadenas y `str` → `int`** (ya existen: `text.slice`, `text.parse_int`) | `trozo` arma cada texto carácter a carácter y `entero` convierte los dígitos a mano. |
| **`.name` sobre una variable de enum** (ya existe: `f"{t}"` escribe el nombre) | `nombre_de` es un `match` de 86 ramas. |
| **Un diccionario en la librería estándar** (ya existe: `collections.Dictionary`) | Las palabras reservadas son un `match` sobre `str`. |
| **Tablas Unicode** | `inicia_nombre` es una aproximación: todo lo no ASCII que no sea un espacio cuenta como letra. |
| **Palabras reservadas como nombres** | `dunder` y `error` no pueden nombrar una variable. El diagnóstico dice "se encontro ERRORTYPE", no "es una palabra reservada". |
| **Comentarios de bloque anidados** | Un `-/` dentro de un comentario lo cierra. |

Diferencias conocidas con la V0, fuera de las pruebas:
- **`#extern cpp { ... }`:** el lexer no captura el bloque crudo y el parser
  lo rechaza (`PAR024`).
- **El anidamiento extremo:** en la V0 es `PAR025`; aquí agota la pila de
  suriaX (`RT019`), que no se puede atrapar.
- **La clase de los símbolos no ASCII**, por la aproximación de arriba.

## El compilador ya se compila a sí mismo

La meta era que la V1 leyera su propio fuente y emitiera un `.phir` IDÉNTICO,
byte a byte, al de la V0. Se cumplió (el punto fijo, lote 19): la V1 compila
sus 30 unidades —ella y cada librería que importa— igual que la V0, y
compilada por sí misma vuelve a dar lo mismo. Cómo se llegó, lote por lote,
y cómo reproducirlo, en [`src/readme.md`](../readme.md).

Este lexer y este parser fueron el primer tramo. Ningún bloqueo del lenguaje
apareció en el camino: lo que hizo falta fue volumen (la Semántica, el
linker y el emisor del HIR).
