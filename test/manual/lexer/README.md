# Prueba del lexer de suriaX

Esta carpeta contiene una prueba funcional del **front-end léxico**: lee un
archivo `.srcx`, lo decodifica a Unicode, genera el arreglo de tokens y lo
vuelca a consola a través de la directiva `#test lexer`.

## Archivos

| Archivo         | Qué es                                                              |
|-----------------|--------------------------------------------------------------------|
| `run_lexer.py`  | Script orquestador (reader → lexer → parser).                      |
| `sample.srcx`   | Código de ejemplo que empieza con `#test lexer`.                   |
| `printf.srcx`   | Ejemplo de `printf` + interpolación de strings.                   |
| `README.md`     | Este documento.                                                    |

## Cómo ejecutarlo

Desde esta misma carpeta:

```bash
python run_lexer.py            # usa sample.srcx
python run_lexer.py otro.srcx  # tokeniza otro archivo
```

El script añade la raíz del paquete (`V0/`) a `sys.path`, así que **no** hace
falta instalar nada ni configurar `PYTHONPATH`. Requiere Python 3.10+ (se usa
`match`, `slots=True` en dataclasses y anotaciones diferidas).

## Qué hace internamente

El pipeline ejercitado es:

```
archivo .srcx
   │
   ▼  source_reader.read_file()      → decodifica UTF-8 a str (una sola vez)
str fuente
   │
   ▼  Lexer.tokenize()               → list[Token] terminada en EOF
tokens
   │
   ▼  Parser.run_test_directive()    → detecta '#test lexer' y vuelca tokens
salida en consola
```

1. **`source_reader`** (`src/frontend/lexer/source_reader.py`): decodifica los
   bytes UTF-8 a `str` y normaliza los saltos de línea (`CRLF`/`CR` → `LF`).
   Esta es la fase previa al lexer; ocurre una sola vez, fuera del bucle de
   tokenización.

2. **`Lexer`** (`src/frontend/lexer/lexer.py`): recorre el texto una vez.
   - mantiene el estado compartido (`pos`, `ln`, inicio de línea) y calcula la
     columna bajo demanda;
   - despacha en O(1) al scanner correcto según el primer carácter del token;
   - **salta los comentarios en el mismo paso**: `//` (una línea) y `/- -/`
     (multilínea);
   - devuelve una `list[Token]` que termina siempre en un token `EOF`.

3. **`Parser`** (`src/frontend/parser/parser.py`): aquí se usa *solo* para
   orquestar la directiva de prueba. Si el flujo empieza con `#test lexer`,
   imprime el arreglo completo de tokens usando el `__repr__` de `Token`. El
   parser real (descenso recursivo + Pratt) está completo y es el que usa
   `V0/main.py`; este script no lo ejercita a propósito, porque su objeto de
   estudio es el lexer.

## La directiva `#test lexer`

Es el disparador de la prueba. Si la **primera** directiva del archivo es
`#test` seguida del identificador `lexer`, el parser vuelca los tokens:

```
=== #test lexer  (N tokens) ===
[  0] Token(DIRECTIVE, '#test', 'test', 1:1)
[  1] Token(IDENTIFIER, 'lexer', 'lexer', 1:7)
[  2] Token(FUNCTION, 'fn', 'fn', 4:1)
...
[ N-1] Token(EOF, '', None, 29:1)
```

Cada línea es `Token(TIPO, lexema, valor, línea:columna)`.

> Si un archivo **no** empieza con `#test lexer`, `run_lexer.py` igualmente
> vuelca los tokens en modo *dump directo*, para que cualquier `.srcx` sirva
> como caso de prueba.

## `printf`, libsrX y la interpolación de strings

La filosofía de suriaX es **pocos tokens reservados**: casi todo (incluido
`printf`) viene de **librerías nativas** (`.libsrx`). Por eso `printf` **no** es
una palabra reservada; el lexer lo tokeniza como un `IDENTIFIER` normal:

```
printf("hola{a}");
```

produce:

```
IDENTIFIER('printf')  L_PAREN('(')  STRING_LIT(...)  R_PAREN(')')  SEMICOLON(';')
```

> El `;` es el **terminador de sentencia obligatorio** del lenguaje. El lexer
> emite el token `SEMICOLON`; exigir su presencia es tarea del parser.

### Interpolación

