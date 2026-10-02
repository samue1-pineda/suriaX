# Cumplimiento: ISO/IEC 25010 (calidad del producto)

> Documento GENERADO por `docs/quality/tools/quality.py` a partir de `docs/quality/reports/`. No se edita a mano: se vuelve a medir.

Modelo de calidad de producto de ISO/IEC 25010:2023. La norma define las características; los INDICADORES y la forma de agregarlos son del proyecto (la norma no fija porcentajes): cada característica es el promedio de sus indicadores medidos. Qué significa cada uno y por qué se eligió: `docs/quality/normas/iso_iec_25010.md`.

| Característica | Subcaracterística | Indicador | Valor |
|---|---|---|---|
| Adecuación funcional | Corrección funcional | pruebas que pasan, de las ejecutadas | 100.0 % |
| Adecuación funcional | Completitud funcional | hoja de ruta hecha (64 hechas, 7 a medias, 12 pendientes; sin la fase web) | 81.3 % |
| Eficiencia de desempeño | Comportamiento temporal | sin medida automática (hay un benchmark manual: `dev/bench_vm.py`) | NO MEDIDO |
| Compatibilidad | Interoperabilidad | el HIR que emite Python lo ejecuta la VM de C++ igual que el intérprete (categoría `backend`) | 100.0 % |
| Capacidad de interacción | Reconocibilidad / aprendizaje | códigos de error documentados (132 de 132) | 100.0 % |
| Fiabilidad | Ausencia de fallos | suite de la VM limpia bajo UBSan | 100.0 % |
| Fiabilidad | Tolerancia a fallos | pruebas aleatorias y de estrés (categoría `fuzz`) | 100.0 % |
| Seguridad | Integridad (memoria) | suite de la VM limpia bajo ASan | 100.0 % |
| Seguridad | Integridad (análisis estático) | archivos C++ sin hallazgos de cppcheck | 55.6 % |
| Mantenibilidad | Analizabilidad | archivos Python sin violaciones de PEP 8 | 78.7 % |
| Mantenibilidad | Analizabilidad | definiciones públicas documentadas (PEP 257) | 73.5 % |
| Mantenibilidad | Analizabilidad | reglas de las C++ Core Guidelines sin hallazgos | 58.1 % |
| Mantenibilidad | Modificabilidad | funciones con complejidad ≤ 15 | 98.9 % |
| Mantenibilidad | Modificabilidad | nota de pylint × 10 | 93.6 % |
| Mantenibilidad | Capacidad de ser probado | líneas del compilador cubiertas por la suite | 88.0 % |
| Flexibilidad | Adaptabilidad | compilador sin dependencias del sistema operativo | 100.0 % |
| Flexibilidad | Adaptabilidad | suite sin dependencias del sistema operativo | 100.0 % |
| Protección (safety) | — | no aplica: el compilador no controla un sistema que pueda dañar personas o bienes | — |

## Por característica

| Característica | Cumplimiento |
|---|---|
| Adecuación funcional | 90.7 % |
| Eficiencia de desempeño | NO MEDIDO |
| Compatibilidad | 100.0 % |
| Capacidad de interacción | 100.0 % |
| Fiabilidad | 100.0 % |
| Seguridad | 77.8 % |
| Mantenibilidad | 81.8 % |
| Flexibilidad | 100.0 % |
| Protección (safety) | no aplica |

**Cumplimiento global (promedio de las características medidas):** 92.9 % — 7 de 8 características aplicables tienen al menos un indicador medido.
