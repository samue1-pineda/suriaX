# Enseñale suriaX: hooks, dunders y traits

suriaX trae muy poco cableado por dentro. Casi todo —imprimir, medir, liberar,
convertir— lo aportan las librerías. Este documento es para ti: cómo hacer que
**tus** tipos participen del lenguaje y cómo definir **tus propios contratos**,
sin ser experto en compiladores.

Hay tres herramientas, de la más simple a la más potente:

1. **Hooks** — haz que tu tipo funcione con operaciones que ya existen
   (`print(x)`, `len(x)`, `sizeof(T)`, `free x`, `cast<T>(x)`).
2. **Dunders** — dale a tu tipo sus **propios** métodos (`lista.__push__(3)`).
3. **Traits** — define un **contrato** con nombre (`iterable`, `sumable`…) y
   pide que un tipo lo cumpla; el compilador lo verifica por ti.

> **Qué ejecuta HOY (Pre-Alpha) y qué no.** Los **hooks** (grupo 1) funcionan
> de punta a punta. Los **dunders** (grupo 2) **ya se ejecutan** cuando el tipo
> y el método viven en el MISMO archivo: `x.__algo__(...)` corre de verdad y,
> si el método muta el receptor, el cambio se propaga. Lo que aún NO corre es
> llamar un método de un tipo que viene de OTRA librería (`vec.__push__()`
> cross-módulo) — eso llega en **V.0.0.3** (ver
> [../docs/propuesta_vectores.md](../docs/propuesta_vectores.md)). Los
> **traits** (grupo 3) se validan en compilación (`SEM021`).

---

## 1. Hooks — que tu tipo entienda las operaciones del lenguaje

Un **hook** conecta tu tipo con una operación que suriaX ya conoce. Escribes un
`fn` con la palabra **`hook`** delante y un nombre especial (`__print__`,
`__len__`…), y el compilador lo llama por ti cuando alguien usa esa operación
sobre tu tipo.

Estas son TODAS las operaciones con hook (el vocabulario es cerrado):

| Quieres que… | Escribe el hook | Se dispara con |
|---|---|---|
| tu tipo se imprima | `hook fn __print__(T ptr x) -> void` | `print(x)` |
| `len(x)` funcione | `hook fn __len__(T ptr x) -> int` | `len(x)` |
| `sizeof(T)` dé un tamaño | `hook fn __sizeof__(T ptr x) -> int` | `sizeof(T)` |
| liberar haga algo tuyo | `hook fn __free__(T ptr x) -> void` | `free x` |
| convertir a/desde tu tipo | `hook fn __cast__(X x) -> T` | `cast<T>(x)` |
| construir en una región | `hook fn __make__(...) -> T ptr` | (memoria por regiones) |

**Ejemplo real** — un `String` que sabe imprimirse y medirse
([io/stdp.libsrx](io/stdp.libsrx)):

```srcx
struct { str text; int len; } String;

hook fn __print__(String ptr s) -> void { __write__(s.text); }
hook fn __len__(String ptr s)   -> int  { return s.len; }
```

Con eso, `print(miString)` y `len(miString)` ya funcionan. **No tocas el
compilador**: basta declararlo en tu `.libsrx`.

Un mismo archivo puede tener **varios** `__sizeof__` o `__cast__`, uno por
tipo: se distinguen por el tipo dueño, no por el nombre.

```srcx
hook fn __sizeof__(int8 ptr x)  -> int { return 1; }
hook fn __sizeof__(int32 ptr x) -> int { return 4; }
```

> El **primer parámetro** decide de quién es el hook (para `__cast__` y
> `__make__`, es el tipo de RETORNO). Y `sizeof` solo acepta tipos con nombre
> propio (structs, enums o alias `const type`), no el `int` crudo.

---

## 2. Dunders — dale a tu tipo tus propios métodos