Dentro de un string entre comillas dobles, `{expr}` es una **interpolación**.
El `value` del token `STRING_LIT` no es un `str` plano sino un `StringValue` con
los segmentos en orden — texto literal (`str`) e interpolaciones (`Interp`):

| Fuente                       | `value` (StringValue)                                  |
|------------------------------|--------------------------------------------------------|
| `"hola"`                     | `Str(['hola'])`                                        |
| `"hola{a}"`                  | `Str(['hola', Interp('a')])`                           |
| `"{x} y {z}"`                | `Str([Interp('x'), ' y ', Interp('z')])`              |
| `""`                         | `Str([])`                                              |

- El lexer **solo delimita** la expresión; no la analiza. `Interp('a')` guarda
  el texto crudo `a`; el parser/runtime futuro lo interpretará como expresión.
- Para una **llave literal** se escribe `{{` o `}}` (estilo f-string de Python):
  `"{{ }}"` → `Str(['{ }'])`.
- Errores: `{` sin `}`, `{}` vacío, o `}` suelto producen `LEX002`
  (`InvalidTokenError`), con recuperación hasta el cierre del string.

> Los **literales de carácter** (`'x'`) **no** interpolan: son exactamente un
> code point Unicode.

### Nota sobre `#import` / `#export` (alcance léxico)

Las directivas de librería se tokenizan como `DIRECTIVE` + `IDENTIFIER`(s):

```
#import IO as InputOutput   →  DIRECTIVE('import')  IDENTIFIER('IO')  IDENTIFIER('as')  IDENTIFIER('InputOutput')
#export IO                  →  DIRECTIVE('export')  IDENTIFIER('IO')
```

Por ahora esto es **solo léxico**: el lexer captura los nombres/alias como
tokens, pero **no** resuelve archivos `.libsrx` en disco ni mantiene un registro
de alias. Esa resolución (que un `.libsrx` se cargue al verificar que termina en
`#export <alias>`) es trabajo futuro del parser/semántica.

## Errores léxicos

El lexer es **tolerante a fallos**: ante un error recuperable emite un token
`ERROR` (cuyo `value` es el código `LEXxxx`), registra el error y continúa.
Al final, `run_lexer.py` los lista:

```
=== errores lexicos ===
  LEX003: literal sin delimitador de cierre  (archivo.srcx:1:9)
```

Códigos que el lexer puede producir hoy (definidos en
`error_handler/lex_error.py`):

| Código  | Clase                            | Situación                                          |
|---------|----------------------------------|----------------------------------------------------|
| LEX001  | `UnexpectedCharacterError`       | Un carácter que no pertenece al alfabeto.          |
| LEX002  | `InvalidTokenError`              | Una secuencia que no forma ningún token válido.    |
| LEX003  | `UnterminatedStringError`        | Una cadena que no cierra antes del fin de línea.   |
| LEX004  | `UnterminatedCommentError`       | Un comentario de bloque sin `-/`.                  |
| LEX005  | `InvalidEscapeSequenceError`     | Un escape que no existe.                           |
| LEX006  | `NumericLiteralOverflowError`    | Un número fuera del rango representable.           |
| LEX007  | `InvalidNumberFormatError`       | Un literal numérico mal formado.                   |
| LEX008  | `InvalidUnicodeCharacterError`   | Un *code point* no válido.                         |
| LEX009  | `UnexpectedEOFError`             | El archivo termina a mitad de un token.            |
| LEX010  | `InvalidDirectiveError`          | Un `#` seguido de algo que no es una directiva.    |
| LEX011  | `InvalidIdentifierError`         | Un identificador que no cumple las reglas Unicode. |
| LEX012  | `InvalidCharacterLiteralError`   | Un literal de carácter vacío o con más de uno.     |
| LEX013  | `InvalidDecoratorError`          | Un `@` sin nombre válido detrás.                   |
| LEX014  | `UnterminatedExternBlockError`   | Un `#extern cpp{` sin llave de cierre.             |

> Esta tabla y la de [`errors.rst`](../../../documentation/source/errors.rst)
> salen del mismo `lex_error.py`, y una prueba de la suite comprueba que
> ningún código del compilador se quede sin documentar.

## Volcar otras fases

`#test` acepta hoy `lexer`, `parser`, `ast`, `sem` y `hir`, y lo mismo hace
`--emit-stage` sin tocar el archivo:

```bash
python V0/main.py archivo.srcx --emit-stage parser
```

Este script se queda en el lexer a propósito: es el banco de pruebas de esa
fase, no un segundo compilador.
