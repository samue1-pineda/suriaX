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

fn promedio(Acc ptr a) -> int {
    if (a.count == 0) {
        return 0;
    }
    return a.total / a.count;
}

fn main() -> void {
    const int n = 3;

    region work {
        // 'acc' vive en la región 'work'; 'ptr mutable' permite escribir
        // a través del puntero (un 'Acc ptr' pelado sería solo lectura)
        Acc ptr mutable acc = make Acc in work;
        acc.total = 0;
        acc.count = 0;

        var int i = 0;
        while (i < n) {
            // cada lectura se ubica en la región de trabajo
            int x = (i * 10) at work;
            acc.total = acc.total + x;
            acc.count = acc.count + 1;
            i = i + 1;
        };

        int avg = promedio(acc);
        IO.printf(f"promedio = {avg}\n");

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
| `ptr T` / `ptr mutable T` | `ptr mutable Acc acc` (escribe), `ptr Acc a` (parámetro solo lectura) |
| acceso a campo `.`  | `acc.total`, `a.count`                 |
| interpolación       | `f"promedio = {avg}\n"` (f-string)     |

## Modelo híbrido: modificadores, handles y vida manual

Una región admite tres **modificadores componibles y de orden libre**
(`shrd mutable na region x` es válido):

| Modificador | Significado |
|-------------|-------------|
| `shrd`      | la región es **compartible** entre otras regiones |
| `mutable`   | la región puede **mutar y dividirse** (split) |
| `na`        | "no auto": **no** se auto-libera al cerrar el bloque (usa `delete`) |

Y dos formas de existir, más operaciones imperativas:

```srcx
fn main() -> int {
    // 1) forma con BLOQUE: se auto-libera al cerrar (salvo 'na')
    region a { var int x = 1; };

    // 2) forma HANDLE (sin bloque): vida manual, hasta el 'delete'
    new(shrd mutable region pool);
    in region pool: delete(region pool);   // "en la región pool, haz ..."

    // 'na': el bloque NO se auto-libera; se libera explícitamente
    na region buf { var int y = 2; delete(); };  // 'delete()' = la región actual

    // move-semantics de regiones: transfiere (no copia) a -> b
    na region src { var int z = 3; };
    na region dst { var int w = 4; };
    move region src -> region dst;
    return 0;
}
```

- `new(<mods> region r);` inicializa una región como **handle**.
- `delete(region r);` la libera por nombre; `delete()` (sin argumento, dentro de
  una `na region`) libera la región que lo encierra.
- `in region r: <stmt>` (o `in region r { ... }`) ejecuta operaciones **en** el
  contexto de `r`.
- `move region a -> region b;` transfiere el contenido de `a` a `b`.

> La ejecución REAL del modelo RBMM (reservar, dividir, compartir, liberar) la
> hace el **runtime** de forma **agnóstica del target**: el intérprete llama a
> la implementación C++ vía **pybind11**, que no depende de ningún target. Así
> se prueba la lógica de memoria antes de la VM, **sin** simularla ni diferirla
> al MIR. El frontend valida existencia de regiones y transporta los
> modificadores al HIR.

## Notas

- Las referencias creadas dentro de una región **no deben escapar** de ella, esa regla la verifica la **semántica** (no el lexer). Ver [DESIGN_PRINCIPLES.md](../../DESIGN_PRINCIPLES.md).
- `move acc;` invalida `acc`: usarlo después de moverlo será un **error de
  tipos** (`use-after-move`).
- El `;` cierra cada sentencia (obligatorio).

