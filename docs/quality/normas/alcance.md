# Alcance de la revisión de calidad

## Qué se revisa

| Parte | Lenguaje | Carpetas |
|---|---|---|
| Frontend (lexer, parser, semántica, HIR) y driver | Python | `V0/` |
| Intérprete y enlace con `#extern cpp` | Python | `runtime/` |
| Extensiones del proyecto (HTIMS) | Python | `htims/` |
| Configuración y comando `suri` | Python | `config/`, `suri/`, `main.py`, `version.py` |
| Herramientas de desarrollo | Python | `dev/` |
| Lector del HIR, MIR y máquina virtual | C++20 | `backend/` |
| Memoria nativa del intérprete | C++ | `runtime/logic_mem/` |
| Suite de pruebas | Python | `test/` (se mide aparte del compilador) |

## Qué queda fuera, y por qué

- **El target web** (`web/`, el playground). Es TypeScript/WebAssembly y tiene
  sus propias normas, que no son las de este documento: las guías de estilo de
  TypeScript y su verificación estricta de tipos, la especificación de
  WebAssembly y, para la interfaz, las pautas de accesibilidad web (WCAG).
  Se revisará con ellas cuando el target se estabilice.
- **El código en suriaX** (`lib/`, `src/`). No hay norma externa para un
  lenguaje propio: su "norma" es el propio compilador, que lo analiza en cada
  compilación y en la suite (categoría `bootstrap`).
- **Lo generado** (`build*/`, los stubs de protobuf en `V0/src/HIR/gen/`, los
  `.phir`): no lo escribe una persona.

## ¿Existe una norma ISO/IEC para compiladores?

No existe una norma ISO/IEC que diga cómo tiene que comportarse **cualquier**
compilador. Lo que existe está atado a un lenguaje concreto:

- las normas de cada lenguaje definen qué es una *implementación conforme* de
  ese lenguaje (ISO/IEC 9899 para C, ISO/IEC 14882 para C++);
- algunas añaden cómo evaluar esa conformidad (ISO/IEC 18009, para los
  procesadores de Ada).

suriaX no es un lenguaje normalizado, así que ninguna de ellas aplica. Lo que
sí aplica son las normas **generales de ingeniería de software**. Evalúan el
producto, el proceso o las pruebas sin importar qué hace el programa:

| Norma | Qué evalúa | Cómo se usa aquí |
|---|---|---|
| [ISO/IEC 25010](iso_iec_25010.md) | la calidad del **producto** | marco principal; porcentaje medido |
| [ISO/IEC/IEEE 12207](iso_iec_12207.md) | los **procesos** del ciclo de vida | referencia adaptada; autoevaluación con evidencias |
| [ISO/IEC/IEEE 29119](iso_iec_ieee_29119.md) | las **pruebas** de software | referencia de la suite; autoevaluación con evidencias |

Y, por debajo, los lineamientos de cada lenguaje de implementación:
[Python](python.md) (PEP 8, PEP 20, PEP 257) y [C++](cpp.md) (C++ Core
Guidelines, más análisis estático y sanitizadores).

Una norma que suriaX sí toca de lado es ISO/IEC 14977 (la notación EBNF), en
la que está escrita su gramática. La gramática está desactualizada respecto
del parser (ver [iso_iec_12207.md](iso_iec_12207.md), proceso 6.4.3); la
fuente de verdad es el parser.
