# Sintaxis de suriaX

Visión legible de la sintaxis del lenguaje. La definición formal está en
[gramar/grammar.ebnf](gramar/grammar.ebnf) y el detalle de tipos/tokens en
[gramar/t_types.md](gramar/t_types.md).

> - Estado: la sintaxis está **diseñada** e **implementada**: el parser la
>   cubre entera y la suite la prueba regla a regla (`test/grammar/`).
> - Lo que no existe todavía (p. ej. literales de arreglo `[1, 2, 3]`) está
>   en [c_errorstfix.md](../c_errorstfix.md).

## Reglas generales

- El `;` termina toda sentencia (**obligatorio**).
- Bloques con `{ }`.
- Comentarios: `//` (una línea) y `/- ... -/` (multilínea).
- Tipado estático fuerte y nominal: todo binding/parametros lleva su tipo.
- palabras como `printf`/`print` no son keywords nativos, vienen de librerías (libsrX) y se invocan como `alias.fn(args)`.

## Ejemplos

```srcx
// importación
#from io #import stdp
#import mem

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
    stdp.println("positivo");
} else {
    stdp.println("negativo");
}

while (y < x) {
    y = y + 1;
}

// memoria: ownership + move-semantics
int ptr mutable p = mem.reserve<int>(1);
int ptr mutable q = move p;      // 'p' deja de ser utilizable
mem.release<int>(q);             // un bloque crudo se devuelve a mano
```

## Secciones

- Declaraciones: funciones, `struct`, `enum`, `type` (metatipo: `const type int8;` declara un nominal opaco; ver [t_types.md](gramar/t_types.md)).
- Visibilidad (prefijo opcional, default público): `public`/`private`/`internal`.
- Métodos especiales: `hook fn __x__` (set fijo del compilador) / `dunder fn __x__` (libre).
- Sentencias: `var`, `if`, `while`, `match`, `return`, `break`, `continue`,
  `try`/`catch`/`throw`, `with`, y las pruebas `test "nombre" { expect (...); }`.
- Expresiones: aritméticas, comparación, lógicas, llamadas, acceso `.`,
  `cast<T>(x)`, el ternario `c ? a : b`, `??` sobre un `T?` y las lambdas
  (`lambda (int x) -> int: x * 2`).
- Memoria: `move`, `free`, `ptr`/`&`/`?`. Las arenas son un tipo de librería,
  no sintaxis (ver el modelo de memoria).
- Directivas: `#import`, `#export`, `#from`, `#test`, `#extern cpp{}`.

## Ejemplos

- [Hello, world!](examples/helloworld.md) — import de librería e interpolación.
- [Propiedad, drop y arenas](examples/ownership.md) — ejemplo completo de memoria.
- [Structs, enums y control de flujo](examples/structs_and_control.md) — `match`/`case`, `if`/`while`.
- [Escribir una librería `.libsrx`](examples/library_libsrx.md) — librería nativa con `#export`.

## TODO

- [ ] Guía de estilo del lenguaje.
