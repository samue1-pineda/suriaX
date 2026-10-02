# Propiedad, drop y arenas

Ejemplo del modelo de memoria de suriaX: **ownership + drop + arenas
explícitas**. Reemplaza al ejemplo de regiones, retirado en la v0.2.0 junto
con el modelo (ver
[el registro de la decisión](../../documentation/source/memory_decision.rst)).

## Idea

- Cada valor con recursos tiene **un dueño**: la variable que lo nombra.
- `move x` **transfiere** la propiedad; después, `x` no se puede usar.
- Al cerrar el ámbito, el dueño **destruye** el valor llamando al `__free__`
  de su tipo. `free p;` hace lo mismo antes de tiempo.
- Un `ptr T` es un **préstamo**: no posee nada.
- Una **arena** reserva mucho de una vez y lo libera de golpe; es un tipo de
  librería, no sintaxis del lenguaje.

## Programa completo

Se ejecuta tal cual con `python main.py archivo.srcx`:

```srcx
/-
procesa un lote de enteros con un acumulador de vida corta.

el acumulador se destruye en un punto visible del codigo: no hay recolector
y no hay bloque magico que lo libere.
-/
#from io #import stdp

struct {
    int total;
    int count;
} Acc;

// destructor del tipo: lo invoca el compilador al cerrar el ambito del dueño
hook fn __free__(Acc ptr a) -> void {
    stdp.println(f"acc destruido (total {a.total})");
}

// un 'ptr' es un PRESTAMO: lee el valor sin ser su dueño
fn promedio(Acc ptr a) -> int {
    if (a.count == 0) {
        return 0;
    };
    return a.total / a.count;
}

fn main() -> int {
    var Acc acc = Acc{ total: 0, count: 0 };

    var int i = 0;
    while (i < 3) {
        acc.total = acc.total + (i * 10);
        acc.count = acc.count + 1;
        i = i + 1;
    };
    stdp.println(f"promedio = {promedio(&acc)}");

    // se transfiere la propiedad: desde aqui el dueño es 'final' y 'acc'
    // ya no se puede usar
    var Acc final = move acc;

    stdp.println("listo");
    return 0;
}   // <- 'final' sale de ambito: se invoca __free__ UNA vez
```

Salida:

```text
promedio = 10
listo
acc destruido (total 30)
```

## Qué demuestra

| Construcción | En el ejemplo |
|---|---|
| propiedad única | `acc` es el único dueño del acumulador |
| `move x` | `var Acc final = move acc;` transfiere la propiedad |
| drop determinista | `__free__` corre al cerrar el ámbito de `main`, **una** vez: `acc` ya no es dueño de nada |
| `ptr T` (préstamo) | `promedio(&acc)` lee sin quitarle la propiedad |
| `hook fn` | `__free__` es un hook del tipo: el compilador lo llama, nunca el consumidor |
| interpolación | `f"promedio = {...}"` (f-string) |

Para ver dónde inserta el compilador la destrucción, `--hir-pretty` deja en
`dumps/` el HIR legible con cada `drop` marcado.

## Pasar la propiedad a una función

Un parámetro **por valor** es el dueño de lo que recibe y lo destruye al
salir. Por eso la llamada tiene que cederlo con `move` (sin él es `SEM032`).
Para solo leer, el parámetro se declara `ptr` y se pasa `&x`:

```srcx
#from io #import stdp

struct { int id; } Recurso;

hook fn __free__(Recurso ptr r) -> void {
    stdp.println(f"recurso {r.id} liberado");
}

fn consumir(Recurso r) -> void {          // dueño: lo destruye al salir
    stdp.println(f"consumiendo {r.id}");
}

fn leer(Recurso ptr r) -> int {           // préstamo: no destruye nada
    return r.id;
}

fn main() -> int {
    var Recurso a = Recurso{ id: 1 };
    stdp.println(f"leido {leer(&a)}");    // 'a' sigue siendo de main
    consumir(move a);                     // ahora es de 'consumir'
    stdp.println("de vuelta en main");
    return 0;
}
```

Salida:

```text
leido 1
consumiendo 1
recurso 1 liberado
de vuelta en main
```

## Liberar antes de tiempo

Cuando el ámbito dura mucho más que el valor, `free` adelanta la destrucción.
`free` recibe un **puntero** al valor:

```srcx
#from io #import stdp

struct { int id; } Recurso;

hook fn __free__(Recurso ptr r) -> void {
    stdp.println(f"recurso {r.id} liberado");
}

fn main() -> int {
    var Recurso r = Recurso{ id: 7 };
    var Recurso ptr p = &r;

    free p;              // se destruye AQUI

    stdp.println("trabajo largo...");   // ...y ya esta devuelto
    return 0;
}   // 'r' no se destruye otra vez al cerrar el ambito
```

A partir del `free`, el valor queda inutilizable igual que tras un `move`, y
el compilador no vuelve a destruirlo al cerrar el ámbito.

## Arenas: liberar mucho de una vez

> **Diseño, todavía no compila:** la librería de arenas está pendiente (ver
> [ROADMAP.md](../../ROADMAP.md), Fase 5.5). El bloque muestra la forma
> prevista.

El patrón que hacía atractivas a las regiones —reservar miles de valores que
nacen y mueren juntos— se conserva, pero como **valor con dueño**:

```srcx
#from mem #import arena

fn compilar() -> void {
    var arena.Arena a = arena.crear(64 * 1024);

    var Nodo ptr raiz = arena.nodo(a, 1);
    var Nodo ptr hijo = arena.nodo(a, 2);
    construir(raiz, hijo);

}   // se destruye 'a': cae el bloque entero, de una vez
```

La diferencia con una región es que la arena **tiene dueño**. No hace falta
ningún análisis de escape para saber cuándo muere: muere cuando su dueño sale
de ámbito, igual que cualquier otro valor. Ese es todo el cambio de diseño.

## Notas

- Usar un valor después de `move` es `SEM004` (lo ve el compilador); volver a
  moverlo, `SEM005`. Lo que el análisis estático no alcanza (un `move` dentro
  de una rama) lo caza el intérprete al ejecutar: `RT001`.
- Un `ptr` hacia un valor ya liberado es colgante: usarlo es `RT003`.
- `move`, `free`, los punteros, `__free__` y el drop automático al cerrar el
  ámbito funcionan hoy. El estado completo está en
  [el capítulo del modelo de memoria](../../documentation/source/memory_model.rst).
