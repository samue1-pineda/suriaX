# `runtime/interpreter` — intérprete tree-walk (sobre el HIR)

Ejecuta el **HIR** (la IR serializada en protobuf, contrato del frontend) para
ver salidas reales y probar librerías/lógica sin el backend C++/LLVM. Es la
ruta de ejecución del target `interp` (ver `.suriaX_config.yaml`).

**Consume HIR, no AST — a propósito.** El HIR es el contrato que **desacopla**
el frontend de sus consumidores: el mismo HIR lo ejecuta este intérprete
(Python) y lo baja el backend nativo (C++ → LLVM). Construir el intérprete
sobre el HIR obliga a terminar el generador AST→HIR (Fase 5), que es trabajo
que se necesita igual, y evita tirar código cuando llegue el backend. Es la
regla no negociable de
[`docs/propuesta_vm_bytecode.md`](../../docs/propuesta_vm_bytecode.md).

**Diseño completo, modelo de memoria en runtime y orden de implementación:**
[`ARQUITECTURA.md`](ARQUITECTURA.md).

## Estado actual: EJECUTA (Fase 5.5, núcleo funcional)

```
python V0/main.py programa.srcx --run          # compila + ejecuta (target interp)
python V0/main.py programa.srcx --run --time   # + tiempos por fase

python runtime/interpreter/main.py dumps/programa.srcx.phir            # resumen
python runtime/interpreter/main.py dumps/programa.srcx.phir --exec     # ejecutar
python runtime/interpreter/main.py dumps/x.phir --exec --trace-memory  # + traza
```

| Módulo | Estado |
|---|---|
| [`loader.py`](loader.py) | carga + validación fail-fast + **module linker** (liga main + N `.phir` de librerías, transitivo) |
| [`evaluator.py`](evaluator.py) | tree-walk: expresiones, control de flujo, llamadas, f-strings, `cast` (nativo + tabla `__cast__`) |
| [`memory/pointer.py`](memory/pointer.py) | **instrucciones de memoria**: celdas con estado (LIVE/MOVED/FREED), `&`, deref implícito, `move` (RT001/RT002), `free` (RT003) — RBMM llega con HIR v2 |
| [`enviroment/environment.py`](enviroment/environment.py) | cadena de frames nombre→Cell |
| [`hook/dispatch.py`](hook/dispatch.py) | índices O(1): hooks (owner,kind) y conversiones (origen,destino) |
| [`intrinsics.py`](intrinsics.py) | interfaz del host: `suriax_write` → stdout (IO imprime sin `#extern`) |
| [`interpreter.py`](interpreter.py) | orquestador: globales por unidad, nivel de módulo, entrada, exit code |
| [`errors.py`](errors.py) | errores de runtime `RTxxx` con posición |

Pendiente del plan: arenas por región (RBMM, HIR v2), structs ejecutables
(`__make__`), vectores, `match` con patrones más ricos.

Puntos clave:

- **No necesita `#extern cpp{}`.** Las primitivas del host (escribir a stdout)
  entran por **intrínsecos**: un prototipo en la librería (`fn __write__(str
  s) -> void;`) que viaja en el HIR y que el intérprete liga a una función
  Python. `#extern` es del backend LLVM. La interfaz del host es la **costura
  de desacople** que ambos consumidores del HIR implementan a su manera.
- **No re-decide semántica.** Ejecuta lo que el HIR ya trae resuelto (despacho
  de hooks, regiones, move); no reimplementa las reglas de la Semántica.
- Selección de target: `target: interp` en `.suriaX_config.yaml` (o
  `python V0/main.py archivo.srcx --run`). `compilerconfig` conserva su rol de
  elegir la ruta; los knobs del intérprete viven en la sección `interpreter:`.
- Esqueleto ya presente: `enviroment/` (scopes), `hook/` (despacho de dunder),
  `memory/` (regiones/punteros/move).

Relación con [`V0/src/intepreter/`](../../V0/src/intepreter/) (readme: "tree-walk
sobre el HIR"): esa nota reflejaba esta misma intención; la implementación vive
aquí, en `runtime/interpreter/`.
