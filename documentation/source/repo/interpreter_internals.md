# Arquitectura del intérprete tree-walk de suriaX (sobre el HIR)

> Documento de diseño. **No contiene código**: define qué ejecuta el
> intérprete, con qué contrato, la responsabilidad de cada módulo, el modelo
> de valores/memoria en runtime y el **orden de implementación** por fases
> testeables. Mismo rigor y objetivo que
> [`semantic/ARQUITECTURA.md`](https://github.com/samue1-pineda/suriaX/blob/main/V0/src/frontend/semantic/ARQUITECTURA.md)
> y [`parser/ARQUITECTURA.md`](https://github.com/samue1-pineda/suriaX/blob/main/V0/src/frontend/parser/ARQUITECTURA.md):
> **modularidad y sostenibilidad**, con el **rendimiento** como restricción
> explícita (aquí, secundaria — ver secc. 11).

---

## 0. Para qué existe (y para qué NO)

Hoy nada de suriaX se **ejecuta**: el frontend llega hasta la Semántica y se
detiene. Este intérprete cierra ese ciclo ejecutando el **HIR** — la IR
serializada en protobuf que ya es el contrato del compilador. Es la ruta del
target `interp` (`.suriaX_config.yaml`), alternativa al backend C++/LLVM.

**Objetivos**

- Ejecutar el HIR de un `.srcx` y sus `.libsrx` importadas de punta a punta.
- Que `IO.print.print("hola")` **escriba en la terminal** — sin `#extern
  cpp{}` (secc. 3).
- **Hacer cumplir en runtime** el modelo de memoria (lifetime de regiones,
  use-after-move): es justo la visualización educativa que busca el lenguaje
  y el terreno donde el diseño falla de formas que el análisis estático no ve.
- Ser un **oráculo de referencia**: correr el mismo HIR aquí y en el backend
  nativo y comparar la salida (*differential testing*).

**No-objetivos** (secc. 12): rendimiento, ser el runtime de producción,
implementar `#extern cpp{}`, reimplementar reglas semánticas.

---

## 1. Por qué sobre el HIR (no sobre el AST)

El intérprete consume **HIR, no AST**. Es la regla no negociable de
[`docs/propuesta_vm_bytecode.md`](https://github.com/samue1-pineda/suriaX/blob/main/docs/propuesta_vm_bytecode.md), y las
razones son estructurales:

1. **El HIR es la costura de desacople.** El MISMO HIR lo ejecuta este
   intérprete (Python) y lo baja el backend nativo (C++ → MIR → LLVM). Todo lo
   que el intérprete valide empíricamente sobre el HIR — modelo de memoria,
   despacho de hooks, semántica de regiones — vale para **ambos** consumidores.
   Ejecutar sobre el AST no daría esa garantía.
2. **Construye el puente que se necesita igual.** Hacer el intérprete sobre el
   HIR *obliga* a terminar el generador AST→HIR (Fase 5), que es trabajo
   necesario para la arquitectura original de todos modos. Sobre el AST, ese
   puente seguiría sin construirse y el trabajo se tiraría al llegar el backend.
3. **Un solo lugar decide las reglas.** El HIR trae ya resueltas las decisiones
   de la Semántica (tipos, despacho de hooks vía `HookRef`, regiones). El
   intérprete las **ejecuta**, no las redefine — cero riesgo de divergencia
   semántica entre la ruta interpretada y la nativa (propuesta, costos #2).

> **Prerrequisito duro**: este intérprete NO puede empezar antes que el
> generador AST→HIR (Fase 5). El orden de implementación (secc. 11) lo asume y
> lista además las extensiones que el esquema HIR necesita para ejecutarse.

Relación con [`V0/src/intepreter/`](https://github.com/samue1-pineda/suriaX/blob/main/V0/src/intepreter) (readme: "tree-walk
sobre el HIR"): esa nota reflejaba esta misma intención. La implementación vive
aquí, en `runtime/interpreter/`.

---

## 2. Entrada y salida

```
   archivo .srcx / .libsrx
        │
        ▼   frontend [YA EXISTE]
  source_reader → Lexer → Parser → AST → AST-tipado → Semántica
        │                                     │
        │                                     ▼   Fase 5 [POR HACER]
        │                            generador AST validado → HIR
        │                                     │
        ▼                                     ▼
   (una unidad HIR por .srcx / .libsrx)  →  Module (protobuf)
        │
        ▼   module linker (secc. 10.1)
   imagen HIR ligada (N unidades + tabla de símbolos combinada)
        │
        ▼   INTÉRPRETE  [este documento]
  deserializar → Environment global → ejecutar entry (main)
        │
        ▼
  efectos (stdout) + código de salida
```

El intérprete consume un **`Module`** protobuf (ver
[`V0/src/HIR/proto/hir.proto`](https://github.com/samue1-pineda/suriaX/blob/main/V0/src/HIR/proto/hir.proto)):

- `Module.items` — `repeated Decl`, el `Program` validado en orden.
- `Module.symbols` — la `SymbolTable` (tipos, valores, `hooks`).
- Anotaciones ya resueltas que el intérprete **ejecuta sin re-decidir**:
  - `Call.hook` / `MakeExpr.hook` / `FreeStmt.hook` / `SizeofExpr.hook` son
    `HookRef` (owner + kind): el intérprete los re-enlaza contra
    `Module.symbols.hooks` en O(1) — el mismo mecanismo que usará el lector
    C++.
  - `Expr.restype` / `FunctionDecl.return_type` — tipos resueltos.
  - `FunctionDecl.dunder` — nombre del hook si la función lo es.

> **Precondición dura**: el HIR solo se genera si la Semántica no reportó
> errores. Un HIR de un programa con errores es indefinido; `main.py` aborta
> antes (secc. 10.2).

Deserializar el protobuf a objetos Python es la primera cosa que hace el
intérprete. A partir de ahí recorre el árbol de mensajes (`Decl`/`Stmt`/`Expr`)
igual que un tree-walk recorre un AST — el HIR es estructuralmente cercano al
AST, con todo resuelto y explícito.

---

## 3. La respuesta a `#extern`: la interfaz del host (intrínsecos)

**`#extern cpp{}` NO hace falta para el intérprete.** Es el puente del backend
LLVM: incrusta C++ que ese backend compila e integra vía pybind11. Un
tree-walk en Python no compila C++ ni lo necesita — el `ExternBlock` viaja en
el HIR (`raw`) y el intérprete simplemente **lo ignora**.

Lo que el compilador necesita para que `print` escriba en consola **sin esa
directiva** es un mecanismo de **intrínsecos** (funciones del host):

1. La librería declara la primitiva como **PROTOTIPO** (sin cuerpo):
   `fn __write__(str s) -> void;`. El HIR la transporta como una
   `FunctionDecl` sin cuerpo (secc. 11: el esquema necesita marcar esto).
2. El intérprete mantiene un **registro de intrínsecos**: nombre → función
   Python nativa. `__write__` → escribir a `stdout`.
3. Al ejecutar una llamada a una función **sin cuerpo**, el intérprete busca su
   nombre en el registro:
   - **está** → ejecuta la función Python (el efecto real, p. ej. escribir);
   - **no está** → error de runtime *"prototipo sin implementación en el
     host"*.

Así `lib/io/print.libsrx` no usa `#extern`: toda su impresión pasa por
`__write__`, y `print`/`println`/`__print__` son suriaX normal encima de esa
única primitiva. Ver el archivo y su comentario de cabecera.

**El HIR es lo que hace esto un desacople y no un parche.** La MISMA primitiva
`__write__` la resuelve cada consumidor del HIR a su manera:

- el **intérprete** la liga a un builtin Python (hoy);
- el **backend nativo** la ligará a un símbolo del runtime C++ o a un `#extern
  cpp{}` (futuro),

sin que la librería ni el HIR cambien. Es la *"host interface pequeña que ambos
backends implementan"* de la propuesta (costos #1). La superficie nativa se
mantiene **mínima**: un puñado de intrínsecos (`__write__`, y a futuro lectura,
reloj, salida con código), y todo lo demás es suriaX sobre ellos.

> Regla de diseño: **una `.libsrx` no debería incrustar `#extern cpp{}` para
> algo que pueda expresarse como prototipo + intrínseco.** `#extern` queda para
> C++ genuino y específico del backend nativo, no para las primitivas de la
> stdlib.

---

## 4. Árbol de módulos

Respeta el esqueleto ya presente (`enviroment/`, `hook/`, `memory/`) y añade lo
que falta. Un archivo por responsabilidad, mismo criterio que el parser y la
Semántica:

```
runtime/interpreter/
├── ARQUITECTURA.md          # este documento
├── __init__.py              # API pública: run(module, config) -> exit_code
│
├── loader.py                # deserializa el Module protobuf -> objetos Python
├── interpreter.py           # ORQUESTADOR: monta el Environment global, liga
│                            #   funciones (propias + librerías) e invoca entry
├── evaluator.py             # el tree-walk: eval_expr / exec_stmt por despacho
│                            #   O(1) sobre el 'case' del oneof HIR (mismo
│                            #   patrón que scope_resolver._stmt_dispatch)
├── values.py                # modelo de valores en runtime (secc. 5)
│
├── enviroment/              # [ya existe] scopes de ejecución (secc. 6)
│   └── environment.py       #   cadena de frames nombre -> Cell; push/pop
│
├── hook/                    # [ya existe] despacho de hooks en runtime (secc. 7)
│   └── dispatch.py          #   re-enlaza HookRef y ejecuta el hook
│
├── memory/                  # [ya existe] regiones, punteros, move (secc. 8)
│   ├── region.py            #   arena por región: enter/exit, make
│   └── pointer.py           #   Cell, &, deref, move (invalida origen)
│
├── intrinsics.py            # interfaz del host: registro nombre -> fn Python (secc. 3)
└── errors.py                # RuntimeError propios (con código y ubicación)
```

Flujo unidireccional: `loader` → `interpreter` → `evaluator` →
(`environment`, `hook`, `memory`, `intrinsics`). `values` y `errors` son hojas
que todos usan. Ningún módulo importa `config/` (igual que el frontend):
`main.py` pasa lo que haga falta.

---

## 5. Modelo de valores (`values.py`)

Representación en Python de cada valor de suriaX. Criterio: **lo más directo
que preserve la semántica**, sin boxing innecesario. El HIR trae el `TypeKind`
resuelto, así que construir el valor correcto es directo.

| Tipo (`TypeKind` del HIR) | Valor Python | Nota |
|---------------------------|--------------|------|
| `INT` | `int` | — |
| `FLOAT` | `float` | — |
| `BOOL` | `bool` | — |
| `CHAR` | `str` de longitud 1 | un code point |
| `STR` | `str` | — |
| `VOID` | singleton `UNIT` | retorno de funciones sin valor |
| `null` (literal) | singleton `NULL` | unifica con cualquier `NULLABLE` |
| `NULLABLE` | el valor de `inner`, o `NULL` | el `?` no cambia la representación |
| `STRUCT` (`NOMINAL`) | `StructValue`: nombre + dict campo→`Cell` | campos como celdas para permitir `&s.campo` |
| `ENUM` item | el nombre del item (o su valor asignado) | modelo C: items pelados |
| `POINTER` | `Pointer` → la `Cell` apuntada (secc. 8) | la forma no cambia la representación |

`UNIT`, `NULL` son singletons (comparaciones por identidad). Los valores son
Python planos siempre que se pueda: el intérprete es educativo, no un runtime
optimizado, pero no hay razón para envolver un `int`.

> El esquema HIR v0 aún no representa el metatipo `type` ni los tipos opacos
> (`const type int8;`); requieren extensión del esquema antes de poder
> ejecutarlos (secc. 9, 11).

---

## 6. Environment: scopes de ejecución (`enviroment/`)

Un `Environment` es una **cadena de frames** (`parent` como en `Scope` de la
Semántica), cada frame un dict `nombre -> Cell`. Una `Cell` es un contenedor
mutable de un valor (necesario para punteros y `move`, secc. 8).

- **Frame global**: funciones (propias + de librerías, secc. 10), variables
  globales, tipos. Se monta una vez desde la imagen HIR ligada.
- **Frame de función**: se crea por llamada; contiene los parámetros ligados a
  los valores de los argumentos. NO ve los locales del llamador (scope léxico,
  no dinámico) — solo el global y el suyo.
- **Frame de bloque**: cada `Block` (if/while/región/bloque suelto) anida su
  frame; se descarta al cerrarse.

> **Paralelo con la Semántica, no reutilización.** `Module.symbols` es estática
> (existencia y tipo de los nombres); el `Environment` es dinámica (su **valor**
> en esta ejecución). Misma forma de cadena, estructuras distintas. La
> Semántica ya garantizó que todo nombre resuelve, así que el intérprete **no
> re-valida**: si un `Identifier` del HIR no está en el environment, es un bug
> del intérprete, no del programa.

Resolución de nombres: O(profundidad de anidamiento), idéntico a
`Scope.resolve_value`. Para funciones y globales termina en el frame global.

---

## 7. Despacho de hooks en runtime (`hook/`)

El HIR ya trae **a qué hook despacha cada sitio** como un `HookRef` (owner +
kind); el intérprete lo re-enlaza contra `Module.symbols.hooks` en O(1) — el
mismo mecanismo del lector C++ — y ejecuta. Cero re-decisión.

| Construcción HIR | Anotación | Qué hace el intérprete |
|------------------|-----------|------------------------|
| `Call` con `hook`=PRINT | `__print__` de `T` | llama al `FunctionDecl` del hook con `&x` |
| `Call` con `hook`=LEN | `__len__` de `T` | íd., devuelve el `int` |
| `MakeExpr.hook`=MAKE | `__make__` de `T` | si hay hook, lo llama; si no, construye el struct por defecto en la región |
| `FreeStmt.hook`=FREE | `__free__` de `T` | llama al hook (si hay) y libera la celda |
| `SizeofExpr.hook`=SIZEOF | `__sizeof__` de `T` | si hay hook lo llama; si no, un tamaño por defecto del modelo |

Un hook es una `FunctionDecl` normal: ejecutarlo es una llamada corriente
(nuevo frame, ligar el `T ptr` de la instancia, correr el cuerpo). Si el
`Call.hook` está ausente (`HookRef` vacío), es una llamada normal — se resuelve
el `callee` como cualquier función. El fallback `print(str)` de la stdlib es
una función normal (no hook) que llama a `__write__`.

---

## 8. Modelo de memoria en runtime (`memory/`) — el núcleo educativo

Aquí es donde el intérprete gana su sueldo: **ejecuta** `region` +
move-semantics y falla en runtime cuando el programa las viola. La Semántica ya
rechazó lo que pudo estáticamente; esto es la red de la que caen los casos que
solo se ven ejecutando.

### 8.1 Regiones como arenas

Una `RegionStmt` es un **arena**: un contenedor de celdas con nombre. El
intérprete mantiene una **pila de arenas**.

- **entrar** a la región: push de un arena vacío con su nombre.
- `MakeExpr` (`make T in r`): construye el valor y lo ubica en el arena `r`;
  devuelve un `Pointer` a su celda. (`alloc` dejó de ser parte del lenguaje:
  la reserva cruda la aporta una librería.)
- `Placement` (`x at r`): ubica el resultado de `x` en el arena `r`.
- **salir** de la región: se libera el arena **entero** de una vez (semántica
  region-based). Todo `Pointer` a una celda de ese arena queda **colgante**;
  desreferenciarlo después es un error de runtime.

`RegionStmt.shared` (`shrd region`): su arena puede sobrevivir al bloque. El
intérprete no lo libera al salir (la verificación profunda es del MIR; aquí
basta con no liberarlo).

### 8.2 Punteros (`pointer.py`)

- `&x` (`UnaryOp` op `&`): produce un `Pointer` a la **celda** de `x` (por eso
  variables y campos son celdas, no valores pelados). `&` es un operador de
  expresión; nunca un modificador de tipo.
- `POINTER` con `mut=false` (solo lectura a través) vs `mut=true`
  (`ptr mutable`): la Semántica ya rechazó las escrituras a través de un `ptr`
  no-mutable (`SEM015`), así que el intérprete **no re-chequea** —
  desreferencia y lee/escribe la celda.
- desreferencia implícita en `MemberAccess` sobre un puntero (`s.text` con `s:
  String ptr`), como ya hace la stdlib.

### 8.3 Move (`MoveStmt`)

- ejecutar `move x`: transfiere el valor de la celda de `x` y **marca la celda
  como movida**.
- usar `x` después: la Semántica ya reporta el use-after-move y double-move que
  ve estáticamente (`SEM004`/`SEM005`); en runtime, una celda movida a la que
  se accede lanza un error — cierra los caminos que el análisis estático
  conservador no cubre (p. ej. a través de ramas).

> **Todo lo que este módulo hace cumplir ya es doctrina de la Semántica** (su
> `ARQUITECTURA.md`, secc. 4 y 13): el intérprete no inventa reglas, las
> **ejecuta**. Si aquí salta un error que la Semántica debió atrapar, es una
> brecha del análisis estático — y encontrarla es para lo que sirve esto.
> `interpreter.trace_memory` (config) vuelca las operaciones de arena/move para
> la visualización educativa.

---

## 9. El metatipo `type` y los tipos opacos

`type` es un tipo de primera clase (`const type int8;`, `fn f() -> type`); un
valor de tipo `type` es un `TypeValue` que envuelve un `Type`.

**Bloqueo actual**: el esquema HIR v0 no representa ni `TypeDecl`
(`const type int8;`) ni el metatipo (`MetaTypeExpr`) ni marca los prototipos.
El frontend ya los produce (ver `t_types.md`), pero no cruzan el HIR todavía.
Ejecutarlos requiere **extender el esquema** primero (secc. 11, prerequisito).
Un tipo opaco sin `__make__`/`__sizeof__` es un valor inerte: se pasa y
devuelve, pero construir una instancia requiere sus hooks.

---

## 10. Integración: unidades múltiples y CLI

### 10.1 Module linker: N unidades HIR → una imagen

Cada `.srcx` y cada `.libsrx` compila a **su propio `Module` HIR**. El
intérprete necesita todas las unidades del programa (main + librerías
importadas) ligadas en una sola imagen ejecutable.

**Module linker** (propuesta, paso 2; reutiliza la resolución de
[`src/linker_p/`](https://github.com/samue1-pineda/suriaX/blob/main/V0/src/linker_p)): toma los `Module` de main y de cada
`.libsrx` importada, y produce:

- un frame global que liga cada función bajo su nombre calificado
  (`IO.print.print` → su `FunctionDecl`), reutilizando el mapeo alias→miembros
  que el linker ya construye;
- una tabla de hooks combinada (los `HookEntry` de todas las unidades).

**Identidad de una unidad: el nombre CALIFICADO.** Una unidad se identifica
por `<paquete>.<submódulo>` (`IO.stdp`), no por el alias suelto del
`#export`: es la clave de `Image.units`, el nombre de su `.phir` y el
`LibraryRef.alias` del HIR. Sin calificar, dos paquetes que publiquen un
submódulo homónimo (`alpha.util` y `beta.util`) compartirían archivo y
entrada, y el segundo ganaría en silencio. Un paquete se materializa como
**varias** unidades hermanas —el padre (`IO`) y una por submódulo
(`IO.stdp`)—; el padre NO importa a sus hijos, así que `Namespace('IO')`
resuelve el miembro `stdp` buscando la unidad hermana `IO.stdp` (una consulta
en dict, secc. 7 de `evaluator._namespace_member`).

**El intérprete no re-resuelve imports.** `ImportDirective` trae del HIR los
tres nombres que la Semántica ya decidió — `lib` (lo escrito), `unit` (la
unidad a cargar) y `binding` (el nombre local) — porque ninguno se deriva de
otro sin rehacer el trabajo de `linker_p` (`#import io` sobre un `#export
package as IO` liga `io` y carga la unidad `IO`). Es D3 aplicado a los
imports: el backend C++ ligará exactamente lo mismo sin reimplementar el
linker de librerías.

Diferencia con el linker de hoy: `src/linker_p/` resuelve **símbolos** entre
`.libsrx`; el module linker liga **unidades HIR** (con cuerpos ejecutables).
Son la misma resolución de imports en dos niveles — la capa de símbolos se
conserva; se añade el acceso a los cuerpos vía HIR. El **linker nativo**
(`ld.lld`, objetos `.o`) no interviene aquí: no hay objetos que enlazar.

### 10.2 CLI y `compilerconfig`

- `target: interp` en `.suriaX_config.yaml` selecciona la ruta HIR →
  intérprete. Los knobs viven en la sección `interpreter:` (`entry`,
  `trace_memory`, `max_steps`).
- atajo: `python V0/main.py archivo.srcx --run` fuerza el target `interp` para
  esa corrida.
- `main.py` es el único puente: tras la Semántica (**si no hubo errores**)
  corre Fase 5 (AST→HIR), el module linker y `interpreter.run(module, config)`;
  enruta stdout y el código de salida. El intérprete no conoce `config/` ni la
  CLI. `compilerconfig` conserva su rol de seleccionar el target.

---

## 11. Prerrequisitos de HIR + orden de implementación

El intérprete consume HIR, así que **Fase 5 es su prerrequisito**. Además, el
esquema HIR v0 va un poco por detrás del frontend y necesita cerrar estas
brechas antes de poder ejecutar todo:

- **P0. Generador AST→HIR (Fase 5).** Sin él no hay nada que ejecutar.
- **P1. Marcar prototipos.** `FunctionDecl.body` en proto3 no distingue
  "sin cuerpo" de "cuerpo vacío"; añadir un `bool is_prototype` (o
  `optional Block body`) para que los intrínsecos se reconozcan (secc. 3).
- **P2. `TypeDecl` y metatipo.** Añadir el nodo de `const type int8;` al
  `oneof` de `Decl`/`Stmt` y un `TypeKind.META` (secc. 9).
- **P3. `#test hir`.** Volcado del HIR para depurar el generador y el
  intérprete contra la misma entrada.

Con eso, las fases del intérprete — cada una deja algo **ejecutable y
verificable**:

1. **Loader + núcleo de expresiones.** `loader.py` deserializa el `Module`;
   `evaluator.eval_expr` para `Literal`/`BinaryOp`/`UnaryOp`/`Identifier`
   contra un environment plano. *Test*: evaluar `2 + 3 * 4` desde un HIR mínimo.
2. **Sentencias y control de flujo.** `exec_stmt` para `VarDecl`/`Assignment`/
   `IfStmt`/`WhileStmt`/`MatchStmt`/`ReturnStmt`/`Break`/`Continue`; frames de
   bloque. *Test*: un `main()` con un bucle que acumula y retorna un `int`.
3. **Llamadas + intrínsecos.** Frames de función; `Call` a funciones propias;
   `intrinsics.py` con `__write__`; ejecución de prototipos vía el registro.
   *Test*: un HIR cuyo `main` llama a `__write__("hola\n")` **imprime en la
   terminal**. Primer "hola mundo" real.
4. **Hooks.** `hook/dispatch.py` re-enlaza `HookRef` y ejecuta `__print__`/
   `__len__`. *Test*: un `struct String` con `__print__` que llama a
   `__write__`; `print(x)` escribe. Cierra el objetivo del usuario.
5. **Module linker.** Ligar N unidades HIR (main + `IO`); resolver
   `IO.print.*` en el frame global (secc. 10.1). *Test*: `#import IO;` +
   `IO.print.println("hola mundo")` **imprime**.
6. **Memoria.** `memory/` completo: arenas por región, `&`/deref,
   `make`/`free`, `move` con invalidación. *Test*: los ejemplos de
   [`docs/examples/regions.md`](https://github.com/samue1-pineda/suriaX/blob/main/docs/examples/regions.md) corren; un
   use-after-move a través de una rama lanza error de runtime.
7. **CLI + config.** `target: interp` / `--run` en `main.py` (secc. 10.2).
   *Test*: `python V0/main.py test.srcx --run`.
8. **Metatipo y opacos.** Tras P2: `TypeValue`, `type` como valor,
   `sizeof`/`make` con y sin hook.

Milestone de valor máximo por esfuerzo: **P0 + fases 1–4** dan "hola mundo"
real con hooks; **fase 5** lo da desde la librería `IO` de verdad.

---

## 12. No-objetivos (explícitos)

- **Rendimiento.** Es Python y es educativo; corrección y claridad antes que
  velocidad (propuesta: "no optimices la VM"). Tree-walk directo sobre el HIR
  deserializado — sin bytecode, sin JIT.
- **`#extern cpp{}`.** No se ejecuta; el intérprete ignora el `ExternBlock` del
  HIR (o lo rechaza con un error claro si un programa depende de él). Las
  primitivas van por intrínsecos (secc. 3).
- **Ser el runtime definitivo.** El backend C++ consume el mismo HIR; el
  intérprete queda como oráculo de *differential testing* y target de
  depuración/visualización (propuesta, "la vuelta a la arquitectura original").
- **Reimplementar reglas semánticas.** Todo lo que valida ya lo decidió la
  Semántica y viaja resuelto en el HIR; aquí solo se ejecuta (secc. 1, 7, 8).
- **Concurrencia, FFI real, GC sofisticado.** Fuera de alcance; regiones + move
  es determinista y no los necesita para el objetivo de prueba.

---

## 13. Resumen de decisiones

| # | Decisión | Porqué |
|---|----------|--------|
| D1 | Consume **HIR** (`Module` protobuf), no AST | El HIR es la costura de desacople: mismo contrato para el intérprete y el backend nativo. Construirlo sobre HIR termina el puente Fase 5 que se necesita igual (secc. 1). |
| D2 | `print` sin `#extern`, vía **intrínseco** `__write__` (prototipo + registro del host) | `#extern` es del backend LLVM; el intérprete provee la primitiva en Python. Es la "host interface" que ambos consumidores del HIR implementan (secc. 3). |
| D3 | **Ejecuta** las anotaciones del HIR (`HookRef`, regiones), no las re-decide | Cero divergencia semántica entre la ruta interpretada y la nativa (secc. 7). |
| D4 | Variables y campos son **celdas** (`Cell`), no valores pelados | Habilita `&`, deref y `move` con invalidación (secc. 8). |
| D5 | Regiones = **arenas** liberadas enteras al salir | Ejecuta la semántica region-based y expone punteros colgantes en runtime (secc. 8.1). |
| D6 | Vive en `runtime/interpreter/` (realiza la intención "sobre el HIR" de `V0/src/intepreter/`) | Una sola implementación; el esqueleto `enviroment`/`hook`/`memory` ya está aquí (secc. 1, 4). |
| D7 | **Module linker** liga N unidades HIR (main + `.libsrx`) | Cada unidad compila a su propio `Module`; ejecutar el programa entero necesita ligarlas (secc. 10.1). |
| D8 | Target seleccionable `interp` en `compilerconfig` (+ `--run`) | Sin romper `native`/`wasm`: los tres parten del mismo HIR; el campo `target` elige la ruta (secc. 10.2). |
