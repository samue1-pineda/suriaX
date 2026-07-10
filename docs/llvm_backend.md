# Backend LLVM

El backend, en **C++**, genera **LLVM IR** (LLVM-22) a partir del MIR y produce
el artefacto del target. Ver [ARCHITECTURE.md](../ARCHITECTURE.md).


en la primera version funcional **.wasm** sera el primer target en funcionar junto a **.exe** 

> Estado: **pendiente**.

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
