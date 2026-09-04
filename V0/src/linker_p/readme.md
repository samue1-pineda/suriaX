# `linker_p` — linker de las librerías nativas (`.libsrx`)

Linker para las librerías nativas del lenguaje (libsrX). Es necesario
diferenciarlo del linker de objetos del backend y del de
`#extern c++{ .... }`: **esto liga unidades del LENGUAJE**, no objetos de
la plataforma.

Resuelve `#import` / `#from` entre archivos `.libsrx` (y `.srcx`), liga sus
símbolos exportados y detecta imports circulares. El frontend
(`semantic/collect.py`) es su único consumidor; este paquete **no importa
`config/`** (la configuración le llega ya cargada desde `V0/main.py`).

## Regla central

> Un módulo se llama como su **alias** (`#export`), y ese alias tiene que
> coincidir con el nombre del archivo o de la carpeta.

El alias es el nombre PÚBLICO: es el que se escribe en el `#import` y el que
prefija todo lo que la librería exporta. El nombre de archivo es lo que la
localiza en disco. **Los dos tienen que decir lo mismo**, y el loader lo
exige (`SEM010`): un `cualquiera.libsrx` que termine en `#export as OTRO`
declararía un nombre que nadie puede importar — `#import OTRO` no encuentra
el archivo y `#import cualquiera` encuentra un archivo que exporta otra cosa.

La única holgura es el *case* de una carpeta: `#import IO` encuentra `io/`,
porque un directorio en minúsculas es una convención del sistema de archivos
y no una decisión del programa.

`lib/io/main.libsrx` con `#export package as IO` se importa como `IO`.

## Identidad de un tipo

> Un tipo se identifica por **(unidad, nombre)**, no por su nombre a secas.
> Su nombre canónico es `<alias>.<Nombre>`.

Un `struct Node` declarado en `a.libsrx` se llama `a.Node` en todo el
pipeline — también dentro de la propia `a`, donde se sigue *escribiendo*
`Node`. El símbolo queda registrado bajo los dos nombres; quien lo consulta
por el canónico y quien lo escribe corto encuentran el mismo tipo.

No es cosmética. Los **hooks**, la tabla de **conversiones** (`__cast__`),
los **dunders** y el filtro de `catch` se indexan por ese nombre: mientras
fue el nombre corto, dos librerías que declararan `Node` compartían entrada y
el `__free__` que corría lo decidía el orden de carga, sin diagnóstico. En un
lenguaje cuyo modelo es la propiedad, destruir con el destructor equivocado
es el peor fallo que el sistema de módulos puede tener.

Los DIAGNÓSTICOS, en cambio, nombran el tipo **como se puede escribir desde
donde está el error**: la sugerencia útil es `cast<dt.float32>(...)`, no
`cast<dt_variables.float32>(...)`, porque el segundo nombre no existe en el
archivo del usuario. Identidad para el compilador, nombre escribible para
quien lee el mensaje.

*Límite conocido*: el calificador es el alias del `#export`, no la ruta
completa de la unidad (`vector`, no `array.vector`). Dos paquetes distintos
con un submódulo del mismo alias que declare un tipo del mismo nombre
seguirían colisionando.

### Los hooks de un tipo viven con el tipo

Declarar un hook para un tipo de OTRA unidad se rechaza:

```srcx
#import a
hook fn __len__(a.P ptr p) -> int { ... }   // error: 'a.P' es de otra unidad
```

El motivo es el mismo de arriba: la tabla de despacho es una sola, así que
dos librerías colgándole un `__free__` al mismo tipo ajeno dejarían la
elección al orden de carga. Declararlo donde se declara el tipo, o envolver
el tipo ajeno en uno propio.

## Estructura

| Módulo        | Responsabilidad                                              |
|---------------|--------------------------------------------------------------|
| `resolver.py` | nombre → ruta en disco: search paths, padre de paquete. Solo stats, sin listar directorios. |
| `loader.py`   | ruta → lexer → parser → AST-tipado → símbolos; valida el contrato `#export`. |
| `packages.py` | carpeta-paquete: archivo padre + un submódulo por alias.     |
| `cache.py`    | caché por ruta absoluta (una carga por proceso) + guard de ciclos. |
| `library.py`  | la estructura `LoadedLibrary` que produce todo lo anterior.   |

El flujo va en una sola dirección (`resolver` → `loader` → `packages`);
ningún módulo importa al anterior. `__init__.py` orquesta y expone la API:

```python
from src import linker_p

lib = linker_p.load_library("IO", source_path=..., config=..., errors=[], ln=1, col=1)
```

## Formato de una librería

Toda `.libsrx` **termina** en un `#export`; sin él no es una librería:

```srcx
fn saludar() -> void { ... }

#export as saludo     // 'as' es opcional: '#export saludo' es equivalente
```

## Paquetes (carpetas)

Una carpeta es un paquete si contiene un archivo **padre** que termina en
`#export package as <alias>`. El padre es `main.libsrx` (convención) o
`<carpeta>.libsrx` (compatibilidad). Cada otro `.libsrx` de la carpeta es un
submódulo cuyo nombre público lo da su propio `#export`:

```
lib/io/
├── main.libsrx      // '#export package as IO'   ← padre; sus decls = raíz
└── print.libsrx     // '#export as print'        ← submódulo 'print'
```

```srcx
#import IO;                        // liga el paquete entero -> IO.print....
#import IO.print;                  // liga solo el submódulo 'print'
#from IO.print #import __print__;  // liga solo ese símbolo (cero polución)
```

Un solo nivel: no hay subpaquetes anidados.

## Resolución de rutas

Orden de búsqueda: **(1)** el directorio del fuente que importa, **(2)** las
rutas de `libraries.libsrx_paths` del `.suriaX_config.yaml`, resueltas
relativas a la **raíz del proyecto** (el directorio del yaml), nunca al CWD.
Por defecto `./lib`.

Preferencia por base: archivo `.libsrx` > paquete > `.srcx`. Un import
**punteado** (`IO.print`) solo lo satisface un paquete. Un `.srcx` usado
como librería es legal pero emite una **NOTA** (`NOTE001`).

## Rendimiento

- Cada archivo/paquete se parsea **una vez por proceso** (caché por ruta
  absoluta); un batch de M fuentes que importen `IO` la carga una sola vez.
- `resolver.py` hace como mucho 2 `stat()` por candidato y **no lista
  directorios**; `os.listdir` se paga una vez por paquete, en su primera
  carga.
- El pipeline de parseo se importa de forma **diferida**: un fuente sin
  `#import` no carga nada de este paquete.
