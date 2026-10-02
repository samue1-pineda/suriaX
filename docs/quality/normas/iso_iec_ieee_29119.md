# ISO/IEC/IEEE 29119: pruebas de software

**Norma:** la serie ISO/IEC/IEEE 29119, *Software and systems engineering —
Software testing*:

| Parte | Tema |
|---|---|
| 29119-1 | conceptos y definiciones |
| 29119-2 | procesos de prueba (organizacional, de gestión, dinámico) |
| 29119-3 | documentación de las pruebas |
| 29119-4 | técnicas de diseño de pruebas |
| 29119-5 | pruebas dirigidas por palabras clave |

## Por qué se usa

La suite es la herramienta principal de verificación del proyecto: más de mil
pruebas en ocho categorías. 29119 da el vocabulario para explicar **qué
técnica usa cada categoría y por qué**. Eso es lo que una revisión externa (la
tesis) necesita para evaluarla.

Como 12207, es una norma de **proceso y documentación**: no se mide con una
herramienta. Se hace una autoevaluación con evidencias, y las medidas
objetivas de la suite (cuántas pasan, cuántas se ejecutan y la cobertura) van
en [ISO/IEC 25010](iso_iec_25010.md) y en
[../cumplimiento/pruebas.md](../cumplimiento/pruebas.md).

## Las técnicas de 29119-4 en la suite

| Técnica | Categoría / archivo | Qué comprueba |
|---|---|---|
| Partición en clases de equivalencia y valores límite | `e2e/test_ancho_fijo.py`, literales | los enteros de ancho fijo en sus bordes, los literales que caben y los que no |
| Basadas en la sintaxis | `grammar/` | la gramática, regla a regla |
| Conjetura de errores | `negative_tests/` | cada código de error, con un programa que lo provoca |
| Aleatorias | `fuzz/` | entradas generadas y estrés de la memoria |
| Espalda con espalda (*back-to-back*) | `backend/`, `bootstrap/` | el mismo programa en la VM y en el intérprete; el frontend escrito en suriaX contra el de Python |
| Escenario | `e2e/test_programas_de_fuego.py` | programas completos con su salida esperada |
| Regresión contra una referencia | `snapshot/` | el AST, el HIR y la tabla de símbolos contra un *golden* revisado |
| Estructurales (sentencias y ramas) | `docs/quality/tools/suite_checks.py` | la cobertura que alcanza la suite |

## Documentación de 29119-3

| Documento de la norma | En suriaX |
|---|---|
| Política de pruebas | reglas del proyecto: toda función nueva trae pruebas, y los cambios grandes corren `--todo` y ASan |
| Plan de pruebas | `audit/pruebas.md` (cómo se corre y el protocolo para cambios grandes); **parcial**: no hay un plan por versión |
| Especificación de casos | el docstring de cada prueba dice qué comprueba y por qué |
| Informe de finalización | el resumen del runner (`--json`): pasadas, fallidas y omitidas con su motivo |
| Informe de incidencias | `c_errorstfix.md` |

## Portabilidad de la suite

La suite no puede depender del sistema operativo. Una prueba que solo corre en
Linux no prueba nada en Windows, y cuenta como fallo o como omisión.
`docs/quality/tools/portability.py` revisa el código de las pruebas buscando:

- APIs solo de POSIX;
- subprocesos y archivos sin codificación explícita;
- `shell=True`;
- rutas y ejecutables escritos a mano;
- enlaces simbólicos sin alternativa.

Lo que depende del sistema vive en `test/helpers.py`:

- `hir_binary` busca el ejecutable con o sin `.exe`, en `build*/bin`;
- `run_with_timeout` es un tiempo límite sin `signal.alarm`;
- `link_lib` enlaza la librería, o la copia si no se puede.

Una prueba **omitida** no es lo mismo que una que depende del sistema. Se
omite cuando falta algo en la máquina (node, pyyaml, el módulo nativo), y la
suite lo dice con su motivo. El resultado sigue siendo el mismo en cualquier
sistema que tenga lo necesario.
