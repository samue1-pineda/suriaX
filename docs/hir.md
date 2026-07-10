# HIR (High-level Intermediate Representation)

El HIR es la **frontera entre el frontend (Python) y el backend (C++)**. Se
serializa en **protobuf**, lo que permite desacoplamiento y mantener un
contexto semántico persistente. Ver [ARCHITECTURE.md](../ARCHITECTURE.md).

> Estado: **pendiente**, El frontend aún no llega a esta fase.

## Propósito

- Representación intermedia de alto nivel, ya con tipos resueltos y símbolos.
- Serializacion en protobuf lo que permite un puente Python → C++.
- Transporta la tabla de símbolos enriquecida (tipos, mutabilidad,
  región/propiedad) hacia el lowering a MIR.

## TODO

- [ ] Definir el esquema `.proto` del HIR.
- [ ] Generador de HIR desde el AST validado (Python).
- [ ] Lector de HIR en C++ (entrada del lowering a MIR).
- [ ] Versionado de esquema y compatibilidad.
