# MIR (Mid-level Intermediate Representation)

El MIR vive en el **backend C++**, este Baja el HIR a una representación con control
de flujo explícito sobre la que se ejecutan las verificaciones del modelo de
memoria. Ver [ARCHITECTURE.md](../ARCHITECTURE.md).

> Estado: **pendiente**.

## Propósito

- IR de más bajo nivel que el HIR, con control de flujo explícito (CFG).
- Punto donde se verifica el modelo **region-based + move-semantics**, principalmente:
  lifetimes de las regiones, validez de los `move`, escapes de región.
- Entrada al backend que genera LLVM IR.

## TODO

- [ ] Definir la estructura del MIR (bloques básicos, CFG).
- [ ] Lowering HIR → MIR.
- [ ] Verificación de regiones y move sobre el MIR.
- [ ] Interfaz MIR → backend LLVM.