Un **dunder** (`dunder fn __algo__`) es un método que TÚ inventas para un tipo.
No pertenece al vocabulario fijo: es tuyo. Se llama con la notación de punto
sobre una instancia.

```srcx
struct { int cur; int max; } Counter;

dunder fn __next__(Counter ptr mutable c) -> int  { c.cur = c.cur + 1; return c.cur; }
dunder fn __done__(Counter ptr c)         -> bool { return c.cur >= c.max; }

// se usan así (ya EJECUTA hoy si tipo y método están en el mismo archivo):
//   var Counter c = Counter{ cur: 0, max: 3 };
//   c.__next__();     // 1  (muta c.cur, y el cambio se ve fuera)
//   c.__done__();     // false
```

Reglas simples:

- El **primer parámetro es el receptor** (`Counter ptr` = solo lectura,
  `Counter ptr mutable` = puede modificar el objeto).
- El nombre va entre dobles guiones bajos: `__next__`, no `next`.
- Dos tipos distintos pueden tener cada uno su `__next__` sin chocar: cada
  dunder pertenece a su tipo.

Un `fn __algo__` **sin** la palabra `dunder` (ni `hook`) es una función normal
que casualmente se llama así — no un método. Las tres palabras (`hook`,
`dunder`, o ninguna) dicen exactamente qué estás declarando.

---

## 3. Traits — define un contrato y pide que se cumpla

Un **trait** es un contrato con nombre: un grupo de métodos que un tipo debe
tener para "ser" algo (iterable, sumable, comparable…). Tú defines el contrato;
el compilador **verifica** que quien dice cumplirlo, lo cumple de verdad —con
las firmas exactas— y te avisa si no (`SEM021`).

Se escribe en dos partes: `@trait` declara el contrato y `@impl(contrato)` marca
un tipo como cumplidor.

```srcx
// 1) el contrato: 'self' es "el tipo que lo implemente"
@trait struct {
    dunder fn __next__(self ptr mutable) -> int;
    dunder fn __done__(self ptr)         -> bool;
} iterable;

// 2) un tipo que promete cumplirlo
@impl(iterable) struct {
    int cur;
    int max;
} Counter;

// 3) y de verdad lo cumple (mismas firmas, con Counter en lugar de self)
dunder fn __next__(Counter ptr mutable c) -> int  { c.cur = c.cur + 1; return c.cur; }
dunder fn __done__(Counter ptr c)         -> bool { return c.cur >= c.max; }
```

Si a `Counter` le falta un método, o la firma no calza (por ejemplo olvidas el
`mutable`), el compilador lo rechaza con `SEM021` señalando cuál y por qué. Así
defines vocabulario nuevo (`iterable`, `sumable`…) **sin** cablearlo en el
lenguaje: el contrato es tuyo, la verificación la pone suriaX.

> `self` dentro del trait significa "el tipo que hará `@impl`". Al verificar,
> suriaX sustituye `self` por el tipo real (`Counter`) y compara firma a firma.

---

## Recetario rápido

| Quiero… | Uso | ¿Toca el compilador? |
|---|---|---|
| que `print(x)`/`len(x)`/… funcione con mi tipo | un **hook** (`hook fn __print__`) | No |
| una primitiva del sistema (memoria, IO) | un `fn __x__();` **sin cuerpo** (prototipo) ligado a una primitiva del host | No |
| métodos propios de mi tipo | un **dunder** (`dunder fn __x__`) | No |
| un contrato reutilizable | un **trait** (`@trait` + `@impl`) | No |
| una operación del lenguaje totalmente nueva | añadir un hook al vocabulario fijo | Sí (raro; casi siempre lo cubre un hook o dunder existente) |

### Primitivas del host (el caso del prototipo sin cuerpo)

Algunos `fn __x__(...)` no tienen cuerpo en suriaX: son **primitivas** que pone
el entorno de ejecución. `__write__` (escribir a pantalla) y `__reserve__`
(reservar memoria) son así. Declaras el prototipo en tu `.libsrx`…

