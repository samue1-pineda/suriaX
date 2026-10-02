# Backend C++ de suriaX

El mundo nativo: **lee** el HIR, lo **resuelve**, lo baja a **MIR** (registros
virtuales + CFG), **verifica** la propiedad sobre el grafo y lo **ejecuta** en
una VM de registros. Falta el JIT y cualquier artefacto nativo (ver
[c_errorstfix.md](../c_errorstfix.md), punto 1).

```
  frontend Python                backend C++ (este paquete)
 ┌────────────────┐   .phir     ┌────────────────────────────────────────┐
 │ lexer → parser │ ──────────▶ │ leer      include/suriax/hir/loader.hpp│
 │ → AST-tipado   │  protobuf   │ ligar     Image (N unidades)           │
 │ → semántica    │             │ ver       include/suriax/hir/view.hpp  │
 │ → HIR          │             │ resolver  include/suriax/hir/resolve.hpp│
 └────────────────┘             │ bajar     include/suriax/mir/mir.hpp   │
                                │ verificar include/suriax/mir/verify.hpp│
                                │ ejecutar  include/suriax/mir/vm.hpp    │
                                │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
                                │ JIT / binario nativo    (pendiente)    │
                                └────────────────────────────────────────┘
```

## Por qué el lector existió antes que el MIR

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
| Resolución | [`include/suriax/hir/resolve.hpp`](include/suriax/hir/resolve.hpp) | Cada función con sus slots, a qué se resuelve cada llamada y qué destruye cada bloque. Falla si queda una llamada sin resolver. |
| MIR | [`include/suriax/mir/mir.hpp`](include/suriax/mir/mir.hpp) | Lowering HIR → MIR: registros virtuales, bloques con terminador, locales en el marco. Lo que no sabe bajar lo nombra con su posición. Ver [docs/mir.md](../docs/mir.md). |
| Verificación | [`include/suriax/mir/verify.hpp`](include/suriax/mir/verify.hpp) | Propiedad sobre el CFG (uso tras `move` por todos los caminos). Préstamos: dentro de un bloque. |
| VM | [`include/suriax/mir/vm.hpp`](include/suriax/mir/vm.hpp) | Ejecuta el MIR con la MISMA semántica que el intérprete de Python; un diferencial lo comprueba. |
| `#extern cpp` en la VM | [`include/suriax/mir/externo.hpp`](include/suriax/mir/externo.hpp) | Construye el C++ del programa, lo carga (`LoadLibrary`/`dlopen`) y llama a sus funciones con una firma tipada, sin libffi. |
| CLI | [`tools/suriax_hir.cpp`](tools/suriax_hir.cpp) | `suriax-hir`. |

Espejo deliberado de [`runtime/interpreter/loader.py`](../runtime/interpreter/loader.py):
mismas piezas, mismos índices y la misma regla de resolución de rutas. Dos
lectores del mismo contrato que no se parecen son dos contratos.

### Sobre el modelo de objetos

El lector trabaja sobre un **modelo C++ generado desde el `.proto`**:
[`include/suriax/hir/hir_modelo.hpp`](include/suriax/hir/hir_modelo.hpp).
- **Lo genera** [`tools/gen_hir_cpp.py`](tools/gen_hir_cpp.py).
- **Su API** es la misma que la de `protoc` (`has_x()`, `x()`, `x_size()`,
  `node_case()`), así que el resto del backend no cambió cuando se quitó
  `libprotobuf`.
- **Decodifica el wire format él mismo:** varints, longitudes y campos
  desconocidos, que se saltan como manda protobuf.

No es una tercera definición del esquema escrita a mano: se genera. Hay una
prueba ([`test_modelo_hir_cpp.py`](../test/unit/test_modelo_hir_cpp.py)) que
falla si el modelo guardado no corresponde al `.proto`. Los campos que son
palabras reservadas de C++ llevan un `_` final (`sizeof_()`, `mutable_()`).

**Por qué se quitó protobuf.** En Windows `libprotobuf` no se conseguía
fácil, y sin ella el backend quedaba sin construir y sus pruebas se
omitían. Los otros dos consumidores ya leían el wire format con un
decodificador propio:
- Python, con [`V0/src/HIR/stubs.py`](../V0/src/HIR/stubs.py);
- el target web, con `web/src/hir/decode.ts`.

El backend era el único que arrastraba la dependencia.

Los errores viajan por **código de estado**, no por excepciones — misma
convención que [`runtime/logic_mem`](../runtime/logic_mem/): esto lo enlazará
la VM, y acoplar el ABI al runtime de excepciones no compra nada.

## Construir

```bash
cmake -S . -B build                                # desde la raíz del repo
cmake --build build --target suriax-hir -j
```

