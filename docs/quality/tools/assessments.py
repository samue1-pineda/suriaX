"""Las AUTOEVALUACIONES de proceso: ISO/IEC/IEEE 12207 (ciclo de vida) e
ISO/IEC/IEEE 29119 (pruebas).

A diferencia del resto de ``docs/quality``, esto no lo mide una herramienta:
es un juicio, escrito aquí como datos para que el porcentaje se calcule
siempre igual y para que cada estado tenga su EVIDENCIA (un archivo del
repositorio que se puede abrir). El informe verifica que cada evidencia
exista: una evidencia que desaparece baja el estado en el documento.

Estados: ``aplicado`` (1), ``parcial`` (0.5), ``no aplica`` (fuera del
cálculo, con su motivo), ``pendiente`` (0).
"""

from __future__ import annotations

APPLIED, PARTIAL, NOT_APPLICABLE, PENDING = "aplicado", "parcial", "no aplica", "pendiente"
WEIGHT = {APPLIED: 1.0, PARTIAL: 0.5, PENDING: 0.0}

#: ISO/IEC/IEEE 12207:2017, cláusula 6: los 30 procesos en sus 4 grupos.
ISO_12207 = [
    # --- 6.1 acuerdo -------------------------------------------------------
    (
        "6.1.1",
        "Acuerdo",
        "Adquisición",
        NOT_APPLICABLE,
        [],
        "No hay adquirente ni contrato: un proyecto de un mantenedor, de código abierto.",
    ),
    (
        "6.1.2",
        "Acuerdo",
        "Suministro",
        NOT_APPLICABLE,
        [],
        "No se suministra a un cliente bajo acuerdo.",
    ),
    # --- 6.2 habilitación organizacional -----------------------------------
    (
        "6.2.1",
        "Organizacional",
        "Gestión del modelo de ciclo de vida",
        PARTIAL,
        ["audit/reglas_generales.md"],
        "Ciclo iterativo por lotes con reglas escritas; sin un modelo formal publicado.",
    ),
    (
        "6.2.2",
        "Organizacional",
        "Gestión de infraestructura",
        APPLIED,
        ["CMakeLists.txt", ".github/workflows/ci.yml", "config"],
        "Build reproducible (CMake), CI y configuración del proyecto versionados.",
    ),
    ("6.2.3", "Organizacional", "Gestión del portafolio", NOT_APPLICABLE, [], "Un solo proyecto."),
    (
        "6.2.4",
        "Organizacional",
        "Gestión de recursos humanos",
        NOT_APPLICABLE,
        [],
        "Un solo mantenedor.",
    ),
    (
        "6.2.5",
        "Organizacional",
        "Gestión de la calidad",
        APPLIED,
        ["docs/quality/README.md", "audit/reglas_generales.md"],
        "Objetivos y normas de calidad escritos y medidos (docs/quality).",
    ),
    (
        "6.2.6",
        "Organizacional",
        "Gestión del conocimiento",
        APPLIED,
        ["documentation/source", "ARCHITECTURE.md", "audit/requerimientos.md"],
        "Documentación del lenguaje, de la arquitectura y bitácora de decisiones.",
    ),
    # --- 6.3 gestión técnica -----------------------------------------------
    (
        "6.3.1",
        "Gestión técnica",
        "Planificación del proyecto",
        APPLIED,
        ["ROADMAP.md", "audit/requerimientos.md"],
        "Hoja de ruta por fases y plan de cada lote.",
    ),
    (
        "6.3.2",
        "Gestión técnica",
        "Evaluación y control del proyecto",
        PARTIAL,
        ["audit/pruebas.md", "CHANGELOG.md"],
        "Línea base medida en cada lote; sin cronograma ni esfuerzo registrados.",
    ),
    (
        "6.3.3",
        "Gestión técnica",
        "Gestión de decisiones",
        APPLIED,
        ["audit/requerimientos.md"],
        "Cada decisión con quién la tomó y las alternativas descartadas.",
    ),
    (
        "6.3.4",
        "Gestión técnica",
        "Gestión de riesgos",
        PARTIAL,
        ["c_errorstfix.md"],
        "Errores y limitaciones abiertos listados; sin registro de riesgos con probabilidad "
        "e impacto.",
    ),
    (
        "6.3.5",
        "Gestión técnica",
        "Gestión de la configuración",
        APPLIED,
        ["version.py", "CHANGELOG.md", ".gitignore"],
        "git, versión con fuente única, historial de cambios por versión.",
    ),
    (
        "6.3.6",
        "Gestión técnica",
        "Gestión de la información",
        APPLIED,
        ["FLAGS.md", "documentation/source/errors.rst"],
        "Documentación verificada por pruebas contra el código (test_docs_al_dia).",
    ),
    (
        "6.3.7",
        "Gestión técnica",
        "Medición",
        APPLIED,
        ["docs/quality/tools/quality.py", "test/main.py"],
        "Medidas automáticas de producto (docs/quality) y de pruebas (--json).",
    ),
    (
        "6.3.8",
        "Gestión técnica",
        "Aseguramiento de la calidad",
        PARTIAL,
        [".github/workflows/tests.yml", "docs/quality/tools/quality.py"],
        "CI y mediciones automáticas; sin revisión independiente (un mantenedor).",
    ),
    # --- 6.4 técnicos ------------------------------------------------------
    (
        "6.4.1",
        "Técnico",
        "Análisis del negocio o misión",
        PARTIAL,
        ["README.md", "DESIGN_PRINCIPLES.md"],
        "El propósito (compilador educativo) está escrito; sin análisis formal.",
    ),
    (
        "6.4.2",
        "Técnico",
        "Definición de necesidades y requisitos de interesados",
        PARTIAL,
        ["audit/requerimientos.md"],
        "Requisitos del mantenedor registrados; no hay otros interesados formales.",
    ),
    (
        "6.4.3",
        "Técnico",
        "Definición de requisitos del sistema/software",
        PARTIAL,
        ["documentation/source", "docs/gramar"],
        "Especificación del lenguaje escrita; la gramática EBNF está desactualizada "
        "respecto del parser.",
    ),
    (
        "6.4.4",
        "Técnico",
        "Definición de la arquitectura",
        APPLIED,
        ["ARCHITECTURE.md", "DESIGN_PRINCIPLES.md"],
        "Arquitectura por fases documentada.",
    ),
    (
        "6.4.5",
        "Técnico",
        "Definición del diseño",
        APPLIED,
        ["docs/hir.md", "docs/mir.md", "V0/src/HIR/PROTOBUF_BRIDGE.md"],
        "Diseño del HIR, del MIR y del contrato entre fases.",
    ),
    (
        "6.4.6",
        "Técnico",
        "Análisis del sistema",
        PARTIAL,
        ["dev/bench_vm.py"],
        "Mediciones de rendimiento puntuales; sin análisis sistemático.",
    ),
    ("6.4.7", "Técnico", "Implementación", APPLIED, ["V0", "backend"], "El compilador."),
    (
        "6.4.8",
        "Técnico",
        "Integración",
        APPLIED,
        ["V0/driver/pipeline.py", ".github/workflows/build.yml"],
        "Pipeline de fases y build integrado en la CI (tres sistemas operativos).",
    ),
    (
        "6.4.9",
        "Técnico",
        "Verificación",
        APPLIED,
        ["test/main.py", "docs/quality/tools/sanitizers.py"],
        "Suite por fases, diferencial entre motores, análisis estático y sanitizadores.",
    ),
    (
        "6.4.10",
        "Técnico",
        "Transición",
        PARTIAL,
        [".github/workflows/release.yml"],
        "Release automatizado; el empaquetado del binario está pendiente (ROADMAP).",
    ),
    (
        "6.4.11",
        "Técnico",
        "Validación",
        PARTIAL,
        ["test/e2e/test_programas_de_fuego.py"],
        "Programas completos como uso real; la validación con usuarios (tesis) está pendiente.",
    ),
    (
        "6.4.12",
        "Técnico",
        "Operación",
        NOT_APPLICABLE,
        [],
        "El proyecto no opera un servicio: cada usuario ejecuta el compilador.",
    ),
    (
        "6.4.13",
        "Técnico",
        "Mantenimiento",
        APPLIED,
        ["c_errorstfix.md", "CHANGELOG.md"],
        "Errores abiertos y correcciones por versión.",
    ),
    (
        "6.4.14",
        "Técnico",
        "Disposición (retiro)",
        NOT_APPLICABLE,
        [],
        "El sistema no se retira; el retiro de funciones (las regiones) se trató como "
        "mantenimiento.",
    ),
]

