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
│   └── stdp.libsrx         // '#export as stdp'          -> 'IO.stdp'
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
│   └── dictionary.libsrx   // '#export as dictionary'    -> Dictionary<K, V>
├── text/
│   └── main.libsrx         // '#export package as text'  -> slice, find, join, parse_int, UTF-8
└── sistema/
    ├── main.libsrx         // '#export package as sistema'
    ├── archivos.libsrx     // '#export as archivos'      -> leer, escribir, listar, File/open, read_bytes/write_bytes
    ├── proceso.libsrx      // '#export as proceso'       -> argumentos, salir
    └── rutas.libsrx        // '#export as rutas'         -> absoluta, normaliza, une, directorio_actual, entorno
```

Toda librería de `lib/` es un paquete, aunque hoy tenga un solo archivo:
así crecer es añadir un submódulo y no mover lo que existe. Un paquete puede
declarar cosas en su RAÍZ (`mem`, `excepciones`): `exc.DivisionPorCero` es un
tipo del `main.libsrx` de `excepciones`, y una familia nueva de excepciones
entraría como `excepciones/<familia>.libsrx` sin cambiar esa ruta.

## Colecciones (`collections`)

`collections.dictionary` es un diccionario genérico `Dictionary<K, V>`
(`put`, `get`, `at`, `take`, `contains`, `remove`, `len`, `keys`, `values`), escrito en
suriaX sobre `mem`: direccionamiento abierto, capacidad en potencias de 2 y la
casilla con `hash(clave) & (cap - 1)`. Una clave necesita un hash y una
igualdad: nativos en `int`, `bool`, `char`, `str` y los enums sin payload; un
struct los da con `__hash__` y `__eq__` (ver [HOOKS.md](HOOKS.md)). Es la
primera librería con nombres de código en inglés y comentarios en español,
la convención para las librerías nuevas.

**Contenedores y destructores.** `Vector<R>` y `Dictionary<K, R>` son dueños
de sus elementos: los destruyen al morir, al reemplazarlos y al quitarlos. Lo
que COPIARÍA un elemento con destructor (`get`, `v[i]`, `values()`) es
`SEM038`; para eso están `at` (presta un puntero) y `take` (lo saca).

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

## Llamadas al host (`sistema`)

`sistema.archivos` lee y escribe archivos (de texto UTF-8, o BINARIOS con
`read_bytes`/`write_bytes` y un `Vector<byte>`) y lista carpetas; `sistema.proceso`
recibe los argumentos del programa (los que van después de `--`: `suri prog.srcx -- a b`) y termina
con un código. Debajo hay **llamadas al host** (prototipos `__leer_archivo__`,
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

El target web no las tiene y rechaza la librería al compilar.

## Hooks de memoria (`mem`)

`mem` publica las primitivas crudas de memoria como **hooks** (`__reserve__`,
`__copy__`, `__release__`, `__take__`, `__move__`), por el mismo patrón
*prototipo + intrínseco* que `__write__`: un
`fn` sin cuerpo que el host (`runtime/interpreter/intrinsics.py` bajo
`target: interp`, o un `#extern` del backend nativo) implementa. Añadir un
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
const dt.int8 abc;
```
