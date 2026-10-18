# `lib/` — librerías nativas del proyecto

Ruta de búsqueda por defecto de `#import` (`libraries.libsrx_paths` en el
`.suriaX_config.yaml`, relativa a la raíz del proyecto). El compilador busca
primero en el directorio del `.srcx` que importa y luego aquí.

Quien resuelve estos archivos es [`V0/src/linker_p/`](../V0/src/linker_p/),
el linker de librerías nativas; la guía para escribirlas está en
[docs/examples/library_libsrx.md](../docs/examples/library_libsrx.md).

## Regla central

> Un módulo se llama como su **alias** (`#export`), no como su archivo ni
> como su carpeta.

## Estructura de un paquete

Cada carpeta es un **paquete**: su archivo padre `main.libsrx` lo cierra con
`#export package as <alias>`, y cada otro `.libsrx` es un submódulo cuyo
nombre público lo da su propio `#export`.

```
lib/
├── io/
│   ├── main.libsrx         // '#export package as IO'    -> '#import IO'
│   ├── stdp.libsrx         // '#export as stdp'          -> 'IO.stdp': print, println
│   └── stdpf.libsrx        // '#export as stdpf'         -> 'IO.stdpf': printf
├── array/
│   ├── main.libsrx         // '#export package as array'
│   └── vector.libsrx       // '#export as vector'
├── math/
│   ├── main.libsrx         // '#export package as math'
│   ├── basic.libsrx        // '#export as basic'
│   └── constants.libsrx    // '#export as constants'
├── d_types/
│   ├── main.libsrx         // '#export package as d_types'
│   └── dt_variables.libsrx // '#export as dt_variables'  -> int8/float16/...
├── mem/
│   └── main.libsrx         // '#export package as mem'   -> reserva/copia de memoria
├── excepciones/
│   └── main.libsrx         // '#export package as excepciones' -> los tipos, en la RAÍZ
├── collections/
│   ├── main.libsrx         // '#export package as collections'
│   ├── dictionary.libsrx   // '#export as dictionary'    -> Dictionary<K, V>
│   └── pair.libsrx         // '#export as pair'          -> Pair<K, V> (key, value)
├── func/
│   └── main.libsrx         // '#export package as func'  -> map, fold sobre Vector
├── result/
│   └── main.libsrx         // '#export package as result' -> Result<T, E>: Ok / Err
├── text/
│   └── main.libsrx         // '#export package as text'  -> slice, find, join, split, lines, trim, replace, lower/upper, is_*, parse_int, UTF-8
└── sistema/
    ├── main.libsrx         // '#export package as sistema'
    ├── archivos.libsrx     // '#export as archivos'      -> leer, escribir, listar, crear_carpeta, borrar, renombrar, modificado, File/open, read_bytes/write_bytes
    ├── proceso.libsrx      // '#export as proceso'       -> argumentos, argumento, escribir_error, salir
    ├── entrada.libsrx      // '#export as entrada'       -> la entrada estándar: linea, todo, terminada
    ├── comandos.libsrx     // '#export as comandos'      -> ejecutar otro programa (Resultado: codigo, salida, errores)
    ├── tiempo.libsrx       // '#export as tiempo'        -> ahora, reloj, dormir
    └── rutas.libsrx        // '#export as rutas'         -> absoluta, normaliza, une, carpeta_de, nombre_de, es_archivo, directorio_actual, entorno...
```

Toda librería de `lib/` es un paquete, aunque hoy tenga un solo archivo:
así crecer es añadir un submódulo y no mover lo que existe. Un paquete puede
declarar cosas en su RAÍZ (`mem`, `excepciones`): `exc.DivisionPorCero` es un
tipo del `main.libsrx` de `excepciones`, y una familia nueva de excepciones
entraría como `excepciones/<familia>.libsrx` sin cambiar esa ruta.

## Colecciones (`collections`)

`collections.dictionary` es un diccionario genérico `Dictionary<K, V>`
(`put`, `get`, `at`, `at_mut`, `take`, `contains`, `remove`, `len`, `keys`, `values`), escrito en
suriaX sobre `mem`: direccionamiento abierto, capacidad en potencias de 2 y la
casilla con `hash(clave) & (cap - 1)`. Una clave necesita un hash y una
igualdad: nativos en `int`, `bool`, `char`, `str` y los enums sin payload. Un
struct necesita `__hash__`; la igualdad ya es la de valor (mismos campos), y
`__eq__` solo hace falta si "igual" no es eso (ver [HOOKS.md](HOOKS.md)). Es la
primera librería con nombres de código en inglés y comentarios en español,
la convención para las librerías nuevas.