Solo necesita **CMake 3.20+ y un compilador de C++20**, sin dependencias. El
estándar es uno solo para todo el proyecto y lo fija `version.py`. Windows
(MSVC con `vcvars64`), el editor y cómo añadir un binario nuevo: ver la guía
[`CMake/README.md`](../CMake/README.md).

Cuando cambia `V0/src/HIR/proto/hir.proto`, se regenera el modelo y se hace
commit de los dos juntos:

```bash
python backend/tools/gen_hir_cpp.py            # regenera hir_modelo.hpp
python backend/tools/gen_hir_cpp.py --check    # ¿está al día?
```

## Usar

```bash
build/bin/suriax-hir dumps/programa.srcx.phir              # resumen
build/bin/suriax-hir dumps/programa.srcx.phir --pretty     # vista legible
build/bin/suriax-hir dumps/programa.srcx.phir --link       # + unidades ligadas
build/bin/suriax-hir dumps/programa.srcx.phir --verify     # ¿algún nodo sin handler?
build/bin/suriax-hir dumps/programa.srcx.phir --resolve    # funciones, slots, llamadas
build/bin/suriax-hir dumps/programa.srcx.phir --mir        # el MIR + la verificación
build/bin/suriax-hir dumps/programa.srcx.phir --run        # lo ejecuta en la VM
build/bin/suriax-hir dumps/programa.srcx.phir --run --trace   # + cada llamada y retorno
build/bin/suriax-hir dumps/programa.srcx.phir --run --memoria # + objetos, cadenas y bytes (pico y vivos)
build/bin/suriax-hir dumps/programa.srcx.phir --run --pasos 0 --memoria-max 512M  # sin límite de pasos, 512 MB de memoria del programa
build/bin/suriax-hir dumps/programa.srcx.phir --run --extern libmio.so   # C++ ya construido
build/bin/suriax-hir dumps/programa.srcx.phir --emit-cpp extern.cpp
```

La VM da la **misma** salida, el mismo código de salida y los mismos códigos
de error que el intérprete. Eso lo comprueba
[`test/backend/test_vm_diferencial_*.py`](../test/backend/)
programa por programa:
- la serie de excepciones;
- los programas de fuego;
- el proyecto de varios archivos;
- el lexer y el parser del bootstrap.

Cuánto más rápida es, y por qué existe, está medido en
[`documentation/source/vm_decision.rst`](../documentation/source/vm_decision.rst).
Esa medición se repite con `python dev/bench_vm.py`.

Las dos vistas son **byte-idénticas** a las de Python:

```
--pretty   ==  python V0/main.py <fuente> --emit-hir --hir-pretty
--summary  ==  python runtime/interpreter/main.py <archivo>.phir
```

Esa identidad es una decisión, no una casualidad: es lo que convierte
[`test/backend/test_backend_cpp_*.py`](../test/backend/) en un
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

`--run` lo **construye y lo liga**, con el mismo contrato que el intérprete
([`runtime/extern_cpp.py`](../runtime/extern_cpp.py)): la misma tabla de
tipos, el mismo compilador (`$CXX`, `g++` o `clang++`) y la misma regla de
caché. La biblioteca queda junto al `.phir` (`extern/extern_cpp_vm.*`); con
`--extern <biblioteca>` se carga una ya construida.

Dos cosas cambian respecto del intérprete, las dos a favor:

- **No hace falta libffi ni ctypes.** Un valor de la VM ya es de máquina (un
  entero de 64 bits o un double), así que una llamada tipada basta. Las
  firmas posibles son pocas —cada parámetro es entero o double, hasta 6—: se
  generan al compilar con una plantilla (127 por tipo de retorno).
- **La memoria no se copia.** Una celda de la VM mide 8 bytes, así que un
  bloque de `int` **es** un `int64_t[]`: C++ recibe el puntero a las celdas
  y escribe en ellas. El intérprete copia de ida y vuelta porque sus celdas
  son objetos de Python.

Con un toolchain de ABI de MSVC (el `clang++` de Windows) una DLL no exporta
nada que no se marque; se compila primero el objeto, se lee su tabla de
símbolos COFF y se exportan los prototipos que de verdad define.

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

- El **JIT** y cualquier artefacto nativo: la VM interpreta el MIR.
- Bajar `&` sobre un CAMPO escalar (`&p.x`; hoy se rechaza con su
  posición). Sobre un local, un parámetro o una global ya baja.
- Seguir los préstamos **entre** bloques en la verificación.
- **Registrar la decisión "sin SSA"**: el MIR no tiene nodos φ (un valor que
  llega por dos caminos va a un local temporal), pero el porqué y las
  alternativas no están escritos. No es un default, es un trade-off.

**LLVM queda fuera del plan**: el MIR ya es un IR de registros con CFG, y
meterlo en medio añadía una dependencia enorme y un segundo modelo de máquina
antes de tener el primero funcionando.
