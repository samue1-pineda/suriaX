# `#extern cpp` que se ejecuta

El bloque `#extern cpp` ya viajaba al otro lado (`suriax-hir --emit-cpp` lo
escribe como una unidad de traducción con `#line`). Ahora además **se compila
y se liga**: un prototipo de suriaX invoca la función de C++.

```bash
suri docs/examples/extern_cpp/consola.srcx
SURIAX_CPP_FLAGS="-lX11" suri docs/examples/extern_cpp/ventana.srcx
```

| archivo | qué demuestra |
|---|---|
| `consola.srcx` | `std::cout` escribiendo, un `long long` volviendo a suriaX, y una `str` cruzando como `const char*` |
| `ventana.srcx` | una **ventana X11 de verdad**: `XCreateSimpleWindow`, `XDrawString` y su bucle de eventos, todo desde C++, orquestado desde suriaX |

## Cómo funciona

No hay mecanismo nuevo: es el de siempre, **prototipo + intrínseco**. Un
`fn abre_ventana(int, int, str) -> int;` sin cuerpo es un contrato; el
intérprete lo cumplía con Python (`__write__`) y ahora también lo cumple con
el C++ que el propio programa trae.

```srcx
#extern cpp{
#include <iostream>
extern "C" void saluda(const char* quien) { std::cout << quien; }
}

fn saluda(str quien) -> void;      // el contrato
```

Tres cosas que hay que saber:

- **`extern "C"` es obligatorio.** El símbolo se busca por su nombre y el
  *mangling* de C++ lo cambia según la firma.
- **Las banderas de enlazado** van en `compilation.cpp_flags` del
  `.suriaX_config.yaml`, o en `SURIAX_CPP_FLAGS` (son de la máquina, no del
  proyecto: la misma librería necesita `-lX11` la use quien la use).
- **La tabla de tipos de la frontera**: `int`→`long long`, `float`→`double`,
  `bool`→`bool`, `char`→code point de 32 bits, `str`→`const char*` UTF-8 a la
  ida. Un `str` de RETORNO no se liga todavía: quién libera ese buffer es una
  pregunta de propiedad sin decidir.
