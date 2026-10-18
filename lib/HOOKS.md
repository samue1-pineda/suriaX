# Enséñale suriaX: hooks, dunders y traits

suriaX trae muy poco cableado por dentro. Casi todo —imprimir, medir, liberar,
convertir, indexar, comparar— lo aportan las librerías. Este documento es para
ti: cómo hacer que **tus** tipos participen del lenguaje y cómo definir **tus
propios contratos**, sin ser experto en compiladores.

Hay tres herramientas, de la más simple a la más potente:

1. **Hooks** — haz que tu tipo funcione con operaciones que ya existen
   (`print(x)`, `len(x)`, `sizeof(T)`, `free x`, `cast<T>(x)`, `v[i]`, `a == b`,
   `a < b`).
2. **Dunders** — dale a tu tipo sus **propios** métodos (`lista.__push__(3)`).
3. **Traits** — define un **contrato** con nombre (`iterable`, `sumable`…) y
   pide que un tipo lo cumpla; el compilador lo verifica por ti.

Y hay una cuarta vía, para lo que el lenguaje delega en el entorno:
**primitivas del host** (un prototipo sin cuerpo que implementa el runtime).

---

## 1. Hooks — que tu tipo entienda las operaciones del lenguaje

Un **hook** conecta tu tipo con una operación que suriaX ya conoce. Escribes un
`fn` con la palabra **`hook`** delante y un nombre especial (`__print__`,
`__len__`…), y el compilador lo llama por ti cuando alguien usa esa operación
sobre tu tipo. **No tocas el compilador**: basta declararlo en tu `.libsrx`.

### 1.1 Glosario: todos los hooks de hoy

Estos doce los trae el compilador y los dispara la **sintaxis** del lenguaje.
Tu proyecto puede añadir los suyos (§5): esos se invocan por su nombre, como un
método. Cada fila dice qué escribir, qué lo dispara, de qué tipo pasa a ser el
hook y si ejecuta hoy.

| Hook | Firma exacta | Se dispara con | Dueño | Ejecuta |
|---|---|---|---|---|
| `__print__` | `hook fn __print__(T ptr x) -> void` | `print(x)` · `x.print()` | 1.er parámetro | ✅ |
| `__len__` | `hook fn __len__(T ptr x) -> int` | `len(x)` · `x.len()` | 1.er parámetro | ✅ |
| `__sizeof__` | `hook fn __sizeof__(T ptr x) -> int` | `sizeof(T)` | 1.er parámetro | ✅ |
| `__free__` | `hook fn __free__(T ptr x) -> void` | `free x;` | 1.er parámetro | ✅ |
| `__cast__` | `hook fn __cast__(X x) -> T` | `cast<T>(x)` | el lado **nominal** de la firma | ✅ |
| `__index__` | `hook fn __index__(T ptr x, int i) -> E` | `x[i]` | 1.er parámetro | ✅ |
| `__index_set__` | `hook fn __index_set__(T ptr mutable x, int i, E v) -> void` | `x[i] = v` | 1.er parámetro | ✅ |
| `__eq__` | `hook fn __eq__(T ptr a, T ptr b) -> bool` | `a == b` | 1.er parámetro | ✅ |
| `__min__` | `hook fn __min__(T ptr x) -> int` | un literal escrito donde se espera `T` | 1.er parámetro | ✅ |
| `__max__` | `hook fn __max__(T ptr x) -> int` | un literal escrito donde se espera `T` | 1.er parámetro | ✅ |
| `__hash__` | `hook fn __hash__(T ptr x) -> int` | `hash(x)` | 1.er parámetro | ✅ |
| `__cmp__` | `hook fn __cmp__(T ptr a, T ptr b) -> int` | `a < b` · `a <= b` · `a > b` · `a >= b` | 1.er parámetro | ✅ (intérprete) |

Qué significa cada uno, con algo más de detalle:

- **`__print__`** — cómo se muestra tu tipo. Es el único punto por el que
  `print(x)` sabe qué hacer con algo que no es un primitivo. Debe devolver
  `void` y recibir exactamente un receptor.
- **`__hash__`** — un entero que resume el valor, para guardarlo en un
  `collections.Dictionary`. La regla es una sola: dos valores iguales (según
  `==`: tu `__eq__` o, sin él, la igualdad campo a campo) tienen que dar el
  mismo hash; al revés no hace falta. Sobre
  `int`, `bool`, `char` y `str`, `hash(x)` es nativo (no se declara); un
  `float` no tiene hash, porque NaN no es igual a sí mismo.
