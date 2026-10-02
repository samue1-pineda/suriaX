# MIR (Mid-level Intermediate Representation)

El MIR vive en el **backend C++** ([`backend/`](../backend/README.md)). Baja el
HIR a una representación con control de flujo explícito sobre la que se
verifica el modelo de memoria y que ejecuta la VM. Ver
[ARCHITECTURE.md](../ARCHITECTURE.md).

> Estado: **implementado** (lowering, verificación de propiedad y VM). Falta
> el JIT. Lo que no funciona todavía está en
> [c_errorstfix.md](../c_errorstfix.md), punto 1.
>
> **LLVM queda fuera del plan** (decidido en la v0.2.0): el MIR ya es un IR
> de registros con CFG, así que LLVM en medio añadía una dependencia enorme y
> un segundo modelo de máquina que verificar.

## Cómo verlo

```bash
python V0/main.py prog.srcx --emit-hir              # -> dumps/prog.srcx.phir
build/bin/suriax-hir dumps/prog.srcx.phir --resolve # funciones, slots y llamadas
build/bin/suriax-hir dumps/prog.srcx.phir --mir     # el MIR + la verificación
build/bin/suriax-hir dumps/prog.srcx.phir --run     # lo ejecuta en la VM
```

`--mir` imprime una línea por instrucción, agrupadas por bloque, con su
terminador. Es la vista educativa de esta etapa: el mismo programa que en
`--hir-pretty` era un árbol aquí es un **grafo**.

## Qué es

Definido en [`mir.hpp`](../backend/include/suriax/mir/mir.hpp), bajado por
[`mir.cpp`](../backend/src/mir.cpp).

| Pieza | Decisión |
|---|---|
| **Registros** | Virtuales e ilimitados: cada valor intermedio estrena el suyo. Asignarlos a registros de máquina es trabajo del JIT. Registros y no pila porque un IR de registros hace explícito el flujo de datos —de dónde lee y dónde escribe cada instrucción—, que es lo que necesitan el JIT y la verificación de préstamos. |
| **Locales** | NO son registros: viven en el marco y se leen/escriben con `LoadLocal`/`StoreLocal`. Así un local puede tener dirección (un `ptr` apunta a él) sin que cada valor intermedio la tenga. |
| **CFG** | Funciones hechas de bloques; cada bloque termina en exactamente un terminador (`Jump`, `Branch`, `Return`, `Throw`). El `if`/`while` anidado del HIR pasa a ser un grafo que se puede recorrer, analizar y dibujar. |
| **Sin SSA** | No hay nodos φ: un valor que llega por dos caminos (p. ej. el resultado de un `and` con cortocircuito) se guarda en un local temporal. *El porqué de esta decisión no está registrado todavía* (ver "Pendiente"). |
| **Tipos** | Solo tres: `I64`, `F64` y `Void`. El ancho de máquina es lo único que la ejecución necesita; `bool`, `char`, un `enum` sin payload, un handle y el índice de una cadena son `I64`. Las distinciones del lenguaje ya las verificó el frontend. |
| **Agregados** | Un struct es un objeto en el montón de la VM y su valor es un **handle**; sus campos se alcanzan por índice (`GetField`/`SetField`), que el frontend ya resolvió. Un struct es un VALOR: guardarlo en otro dueño —ligar, asignar, pasar por valor, meterlo en un campo, devolver un campo— lo COPIA (`Copy`, profunda en sus objetos propios). Solo se copia lo que sale de un *lugar* (una variable, un campo, una celda); un valor recién hecho se entrega tal cual. |
| **Cadenas** | Una `str` es el índice de su entrada en una tabla que crece al concatenar o interpolar. Comparar es comparar texto (`EqStr`), no índices. |
| **Excepciones** | Un `throw` es una **arista**: cada bloque dice a dónde va el control si algo lanza dentro (`handler`). El filtro del `catch` se decide comparando una etiqueta entera del tipo. Un `finally` se baja **copiado en cada salida** (normal, `return`, `break`/`continue`, excepción), cada copia con slots propios; la de la excepción relanza al terminar y, si lanza ella misma, aborta (`Fallar`, RT022). |
| **Propiedad** | `move`/`free` dejan su huella (`MarkMoved`) y `&x` la suya (`Borrow`), aunque no calculen nada: son lo que la verificación sigue. Lo que inserta el lowering (drops, banderas) va marcado como `synthetic`. |
| **Memoria cruda** | Reservar y liberar bloques NO son instrucciones: son prototipos del host (`__reserve__`, `__copy__`, `__release__`, `__take__`, `__move__` de `lib/mem`), como `__write__`. Indexar un bloque sí lo es (`GetIndex`/`SetIndex`). Un bloque de `byte` es COMPACTO (un byte por celda, no 8): `__reserve__` lo pide con `imm = 1`, y es el `uint8_t*` que ve un `#extern cpp`. |
| **Texto** | `ToStr` escribe un valor según su modo (los 3 bits bajos: 0 int/byte, 1 float, 2 bool, 3 char, 4 cadena, 5 enum suma, 6 enum sin payload, 7 struct con sus campos). `Formatear` es lo mismo con el formato de un f-string (`{x!r:08b}`), ya partido en `Program::formatos`: el mismo algoritmo que el intérprete, no el `printf` de C. |
| **Genéricos** | Se **monomorfizan**: cada función genérica se baja una vez por juego de tipos concretos (`Vector<C>.push` y `Vector<int>.push` son dos funciones), como en C++ y Rust. `T` se deduce unificando la firma con los tipos que el HIR anota en los argumentos y el resultado (`FunctionDecl.type_params` y `StructDecl.type_params` dicen cuáles son parámetros). Es lo que deja saber al compilar si un `T` es un objeto que hay que copiar y liberar. |
| **Lo que no baja** | Se anota con su posición (`Program::unsupported`) y la función queda sin cuerpo en vez de a medias: un cuerpo incompleto ejecutaría otro programa. Hoy no queda nada que el intérprete ejecute y el MIR no baje. `&b[i]` de un elemento que es un objeto es su handle (el préstamo de `Vector.at`); el de un escalar necesitaría un puntero interior y es `RT011` en los dos motores. |

