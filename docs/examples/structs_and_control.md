# Structs, enums y control de flujo

Tipos compuestos (`struct`, `enum`) y control de flujo (`if`/`else`, `while`,
`match`/`case`). El programa del final se ejecuta tal cual con
`python main.py archivo.srcx`; los bloques anteriores son las piezas que lo
forman.

## struct

El nombre del `struct` va **después** de las llaves; cada campo es
`<tipo> <nombre>;`. Un valor se construye nombrando sus campos:

```srcx
struct {
    int x;
    int y;
} Punto;

var Punto p = Punto{ x: 3, y: 0 };
p.x = 0;              // acceso y escritura de campos con '.'
```

Un `struct` es un **valor**: `var Punto q = p;` copia, y cambiar `q` no toca
`p`. Para que una función lea o modifique el original sin copiarlo se le pasa
un **préstamo**: `Punto ptr` (solo lectura) o `Punto ptr mutable` (escritura),
con `&p` en la llamada.

## enum

```srcx
enum Cuadrante { ORIGEN, EJE, INTERIOR };

var Cuadrante c = Cuadrante.EJE;     // los valores se nombran con el tipo
```

## match / case

Cada rama nombra un valor y lleva su bloque. Si un `match` sobre un `enum` no
cubre todas las variantes, el compilador avisa (`SEM030`).

```srcx
fn describir(Cuadrante c) -> str {
    match (c) {
        case Cuadrante.ORIGEN: { return "origen"; }
        case Cuadrante.EJE: { return "sobre un eje"; }
        case Cuadrante.INTERIOR: { return "interior"; }
    }
    return "?";
};
```

## if / else y while

```srcx
fn fizzbuzz(int n) -> void {
    var int i = 1;
    while (i <= n) {
        if (i % 15 == 0) {
            stdp.println("FizzBuzz");
        } else {
            if (i % 3 == 0) {
                stdp.println("Fizz");
            } else {
                if (i % 5 == 0) {
                    stdp.println("Buzz");
                } else {
                    stdp.println(f"{i}");
                };
            };
        };
        i = i + 1;
    };
};
```

## Programa que junta todo

```srcx
#from io #import stdp

struct {
    int x;
    int y;
} Punto;

enum Cuadrante { ORIGEN, EJE, INTERIOR };

fn clasificar(Punto ptr p) -> Cuadrante {
    if (p.x == 0 and p.y == 0) {
        return Cuadrante.ORIGEN;
    };
    if (p.x == 0 or p.y == 0) {
        return Cuadrante.EJE;
    };
    return Cuadrante.INTERIOR;
};

fn describir(Cuadrante c) -> str {
    match (c) {
        case Cuadrante.ORIGEN: { return "origen"; }
        case Cuadrante.EJE: { return "sobre un eje"; }
        case Cuadrante.INTERIOR: { return "interior"; }
    }
    return "?";
};

fn fizzbuzz(int n) -> void {
    var int i = 1;
    while (i <= n) {
        if (i % 15 == 0) {
            stdp.println("FizzBuzz");
        } else {
            if (i % 3 == 0) {
                stdp.println("Fizz");
            } else {
                if (i % 5 == 0) {
                    stdp.println("Buzz");
                } else {
                    stdp.println(f"{i}");
                };
            };
        };
        i = i + 1;
    };
};

fn main() -> int {
    var Punto p = Punto{ x: 3, y: 0 };
    stdp.println(describir(clasificar(&p)));   // sobre un eje
    p.x = 0;
    stdp.println(describir(clasificar(&p)));   // origen
    fizzbuzz(5);                               // 1 2 Fizz 4 Buzz
    return 0;
};
```

## Notas

- Los tipos de usuario (`Punto`, `Cuadrante`) son **nominales**: la identidad
  viene del nombre declarado, no de la forma.
- `println` viene de la librería `IO` (libsrX), no del lenguaje: ver
  [helloworld.md](helloworld.md).
- Para ver qué hace el compilador con este programa, `--hir-pretty` deja en
  `dumps/` el HIR legible, con los tipos resueltos de cada expresión.
