# Resumen de cumplimiento

> Documento GENERADO por `docs/quality/tools/quality.py` a partir de `docs/quality/reports/`. No se edita a mano: se vuelve a medir.

Porcentaje de cumplimiento de cada norma y lineamiento. "Medido" sale de una herramienta; "autoevaluado" es un juicio con evidencias (12207 y 29119 son normas de PROCESO: no hay herramienta que las mida). El target web está fuera del alcance (ver `docs/quality/normas/alcance.md`).

| Norma / lineamiento | Cómo | Cumplimiento | Detalle |
|---|---|---|---|
| ISO/IEC 25010 (producto) | medido | 92.9 % | [iso_iec_25010.md](iso_iec_25010.md) |
| ISO/IEC/IEEE 12207 (ciclo de vida) | autoevaluado | 79.2 % | [iso_iec_12207.md](iso_iec_12207.md) |
| ISO/IEC/IEEE 29119 (pruebas) | autoevaluado | 93.3 % | [iso_iec_ieee_29119.md](iso_iec_ieee_29119.md) |
| PEP 8 (archivos limpios, compilador) | medido | 78.7 % | [python.md](python.md) |
| PEP 20 (complejidad ≤ 15) | medido | 98.9 % | [python.md](python.md) |
| PEP 20 (errores no silenciados) | medido | 100.0 % | [python.md](python.md) |
| PEP 257 (lo público documentado) | medido | 73.5 % | [python.md](python.md) |
| pylint (nota × 10) | medido | 93.6 % | [python.md](python.md) |
| black (archivos con su formato; informativo, no es una norma) | medido | 24.8 % | [python.md](python.md) |
| C++ Core Guidelines (reglas sin hallazgos) | medido | 58.1 % | [cpp.md](cpp.md) |
| cppcheck (archivos sin hallazgos) | medido | 55.6 % | [cpp.md](cpp.md) |
| ASan (suite de la VM limpia) | medido | 100.0 % | [cpp.md](cpp.md) |
| UBSan (suite de la VM limpia) | medido | 100.0 % | [cpp.md](cpp.md) |
| Suite (pasan, de las ejecutadas) | medido | 100.0 % | [pruebas.md](pruebas.md) |
| Cobertura de líneas | medido | 88.0 % | [pruebas.md](pruebas.md) |
| Portabilidad de la suite | medido | 100.0 % | [pruebas.md](pruebas.md) |
