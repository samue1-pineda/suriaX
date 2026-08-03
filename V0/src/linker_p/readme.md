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

> Un módulo se llama como su **alias** (`#export`), no como su archivo ni
> como su carpeta.

`lib/io/main.libsrx` con `#export package as IO` se importa como `IO`. El
nombre de archivo solo sirve para **localizarlo en disco**.

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