#: ISO/IEC/IEEE 29119: qué parte de cada sección de la norma usa la suite.
ISO_29119 = [
    # --- parte 2: procesos --------------------------------------------------
    (
        "29119-2",
        "Procesos",
        "Política de pruebas de la organización",
        APPLIED,
        ["audit/reglas_generales.md"],
        "Toda función nueva trae pruebas; los cambios grandes corren --todo y ASan.",
    ),
    (
        "29119-2",
        "Procesos",
        "Gestión de pruebas (plan, seguimiento, cierre)",
        PARTIAL,
        ["audit/pruebas.md"],
        "Protocolo para cambios grandes y línea base por lote; sin plan de pruebas por "
        "versión.",
    ),
    (
        "29119-2",
        "Procesos",
        "Proceso dinámico de pruebas (diseño, ejecución, informe)",
        APPLIED,
        ["test/main.py", "test/helpers.py"],
        "Runner propio: descubre, ejecuta, informa fallos y omisiones con motivo.",
    ),
    # --- parte 3: documentación ----------------------------------------------
    (
        "29119-3",
        "Documentación",
        "Plan de pruebas",
        PARTIAL,
        ["audit/pruebas.md"],
        "Cómo se corre y qué va en cada categoría; no hay un plan formal por versión.",
    ),
    (
        "29119-3",
        "Documentación",
        "Especificación de casos de prueba",
        APPLIED,
        ["test/unit/test_lang_info.py"],
        "Cada prueba documenta en su docstring qué comprueba y por qué.",
    ),
    (
        "29119-3",
        "Documentación",
        "Informe de finalización de pruebas",
        APPLIED,
        ["test/main.py", ".github/workflows/tests.yml"],
        "Resumen --json (pasadas, fallidas, omitidas con motivo) e informe en la CI.",
    ),
    (
        "29119-3",
        "Documentación",
        "Informe de incidencias",
        APPLIED,
        ["c_errorstfix.md"],
        "Los fallos abiertos, con causa y estado.",
    ),
    # --- parte 4: técnicas -----------------------------------------------------
    (
        "29119-4",
        "Técnicas",
        "Partición en clases de equivalencia y valores límite",
        APPLIED,
        ["test/e2e/test_ancho_fijo.py"],
        "Enteros de ancho fijo, literales en sus límites, rangos de índices.",
    ),
    (
        "29119-4",
        "Técnicas",
        "Pruebas basadas en la sintaxis",
        APPLIED,
        ["test/grammar/test_grammar_ast.py"],
        "La gramática regla a regla.",
    ),
    (
        "29119-4",
        "Técnicas",
        "Conjetura de errores (pruebas negativas)",
        APPLIED,
        ["test/negative_tests/test_diagnostics_memory.py"],
        "Cada código de error con un programa que lo provoca.",
    ),
    (
        "29119-4",
        "Técnicas",
        "Pruebas aleatorias (fuzz)",
        APPLIED,
        ["test/fuzz"],
        "Entradas generadas y estrés de memoria.",
    ),
    (
        "29119-4",
        "Técnicas",
        "Pruebas espalda con espalda (diferencial)",
        APPLIED,
        ["test/backend/test_vm_diferencial_corpus.py"],
        "El mismo programa en la VM y en el intérprete; la V1 contra la V0.",
    ),
    (
        "29119-4",
        "Técnicas",
        "Pruebas de escenario",
        APPLIED,
        ["test/e2e/test_programas_de_fuego.py"],
        "Programas completos con su salida esperada.",
    ),
    (
        "29119-4",
        "Técnicas",
        "Técnicas estructurales (cobertura de sentencias y ramas)",
        APPLIED,
        ["docs/quality/tools/suite_checks.py"],
        "Cobertura medida con coverage.py (ramas incluidas).",
    ),
    (
        "29119-4",
        "Técnicas",
        "Pruebas de regresión con referencia (golden)",
        APPLIED,
        ["test/snapshot/test_golden.py"],
        "AST, HIR y tabla de símbolos contra una referencia.",
    ),
    # --- parte 5 -------------------------------------------------------------
    (
        "29119-5",
        "Pruebas por palabras clave",
        "Pruebas dirigidas por palabras clave",
        NOT_APPLICABLE,
        [],
        "Las pruebas son código; no hay un lenguaje de palabras clave.",
    ),
]
