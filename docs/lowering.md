# Lowering

Documenta las **bajadas (lowering)** entre representaciones: de AST a HIR
(Python) y de HIR a MIR (C++). Ver [ARCHITECTURE.md](../ARCHITECTURE.md).

> Estado: **pendiente**.

## Etapas de lowering

| De → A         | lenguaje  | Responsabilidad |
|----------------|--------|-----------------|
| AST → HIR      | Python | Serializa a protobuf con tipos/símbolos resueltos. |
| HIR → MIR      | C++    | Control de flujo explícito; verificación de memoria. |
| MIR → bytecode | C++    | Generación de código para la VM con JIT. |
| HIR → WIR      | TypeScript | El target web, ya funcional (ver [ARCHITECTURE.md](../ARCHITECTURE.md)). |

## TODO

- [ ] Reglas de lowering AST → HIR.
- [ ] Reglas de lowering HIR → MIR.
- [ ] Tratamiento de `move`/`free` y del drop de ámbito en cada bajada.
- [ ] Generación de bytecode y diseño del conjunto de instrucciones.