- **`__len__`** — el "tamaño lógico" (elementos de una lista, caracteres de una
  cadena). Devuelve `int`. Es cosa tuya qué cuenta: el compilador no supone
  nada.
- **`__sizeof__`** — el tamaño en memoria que tú declaras para el tipo. Solo se
  puede pedir sobre tipos **con nombre propio** (structs, enums, alias
  `const type`), nunca sobre `int` crudo: el tamaño de los primitivos lo fija
  el backend, no una librería (`SEM006`).
- **`__free__`** — qué hacer al liberar. `free x;` exige que `x` sea `T ptr`
  (`SEM014`); si `T` declara este hook, se ejecuta **antes** de invalidar la
  celda. También corre solo: al cerrarse el ámbito del dueño y, para una
  variable **global**, al terminar el programa (en orden inverso de
  declaración, tras volver de `main`; en el intérprete).
- **`__cast__`** — la conversión explícita. Tiene la convención más particular:
  el dueño es el lado **nominal** de la firma, sea el retorno
  (`fn __cast__(int x) -> int8` pertenece a `int8`) o el parámetro
  (`fn __cast__(int8 x) -> int`, también de `int8`). Un tipo puede declarar
  varias, una por par origen→destino. Se dispara con `cast<T>(x)`: **nunca**
  se escribe `__cast__` a mano.
- **`__index__`** — leer `x[i]` sobre un tipo con nombre. El segundo parámetro
  es el índice y el retorno es el **elemento** (tipo libre: tú decides). La
  indexación cruda de punteros y bloques sigue funcionando sin hook. Si
  devuelve por valor, `x[i]` es una **copia**: escribir en ella (`x[i].n = 5`,
  o llamar a un método que modifica su receptor, `x[i].push(v)`) es `SEM041`.
  Para modificar el elemento en su sitio, el tipo ofrece un método que lo
  preste mutable (`Vector.at_mut`, `Dictionary.at_mut`).
- **`__index_set__`** — escribir `x[i] = v`. El receptor va `T ptr mutable`
  porque va a modificar el objeto, y devuelve `void`. Tres parámetros:
  receptor, índice y valor.
- **`__eq__`** — comparar `a == b` entre dos valores del mismo tipo nominal.
  Devuelve `bool`, y `a != b` es su negación. Sin él, `==` es igualdad de
  **valor**: un struct se compara campo a campo (cada campo con su propia
  igualdad, así que un campo con `__eq__` lo usa), un enum con datos por
  variante y payload, y un **puntero por su dirección** —no por lo apuntado—.
  Decláralo cuando "igual" no sea "mismos campos": un tipo que guarda un
  bloque de `mem` (como `Vector`, que lo declara) o que ignora un campo.
- **`__cmp__`** — el **orden** de tu tipo: `a < b`, `a <= b`, `a > b` y
  `a >= b` salen de él. Devuelve un `int`: negativo si `a` va antes, `0` si
  empatan, positivo si va después (`return a.clave - b.clave;`). Es uno y no
  cuatro (`__lt__`, `__le__`…) porque cuatro hooks se pueden contradecir y uno
  no. Los dos parámetros son del mismo tipo (`SEM006` si no). Sin él, ordenar
  tu tipo es un error (`AST006`); los primitivos (`int`, `float`, `char`,
  `str`, `byte`) y los enums **sin datos** se ordenan solos. Con él tu tipo
  vale en un genérico que ordena (`menor<T>`, `Vector.sort`); sin él, esa
  instancia es `SEM039`. Para ordenar por OTRO criterio sin tocar el tipo
  (por una clave, al revés), `v.sort_by(f)` recibe una función con la misma
  forma, `fn(T ptr, T ptr) -> int`, y no necesita `__cmp__`.
- **Un enum sin datos no declara `__eq__`, `__cmp__` ni `__hash__`**
  (`SEM006`): al ejecutar es un entero, y se compara, se ordena y se hashea
  como uno, por el valor de su variante. El hook no se llamaría nunca.
