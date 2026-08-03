   # logic_mem — backend de memoria real de suriaX (C++ / pybind11)

Administrador de memoria lógica en C++, **desacoplado y agnóstico del target**:
lo llama el intérprete hoy (vía pybind11) y lo llamarán la VM de bytecode/JIT y
el backend LLVM IR/WASM por igual — **sin** "depende de X y no se encontró".
Aquí vive la LÓGICA de memoria; los consumidores solo la invocan.

```
             Frontend (Lexer/Parser)
                       │
                 HIR (protobuf)
                /              \
        Python Interpreter    C++ MIRBuilder
                │                    │
                │              MIR → { Bytecode VM | LLVM IR/WASM }
                │                    │
                └─────── pybind11 ───┴──────►  logic_mem (C++)   ◄── mismo core
```

## Arquitectura (dos capas)

1. **Core puro** — [`include/mem_core.hpp`](include/mem_core.hpp): C++ **sin
   pybind11 ni Python**. Es lo que la VM/LLVM enlazan directo. Define:
   - `Value`: valor etiquetado (`null`/`int`/`float`/`bool` + un id `EXTERN`
     opaco para lo que no es primitivo — el core nunca toca objetos del host).
   - `Cell` + máquina de estados `LIVE / MOVED / FREED`.
   - `Manager`: `create` · `read` · `write` (revive un MOVED) · `move_out` ·
     `free_cell` · `peek` (crudo) · `state` · `reset`. Devuelve **códigos de
     estado** (no excepciones) para no acoplar el ABI: `OK`, `USE_AFTER_MOVE`,
     `USE_AFTER_FREE`, `DOUBLE_MOVE`, `DOUBLE_FREE`.
   - Handles **monotónicos** dentro de un run (imposible un *stale handle*);
     `reset()` recicla entre runs. La reclamación fina por celda llegará con
     las **regiones** (su propósito es liberar en bloque).

2. **Binding pybind11** — [`cxx_entry.cpp`](cxx_entry.cpp): el ADAPTADOR de
   Python. Expone la clase `Memory`, convierte objetos de Python ↔ `Value` y
   guarda lo no primitivo (str, struct, puntero...) en un *extern store* propio
   del binding. Así el core sigue siendo agnóstico. Módulo resultante:
   `memory_c`.

El intérprete lo consume por [`runtime/interpreter/memory/native.py`](../interpreter/memory/native.py):
`NativeCell` tiene la MISMA interfaz que la `Cell` de Python pura, así el
evaluator no cambia. Los códigos de estado se traducen a los errores de runtime
`RT001`/`RT002`/`RT003` con su línea/columna.

## Selección de backend

Por defecto se usa el **nativo** si `memory_c` carga; si no (p. ej. el `.so` no
está compilado para el intérprete actual), se cae a Python puro. Override:

- `SURIAX_NATIVE_MEM=0` — fuerza Python puro.
- `SURIAX_NATIVE_MEM=1` — exige el nativo (error si no cargó).

`test/e2e/test_native_memory.py` valida la clase `Memory` (máquina de estados) y
un *differential test*: el backend C++ y el de Python dan idéntica salida.

## Compilar

Requiere `pybind11` y CMake ≥ 3.20, con el MISMO Python del intérprete.

```bash
cd runtime/logic_mem/build
cmake ..          # solo la primera vez
cmake --build .   # -> memory_c.cpython-<ver>-<plat>.so
```

`runtime/cxx_api.py` descubre y carga el `.so` bajo `runtime/*/build`.

## Alcance actual

Punteros, `&` y **move-semantics** funcionan de punta a punta por este backend
(361 tests verde con el nativo por defecto). Las **regiones (RBMM)** se
construyen ENCIMA de estas primitivas — es el siguiente paso, deliberadamente
después de validar que los punteros son reales y manejables.

> Mapa de visibilidad (mismo modelo que el lenguaje): archivo = `private`,
> módulo = `internal`, API pública = `public`.
