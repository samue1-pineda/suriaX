# Cumplimiento: pruebas, cobertura y portabilidad

> Documento GENERADO por `docs/quality/tools/quality.py` a partir de `docs/quality/reports/`. No se edita a mano: se vuelve a medir.

## La suite (`test/main.py`)

| Indicador | Valor | Porcentaje |
|---|---|---|
| pruebas que pasan (de las ejecutadas) | 1145 de 1145 | 100.0 % |
| pruebas ejecutadas (del total) | 1145 de 1161 | 98.6 % |
| módulos | 86 | — |
| categorías corridas | unit, grammar, negative_tests, snapshot, e2e, fuzz, backend, bootstrap | — |

Omitidas (no se ejecutaron: falta algo en la máquina, no es un fallo):

| Motivo | Pruebas |
|---|---|
| el módulo nativo 'memory_c' no cargó (ImportError: No se pudo cargar el módulo nativo 'memory_c'. Comprueba que el .so/.pyd exista y que se haya compilado con el mismo intérprete de Python que estás usando para importarlo.); constrúyelo con: cmake -S . -B build && cmake --build build --target suriax-native | 8 |
| node no está instalado; el target web no corre | 2 |
| node no disponible; no se puede ejecutar el target web | 2 |
| el repositorio no versiona un .suriaX_config.yaml (está en .gitignore): no hay configuración distribuida que validar | 1 |
| google.protobuf no está instalado (pip install protobuf): es la referencia independiente contra la que se compara el codec | 1 |
| node no disponible para re-serializar | 1 |
| node no está instalado; la suite del backend web no se ejecuta | 1 |

Pruebas por categoría (cuenta estática):

| Categoría | Módulos | Pruebas |
|---|---|---|
| backend | 14 | 75 |
| bootstrap | 3 | 18 |
| e2e | 25 | 340 |
| fuzz | 2 | 23 |
| grammar | 4 | 141 |
| negative_tests | 8 | 146 |
| snapshot | 1 | 5 |
| unit | 29 | 374 |

## Cobertura (coverage.py)

Herramienta: `Coverage.py, version 7.16.2 with C extension`, configuración `[tool.coverage]` de `pyproject.toml` (subprocesos incluidos).

| Indicador | Valor | Porcentaje |
|---|---|---|
| líneas del compilador ejecutadas por la suite | 11167 de 12415 | 88.0 % |
| ramas ejecutadas | 3794 de 4590 | 82.7 % |

Por paquete:

| Paquete | Sentencias | Cubiertas | Porcentaje |
|---|---|---|---|
| V0 | 8928 | 8291 | 92.9 % |
| config | 568 | 368 | 64.8 % |
| htims | 630 | 525 | 83.3 % |
| runtime | 2239 | 1933 | 86.3 % |
| suri | 50 | 50 | 100.0 % |

## Portabilidad (dependencias del sistema operativo)

Lo que busca `docs/quality/tools/portability.py`: APIs solo de POSIX, `open()` y subprocesos sin codificación, `shell=True`, rutas y ejecutables escritos a mano, enlaces simbólicos sin alternativa.

| Alcance | Archivos sin hallazgos | Hallazgos | Porcentaje |
|---|---|---|---|
| compilador | 141 de 141 | 0 | 100.0 % |
| suite de pruebas | 95 de 95 | 0 | 100.0 % |