- **`__min__` / `__max__`** — el **rango** de un tipo numérico. Son los únicos
  hooks que el compilador **lee en compilación** en vez de ejecutar: mira el
  literal de su `return`, así que el cuerpo tiene que ser exactamente
  `{ return <entero>; }` (el `-` unario vale). Sirven para una sola cosa, y es
  la que hace usable un tipo de ancho fijo: decidir si un **literal** cabe.

  ```srcx
  const type int8;
  hook fn __cast__(int n)     -> int8;
  hook fn __min__(int8 ptr _) -> int { return -128; }
  hook fn __max__(int8 ptr _) -> int { return 127; }
  ```

  Con eso, `const dt.int8 a = 10;` compila (el compilador inserta la
  conversión declarada) y `= 300` es un error que dice el rango. Sin ellos el
  tipo sigue funcionando, pero solo con `cast<dt.int8>(...)` explícito: el
  compilador sabría por `__sizeof__` que mide un byte y no si ese byte va de
  −128 a 127 o de 0 a 255.

  > La asimetría es deliberada, la misma de Rust: el literal **implícito**
  > tiene que caber; `cast<T>(x)` **explícito** trunca.

> El **primer parámetro** decide de quién es el hook (salvo `__cast__`, que
> se asocia por el lado NOMINAL de su firma). Un mismo archivo puede tener **varios**
> `__sizeof__` o `__cast__`, uno por tipo: se distinguen por el tipo dueño, no
> por el nombre.

### 1.2 Ejemplo real

Un `String` que sabe imprimirse y medirse ([io/stdp.libsrx](io/stdp.libsrx)):

```srcx
struct { str text; int len; } String;

hook fn __print__(String ptr s) -> void { __write__(s.text); }
hook fn __len__(String ptr s)   -> int  { return s.len; }
```

Con eso, `print(miString)` y `len(miString)` ya funcionan.

Y un tipo que se comporta como un contenedor:

```srcx
struct { int a; int b; } Par;

hook fn __index__(Par ptr p, int i) -> int {
    if (i == 0) { return p.a; }
    return p.b;
}
hook fn __index_set__(Par ptr mutable p, int i, int v) -> void {
    if (i == 0) { p.a = v; } else { p.b = v; }
}
hook fn __eq__(Par ptr x, Par ptr y) -> bool { return x.a == y.a; }
hook fn __cmp__(Par ptr x, Par ptr y) -> int { return x.a - y.a; }

// var Par p = Par{ a: 1, b: 2 };
//   p[0]        -> 1
//   p[1] = 7;   -> muta p.b
//   p == q      -> compara por 'a'
//   p < q       -> ordena por 'a' (y un Vector<Par> ya se puede 'sort')
```

Varios `__sizeof__` en el mismo archivo, uno por tipo:

```srcx
hook fn __sizeof__(int8 ptr x)  -> int { return 1; }
hook fn __sizeof__(int32 ptr x) -> int { return 4; }
```

---

## 2. Dunders — dale a tu tipo tus propios métodos

Un **dunder** (`dunder fn __algo__`) es un método que TÚ inventas para un tipo.
No pertenece al vocabulario fijo: es tuyo. Se llama con la notación de punto
sobre una instancia.

```srcx
struct { int cur; int max; } Counter;

dunder fn __next__(Counter ptr mutable c) -> int  { c.cur = c.cur + 1; return c.cur; }
dunder fn __done__(Counter ptr c)         -> bool { return c.cur >= c.max; }

// var Counter c = Counter{ cur: 0, max: 3 };
//   c.__next__();     // 1  (muta c.cur, y el cambio se ve fuera)
//   c.__done__();     // false
```

Reglas simples:

- El **primer parámetro es el receptor** (`Counter ptr` = solo lectura,
  `Counter ptr mutable` = puede modificar el objeto).
- El nombre va entre dobles guiones bajos: `__next__`, no `next`.
- Dos tipos distintos pueden tener cada uno su `__next__` sin chocar: cada
  dunder pertenece a su tipo.
- **Funcionan cross-módulo**: si el tipo viene de una librería importada, sus
  dunders se despachan igual (`c.__bump__()` sobre un `conta.Contador`).
  Recuerda declarar `public` el struct **y** el dunder para que crucen la
  frontera de la librería.

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

Un trait también puede pedir **métodos de nombre llano** (los de un bloque
`@impl Tipo { ... }`), y los parámetros del prototipo pueden llevar nombre:

```srcx
@trait struct { fn area(self ptr s) -> int; } shape;

@impl(shape) struct { int r; } Circle;
@impl Circle { fn area(Circle ptr self) -> int { return self.r * 3; } }

fn twice<T: shape>(T ptr x) -> int { return x.area() * 2; }   // una COTA

fn main() -> int {
    var Circle c = Circle{ r: 1 };
    return twice(&c) - 6;
}
```

