# Sintaxis de suriaX

Visión legible de la sintaxis del lenguaje. La definición formal está en
[gramar/grammar.ebnf](gramar/grammar.ebnf) y el detalle de tipos/tokens en
[gramar/t_types.md](gramar/t_types.md).

> - Estado: la sintaxis está **diseñada** casi que completamente.
> - Estado: **en progreso**: terminar el parser.

## Reglas generales

- El `;` termina toda sentencia (**obligatorio**).
- Bloques con `{ }`.
- Comentarios: `//` (una línea) y `/- ... -/` (multilínea).
- Tipado estático fuerte y nominal: todo binding/parametros lleva su tipo.
- palabras como `printf`/`print` no son keywords nativos, vienen de librerías (libsrX) y se invocan como `alias.fn(args)`.

## Ejemplos

```srcx
// importación
const IO = #import IO;

// función
fn suma(int a, int b) -> int {
    return a + b;
}

// variables
const int x = 10;
var int y = 0;
int z = 3;

// control de flujo
if (x > 0) {
    IO.printf("positivo");
} else {
    IO.printf("negativo");
}

while (y < x) {
    y = y + 1;
}

// memoria: region-based + move-semantics
region scratch {
    int ptr p = make int in scratch;
    move p;
}   // se libera toda la región
```

## Secciones

- Declaraciones: funciones, `struct`, `enum`, `type` (pendiente).
- Visibilidad (prefijo opcional, default público): `public`/`private`/`internal`.
- Métodos especiales: `hook fn __x__` (set fijo del compilador) / `dunder fn __x__` (libre).
- Sentencias: `var`, `if`, `while`, `match`, `return`, `break`, `continue`.
- Expresiones: aritméticas, comparación, lógicas, llamadas, acceso `.`.
- Memoria: `region` (mods `shrd`/`mutable`/`na`), `new`/`delete`/`in region`,
  `move region a -> region b`, `make ... in`, `at`, `move`, `ptr`/`&`/`?`.
- Directivas: `#import`, `#export`, `#from`, `#test`, `#extern cpp{}`.

## Ejemplos

- [Hello, world!](examples/helloworld.md) — import de librería e interpolación.
- [Regiones y move-semantics](examples/regions.md) — ejemplo completo de memoria.
- [Structs, enums y control de flujo](examples/structs_and_control.md) — `match`/`case`, `if`/`while`.
- [Escribir una librería `.libsrx`](examples/library_libsrx.md) — librería nativa con `#export`.

## TODO

- [ ] Fijar la sintaxis de `type` o borrarlo.
- [ ] Guía de estilo del lenguaje.
