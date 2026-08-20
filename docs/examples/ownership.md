# Propiedad, drop y arenas

Ejemplo del modelo de memoria de suriaX: **ownership + drop + arenas
explícitas**. Reemplaza al ejemplo de regiones, retirado en la v0.2.0 junto
con el modelo (ver
[el registro de la decisión](../../documentation/source/memory_decision.rst)).

## Idea

- Cada valor con recursos tiene **un dueño**: la variable que lo nombra.
- `move x` **transfiere** la propiedad; después, `x` no se puede usar.
- Al cerrar el ámbito, el dueño **destruye** el valor llamando al `__free__`
  de su tipo. `free x;` hace lo mismo antes de tiempo.
- Un `ptr T` es un **préstamo**: no posee nada.
- Una **arena** reserva mucho de una vez y lo libera de golpe; es un tipo de
  librería, no sintaxis del lenguaje.

## Programa completo

```srcx
/-
procesa un lote de enteros con un acumulador de vida corta.

el acumulador se destruye en un punto visible del código: no hay recolector
y no hay bloque mágico que lo libere.
-/
const IO = #import IO;

struct {
    int total;
    int count;
} Acc;

// destructor del tipo: lo invoca el compilador, nunca el consumidor
fn __free__(Acc ptr a) -> void {
    IO.printf("acc destruido\n");
}

fn promedio(Acc ptr a) -> int {
    if (a.count == 0) {
        return 0;
    }
    return a.total / a.count;
}

fn consumir(Acc ptr a) -> void {
    IO.printf(f"promedio = {promedio(a)}\n");
}

fn main() -> void {
    const int n = 3;

    // 'acc' es el dueño; 'ptr mutable' permite escribir a través del puntero
    Acc ptr mutable acc = nuevo_acc();
    acc.total = 0;
    acc.count = 0;

    var int i = 0;
    while (i < n) {
        acc.total = acc.total + (i * 10);
        acc.count = acc.count + 1;
        i = i + 1;
    };

    // se transfiere la propiedad: a partir de aquí 'acc' no es utilizable
    consumir(move acc);

    IO.printf("listo\n");
}   // <- el dueño actual sale de ámbito: se invoca __free__
```

## Qué demuestra

| Construcción              | En el ejemplo                                    |
|---------------------------|--------------------------------------------------|
| propiedad única           | `acc` es el único dueño del acumulador           |
| `move x`                  | `consumir(move acc)` transfiere la propiedad     |
| drop determinista         | `__free__(Acc ptr a)` corre al cerrar el ámbito  |
| `ptr T` / `ptr mutable T` | `ptr mutable Acc` (escribe), `Acc ptr` (préstamo)|
| acceso a campo `.`        | `acc.total`, `a.count`                           |
| interpolación             | `f"promedio = {...}\n"` (f-string)               |

## Liberar antes de tiempo

Cuando el ámbito dura mucho más que el valor, `free` adelanta la destrucción:

```srcx
fn procesar() -> void {
    Buffer ptr b = crear_buffer(1024);
    usar(b);

    free b;              // se destruye AQUÍ

    trabajo_largo();     // ...y la memoria ya está devuelta
    // usar(b);          // error: 'b' fue liberado
}
```

A partir del `free`, `b` queda inutilizable igual que tras un `move`, y el
compilador no vuelve a destruirlo al cerrar el ámbito.

## Arenas: liberar mucho de una vez

El patrón que hacía atractivas a las regiones —reservar miles de valores que
nacen y mueren juntos— se conserva, pero como **valor con dueño**:

```srcx
#from mem #import arena

fn compilar() -> void {
    arena.Arena a = arena.crear(64 * 1024);

    Nodo ptr raiz = arena.nodo(a, 1);
    Nodo ptr hijo = arena.nodo(a, 2);
    construir(raiz, hijo);

}   // se destruye 'a': cae el bloque entero, de una vez
```

La diferencia con una región es que la arena **tiene dueño**. No hace falta
ningún análisis de escape para saber cuándo muere: muere cuando su dueño sale
de ámbito, igual que cualquier otro valor. Ese es todo el cambio de diseño.

> **Estado**: `move`, `free`, los punteros y `__free__` funcionan hoy. El drop
> automático al cerrar el ámbito y la librería de arenas están **pendientes**
> — ver la tabla de estado en
> [el capítulo del modelo de memoria](../../documentation/source/memory_model.rst).

## Notas

- `move acc;` invalida `acc`: usarlo después es `SEM004` (uso tras move) y
  volver a moverlo, `SEM005`.
- Un `ptr` hacia un valor ya liberado es colgante: desreferenciarlo es `RT003`.
- El `;` cierra cada sentencia (obligatorio).
