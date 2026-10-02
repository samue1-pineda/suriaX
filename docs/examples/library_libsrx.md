# Escribir una librería nativa (`.libsrx`)

La filosofía libsrX de suriaX es: **pocos tokens reservados, casi todo viene de
librerías nativas**. Una librería se escribe en un archivo `.libsrx` y se
**cierra con la directiva `#export [as] <alias>`**: ese alias es el nombre con
el que otros archivos la importan (`#import <alias>`) — no el nombre del
archivo. El `as` es opcional (`#export io` ≡ `#export as io`).

tambien se pueden crear archivos usar igual que una libreria pero hacer muchas llamadas a un mismo archivo puede llegar a ser contraproducente por lo cual el compilador arrojara una nota si observa que un archivo se usa de esta forma.
`
NOTE: "file.srcx" is used as a library, for better performance create a library using the extension .libsrx
`

> **Estado:** la resolución de `#import`/`#export` y la carga de `.libsrx`
> funcionan (linker de librerías, `V0/src/linker_p/`). Los ejemplos de esta
> página son de **varios archivos**: la librería `IO` que se escribe aquí es
> una de ejemplo (sus funciones no imprimen nada) y se usa poniéndola como
> `io.libsrx` junto al `.srcx` que la importa. El directorio del fuente se
> busca **antes** que la stdlib, así que esa `IO` tapa a la real. La `IO` de
> verdad está en [`lib/io/`](../../lib/io/) (`IO.stdp`, `IO.stdpf`): ver
> [helloworld.md](helloworld.md).

## Reglas de una `.libsrx`

- Declara tipos y funciones que la librería expone.
- Los **métodos dunder** (`__foo__`) son especiales del tipo; en una librería
  pueden invocarse sin los `__` desde el consumidor.
- **Debe terminar** con `#export [as] <alias>`. Sin ese `#export`, la librería
  no es importable (se reportaría un error al resolverla).

## Ejemplo: librería `IO`

Archivo `io.libsrx` (se crea junto al `.srcx` que lo importa):

```srcx
// io.libsrx — librería de entrada/salida (ejemplo)

// tipo cadena con su longitud (struct: nombre al final, estilo C)
struct {
    str text;
    int len;
} String;

// hooks del tipo String: se pueden llamar sin '__' desde fuera. El
// especificador 'hook' es obligatorio (set fijo del compilador).
hook fn __print__(String ptr s) -> void {
    // implementación real provista por el runtime / #extern cpp
}

hook fn __len__(String ptr s) -> int {
    return s.len;
}

// API pública de la librería
fn printf(str fmt) -> void {
    // imprime una cadena; si el llamador pasó una f-string, la
    // interpolación ya viene resuelta por el frontend
}

fn println(str fmt) -> void {
    printf(fmt);
    printf("\n");
}

// la librería se cierra exportándose con su alias público
#export IO
```

## Implementación real vía `#extern cpp{ ... }`

Las primitivas de bajo nivel (escribir a stdout) se delegan a C++ con un bloque
crudo. El lexer captura su cuerpo como `RAW_BLOCK` (no lo tokeniza); el backend
lo compila e integra vía bindings.

```srcx
// io.libsrx (variante con backend C++)

#extern cpp{
    #include <cstdio>
    extern "C" void suriax_write(const char* s) { std::fputs(s, stdout); }
}

fn printf(str fmt) -> void {
    // 'fmt' se pasa a suriax_write a través del binding generado
}

#export IO
```
>**Nota**: inicialmente solo esta el binding con c++, motivo por el cual el codigo hace una llamada extra en c++ hacia c.   


## Usar la librería

Desde un programa `.srcx`:

Cada forma va en su propio programa (son tres maneras de importar lo mismo):

```srcx
// forma con alias explícito
const IO = #import IO;
IO.printf("Hola desde la librería\n");

// forma directa
#import IO;
IO.printf("Hola otra vez\n");

// con alias renombrado
#import IO as Consola;
Consola.println("línea con salto");
```

## Paquetes: carpetas de librerías (anti-polución de namespaces)

Una carpeta puede exportarse entera como **paquete**: su **archivo padre**
—`main.libsrx` (convención) o `<carpeta>.libsrx`— termina en
`#export package as <alias>`; cada otro `.libsrx` de la carpeta es un
submódulo cuyo nombre público lo da su propio `#export`. Así el usuario no
crea un alias por archivo:

```
lib/io/
├── main.libsrx      // '#export package as IO'  (sus decls = raíz del paquete)
├── print.libsrx     // '#export as print'
└── console.libsrx   // '#export as console'
```