**Contenedores y destructores.** `Vector<R>` y `Dictionary<K, R>` son dueños
de sus elementos: los destruyen al morir, al reemplazarlos y al quitarlos. Lo
que COPIARÍA un elemento con destructor (`get`, `v[i]`, `values()`) es
`SEM038`; para eso están `at` (presta un puntero) y `take` (lo saca).

## Vectores (`array`)

`array.vector` es un `Vector<T>` genérico sobre `mem`: `make` (capacidad
fija) y `dynamic` (crece), con `push`, `pop`, `get`, `at`, `take`, `set`,
`len`, `cap`, `data`, `fixed`, `at_mut` y `v[i]`. `get`, `pop` y `v[i]`
entregan COPIAS: `v[i].campo = x` o `v[i].push(x)` es `SEM041`, y se escribe
`v.at_mut(i).campo = x` (un préstamo que muere si el vector crece:
`RT003`). `v.sort()` ordena de menor a mayor
con `<`, de forma estable (mezcla, O(n log n), mueve sin copiar). Sirve para
cualquier `T` que se ordene: números, `char`, `str`, `byte`, enums sin datos
y tipos con `__cmp__`; con otro `T` es `SEM039`. Dos vectores son `==` si
tienen el mismo largo y los mismos elementos; la capacidad no cuenta.
`sort` está en `@impl Vector<T: Ord>`: la cota se comprueba en la llamada
(`SEM039` si el tipo no se ordena). `v.sort_by(f)` ordena con una función `fn(T ptr, T ptr) -> int` (estable,
sin `__cmp__`), y `v.filter(f)` con una `fn(T ptr) -> bool` da un vector
nuevo con copias de los que cumplen. `get`, `set`, `v[i]` y `v[i] = x`
trabajan sobre los elementos: fuera de `[0, len)` lanzan
`excepciones.IndiceFueraDeRango`, aunque el índice quepa en la capacidad.
`v.any(p)`, `v.all(p)`, `v.count_if(p)` y `v.find(p)` (`-> int?`) preguntan
con un `fn(T ptr) -> bool`; `any`, `all` y `find` cortan en cuanto saben la
respuesta. Copian el elemento como `filter` (`SEM038` con destructor).
`d.get_or(k, d0)` da el valor o `d0` sin lanzar ni agregar la clave, y
`d.items()` las claves con sus valores, como un `Vector<Pair<K, V>>` de
`collections.pair` (copias, en el orden de `keys()`).
`sort_by`, `filter`, `func.map` y `func.fold` aceptan también una lambda:
`v.sort_by(lambda (P ptr a, P ptr b) -> int: a.edad - b.edad)`,
`v.filter(lambda (int ptr x) -> bool: x[0] > umbral)` (lee `umbral`).
`at` y `at_mut` (aquí y en `Dictionary`) prestan elementos que son objetos
(structs, enums con datos). Con elementos escalares (`int`, `str`…) la
llamada es `SEM013` al compilar: se lee con `get`/`v[i]` y se escribe con
`set`/`v[i] = x` (o `d.put`). Una clave de `Dictionary` sin hash (una
función, un `float`, un struct sin `__hash__`) es un error en la llamada que
la hashea.

Quien escribe un genérico no puede pedirle a su `T` métodos, campos ni `[]`
(`SEM043`): nada lo promete. El comportamiento se le pasa como función
(`fn(T ptr, T ptr) -> int`). Los métodos de un tipo genérico (`Vector.push`)
todavía no pueden ser valores; los de un tipo que no es genérico sí
(`v.sort_by(Persona.compara)`).

## Resultados (`result`)

`result.Result<T, E>` es un enum genérico con `Ok(T)` y `Err(E)` para lo que
puede fallar como respuesta normal (las excepciones siguen siendo para lo
inesperado). Los tipos se escriben siempre (`res.Result<int, str>.Ok(5)`,
también en cada `case`) y se abre con `match`. Ayudas: `r.is_ok()` y
`r.unwrap_or(d)` (copia: `SEM038` con un `T` con destructor). Vive en su
propio paquete porque la VM rechaza (`VM002`) todo programa que cargue un
enum genérico: así solo lo paga quien lo importa.

## Funcional (`func`)

