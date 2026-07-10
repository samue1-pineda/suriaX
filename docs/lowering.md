# Lowering

Documenta las **bajadas (lowering)** entre representaciones: de AST a HIR
(Python) y de HIR a MIR (C++). Ver [ARCHITECTURE.md](../ARCHITECTURE.md).

> Estado: **pendiente**.

## Etapas de lowering

| De → A         | lenguaje  | Responsabilidad |
|----------------|--------|-----------------|
| AST → HIR      | Python | Serializa a protobuf con tipos/símbolos resueltos. |
| HIR → MIR      | C++    | Control de flujo explícito; verificación de memoria. |
| MIR → LLVM IR  | C++    | Generación de código (ver [llvm_backend.md](llvm_backend.md)). |

## TODO

- [ ] Reglas de lowering AST → HIR.
- [ ] Reglas de lowering HIR → MIR.
- [ ] Tratamiento de `region`/`make in`/`at`/`move` en cada bajada.
- [ ] (Idea) añadir un pass de LLVM IR para el manejo de memoria.