# Backend LLVM — DESCARTADO

> **Este plan no se va a ejecutar.** Se conserva como registro de la decisión,
> no como trabajo pendiente.
>
> El target nativo es una **VM de bytecode con JIT** (ver
> [ARCHITECTURE.md](../ARCHITECTURE.md) y [mir.md](mir.md)). El MIR ya es un
> IR de registros con CFG, así que LLVM en medio añadía una dependencia
> enorme y un segundo modelo de memoria que verificar, a cambio de un
> generador de código que la VM también da.
>
> `--check` sigue detectando `llvm-config` y reportándolo, pero nada del
> pipeline lo usa.
>
> WebAssembly sí llegó, y por otro camino: el target web baja del `.phir` a
> WIR y de ahí a JS/WASM, sin pasar por LLVM.

Lo que sigue es el plan tal como estaba escrito antes de descartarlo.

El backend, en **C++**, generaría **LLVM IR** (LLVM-22) a partir del MIR y
produciría el artefacto del target.

## Targets

El target se elige según los flags de `compilerconfig`:

| Flag       | Target | Artefacto | Paso final |
|------------|--------|-----------|------------|
| `IS_WEB`   | wasm   | `.wasm`   | (playground) |
| `IS_WIN32` | native | `.exe`    | linker      |
| `IS_LINUX` | native | `.o`      | **linker** → ejecutable |

En Linux/Windows, tras emitir el objeto, un paso de **linker** (etapa final
dentro del backend) produce el ejecutable, `compilerconfig` aporta rutas/flags.

## Interoperabilidad C++

El cuerpo de `#extern cpp{ ... }` (token `RAW_BLOCK`) se compila e integra aquí
vía los *bindings* (pybind11).

## TODO

- [ ] Generación MIR → LLVM IR.
- [ ] Emisión por target (wASM / .exe / .o).
- [ ] Integración del linker por plataforma.
- [ ] Integración del C++ de `#extern cpp{}`.