Con la cota `T: shape`, `x.area()` se comprueba en la definición, y quien
llama a `twice` con un tipo que no declara `@impl(shape)` recibe `SEM021` en
la llamada. Además de tus traits existen cuatro **conceptos nativos**, `Eq`,
`Ord`, `Hash` y `Print`, que se cumplen solos (los primitivos que ya los
tienen y los tipos que declaran `__eq__`, `__cmp__`, `__hash__` o
`__print__`).

---

## 4. Primitivas del host (el prototipo sin cuerpo)

Algunos `fn __x__(...)` no tienen cuerpo en suriaX: son **primitivas** que pone
el entorno de ejecución. `__write__` (escribir a pantalla), `__reserve__`
(reservar memoria) y `__copy__` (copiar bloques) son así. Declaras el prototipo
en tu `.libsrx`…

```srcx
fn __write__(str s) -> void;              // sin cuerpo: lo provee el host
fn reserve(int n) -> int ptr mutable { return __reserve__(n); }
```

…y el host lo conecta con la implementación real (en el intérprete,
[../runtime/interpreter/intrinsics.py](../runtime/interpreter/intrinsics.py);
el backend C++ liga el mismo símbolo a su `#extern`). Es la vía para memoria,
entrada/salida y todo lo que el lenguaje delega afuera — y **no requiere**
`#extern cpp{}` para imprimir bajo `target: interp`.

---

## Recetario rápido

| Quiero… | Uso | ¿Toca el compilador? |
|---|---|---|
| que `print(x)`/`len(x)`/`x[i]`/`a == b`/`a < b` funcione con mi tipo | un **hook** | No |
| una primitiva del sistema (memoria, IO) | un `fn __x__();` **sin cuerpo** ligado al host | No |
| métodos propios de mi tipo | un **dunder** | No |
| un contrato reutilizable | un **trait** (`@trait` + `@impl`) | No |
| un hook **propio de mi proyecto** (`__gravity__`) | declararlo en tu `extends.srcx` (§5) e implementarlo con `hook fn` | No |
| una operación con **sintaxis** nueva del lenguaje (`x @@ y`) | añadirla al vocabulario fijo | Sí (raro) |

## 5. Tus propios hooks (HTIMS)

Que añadir vocabulario obligara a tocar el compilador significaba que los hooks
eran "suyos" y no tuyos. Ya no: un `extends.srcx` en la raíz de tu proyecto
apunta a un directorio de declaraciones en Python, y lo que declares ahí es
vocabulario de primera clase **para tu proyecto**.

```python
# extensions/calls/physics.py
from htims import hook

@hook("__gravity__", owner="Body",
      params=["Body ptr mutable", "int"], returns="void")
def gravity(body, dt): ...
```

```srcx
// juego.srcx
hook fn __gravity__(Body ptr mutable b, int dt) -> void {
    b.vy = b.vy - 10 * dt;
}

fn main() -> int {
    var Body b = Body{ vy: 20 };
    b.__gravity__(1);     // se invoca por su nombre
    return b.vy;          // 10
}
```

Tres cosas que conviene entender:

- **El compilador no ejecuta tu `.py`**: lo lee con el `ast` de Python. Tu
  declaración es un dato, no código que corra al compilar.
- **La firma se hace cumplir.** Si el `hook fn` no coincide con lo que declaró
  la extensión —un `ptr` sin `mutable`, un `float` donde dijiste `int`— el
  compilador lo rechaza diciendo exactamente qué y quién lo prometió.
- **El vocabulario es del proyecto.** El mismo archivo, en un proyecto sin esa
  extensión, no compila: `__gravity__` no existe ahí.

Se invocan **por su nombre** (`b.__gravity__(dt)`) y no con sintaxis dedicada,
porque el compilador no sabe qué significa tu hook — a diferencia de `print(x)`
o `a == b`. Detalles completos en [../htims/readme.md](../htims/readme.md).

---

## Detalles que conviene saber

- **`ptr mutable` para escribir**: si tu método o tu hook va a MODIFICAR el
  objeto, el puntero debe ser `T ptr mutable`, no `T ptr` (si no, el compilador
  lo marca con `SEM015`). `T ptr` es "solo lectura a través del puntero".
