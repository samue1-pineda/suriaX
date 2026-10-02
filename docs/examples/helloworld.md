# Hello, world!

"hola mundo!" en suriaX. Muestra cómo se importa una librería nativa (libsrX)
y cómo se llama a una de sus funciones. Todos los ejemplos de esta página se
ejecutan tal cual con `python main.py archivo.srcx` (compila y ejecuta).

```srcx
// hello.srcx
#from io #import stdp

// 'println' no es una palabra reservada: es una función del submódulo
// 'stdp' del paquete IO (lib/io/stdp.libsrx)
stdp.println("Hello, world!");
```

Puntos clave:

- **`;` obligatorio:** toda sentencia termina en punto y coma.
- **libsrX:** `println` viene de la librería `IO`, no del lenguaje. El paquete
  vive en `lib/io/` y se llama como su alias (`#export package as IO`).
- **`fn main` es opcional:** las sentencias del nivel superior se ejecutan en
  orden, como un script. Con `main`, el valor que devuelve es el código de
  salida:

```srcx
#from io #import stdp

fn main() -> int {
    stdp.println("desde main");
    return 0;
};
```

## Formas de importar

Las cuatro formas siguientes imprimen lo mismo. Cambia el nombre con el que se
llega a la función:

```srcx
#from io #import stdp;            // el submódulo, directo:      stdp.println(...)
#import IO;                       // el paquete:                  IO.stdp.println(...)
#import IO as es;                 // el paquete con otro alias:   es.stdp.println(...)
const IO = #import IO;            // lo mismo, como declaración:  IO.stdp.println(...)
```

> `const IO = #import IO;` y `#import IO as IO;` son equivalentes: las dos
> ligan el paquete a un nombre. (Una sola línea de import por archivo en estos
> ejemplos; se pueden combinar.)

## `print`, `println` y `printf`

`stdp.print` escribe el texto tal cual, `stdp.println` le añade un salto de
línea, y `stdpf.printf` (otro submódulo) escribe el texto sin añadir nada:

```srcx
#from io #import stdpf

stdpf.printf("sin salto de linea; ");
stdpf.printf("ahora si\n");
```

## Interpolación

La interpolación es **opt-in**: solo una **f-string** (`f"..."`) interpola
`{expr}` (con `{{` / `}}` para una llave literal). Una cadena normal `"..."`
nunca interpola; ahí `{veces}` es texto.

```srcx
#from io #import stdp

var int veces = 3;
stdp.println(f"Hola mundo x{veces}");   // -> Hola mundo x3
stdp.println("Hola mundo x{veces}");    // -> Hola mundo x{veces}
```

## Ver cada fase

El objetivo de suriaX es que se vea qué entrega cada fase del compilador.
Antepón `#test <fase>` al archivo para volcar esa fase y terminar:

```srcx
#test lexer
#from io #import stdp
stdp.println("Hello, world!");
```

Las fases disponibles son `lexer`, `parser`, `ast`, `sem` y `hir`. Sin tocar
el archivo, `python V0/main.py hello.srcx --emit-stage ast` hace lo mismo, y
`--hir-pretty` deja en `dumps/` el HIR legible. Todas las opciones están en
[FLAGS.md](../../FLAGS.md).
