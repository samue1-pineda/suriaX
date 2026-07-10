# Structs, enums y control de flujo

Ejemplos de tipos compuestos (`struct`, `enum`) y del control de flujo
(`if`/`else`, `while`, `match`/`case`). Válidos a nivel léxico usando  (`#test lexer`) ejecutables cuando el compilador esté completo.

## struct 

El nombre del `struct` va **después** de las llaves; cada campo es `<tipo> <nombre>;`.

```srcx
struct {
    int x;
    int y;
} punto;

fn distancia_origen(ptr Punto p) -> int {
    // (simplificado: suma de magnitudes)
    mutable int dx = punto.x;
    mutable int dy = punto.y;
    if (dx < 0) { dx = 0 - dx; }
    if (dy < 0) { dy = 0 - dy; }
    return dx + dy;
};
```

## enum 

```srcx
enum Estado {
    Inactivo,
    Activo,
    Pausado
};
```

## match / case

```srcx
const IO = #import IO;

fn describir(Estado s) -> void {
    match (s) {
        case Inactivo: IO.printf("inactivo\n");
        case Activo:   IO.printf("activo\n");
        case Pausado:  IO.printf("pausado\n");
    };
};
```

## if / else y while

```srcx
const IO = #import IO;

fn fizzbuzz(int n) -> void {
    mutable int i = 1;
    while (i <= n) {
        if (i / 3 * 3 == i and i / 5 * 5 == i) {
            IO.printf("FizzBuzz\n");
        }; else {
            if (i / 3 * 3 == i) {
                IO.printf("Fizz\n");
            }; else {
                if (i / 5 * 5 == i) {
                    IO.printf("Buzz\n");
                }; else {
                    IO.printf("{i}\n");
                };
            };
        };
        i = i + 1;
    };
};
```

## Programa que junta todo

```srcx
const IO = #import IO;

struct {
    int x;
    int y;
} Punto;

enum Cuadrante { Origen, Eje, Interior };

fn clasificar(ptr Punto p) -> Cuadrante {
    if (p.x == 0 and p.y == 0) {
        return Origen;
    };
    if (p.x == 0 or p.y == 0) {
        return Eje;
    };
    return Interior;
};

fn main() -> void {
    region r {
        ptr Punto p = make Punto in r;
        p.x = 3;
        p.y = 0;

        Cuadrante c = clasificar(p);
        match (c) {
            case Origen {IO.printf("origen\n");};
            case Eje {IO.printf("sobre un eje\n");};
            case Interior{ IO.printf("interior\n");};
        };
    };
};
```

## Notas

- Los tipos de usuario (`Punto`, `Estado`) son **nominales**: la identidad viene
  del nombre declarado.
- `printf` viene de la librería `IO` (libsrX): `IO.printf(...)`.