- **`sizeof` necesita un tipo con nombre** (`SEM006`).
- **En un genérico, el lenguaje despacha los hooks de `T`; tú no le pides
  nada por su nombre.** Sobre un `T` sin cota siguen valiendo `==`
  (`__eq__`), `<` (`__cmp__`, `SEM039` por instancia), `hash` (`__hash__`),
  copiarlo (`SEM038`), destruirlo (`__free__`) y escribirlo en un f-string:
  cada instancia lo comprueba con su tipo concreto. Lo que es `SEM043` es
  llamar a un método o a un dunder (`x.__aplica__(1)`), leer un campo o usar
  `x[i]` sobre un valor de tipo `T` (o `T ptr`): un `T` sin cota no promete
  nada. Para pedirle algo, declara una **cota** (`fn f<T: Contrato>`,
  `<T: Ord>`, `<T: Print>`): dentro del cuerpo `T` ofrece lo que la cota
  promete y se comprueba en la definición; cada instancia la cumple en su
  llamada. O pásale una función (`fn(T) -> R`). Ver `type_system.rst`
  (Cotas y conceptos).
- **Un hook o un dunder no es un valor** (`SEM044`): no se guarda en una
  variable ni se pasa. Un método de `@impl` sí: `Tipo.metodo` es una función
  con el receptor como primer parámetro (`fn(Tipo ptr, ...) -> R`).
- **`print` y `len` no son palabras clave**: son identificadores que, si no
  resuelven a una función declarada, despachan al hook del tipo de su primer
  argumento. Una función tuya llamada `print` tiene prioridad sobre el hook.
- **La extensión de VS Code aún marca falsos rojos** sobre hooks/prototipos
  válidos (su verificador está desincronizado con el compilador). Si tu archivo
  compila con `python V0/main.py archivo.srcx`, esos subrayados son ruido de la
  extensión. La fuente de verdad es el compilador.

---

## Estado actual, sin adornos

"Se valida" = el compilador comprueba que lo escribiste bien; "ejecuta" = corre
de verdad con `--run`.

| Herramienta | ¿Se escribe y valida? | ¿Ejecuta hoy? |
|---|---|---|
| Hooks **declarados por tu proyecto** (HTIMS) | Sí — contra la firma que declara tu extensión | ✅ Sí, invocados como `x.__hook__(...)` |
| Hooks `__print__` / `__len__` / `__sizeof__` / `__free__` / `__cast__` | Sí | ✅ Sí |
| Hooks `__index__` / `__index_set__` / `__eq__` | Sí | ✅ Sí (`v[i]`, `v[i] = x`, `a == b`) |
| Hook `__cmp__` | Sí | ✅ en el intérprete. ❌ La VM todavía no lo despacha (compararía los *handles*); el target web, sin verificar |
| `==` sin `__eq__` (igualdad de valor) | — | ✅ en el intérprete. ❌ La VM todavía compara la identidad; el target web, sin verificar |
| Dunders (`x.__metodo__()`) en el mismo archivo | Sí | ✅ Sí — el método corre y la mutación del receptor se propaga |
| Dunders sobre un tipo de **otra librería** | Sí | ✅ Sí — el despacho cross-módulo funciona |
| Traits (`@trait` / `@impl`) | Sí (conformidad verificada, `SEM021`) | — (el contrato no "ejecuta"; los dunders que exige, sí) |
| Cotas `<T: Contrato>` / conceptos | Sí (en la definición y en cada instancia) | ✅ en el intérprete. ❌ La VM rechaza lo que despacha una cota (`print(x)`, `x.metodo()` sobre `T`) con `VM003` |

## TODO

- [x] **Ejecutar dunders en el intérprete** (mismo módulo).
- [x] **Resolución de métodos cross-módulo**: `c.__m__()` encuentra el dunder
  cuando el TIPO viene de una librería importada.
- [x] **Hook `__index__`** (y `__index_set__`, y `__eq__`) para tipos con
  nombre.
- [ ] **Métodos de nombre llano** (`lista.push(3)` en vez de
  `lista.__push__(3)`) vía un bloque `@impl Tipo { fn push(...) }`.
- [x] **Vocabulario extensible por el usuario** (HTIMS): `__gravity__` ya
  puede ser un hook de primera clase declarado por tu proyecto — se valida
  contra la firma que declara tu extensión y ejecuta. Ver
  [../htims/readme.md](../htims/readme.md).
- [ ] **Que el LSP conozca los hooks del proyecto**: `--emit-lang-info`
  publica hoy solo el vocabulario fijo.
- [ ] **Sincronizar la extensión de VS Code**: que consuma `--emit-diagnostics`
  en vez de reimplementar la gramática.