`func.map<T, U>(&v, f)` aplica una `fn(T ptr) -> U` a cada elemento y da un
`Vector<U>`; `func.fold<T, A>(&v, init, f)` acumula con una
`fn(A, T ptr) -> A`. Los argumentos de tipo se deducen (`func.map(&v, f)`);
la forma escrita sigue valiendo. Están fuera de
`Vector` porque se escribieron antes de que existieran los métodos
genéricos; hoy podrían ser métodos (`fn map<U>` dentro de `@impl Vector<T>`). `f` recibe un puntero (`x[0]` para
leer un `int`) a una COPIA del elemento, así que con un `T` con destructor
son `SEM038`.

## Cadenas (`text`)

`text` son las operaciones sobre cadenas que costaban demasiado escritas a
mano (un trozo se armaba carácter a carácter y unir mil partes era
cuadrático): `slice`, `find`/`find_from`, `starts_with`/`ends_with`, `join`
(que es también la forma de CONSTRUIR un texto largo: las partes en un
`Vector<str>` y una sola unión al final), `parse_int` (`str` -> `int`, con
`excepciones.ConversionInvalida`, EXC004, si no se puede), `parse_float`
(`str` -> `float` con redondeo correcto: el mismo `double` que Python) y
`to_bytes` / `from_bytes` (UTF-8). Los índices cuentan caracteres, como `s[i]`. Cada una es
una llamada al host, con el mismo contrato en los dos motores.

Para las herramientas que analizan código o texto, además:

- **Partir:** `split(s, sep)` (como `str.split(sep)` de Python: una parte
  más que separadores, `""` en los extremos; `sep` vacío es
  `excepciones.ValorInvalido`), `split_whitespace(s)` (las palabras, sin
  partes vacías) y `lines(s)` (corta en `"\n"` y `"\r\n"`, como
  `sistema.entrada`; un `"\r"` suelto no corta; el último fin de línea no
  abre una línea vacía). Las tres devuelven un `Vector<str>`.
- **Recortar y buscar:** `trim`/`trim_start`/`trim_end`, `contains`,
  `rfind` (la última aparición, o -1) y `count` (sin solaparse; parte vacía
  = `ValorInvalido`).
- **Armar:** `replace(s, old, new)` (`old` vacío = `ValorInvalido`),
  `repeat(s, n)` (`n` negativo = `ValorInvalido`) y `pad_left`/`pad_right(s,
  width, fill)` con un `char` de relleno (cuentan caracteres, no columnas
  de la terminal).
- **Unicode, sin idioma:** `lower`/`upper` (pueden cambiar el largo:
  `upper("ß")` es `"SS"`) y las clases de un `char`: `is_digit` (dígito
  decimal de cualquier escritura; `'²'` no), `is_alpha`, `is_alnum`
  (exactamente `is_alpha or is_digit`), `is_space` (lo que recortan `trim*`
  y separa `split_whitespace`), `is_upper`, `is_lower`.

Mayúsculas, clases, `split*`, `lines`, `trim*`, `count` y `rfind` son
llamadas al host (las tablas de Unicode, o un bucle que en el intérprete
costaría una vuelta por carácter); por ahora **solo en el intérprete** (en
la VM, `RT008`). `contains`, `replace`, `repeat` y `pad_*` están escritas en
suriaX sobre las otras (`replace` usa `split`, así que también es solo del
intérprete).

## Llamadas al host (`sistema`)

`sistema.archivos` lee y escribe archivos (de texto UTF-8, o BINARIOS con
`read_bytes`/`write_bytes` y un `Vector<byte>`), lista carpetas y las crea
(`crear_carpeta`, con las que le falten, como `mkdir -p`), borra un archivo
o una carpeta vacía, renombra de una vez (`renombrar`: quien mire ve el
viejo o el nuevo, nunca uno a medias) y da la fecha de modificación en
milisegundos; `sistema.proceso` recibe los argumentos del programa (los que
van después de `--`: `suri prog.srcx -- a b`) y termina con un código;
`sistema.entrada` lee la entrada estándar (para usar el programa en una
tubería); `sistema.comandos` lanza otro programa, sin intérprete de órdenes
de por medio, y devuelve su código, su salida y sus errores;
`sistema.tiempo` da la hora (milisegundos desde 1970), un reloj que no va
hacia atrás para medir, y espera. Debajo hay **llamadas al host** (prototipos `__leer_archivo__`,
`__argumento__`...), no syscalls. Cada motor las cumple con su plataforma y
con el MISMO contrato:
- UTF-8 sin traducir los fines de línea;
- el fallo es `excepciones.ErrorDeArchivo` (`EXC003`), con un mensaje
  canónico;