```srcx
fn __write__(str s) -> void;              // sin cuerpo: lo provee el host
fn reserve(int n) -> int ptr mutable { return __reserve__(n); }
```

…y el host lo conecta con la implementación real (en el intérprete,
[../runtime/interpreter/intrinsics.py](../runtime/interpreter/intrinsics.py)).
Es la vía para memoria, entrada/salida y todo lo que el lenguaje delega afuera.

---

## Detalles que conviene saber

- **`ptr mutable` para escribir**: si tu método o tu bloque de memoria va a
  MODIFICAR el objeto, el puntero debe ser `T ptr mutable`, no `T ptr` (si no,
  el compilador lo marca con `SEM015`). `T ptr` es "solo lectura a través del
  puntero".
- **`sizeof` necesita un tipo con nombre** (`SEM006`): funciona con structs,
  enums y alias `const type`, no con `int`/`float` crudos (el tamaño de esos lo
  fija el backend).
- **La extensión de VS Code aún marca falsos rojos** sobre hooks/prototipos
  válidos (su verificador está desincronizado con el compilador). Si tu archivo
  compila con `python V0/main.py archivo.srcx`, esos subrayados son ruido de la
  extensión, no errores de tu código. La fuente de verdad es el compilador.

---

## Estado actual, sin adornos

Qué está realmente disponible HOY (Pre-Alpha) y qué todavía no. "Se valida"
significa que el compilador comprueba que lo escribiste bien; "ejecuta" significa
que corre de verdad con `--run`.

| Herramienta | ¿Se escribe y valida? | ¿Ejecuta hoy? |
|---|---|---|
| Hooks `__print__` / `__len__` | Sí | ✅ Sí (verificado con tipos de usuario) |
| Hooks `__sizeof__` / `__cast__` / `__free__` | Sí | ✅ Sí |
| Hook `__make__` | Sí | ⛔ No — es para construir en REGIONES, y las regiones (RBMM) no están en v1 (se rechazan con `HIR005`) |
| Dunders (`x.__metodo__()`) mismo archivo | Sí | ✅ Sí — el método corre y la mutación del receptor se propaga |
| Dunders sobre un tipo de OTRA librería | Sí | ⛔ No aún — resolución cross-módulo llega en V.0.0.3 |
| Traits (`@trait` / `@impl`) | Sí (conformidad verificada, `SEM021`) | — (el contrato no "ejecuta" nada; pero los dunders que exige tampoco corren aún) |

En una frase: **los hooks funcionan de punta a punta hoy; los dunders y traits
ya se escriben y se validan, pero su ejecución llega con V.0.0.3.**

## TODO (hacia V.0.0.3)

- [x] **Ejecutar dunders en el intérprete** (same-module): `x.__metodo__(args)`
  despacha al cuerpo con el receptor por referencia. Hecho y con tests e2e.
- [ ] **Resolución de métodos cross-módulo**: que `c.__m__()` encuentre el
  dunder cuando el TIPO viene de una librería importada (hoy el frontend no
  liga el hook cross-módulo por la calificación del nombre nominal). Es lo que
  falta para que un tipo de librería (Vector) tenga métodos. Plan en
  [../docs/propuesta_vectores.md](../docs/propuesta_vectores.md) §6.
- [ ] **Hook `__index__`** nuevo para `x[i]` sobre tipos con nombre
  (indexación sobrecargable, hoy `[]` es solo para punteros crudos).
- [ ] **Métodos de nombre llano** (`lista.push(3)` en vez de `lista.__push__(3)`)
  vía un bloque `@impl Tipo { fn push(...) }`.
- [ ] **`__make__` / regiones**: reintroducir RBMM (HIR v2) para que la
  construcción en región y su hook ejecuten.
- [ ] **Sincronizar la extensión de VS Code**: que consuma `--emit-diagnostics`
  en vez de reimplementar la gramática (elimina los falsos rojos sobre
  hooks/prototipos válidos).
