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
├── utils/
│   └── main.libsrx         // '#export package as utils'  (paquete vacío por ahora)
├── d_types/
│   ├── main.libsrx         // '#export package as d_types'
│   └── dt_variables.libsrx // '#export as dt_variables'  -> int8/float16/...
└── mem/
    └── main.libsrx         // '#export package as mem'   -> reserva/copia de memoria
```

## Hooks de memoria (`mem`)

`mem` publica las primitivas crudas de memoria como **hooks** (`__reserve__`,
`__copy__`), por el mismo patrón *prototipo + intrínseco* que `__write__`: un
`fn` sin cuerpo que el host (`runtime/interpreter/intrinsics.py` bajo
`target: interp`, o un `#extern` del backend nativo) implementa. Añadir un
hook así **no toca el compilador** — es la vía para no cablear cada dunder en
la Semántica. Sobre `mem` se construye un vector (reservar un bloque contiguo,
indexar con `buf[i]`, crecer = reservar mayor + `__copy__`).

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
