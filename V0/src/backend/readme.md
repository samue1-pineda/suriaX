> **Obsoleto (0.4.1):** estas notas planeaban un backend LLVM IR dentro de
> `V0/`. El backend real vive en [`backend/`](../../../backend/README.md) (C++:
> MIR y una VM de registros) y LLVM quedó fuera del plan en la v0.2.0. Se
> conservan como historia hasta que se decida si se borran (ver
> [c_errorstfix.md](../../../c_errorstfix.md)).

## t_pir t_int y t_vm?

suriaX ha enfrentado muchas decisiones de diseño, las mas cruciales han sido el HIR/MIR 
el puente de protobuf definido en el HIR permite un desacoplamiento importante en el desarroollo del compilador, logicamente se usara esta ventaja.

luego de muchas investigaciones y horas de desarollo en el frontend/HIR se noto una necesidad: tener un segundo backend menos complejo para hacer pruebas y test, gracias a esto se propuso lo siguiente:

Target Virtual Machine y target: LLVM IR, gracias a compiler config solo se necesitara una configuracion en suriaX_config.yaml y el compilador ejecutara el codigo de acuerdo a esta configuracion, permitiendo realizar pruebas tempranas sobre la logica funcionalidades e incluso probar nuevas caracteristicas sin la necesidad de esperar meses por el backend de LLVM IR.

como es de esperarse existen algunas cosas que se mantendran entre estos dos backends: el sistema de tipos, el sistema de runtime y el contrato del HIR(protobuf) seran agnosticos a estos facilitando asi muchas pruebas que podrian llegar a esperar meses.

happy coding :)