## Memoria: cada objeto muere con su dueño

La VM no tiene recolector de objetos: el MIR le dice cuándo muere cada uno.

- **Formas.** `Program::layouts` dice, para cada tipo concreto, qué campos de
  sus objetos son **propios**: un struct por valor, un enum con payload, o un
  bloque de `mem` guardado en un campo (el almacenamiento de un `Vector` es
  del `Vector`, como el buffer de un `std::vector`). `Copy` y `Free` son
  profundos según la forma.
- **Dueños.**
  - **Un slot propio** (local, parámetro, binding de `catch`) tiene una
    bandera de vivo. Al cerrar su ámbito —o salir por `return`, `break` o una
    excepción— se libera si sigue vivo. `move`, `return x` y `throw x` apagan
    la bandera.
  - **Un objeto recién hecho** que nadie toma (`f().x`, `crear();`) muere al
    terminar su expresión completa: la sentencia, la condición de un
    `if`/`while` o el lado derecho de un `and`/`or`.
  - **Asignar a un lugar** libera lo que había; si el frontend lo pide
    (`Assignment.drops_old`: el destino posee), lo DESTRUYE por su tipo.
  - **`catch (e)` sin tipo** se destruye según la etiqueta con la que llegó
    (`Destruir` con la etiqueta): un `throw 7` no es un objeto.
- **Destruir por tipo (`Destruir`).** Lo que el frontend no puede aplanar en
  su lista de drops —un `T`, un `catch (e)` sin tipo, el valor viejo de una
  asignación, las celdas de un bloque— lo destruye la VM por la FORMA del
  objeto: cada forma lleva el índice de su `__free__` (la instancia para su
  tipo concreto, calculada después de bajar todo); si lo tiene, corre ese y
  se hace cargo de sus campos; si no, sus campos propios y sus bloques, del
  último al primero; un bloque, sus celdas no vacías. Con una pila, como
  `Free`. Soltar un bloque (`__release__`) también destruye lo que tiene;
  `__take__` y `__move__` dejan celdas vacías (0) para sacar sin destruir.
- **Handles con generación.** Un objeto liberado deja su hueco a otro, pero
  con otra generación. Un handle viejo da `RT003` (uso después de liberar), no
  el objeto de otro.
- **Celdas.** Un escalar que tiene que vivir en el montón es un objeto de
  UN campo:
  - el de un local, un parámetro o una global al que se le toma la dirección
    (`&n`): el slot guarda el handle de la celda, leer `n` es leerla, `&n`
    es el handle y `p[0]` la lee por el puntero. La celda muere con su
    ámbito;
  - el valor de un `int?`, `float?`, `bool?` o `char?`: `-1` sigue siendo
    null y cualquier otro valor es una celda propia. Un escalar que entra
    donde se espera un `T?` se **encaja** (ligar, asignar, pasar, devolver,
    un campo, un payload) y `==` compara lo que guardan (`EqCaja`).