> **Los nombres los dan los alias, no los archivos.** La carpeta se llama
> `io/` y su padre `main.libsrx`, pero el paquete se importa como `IO`
> porque eso es lo que declara su `#export package as`. El nombre de archivo
> solo sirve para **localizarlo en disco**.

> El padre **no importa a sus submódulos**: la carpeta los descubre sola.
> Un `#import print` dentro de `main.libsrx` crearía una unidad suelta
> `print` además de la del paquete (`IO.print`).

Con ese paquete de ejemplo (`print` y `console` son hipotéticos: la stdlib
real tiene `stdp` y `stdpf`):

```srcx
#from IO.print #import __print__;   // liga SOLO ese símbolo (cero polución)

#import IO.print;                   // liga el submódulo como 'print'
#import IO.print as p;              // ...o bajo el alias que quieras

#import IO;                         // liga el paquete entero
IO.console.log("anidado\n");
```

**Los tipos que publica la librería se nombran cualificados**, igual que sus
funciones — tanto en una anotación como en un literal de struct. El nombre
cualificado se canonicaliza al que declaró la librería, así que unifica con
lo que devuelven sus propias funciones (con una librería hipotética
`geo/point.libsrx`):

```srcx
#import geo.point;

var point.Point a = point.build(3, 4);          // fábrica de la librería
var point.Point b = point.Point{ x: 3, y: 4 };  // literal cualificado
fn total(point.Point ptr p) -> int { ... };     // envuelto en 'ptr'/'?'
```

**Unidades y `.phir`.** Cada archivo compila a su propia unidad HIR,
nombrada por su alias **calificado** (`IO.phir`, `IO.print.phir`). Es lo que
permite que dos paquetes publiquen un submódulo homónimo (`alpha.util` y
`beta.util`) sin pisarse el archivo ni la entrada del *module linker*.

> El alias de un `#export` **no puede ser una palabra reservada** (`str`,
> `free`, `int`...): el compilador lo reporta con `PAR026` y hay que
> renombrarlo.

También puede importarse un `.srcx` como librería (mismo contrato: terminar
en `#export`), pero el compilador emite una **NOTA** en `log/notes.jsonl`
recomendando `.libsrx` — la extensión comunica la intención.

**Reglas de resolución** (orden de búsqueda: dir del fuente →
`libraries.libsrx_paths`): un import **punteado** (`IO.print`) solo lo
satisface un paquete — un archivo plano homónimo no lo bloquea. Un import
**no punteado** (`io`) prefiere el archivo plano `io.libsrx` sobre un
paquete `io/` si ambos existen en la búsqueda; evita nombrar igual un
archivo y un paquete.

La **carpeta** se busca por el nombre del import (tolerando el case: `#import
IO` encuentra `lib/io/`), pero el que manda es el **alias**: si la carpeta
existe y su padre exporta otro nombre, el compilador lo dice explícitamente
en vez de fallar con un "no encontrado":

```
SEM010: el paquete 'd_types/' exporta 'd_tpypes', no 'd_types'
        (el alias de '#export' debe coincidir con el nombre del import)
```

## Publicar tipos desde una librería

Una librería puede declarar **tipos no nativos** del lenguaje con `type`
(tipo nominal opaco, ver [t_types.md](../gramar/t_types.md)):

```srcx
// lib/d_types/dt_variables.libsrx
const type int8;
const type float16;

#export as dt_variables
```

y el consumidor los usa como cualquier otro tipo, cualificados por el módulo:

```srcx
#from d_types #import dt_variables as dt;
const dt.int8 abc;
```

Si el tipo no existe, el error nombra los que sí:

```
SEM011: 'dt' no publica el tipo 'uint8'
        (tipos disponibles: float16, float32, float64, int16, int32, int8)
```

## Resumen de directivas de librería

| Directiva                       | Uso                                            |
|---------------------------------|------------------------------------------------|
| `#import <lib> [as <alias>];`   | Importa una librería (opcionalmente con alias).|
| `#import <pkg>.<sub> [as <a>];` | Importa un submódulo de un paquete.            |
| `#export [as] <alias>`          | Cierra y publica una `.libsrx` con su alias. El `as` es **opcional**: `#export io` y `#export as io` son equivalentes. |
| `#export package as <alias>`    | Declara el archivo PADRE de un paquete (`main.libsrx` o `<carpeta>.libsrx`). Aquí `as` es obligatorio. |
| `#from <lib> #import <name>;`   | Importa un elemento concreto de una librería.  |
| `#extern cpp{ ... }`            | Incrusta C++ (capturado como `RAW_BLOCK`).     |

Ver la gramática en [docs/gramar/grammar.ebnf](../gramar/grammar.ebnf) y los
tipos/tokens en [docs/gramar/t_types.md](../gramar/t_types.md).
