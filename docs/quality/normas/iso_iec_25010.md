# ISO/IEC 25010: modelo de calidad del producto

**Norma:** ISO/IEC 25010:2023, *Systems and software engineering — Systems and
software Quality Requirements and Evaluation (SQuaRE) — Product quality
model*. Reemplaza a la edición de 2011.

## Por qué es el marco principal

- Evalúa el **producto** (el compilador), que es lo que el proyecto entrega.
- Divide la calidad en características con nombre, así que cada medida
  sabe a qué aporta.
- Varias de sus características se pueden medir con herramientas:
  mantenibilidad, flexibilidad, fiabilidad y parte de la adecuación
  funcional. Por eso tiene sentido darle un **porcentaje**, cosa que las
  normas de proceso no permiten sin inventarlo.

La norma define **qué** es calidad, pero no fija umbrales ni porcentajes.
Las medidas de referencia están en ISO/IEC 25023, que este proyecto no adopta
formalmente. Los **indicadores y su agregación son del proyecto**, y están
escritos abajo para que se puedan discutir y cambiar.

## Nombres de la edición de 2011

Si un texto cita la edición de 2011, estas son las equivalencias:

| 2011 | 2023 |
|---|---|
| Usabilidad | Capacidad de interacción |
| Portabilidad | Flexibilidad (gana *escalabilidad*) |
| Madurez (en fiabilidad) | Ausencia de fallos (*faultlessness*) |
| — | Protección (*safety*), característica nueva |
| — | Resistencia (en seguridad), subcaracterística nueva |

## Indicadores

Cada fila dice qué se mide y con qué herramienta. El resultado vigente está en
[../cumplimiento/iso_iec_25010.md](../cumplimiento/iso_iec_25010.md).

| Característica | Subcaracterística | Indicador | Fuente |
|---|---|---|---|
| Adecuación funcional | Corrección funcional | % de pruebas que pasan, de las ejecutadas | la suite (`test/main.py --todo`) |
| Adecuación funcional | Completitud funcional | % de la hoja de ruta hecha (`[x]` = 1, `[ / ]` = ½), sin la fase web | `ROADMAP.md` |
| Eficiencia de desempeño | Comportamiento temporal | **no medido** automáticamente: hay un benchmark manual (`dev/bench_vm.py`) sin umbral acordado | — |
| Compatibilidad | Interoperabilidad | % de la categoría `backend`: el HIR que emite Python lo ejecuta la VM de C++ igual que el intérprete | la suite |
| Capacidad de interacción | Reconocibilidad, aprendizaje | % de códigos de error con su entrada en la documentación | `--emit-lang-info` contra `errors.rst` |
| Fiabilidad | Ausencia de fallos | % de la suite de la VM limpia bajo UBSan | `quality.py sanitizers` |
| Fiabilidad | Tolerancia a fallos | % de la categoría `fuzz` (entradas aleatorias y estrés) | la suite |
| Seguridad | Integridad | % de la suite de la VM limpia bajo ASan (sin accesos inválidos a memoria) | `quality.py sanitizers` |
| Seguridad | Integridad | % de archivos C++ sin hallazgos de cppcheck | `quality.py cpp` |
| Mantenibilidad | Analizabilidad | % de archivos Python sin violaciones de PEP 8 | flake8 |
| Mantenibilidad | Analizabilidad | % de definiciones públicas con docstring (PEP 257) | análisis del AST |
| Mantenibilidad | Analizabilidad | % de reglas de las C++ Core Guidelines sin hallazgos | clang-tidy |
| Mantenibilidad | Modificabilidad | % de funciones con complejidad ciclomática ≤ 15 | flake8 (mccabe) |
| Mantenibilidad | Modificabilidad | nota de pylint × 10 | pylint |
| Mantenibilidad | Capacidad de ser probado | % de líneas del compilador que ejecuta la suite | coverage.py |
| Flexibilidad | Adaptabilidad | % de archivos del compilador sin dependencias del sistema operativo | `portability.py` |
| Flexibilidad | Adaptabilidad | % de archivos de la suite sin dependencias del sistema operativo | `portability.py` |
| Protección | — | **no aplica**: el compilador no controla un sistema que pueda dañar a personas o bienes | — |

**Agregación:** una característica vale el promedio de sus indicadores
medidos, y el global el promedio de las características con al menos uno
medido. Un indicador NO MEDIDO no cuenta como 0 ni como 100: se deja fuera
y el documento dice cuántas características quedaron sin medir.

## Límites que hay que decir

- La completitud funcional se mide contra la hoja de ruta del propio
  proyecto, no contra una especificación externa (no la hay: ver
  [alcance.md](alcance.md)).
- La seguridad de un compilador educativo se reduce aquí a la **integridad de
  la memoria** de la VM. Confidencialidad, no repudio y autenticidad no
  aplican: no hay usuarios, credenciales ni datos de terceros.
- La eficiencia de desempeño queda sin porcentaje hasta que se acuerde contra
  qué comparar (otro intérprete, una versión anterior, un tiempo máximo).