- **Globales.** Una global dueña de un objeto se libera cuando `main`
  vuelve, sin su `__free__` (el intérprete tampoco lo corre al salir).
- **Campos en celda.** `&p.x` sobre un campo escalar: antes de bajar nada se
  marcan, para todo el programa, los campos a los que se les toma la
  dirección; ese campo guarda una celda en todas las instancias de su struct
  (es un propio de su forma: se copia y se libera con el struct).
- **Temporales y excepciones.** Un temporal vive en un registro y el
  desenrollado solo libera slots. Si algo que puede lanzar (una llamada, una
  división, un índice, un desplazamiento) se emite mientras un temporal
  espera dueño, el temporal pasa a un slot con bandera, y ese guardado se
  escribe DONDE NACIÓ (domina todos sus usos, también las ramas de un `match`
  o de un `and`). Lo libera el `catch` de un `try` abierto cuando nació, o la
  limpieza de la función. Sin nada que lance en medio no cuesta nada. Los
  argumentos por valor se consumen todos juntos, justo antes de la llamada,
  y un `move x` pasado como argumento es un temporal más hasta entonces. Un
  temporal que el camino de una excepción suelta se destruye por su tipo
  (`Destruir`): nunca llegó a su dueño. Los campos de un literal se calculan
  antes de reservar el objeto: si uno lanza mueren los ya calculados, no un
  objeto a medias (C++ tampoco le corre el destructor).
- **Cadenas.** Se comparten, así que no tienen un dueño: se **barren**. El
  barrido es conservador (todo valor de los marcos, las globales y los objetos
  vivos que pueda ser un índice la mantiene viva), corre en un punto seguro
  (el inicio de un bloque) y está amortizado.
- **Verificarlo.** `suriax-hir prog.phir --run --memoria` dice cuántos
  objetos y cadenas quedaron vivos al terminar y de qué tipo. El diferencial
  exige cero en todo programa que termina normalmente, y la CI lo corre bajo
  ASan y UBSan.

## Verificación de propiedad

[`verify.hpp`](../backend/include/suriax/mir/verify.hpp): análisis de flujo hacia
adelante con un retículo por slot — `NoInicializado → Vivo → Movido`, y
`QuizaMovido` como la unión de los dos. Unir dos caminos toma el peor: si por
uno llega vivo y por otro movido, leerlo es un error, porque el programa no
sabe por cuál vino.

Es la pieza que faltaba entre el frontend (que rechaza lo que se ve en una
sentencia) y el intérprete (que caza en ejecución lo que se le escapa, `RT001`):
un error de propiedad no debería depender de que la rama que lo contiene
llegue a ejecutarse.

**Límite actual:** los préstamos se siguen dentro de un bloque. Prestar en una
rama y transferir en otra no se cruza todavía.

## La VM

[`vm.hpp`](../backend/include/suriax/mir/vm.hpp): un intérprete de **registros**
del MIR. Cada marco lleva sus slots y sus registros en dos vectores planos.
Tiene la MISMA semántica que el intérprete de Python —enteros de 64 bits que
envuelven, división entera que trunca hacia cero, dividir por cero entre
enteros es un error— y un diferencial en
[`test_backend_cpp_*.py`](../test/backend/) lo comprueba programa a
programa. Los errores viajan por código de estado, no por excepciones.

La VM es el requisito del JIT, no su sustituto: un JIT compila lo que la VM ya
sabe ejecutar, y necesita algo con qué comparar sus resultados.

## Pendiente

- [ ] **JIT** y artefactos nativos.
- [ ] Bajar `&` sobre un escalar (exige promover el local a una caja).
- [ ] Préstamos entre bloques en la verificación.
- [x] Enlazar el C++ de `#extern cpp` a la VM (`externo.cpp`; sus límites, en
      [c_errorstfix.md](../c_errorstfix.md)).
- [ ] **Registrar la decisión "sin SSA"** con su análisis (E-4 de las reglas
      del proyecto): hoy está en el código pero no su porqué ni las
      alternativas.
- [ ] Mostrar el CFG del MIR en el playground (Fase 7 del ROADMAP).
