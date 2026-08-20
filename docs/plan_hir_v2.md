# Plan: aligerar el HIR (tiempo, tamaño y legibilidad)

**Estado**: etapas 1 y 3a hechas y medidas; 3b, 3c y 4 pendientes. Todas las cifras de
la sección 1 son mediciones reales de este repo; las de las etapas no hechas
son estimaciones, y **cada etapa se valida contra la medición, no contra la
estimación** — la etapa 1 acabó dando la vuelta a su propia estimación, que
es exactamente para lo que sirve la regla.

Banco de medida reproducible: `python dev/bench_hir.py`.

## 0. El problema, en una frase

El `.phir` carga más de lo que necesita para ejecutar una unidad, y el emisor
paga por escribir esa carga: **emitir cuesta 22 veces más que leer**, y la
vista de texto cuesta 8 veces más que emitir.

## 1. Línea base (medida)

Programas reales del repo y sintéticos (structs + funciones con bucles,
condicionales, llamadas encadenadas, literales de struct y acceso a campos).

| programa | tokens | items | emitir | serializar | leer (`load_image`) | texto | `.phir` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `a.srcx` | 19 | 3 | 0,10 ms | 0,01 ms | — | 2,2 ms | 330 B |
| `prog.srcx` (fixture web) | 151 | 7 | 0,28 ms | 0,02 ms | — | 1,7 ms | 1,6 KB |
| sintético 10/50 | 6 496 | 62 | 11,6 ms | 0,6 ms | — | 87 ms | 60 KB |
| sintético 40/400 | 47 256 | 442 | **87 ms** | 4,8 ms | **3,9 ms** | **724 ms** | 429 KB |
| sintético 100/1500 | 174 776 | 1 602 | 321 ms | 16,5 ms | — | 2 610 ms | 1,6 MB |

Escala lineal en todo (≈0,2 ms por item emitido). Dos hechos incómodos:

- **leer es barato** (3,9 ms para 429 KB: el lector es `upb`, C++). El coste
  está en **construir** el mensaje, no en consumirlo;
- **`module_to_text` es el proceso más caro de la fase**: 724 ms y 6,6 MB de
  texto para un programa de 47 k tokens; 2,6 s y 24 MB para el de 175 k. Es
  `text_format` de protobuf, que imprime el árbol crudo, no un HIR legible.

### 1.1 En qué se van los bytes (sintético 40/400, 429 KB)

| partida | ocurrencias | bytes | % | distintos | repetición |
|---|---:|---:|---:|---:|---:|
| cadenas (`name`, `op`, `kind`…) | 47 957 | ~147 KB | 33,5 % | **47** | **1 020x** |
| `ln`/`col` | 49 404 | ~123 KB | 28,0 % | — | — |
| mensajes `Type` (con su tag+len) | 21 067 | ~88 KB | 20,1 % | **45** | **468x** |
| `SymbolTable` | — | 19 KB | 4,4 % | — | — |

En el de 175 k tokens la repetición llega a **3 781x** en cadenas y **740x**
en tipos: el conjunto de cosas distintas crece muchísimo más despacio que el
de nodos. Es exactamente el perfil que justifica un *pool*.

### 1.2 En qué se va el tiempo de emisión (perfil, 40/400)

| función | llamadas | tottime |
|---|---:|---:|
| `_emit_expr` | 19 605 | 0,287 s |
| `_emit_type` | 21 067 | 0,125 s |
| **`enum.__hash__` + `hash` + `dict.get`** | ~67 000 | **0,223 s** |
| `_expr_binary` | 4 451 | 0,050 s |

El tercer renglón es el hallazgo barato: **una quinta parte del tiempo se va
en hashear miembros de `Enum` de Python** para resolver `self._type_kind[t.kind]`
y sus hermanos. No es un problema de esquema; es la tabla de despacho.

## 2. Objetivos y no-objetivos

**Objetivos**

1. **Tiempo**: bajar el coste de emisión, que hoy domina la fase.
2. **Lo que genera**: que el `.phir` contenga la unidad y no repita el mismo
   tipo 740 veces ni el mismo nombre 3 781 veces.
3. **Legibilidad**: un `--hir-pretty` que sea *el* HIR legible — no el volcado
   crudo del protobuf — y que no cueste 2,6 s.

**No-objetivos** (explícitos, para que no se cuelen)

- No cambiar la semántica del HIR ni qué información transporta: los mismos
  hechos, codificados mejor.
- No mover trabajo al lector: cada plegado tiene que ser O(1) de deshacer.
- No tocar el backend web más que para el bump de esquema que le corresponda.
- No perder posiciones: un diagnóstico de runtime necesita línea y columna.

## 3. Etapas

Cada una es un commit independiente, con su medición y su reja de validación.
Las etapas 1 y 2 **no cambian un solo byte** del `.phir`; la 3 sí.

### Etapa 1 — emisión más rápida, mismo artefacto ✅ HECHA

Sin tocar el esquema, con el `.phir` **idéntico byte a byte** (verificado en
19 unidades del repo y sintéticas, emisor anterior contra actual en el mismo
proceso).