- el listado sale ordenado;
- `salir` no desenrolla.

`sistema.rutas` calcula rutas EXACTAMENTE como `os.path` de Python en ese
sistema (`absoluta` es `abspath`, `normaliza` es `normpath`, `une` es `join`,
y así cada una), más el directorio actual y las variables de entorno. No
inventa reglas: existe para que el compilador escrito en suriaX ubique las
librerías y escriba sus rutas igual que el de Python. En la VM es una
reimplementación de `ntpath`/`posixpath` (`backend/src/rutas.cpp`, con las
mismas llamadas de Windows que usa Python); la prueba diferencial la compara
con el intérprete, que usa `os.path` tal cual.

Implementaciones:
- el intérprete: `runtime/interpreter/intrinsics.py`;
- la VM: `llamada_al_sistema` en `backend/src/vm.cpp` (y `backend/src/rutas.cpp`).

La lista completa —cada llamada, su firma y qué motor la cumple— está en
[`LLAMADAS_AL_HOST.md`](LLAMADAS_AL_HOST.md), que una prueba compara con la
librería y con los motores. La entrada estándar, borrar, renombrar, la fecha
de modificación, los comandos y el tiempo existen **solo en el intérprete**
por ahora.

El target web no las tiene y rechaza la librería al compilar.

## Hooks de memoria (`mem`)

`mem` publica las primitivas crudas de memoria como **hooks** (`__reserve__`,
`__copy__`, `__release__`, `__take__`, `__move__`), por el mismo patrón
*prototipo + intrínseco* que `__write__`: un
`fn` sin cuerpo que el host implementa (`runtime/interpreter/intrinsics.py`
en el intérprete; la VM, con sus propias instrucciones de memoria). Añadir un
hook así **no toca el compilador** — es la vía para no cablear cada dunder en
la Semántica. Sobre `mem` se construye un vector (reservar un bloque contiguo,
indexar con `buf[i]`, crecer = reservar mayor + `transfer` + soltar el viejo).

Un bloque **posee sus celdas no vacías**: `release` las destruye (el
`__free__` de cada una). `take` saca una celda y `transfer` un tramo sin
destruir nada: las celdas quedan vacías y cada valor sigue con un solo dueño.
`copy` copia, y con un tipo con destructor es `SEM038`.
`float_bits` / `float_from_bits` reinterpretan los 64 bits IEEE-754 de un
`float` (el `f64::to_bits` de Rust): así se escribe un `double` en binario.

El nombre de la **carpeta** localiza el paquete en disco (tolerando el case:
`#import IO` encuentra `lib/io/`); el **alias** es el que manda y debe
coincidir con el nombre del import.

> El archivo padre **no importa a sus submódulos**: la carpeta los descubre
> sola. Escribir `#import stdp` dentro de `io/main.libsrx` crearía una
> unidad suelta `stdp` ADEMÁS de la del paquete (`IO.stdp`).

## Cómo se usan desde el consumidor

```srcx
#import IO;            // el paquete -> IO.stdp.print("hola");
#import IO.stdp;       // solo el submódulo -> stdp.print("hola");
#import IO.stdp as p;  // con alias -> p.print("hola");
#from IO.stdp #import print;   // solo ese símbolo -> print("hola");
```

Los **tipos** que publica una librería se nombran igual que sus funciones,
cualificados por el módulo — tanto en una anotación como en un literal:

```srcx
#import geo.point;
var point.Point a = point.build(3, 4);       // fábrica de la librería
var point.Point b = point.Point{ x: 3, y: 4 };  // literal cualificado
```

Cada unidad compila a su propio `.phir`, nombrado por su alias **calificado**
(`IO.phir`, `IO.stdp.phir`): así dos paquetes con un submódulo homónimo no se
pisan. El *module linker* del intérprete los liga al cargar.

## Tipos no nativos

`d_types` publica con `type` los tipos que no son primitivos del lenguaje
(ver [t_types.md](../docs/gramar/t_types.md)):

```srcx
// dt_variables.libsrx
const type int8;
const type float16;

#export as dt_variables
```

```srcx
// consumidor
#from d_types #import dt_variables as dt;
const dt.int8 abc = 5;
```
