# ISO/IEC/IEEE 12207: procesos del ciclo de vida del software

**Norma:** ISO/IEC/IEEE 12207:2017, *Systems and software engineering —
Software life cycle processes*.

## Qué es y por qué se usa como referencia (no como marco)

12207 describe **procesos**: cómo una organización adquiere, suministra,
desarrolla, opera y mantiene software. Tiene 30 procesos en cuatro grupos:
acuerdo, habilitación organizacional, gestión técnica y técnicos.

Está pensada para organizaciones con roles separados (adquirente,
proveedor, calidad, gestión). suriaX tiene **un solo mantenedor**, así que
varios procesos no tienen a quién aplicarse: no hay contrato, portafolio ni
personal que gestionar. Declarar un porcentaje "medido" de 12207 sería
inventarlo. Por eso:

- **no** es el marco de calidad del proyecto (lo es [ISO/IEC 25010](iso_iec_25010.md));
- se usa como **referencia de proceso adaptada**. La norma prevé esta
  *conformidad adaptada* (*tailored conformance*): se eligen los procesos
  que aplican y se justifica el recorte;
- el grado de aplicación es una **autoevaluación** con evidencias, no una
  medición.

## Cómo se adaptó

| Grupo | Procesos | Adaptación |
|---|---|---|
| Acuerdo (6.1) | adquisición, suministro | no aplican: no hay contrato |
| Habilitación organizacional (6.2) | 6 | aplican los que tienen sentido con un mantenedor (infraestructura, calidad, conocimiento, modelo de ciclo de vida); portafolio y recursos humanos no |
| Gestión técnica (6.3) | 8 | aplican todos; riesgos, control y aseguramiento de la calidad de forma parcial |
| Técnicos (6.4) | 14 | aplican casi todos; operación y disposición no (no se opera un servicio) |

## Correspondencia con el repositorio

| Proceso de 12207 | Dónde vive en suriaX |
|---|---|
| Gestión de decisiones (6.3.3) | `audit/requerimientos.md`: cada decisión con quién la tomó y qué se descartó |
| Gestión de la configuración (6.3.5) | git, `version.py` (fuente única de la versión), `CHANGELOG.md` |
| Gestión de la información (6.3.6) | documentación verificada contra el código por la suite (`test_docs_al_dia`) |
| Medición (6.3.7) | `docs/quality/tools/` y el resumen `--json` de la suite |
| Definición de requisitos (6.4.3) | la documentación del lenguaje; la gramática EBNF está **desactualizada** |
| Verificación (6.4.9) | la suite, el diferencial entre motores, el análisis estático y los sanitizadores |
| Mantenimiento (6.4.13) | `c_errorstfix.md` (errores abiertos) y `CHANGELOG.md` (corregidos) |

`audit/` es una carpeta **local**: no se versiona, por decisión del
mantenedor. Las evidencias que viven ahí existen en la máquina de desarrollo,
pero no en el repositorio público. El informe lo marca en cada fila.

La tabla completa, proceso por proceso con su estado y su evidencia, se genera
en [../cumplimiento/iso_iec_12207.md](../cumplimiento/iso_iec_12207.md) a partir
de `docs/quality/tools/assessments.py`.