**Lo que se midió, y que contradice al perfil.** Las tres optimizaciones que
el perfil señalaba resultaron ser **pérdidas** al cronometrarlas
(`gen_40_400.srcx`, min de 7 corridas, salida byte a byte idéntica en todas):

| variante | vs. original |
|---|---:|
| `_emit_type` vacío (cota superior de todo el método) | +21,0 % |
| memoizar `_emit_type` por valor + `CopyFrom` | **−14,4 %** |
| memoizar por identidad + `CopyFrom` | **−7,5 %** |
| memoizar bytes ya serializados | **−12,1 %** |
| tabla de enums indexada por `.value` (sin hashear) | **−4,8 %** |
| `_emit_expr` sin `getattr` | **+6,1 %** |

La razón: escribir dos campos en un message `upb` **es código C**, mientras
que el `dict.get`, el `CopyFrom` y el `.value` (un `DynamicClassAttribute`)
son llamadas desde Python. El `cProfile` inflaba justo lo que aquí abunda —
millones de llamadas diminutas—, y el 22 % que atribuía a `enum.__hash__` era
un artefacto suyo.

**Lo aplicado**: reordenar `_emit_expr` para leer `node.restype` directo en
vez de con `getattr` defensivo (toda `Expression` lo tiene; quien no está en
la tabla de despacho sale antes por `_error_unsupported`).

**Ganancia real: ~5–6 %**, no el 20–30 % estimado. La lección va al plan: el
camino para acercarse a esa cota del 21 % no es hacer `_emit_type` más rápido
sino **llamarlo menos** — que es la etapa 3.

**Extra no planeado, y más valioso que la optimización**: el `.phir` **no era
reproducible**. Los `map<string, Symbol>` de la `SymbolTable` se serializaban
en orden no especificado, así que compilar dos veces el mismo archivo daba
artefactos con los mismos datos y bytes distintos (tres corridas, tres
hashes; `PYTHONHASHSEED` no lo arreglaba porque el orden lo decide la tabla
de `upb`). Eso invalidaba los golden `.phir` del backend web, cualquier caché
por hash y —en particular— el diferencial que este plan necesita para
demostrar que un cambio no altera la salida. Ahora hay **un solo sitio que
serializa** (`emmit_IR.serialize`, con `deterministic=True`), y tres tests lo
sostienen (`test/unit/test_hir_reproducible.py`), incluido uno que compila en
tres procesos distintos y compara hashes.

### Etapa 2 — el emisor en etapas ❌ NO HECHA (y no hizo falta)

El plan la ponía como andamio obligatorio de la 3: partir `_Emitter` en
recolección / lowering / plegado antes de poder plegar nada.

Al llegar resultó **innecesaria para el pool de tipos**. La razón es que el
pool vive en el `Module` (campo 6) y los nodos guardan un índice, así que el
emisor no necesita una fase de plegado posterior: asigna el id en el momento
de escribir el nodo y el pool se llena solo, en una única pasada. Un refactor
de 600 líneas que no habilita nada es churn, así que no se hizo.

Queda pendiente de reevaluar si la 3b (pool de cadenas) lo pide, aunque el
mismo argumento parece aplicar.

### Etapa 3a — pool de tipos (`schema_version = 2`) ✅ HECHA

**Antes de escribir una línea** se comprobó la sospecha que dejó la etapa 1
(que un pool cambia escrituras en C por búsquedas en Python, y podía ser otra
pérdida). Coste por aparición, medido:

| búsqueda | ns/op |
|---|---:|
| `hash(Type)` — dataclass frozen, recursivo | 472 |
| `pool_por_valor[t]` | 402 |
| **`pool_por_id[id(t)]`** | **115** |
| escribir el índice (`uint32`) en el message | 123 |
| *escribir el `Type` inline hoy: simple / puntero* | *413 / 2 176* |

Con la clave por identidad el pool gana en todos los casos (242 ns frente a
413 en un tipo simple; 261 frente a 2 176 en un puntero). Y funciona porque
el frontend **reutiliza sus objetos `Type`**: 19 666 apariciones sobre 805
instancias (24x) que colapsan a 43 formas. De ahí el índice doble del emisor
—rápido por `id()`, dedupe por valor— con su porqué escrito en el código.

**Resultado medido** (`gen_40_400.srcx`, 47 k tokens):

| métrica | v1 | v2 | |
|---|---:|---:|---:|
| emitir | 84,67 ms | **70,90 ms** | **−16,3 %** |
| `.phir` | 439 083 B | **394 607 B** | **−10,1 %** |
| `Type` en el artefacto | 88 250 B (20,1 %) | 6 158 B (1,6 %) | −93 % |
| vista de texto | 658,7 ms | 499,4 ms | −24 % |
| re-parseo (lector) | 3,44 ms | 3,43 ms | igual |

El lector no paga nada: resolver un índice es un acceso a lista. La caída del
24 % en la vista de texto es un efecto secundario — hay 20 000 submensajes
menos que imprimir.

