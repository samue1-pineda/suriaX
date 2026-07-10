# Regiones y move-semantics

Ejemplo **completo y funcional** del modelo de memoria de suriaX:
**region-based + move-semantics**. Está escrito para ejecutarse tal cual cuando
el compilador esté completo.

## Idea

- Una **región** (`region r { ... }`) agrupa las asignaciones en el heap. Al
  cerrarse el bloque, **toda** la memoria de la región se libera de una vez (no
  objeto por objeto).
- `make T in r` construye un valor dentro de la región `r`.
- `expr at r` ubica el resultado de una expresión en la región `r`.
- `move x` transfiere la propiedad de `x`; tras el `move`, `x` deja de ser
  usable (lo verifica la semántica / el lowering a MIR).

## Programa completo

```srcx
/- 
procesa un lote de enteros usando una región temporal de trabajo.

al salir de la región, toda su memoria se libera automáticamente.
-/
const IO = #import IO;

// estructura de un acumulador 
struct {
    int total;
    int count;
} Acc;

fn promedio(ptr Acc a) -> int {
    if (a.count == 0) {
        return 0;
    }
    return a.total / a.count;
}

fn main() -> void {
    const int n = 3;

    region work {
        // 'acc' vive en la región 'work'
        ptr Acc acc = make Acc in work;
        acc.total = 0;
        acc.count = 0;

        mutable int i = 0;
        while (i < n) {
            // cada lectura se ubica en la región de trabajo
            int x = (i * 10) at work;
            acc.total = acc.total + x;
            acc.count = acc.count + 1;
            i = i + 1;
        };

        int avg = promedio(acc);
        IO.printf("promedio = {avg}\n");

        // transferimos la propiedad del acumulador a un consumidor
        move acc;
    }   // <- aquí 'work' se cierra: toda su memoria se libera

    IO.printf("listo\n");
}
```

## Qué demuestra

| Construcción        | En el ejemplo                          |
|---------------------|----------------------------------------|
| `region r { ... }`  | `region work { ... }`                  |
| `make T in r`       | `make Acc in work`                     |
| `expr at r`         | `(i * 10) at work`                     |
| `move x`            | `move acc;`                            |
| `ptr T`             | `ptr Acc acc`, `ptr Acc a` (parámetro) |
| acceso a campo `.`  | `acc.total`, `a.count`                 |
| interpolación       | `"promedio = {avg}\n"`                 |

## Notas

- Las referencias creadas dentro de una región **no deben escapar** de ella, esa regla la verifica la **semántica** (no el lexer). Ver [DESIGN_PRINCIPLES.md](../../DESIGN_PRINCIPLES.md).
- `move acc;` invalida `acc`: usarlo después de moverlo será un **error de
  tipos** (`use-after-move`).
- El `;` cierra cada sentencia (obligatorio).

