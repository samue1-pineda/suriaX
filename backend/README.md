# Backend C++ de suriaX

El mundo nativo. Hoy tiene **una** pieza: el **lector del HIR**, la entrada
del futuro lowering a MIR.

```
  frontend Python                backend C++ (este paquete)
 ┌────────────────┐   .phir     ┌────────────────────────────────────────┐
 │ lexer → parser │ ──────────▶ │ leer      include/suriax/hir/loader.hpp│
 │ → AST-tipado   │  protobuf   │ ligar     Image (N unidades)           │
 │ → semántica    │             │ ver       include/suriax/hir/view.hpp  │
 │ → HIR          │             │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
 └────────────────┘             │ MIR → VM/JIT            (no existe)    │
                                └────────────────────────────────────────┘
```

## Por qué existe antes que el MIR

Es el paso 3 de [`PROTOBUF_BRIDGE.md`](../V0/src/HIR/PROTOBUF_BRIDGE.md)
secc. 4, y su propósito no es ejecutar nada: es **congelar el contrato de la
frontera**. Mientras exista un consumidor C++ que lee *todo* lo que el emisor
escribe —y una prueba que lo comprueba contra el lector de Python— el HIR no
puede derivar sin que se note. El día que empiece el lowering a MIR, la
entrada ya está probada.

## Qué hay

| Pieza | Archivo | Qué hace |
|---|---|---|
| Lector | [`include/suriax/hir/loader.hpp`](include/suriax/hir/loader.hpp) | `.phir` → `Module`, con **fail-fast** de `schema_version`. |
| Unidad | idem (`Unit`) | Índices locales: funciones, dunder por `(nombre, línea)`, valores de `enum`, bloques `test`. |
| Module linker | idem (`Image`, `load_image`) | Liga main + `.libsrx` transitivamente; índices de hooks y de conversiones en O(1). |
| Vistas | [`include/suriax/hir/view.hpp`](include/suriax/hir/view.hpp) | La legible y el resumen — **byte-idénticas** a las de Python. |
| `#extern cpp` | [`include/suriax/hir/view.hpp`](include/suriax/hir/view.hpp) | Recoge los bloques de todas las unidades y los escribe como una unidad de traducción de C++. |
| CLI | [`tools/suriax_hir.cpp`](tools/suriax_hir.cpp) | `suriax-hir`. |

Espejo deliberado de [`runtime/interpreter/loader.py`](../runtime/interpreter/loader.py):
mismas piezas, mismos índices y la misma regla de resolución de rutas. Dos
lectores del mismo contrato que no se parecen son dos contratos.

### Sobre el modelo de objetos

Este lector trabaja **directamente sobre los mensajes que genera `protoc`**,
sin materializar un AST paralelo en C++. Es lo que hacen los otros dos
consumidores que ya existen (el intérprete y `pretty.py`); el backend web
tiene su propio modelo solo porque escribió a mano el decodificador del wire
format, cosa que aquí no hace falta. Un modelo paralelo sería una tercera
definición del mismo esquema que mantener sincronizada con el `.proto`.

Los errores viajan por **código de estado**, no por excepciones — misma
convención que [`runtime/logic_mem`](../runtime/logic_mem/): esto lo enlazará
la VM, y acoplar el ABI al runtime de excepciones no compra nada.

## Construir

```bash
cmake -S . -B build                                # desde la raíz del repo
cmake --build build --target suriax-hir -j
```

Necesita **protobuf para C++** (`libprotobuf` + `protoc`). Si falta, el
backend se omite con un aviso y todo lo demás sigue compilando: el frontend
en Python no depende de este lado.

Los stubs C++ del esquema se generan **en build** desde
`V0/src/HIR/proto/hir.proto` —la fuente única— igual que los de Python en
`V0/src/HIR/stubs.py`. No se commitean.

## Usar

```bash
build/bin/suriax-hir dumps/programa.srcx.phir              # resumen
build/bin/suriax-hir dumps/programa.srcx.phir --pretty     # vista legible
build/bin/suriax-hir dumps/programa.srcx.phir --link       # + unidades ligadas
build/bin/suriax-hir dumps/programa.srcx.phir --verify     # ¿algún nodo sin handler?
build/bin/suriax-hir dumps/programa.srcx.phir --emit-cpp extern.cpp
```

Las dos vistas son **byte-idénticas** a las de Python:

```
--pretty   ==  python V0/main.py <fuente> --emit-hir --hir-pretty
--summary  ==  python runtime/interpreter/main.py <archivo>.phir
```

Esa identidad es una decisión, no una casualidad: es lo que convierte
[`test/e2e/test_backend_cpp.py`](../test/e2e/test_backend_cpp.py) en un
**diferencial entre consumidores** de verdad. Una vista "parecida" no probaría
nada.

## `#extern cpp`: dónde aterriza

El lexer captura el bloque **crudo** (token `RAW_BLOCK`), la Semántica no lo
mira y el HIR lo transporta intacto hasta aquí. `--emit-cpp` lo convierte en
un archivo que un compilador de C++ lee de verdad:

```cpp
// Generado por suriaX: los bloques '#extern cpp' del programa.
// unidad '<principal>'
#line 84 "programa.srcx"
int ayuda_nativa() { return 1; }
```

El `#line` no es adorno: hace que **los errores del compilador de C++ apunten
al `.srcx` del usuario**, con su línea y su código, en vez de a un archivo
generado que nadie escribió. Sin esa trazabilidad, depurar un `#extern` sería
leer código que uno no ha visto nunca.

Se recogen los bloques de **todas** las unidades (una librería también puede
traer C++), en el mismo orden en que el intérprete las inicializa. Un target
que no sea `cpp` se rechaza con su unidad y su posición en vez de escribirse
en un archivo que luego no compilaría.

Compilarlo y enlazarlo es del backend nativo, que todavía no existe.
Producirlo, ya no.

## Las dos invariantes que este lector sostiene

**1. Fail-fast de esquema.** `Module.schema_version` se valida antes de mirar
el contenido. Un `.phir` de otra versión no es "casi correcto": es un
artefacto cuyo significado cambió. Las versiones soportadas están en
`kSupportedSchemaVersions` y se mueven a la vez que las de
`runtime/interpreter/loader.py` y `web/src/hir/decode.ts` — son los tres
lectores vivos del contrato.

**2. Ningún nodo se salta en silencio.** El recorrido es un `switch` por cada
`oneof` **sin rama `default`**: añadir un caso al esquema rompe la compilación
de este archivo, que es la exhaustividad verificable por el compilador que
promete `PROTOBUF_BRIDGE.md`. Y un mensaje que llega *sin* caso puesto (un tag
que este lector no conoce, que protobuf deja en los campos desconocidos) se
**anota con su posición** en vez de saltarse — el equivalente C++ de
`_error_unsupported` del emisor. `--verify` falla si queda alguno.

## Lo que sigue (y no está)

El **MIR** (`docs/mir.md`): registros, CFG y la verificación de propiedad y
préstamos. Y después la VM de bytecode con JIT. Antes de escribir la primera
estructura del MIR hay una decisión que documentar —**¿SSA o no?**— con su
análisis de dataflow; no es un default, es un trade-off (ver la skill
`compiler-ir-quality`).

**LLVM queda fuera del plan**: el MIR ya es un IR de registros con CFG, y
meterlo en medio añadía una dependencia enorme y un segundo modelo de máquina
antes de tener el primero funcionando.