**Radio real**: el intérprete NO lee `restype` (solo aparece en un docstring),
así que el cambio le costó **un** sitio (`index_dunders`, que resuelve el tipo
del receptor). El backend web resuelve el pool al decodificar y devuelve las
MISMAS formas, así que DCE, lowering y emisores (2 900 líneas) no se tocaron.

### Etapa 3b — pool de cadenas (pendiente)

El mismo patrón sobre `Identifier.name`, los operadores, `Literal.kind`,
nombres de campo… 47 801 campos de **43 cadenas distintas** (1 112x), el
33 % del artefacto. Medido: 157 ns por aparición frente a 395 (las cadenas se
hashean rápido porque el hash de un `str` va cacheado en el propio objeto).
Ahorro estimado: ~12 % de bytes y ~13 % del tiempo de emisión. Radio mayor
que el pool de tipos: el intérprete SÍ lee nombres y operadores.

### Etapa 3c — posiciones compactas (pendiente)

`ln`+`col` en un solo varint: ~8 % de bytes y ~3 % de tiempo, contra **101
sitios** del intérprete que leen `.ln`/`.col`. Es la peor relación de las
tres, y por eso va la última.

Dos plegados más, de familias y no de bytes:

- **`op` y `Literal.kind` como enums** en vez de cadenas. El propio
  `hir.proto` dice que los consumidores «despachan por caso, nunca comparando
  strings de operadores», y sin embargo `BinaryOp.op` es un `string`.
- **una sola tabla de símbolos ligados a tipo**: hoy `symbols.hooks`,
  `symbols.casts` y los dunders (que el runtime **reconstruye escaneando
  `items`**, ver `hook/dispatch.index_dunders`) son tres índices del mismo
  hecho. Con `hook_name` ya en el esquema, la identidad está completa y caben
  en una tabla con su discriminante.

**Riesgo** (el que se corrió en 3a, y el que queda en 3b/3c): toca
intérprete, decodificador web, golden fixtures y el futuro lector C++.
**Reja**: diferencial de EJECUCIÓN (§4) — los bytes cambian a propósito, así
que lo que tiene que ser idéntico es lo que el programa hace — más regenerar
los golden del web y la suite entera.

### Etapa 4 — `--hir-pretty`

Una vista **propia**, no `text_format`. Objetivo: que quepa en una pantalla lo
que hoy ocupa 6,6 MB, y que resolver los pools la haga **más** legible, no
menos (un `type_id` se imprime como `Punto ptr mutable`, no como `#7`).

```
unit prog.srcx  (schema 2, 42 símbolos, 7 items)

types   #0 int  #1 bool  #2 Punto  #3 Punto ptr
strings 47 entradas

fn suma(int a, int b) -> int            @14:1
  return (a + b):int                    @15:5

fn main() -> int                        @28:1
  var Punto p = Punto{x: 1, y: 2}       @29:5
  var int total = suma(p.x, p.y):int    @30:5
  if (total > 2):bool                   @32:5
    call stdp.println("mayor")          @33:9
```

- **streaming a archivo**, sin construir un `str` de 24 MB;
- una línea por sentencia, expresiones en línea con su `restype`;
- posiciones a la derecha, alineadas, para poder cruzar con el fuente.

**Objetivo medible**: < 150 ms y < 2 MB donde hoy hay 2 610 ms y 24 MB.
`--hir-text` (el volcado crudo) se mantiene: sigue siendo la herramienta para
depurar el *wire format*, que es otra cosa.

## 4. Cómo se valida (reja de cada etapa)

En este orden, que es el del enunciado:

1. **`a.srcx` contra el intérprete**: mismo stdout, mismo exit code, antes y
   después. Es el caso mínimo y el primero que tiene que pasar.
2. **Diferencial sobre todos los programas de la suite**: para cada `.srcx` de
   `test/`, ejecutar con el HIR viejo y con el nuevo y comparar salida y
   código de salida. Un cambio de codificación que altere una sola salida
   queda descartado ahí mismo.
3. **Archivos grandes**: los sintéticos de §1, comprobando que la ganancia
   medida es la estimada y que **el lector no se ha hecho más lento** (el
   plegado no puede pagarse moviendo trabajo al intérprete).
4. **Suite completa** (`python test/main.py`), 480 tests hoy.
5. En la etapa 3, además: regenerar los golden `.phir` del backend web y que
   su suite pase con el esquema nuevo.

El banco de medida entra al repo (`dev/bench_hir.py`) para que las cifras se
puedan reproducir y para que una regresión de rendimiento sea detectable.

## 5. Decisiones abiertas

1. **Compatibilidad**: ¿el lector v2 rechaza los `.phir` v1 (fail-fast, hay
   que recompilar) o los lee durante una transición?
2. **Posiciones**: empaquetar `ln`+`col` en un campo (~8 % de ahorro, trivial
   de deshacer) o delta contra el padre (~17 %, más ahorro pero el lector
   tiene que llevar estado).
3. **Alcance del primer commit**: etapa 1 sola (ganancia inmediata, riesgo
   nulo) o 1+2 juntas.
