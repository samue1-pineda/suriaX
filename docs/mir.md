# MIR (Mid-level Intermediate Representation)

El MIR vive en el **backend C++**, este Baja el HIR a una representación con control
de flujo explícito sobre la que se ejecutan las verificaciones del modelo de
memoria. Ver [ARCHITECTURE.md](../ARCHITECTURE.md).

> Estado: **pendiente**.
>
> **LLVM queda fuera del plan** (decidido en la v0.2.0): el MIR ya es un IR
> de registros con CFG, así que LLVM en medio añadía una dependencia enorme y
> un segundo modelo de memoria que verificar. Ver
> [ARCHITECTURE.md](../ARCHITECTURE.md).

## Propósito

- IR de más bajo nivel que el HIR, con control de flujo explícito (CFG).
- Punto donde se verifica el modelo **ownership + move-semantics**, principalmente:
  validez de los `move` y tiempos de vida de los préstamos (`ptr`).
- Entrada a la **VM de bytecode con JIT**, el target nativo.

## TODO

- [ ] Definir la estructura del MIR (bloques básicos, CFG).
- [ ] Lowering HIR → MIR.
- [ ] Verificación de propiedad y préstamos sobre el MIR.
- [ ] Interfaz MIR → generador de bytecode de la VM.
