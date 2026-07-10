# Hello, world!

"hola mundo!" en suriaX. Muestra la importación de una librería nativa
(libsrX) y la llamada a una función a través de su alias.

>**NOTA**: la libreria IO aun no existe, en la pre-alpha, el lexer lo identificara como un IDENTIFIER pero el parser arrojara error.
 

```srcx
//hello.srcx

// se importa la librería de entrada/salida con un alias
const IO = #import IO;

// 'printf' no es una palabra reservada: es una función de la librería 'IO'
IO.printf("Hello, world!");
```

Puntos clave:

- **`;` obligatorio:** toda sentencia termina en punto y coma.
- **libsrX:** `printf` llega de la librería `IO`; se invoca como `IO.printf(...)`.
- **forma corta del import:** también puede escribirse `#import IO;` y luego
  usar el alias por defecto.

## Variante con interpolación

Los strings admiten interpolación con `{expr}` (y `{{` / `}}` para llave
literal), importante destacar que print y printf no son lo mismo, incluso si vienen de la misma libreria, un ejemplo: 

```srcx
const IO = #import IO;

int veces = 3;
IO.printf("Hola mundo x{veces}");

IO.print("Hola mundo x{veces}");//errorxxx: print no soporta "{veces}"

```

## Probar la tokenización

Para ver cómo el lexer tokeniza este programa, antepón la directiva
`#test lexer` y ejecútalo:

```srcx
#test lexer
const IO = #import IO;
IO.printf("Hello, world!");
```

```bash
python V0/main.py archivo.srcx
```

Esto vuelca el arreglo de tokens en consola. Ver [how_to_run.md](../../how_to_run.md).
