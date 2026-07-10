# Escribir una librería nativa (`.libsrx`)

La filosofía libsrX de suriaX es: **pocos tokens reservados, casi todo viene de
librerías nativas**. Una librería se escribe en un archivo `.libsrx` y se
**cierra con la directiva `#export <alias>`**: ese alias es el nombre con el que
otros archivos la importan (`#import <alias>`).

tambien se pueden crear archivos usar igual que una libreria pero hacer muchas llamadas a un mismo archivo puede llegar a ser contraproducente por lo cual el compilador arrojara una nota si observa que un archivo se usa de esta forma.
`
NOTE: "file.srcx" is used as a library, for better performance create a library using the extension .libsrx
`

> Estado: válido a nivel léxico. La resolución real de
> `#import`/`#export` y la carga de `.libsrx` es trabajo del parser/semántica (ver [ROADMAP.md](../../ROADMAP.md), Fase 9).

## Reglas de una `.libsrx`

- Declara tipos y funciones que la librería expone.
- Los **métodos dunder** (`__foo__`) son especiales del tipo; en una librería
  pueden invocarse sin los `__` desde el consumidor.
- **Debe terminar** con `#export <alias>`. Sin ese `#export`, la librería no es
  importable (se reportaría un error al resolverla).

## Ejemplo: librería `IO`

Archivo [`io.libsrx`](io.libsrx):

```srcx
// io.libsrx — librería de entrada/salida (ejemplo)

// tipo cadena con su longitud (struct: nombre al final, estilo C)
struct {
    str text;
    int len;
} String;

// métodos dunder del tipo String: se pueden llamar sin '__' desde fuera
fn __print__(ptr String s) -> void {
    // implementación real provista por el runtime / #extern cpp
}

fn __len__(ptr String s) -> int {
    return s.len;
}

// API pública de la librería
fn printf(str fmt) -> void {
    // imprime una cadena con interpolación ya resuelta por el front
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

## Resumen de directivas de librería

| Directiva                       | Uso                                            |
|---------------------------------|------------------------------------------------|
| `#import <lib> [as <alias>];`   | Importa una librería (opcionalmente con alias).|
| `#export <alias>`               | Cierra y publica una `.libsrx` con su alias.   |
| `#from <lib> #import <name>;`   | Importa un elemento concreto de una librería.  |
| `#extern cpp{ ... }`            | Incrusta C++ (capturado como `RAW_BLOCK`).     |

Ver la gramática en [docs/gramar/grammar.ebnf](../gramar/grammar.ebnf) y los
tipos/tokens en [docs/gramar/t_types.md](../gramar/t_types.md).
