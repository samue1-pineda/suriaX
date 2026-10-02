# Cumplimiento: ISO/IEC/IEEE 29119 (pruebas de software)

> Documento GENERADO por `docs/quality/tools/quality.py` a partir de `docs/quality/reports/`. No se edita a mano: se vuelve a medir.

Autoevaluación contra ISO/IEC/IEEE 29119 (partes 2 a 5): NO la mide una herramienta. Los estados y sus evidencias están en `docs/quality/tools/assessments.py`; el porcentaje se calcula como (aplicado + ½·parcial) / procesos aplicables. Por qué se usa esta norma y cómo se adaptó: `docs/quality/normas/`.

| Cláusula | Grupo | Proceso | Estado | Evidencia | Justificación |
|---|---|---|---|---|---|
| 29119-2 | Procesos | Política de pruebas de la organización | aplicado | `audit/reglas_generales.md` | Toda función nueva trae pruebas; los cambios grandes corren --todo y ASan. (`audit/` es local: no se versiona) |
| 29119-2 | Procesos | Gestión de pruebas (plan, seguimiento, cierre) | parcial | `audit/pruebas.md` | Protocolo para cambios grandes y línea base por lote; sin plan de pruebas por versión. (`audit/` es local: no se versiona) |
| 29119-2 | Procesos | Proceso dinámico de pruebas (diseño, ejecución, informe) | aplicado | `test/main.py`, `test/helpers.py` | Runner propio: descubre, ejecuta, informa fallos y omisiones con motivo. |
| 29119-3 | Documentación | Plan de pruebas | parcial | `audit/pruebas.md` | Cómo se corre y qué va en cada categoría; no hay un plan formal por versión. (`audit/` es local: no se versiona) |
| 29119-3 | Documentación | Especificación de casos de prueba | aplicado | `test/unit/test_lang_info.py` | Cada prueba documenta en su docstring qué comprueba y por qué. |
| 29119-3 | Documentación | Informe de finalización de pruebas | aplicado | `test/main.py`, `.github/workflows/tests.yml` | Resumen --json (pasadas, fallidas, omitidas con motivo) e informe en la CI. |
| 29119-3 | Documentación | Informe de incidencias | aplicado | `c_errorstfix.md` | Los fallos abiertos, con causa y estado. |
| 29119-4 | Técnicas | Partición en clases de equivalencia y valores límite | aplicado | `test/e2e/test_ancho_fijo.py` | Enteros de ancho fijo, literales en sus límites, rangos de índices. |
| 29119-4 | Técnicas | Pruebas basadas en la sintaxis | aplicado | `test/grammar/test_grammar_ast.py` | La gramática regla a regla. |
| 29119-4 | Técnicas | Conjetura de errores (pruebas negativas) | aplicado | `test/negative_tests/test_diagnostics_memory.py` | Cada código de error con un programa que lo provoca. |
| 29119-4 | Técnicas | Pruebas aleatorias (fuzz) | aplicado | `test/fuzz` | Entradas generadas y estrés de memoria. |
| 29119-4 | Técnicas | Pruebas espalda con espalda (diferencial) | aplicado | `test/backend/test_vm_diferencial_corpus.py` | El mismo programa en la VM y en el intérprete; la V1 contra la V0. |
| 29119-4 | Técnicas | Pruebas de escenario | aplicado | `test/e2e/test_programas_de_fuego.py` | Programas completos con su salida esperada. |
| 29119-4 | Técnicas | Técnicas estructurales (cobertura de sentencias y ramas) | aplicado | `docs/quality/tools/suite_checks.py` | Cobertura medida con coverage.py (ramas incluidas). |
| 29119-4 | Técnicas | Pruebas de regresión con referencia (golden) | aplicado | `test/snapshot/test_golden.py` | AST, HIR y tabla de símbolos contra una referencia. |
| 29119-5 | Pruebas por palabras clave | Pruebas dirigidas por palabras clave | no aplica | — | Las pruebas son código; no hay un lenguaje de palabras clave. |

| Estado | Procesos |
|---|---|
| aplicado | 13 |
| parcial | 2 |
| pendiente | 0 |
| no aplica | 1 |

**Grado de aplicación (autoevaluado):** 93.3 % de 15 aplicables
