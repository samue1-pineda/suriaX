# Cumplimiento: ISO/IEC/IEEE 12207 (procesos del ciclo de vida)

> Documento GENERADO por `docs/quality/tools/quality.py` a partir de `docs/quality/reports/`. No se edita a mano: se vuelve a medir.

Autoevaluación contra ISO/IEC/IEEE 12207:2017: NO la mide una herramienta. Los estados y sus evidencias están en `docs/quality/tools/assessments.py`; el porcentaje se calcula como (aplicado + ½·parcial) / procesos aplicables. Por qué se usa esta norma y cómo se adaptó: `docs/quality/normas/`.

| Cláusula | Grupo | Proceso | Estado | Evidencia | Justificación |
|---|---|---|---|---|---|
| 6.1.1 | Acuerdo | Adquisición | no aplica | — | No hay adquirente ni contrato: un proyecto de un mantenedor, de código abierto. |
| 6.1.2 | Acuerdo | Suministro | no aplica | — | No se suministra a un cliente bajo acuerdo. |
| 6.2.1 | Organizacional | Gestión del modelo de ciclo de vida | parcial | `audit/reglas_generales.md` | Ciclo iterativo por lotes con reglas escritas; sin un modelo formal publicado. (`audit/` es local: no se versiona) |
| 6.2.2 | Organizacional | Gestión de infraestructura | aplicado | `CMakeLists.txt`, `.github/workflows/ci.yml`, `config` | Build reproducible (CMake), CI y configuración del proyecto versionados. |
| 6.2.3 | Organizacional | Gestión del portafolio | no aplica | — | Un solo proyecto. |
| 6.2.4 | Organizacional | Gestión de recursos humanos | no aplica | — | Un solo mantenedor. |
| 6.2.5 | Organizacional | Gestión de la calidad | aplicado | `docs/quality/README.md`, `audit/reglas_generales.md` | Objetivos y normas de calidad escritos y medidos (docs/quality). (`audit/` es local: no se versiona) |
| 6.2.6 | Organizacional | Gestión del conocimiento | aplicado | `documentation/source`, `ARCHITECTURE.md`, `audit/requerimientos.md` | Documentación del lenguaje, de la arquitectura y bitácora de decisiones. (`audit/` es local: no se versiona) |
| 6.3.1 | Gestión técnica | Planificación del proyecto | aplicado | `ROADMAP.md`, `audit/requerimientos.md` | Hoja de ruta por fases y plan de cada lote. (`audit/` es local: no se versiona) |
| 6.3.2 | Gestión técnica | Evaluación y control del proyecto | parcial | `audit/pruebas.md`, `CHANGELOG.md` | Línea base medida en cada lote; sin cronograma ni esfuerzo registrados. (`audit/` es local: no se versiona) |
| 6.3.3 | Gestión técnica | Gestión de decisiones | aplicado | `audit/requerimientos.md` | Cada decisión con quién la tomó y las alternativas descartadas. (`audit/` es local: no se versiona) |
| 6.3.4 | Gestión técnica | Gestión de riesgos | parcial | `c_errorstfix.md` | Errores y limitaciones abiertos listados; sin registro de riesgos con probabilidad e impacto. |
| 6.3.5 | Gestión técnica | Gestión de la configuración | aplicado | `version.py`, `CHANGELOG.md`, `.gitignore` | git, versión con fuente única, historial de cambios por versión. |
| 6.3.6 | Gestión técnica | Gestión de la información | aplicado | `FLAGS.md`, `documentation/source/errors.rst` | Documentación verificada por pruebas contra el código (test_docs_al_dia). |
| 6.3.7 | Gestión técnica | Medición | aplicado | `docs/quality/tools/quality.py`, `test/main.py` | Medidas automáticas de producto (docs/quality) y de pruebas (--json). |
| 6.3.8 | Gestión técnica | Aseguramiento de la calidad | parcial | `.github/workflows/tests.yml`, `docs/quality/tools/quality.py` | CI y mediciones automáticas; sin revisión independiente (un mantenedor). |
| 6.4.1 | Técnico | Análisis del negocio o misión | parcial | `README.md`, `DESIGN_PRINCIPLES.md` | El propósito (compilador educativo) está escrito; sin análisis formal. |
| 6.4.2 | Técnico | Definición de necesidades y requisitos de interesados | parcial | `audit/requerimientos.md` | Requisitos del mantenedor registrados; no hay otros interesados formales. (`audit/` es local: no se versiona) |
| 6.4.3 | Técnico | Definición de requisitos del sistema/software | parcial | `documentation/source`, `docs/gramar` | Especificación del lenguaje escrita; la gramática EBNF está desactualizada respecto del parser. |
| 6.4.4 | Técnico | Definición de la arquitectura | aplicado | `ARCHITECTURE.md`, `DESIGN_PRINCIPLES.md` | Arquitectura por fases documentada. |
| 6.4.5 | Técnico | Definición del diseño | aplicado | `docs/hir.md`, `docs/mir.md`, `V0/src/HIR/PROTOBUF_BRIDGE.md` | Diseño del HIR, del MIR y del contrato entre fases. |
| 6.4.6 | Técnico | Análisis del sistema | parcial | `dev/bench_vm.py` | Mediciones de rendimiento puntuales; sin análisis sistemático. |
| 6.4.7 | Técnico | Implementación | aplicado | `V0`, `backend` | El compilador. |
| 6.4.8 | Técnico | Integración | aplicado | `V0/driver/pipeline.py`, `.github/workflows/build.yml` | Pipeline de fases y build integrado en la CI (tres sistemas operativos). |
| 6.4.9 | Técnico | Verificación | aplicado | `test/main.py`, `docs/quality/tools/sanitizers.py` | Suite por fases, diferencial entre motores, análisis estático y sanitizadores. |
| 6.4.10 | Técnico | Transición | parcial | `.github/workflows/release.yml` | Release automatizado; el empaquetado del binario está pendiente (ROADMAP). |
| 6.4.11 | Técnico | Validación | parcial | `test/e2e/test_programas_de_fuego.py` | Programas completos como uso real; la validación con usuarios (tesis) está pendiente. |
| 6.4.12 | Técnico | Operación | no aplica | — | El proyecto no opera un servicio: cada usuario ejecuta el compilador. |
| 6.4.13 | Técnico | Mantenimiento | aplicado | `c_errorstfix.md`, `CHANGELOG.md` | Errores abiertos y correcciones por versión. |
| 6.4.14 | Técnico | Disposición (retiro) | no aplica | — | El sistema no se retira; el retiro de funciones (las regiones) se trató como mantenimiento. |

| Estado | Procesos |
|---|---|
| aplicado | 14 |
| parcial | 10 |
| pendiente | 0 |
| no aplica | 6 |

**Grado de aplicación (autoevaluado):** 79.2 % de 24 aplicables
