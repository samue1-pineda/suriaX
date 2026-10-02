# Cumplimiento: C++ (Core Guidelines, cppcheck, sanitizadores)

> Documento GENERADO por `docs/quality/tools/quality.py` a partir de `docs/quality/reports/`. No se edita a mano: se vuelve a medir.

## C++ Core Guidelines (clang-tidy)

Herramienta: `clang-tidy`, configuración `.clang-tidy`, compilación según `build-msvc/compile_commands.json` (8 unidades, 17805 líneas).

| Indicador | Valor | Cumplimiento |
|---|---|---|
| reglas de las Core Guidelines sin ningún hallazgo | 25 de 43 | 58.1 % |
| archivos sin hallazgos de las Core Guidelines | — | 31.2 % |
| hallazgos de las Core Guidelines | 1148 | — |
| hallazgos por cada 1000 líneas | 64.48 | — |
| otros grupos: `bugprone-*` | 192 | — |
| otros grupos: `performance-*` | 68 | — |
| otros grupos: `portability-*` | 8 | — |

No analizado por clang-tidy (no está en la base de compilación; lo cubre cppcheck): `runtime/logic_mem/cxx_entry.cpp`, `runtime/logic_mem/include/mem_core.hpp`

Reglas con hallazgos:

| Regla | Hallazgos |
|---|---|
| cppcoreguidelines-pro-bounds-avoid-unchecked-container-access | 347 |
| cppcoreguidelines-pro-type-union-access | 269 |
| cppcoreguidelines-avoid-magic-numbers | 229 |
| cppcoreguidelines-init-variables | 211 |
| cppcoreguidelines-avoid-const-or-ref-data-members | 25 |
| cppcoreguidelines-pro-bounds-pointer-arithmetic | 20 |
| cppcoreguidelines-pro-bounds-array-to-pointer-decay | 11 |
| cppcoreguidelines-use-enum-class | 9 |
| cppcoreguidelines-pro-type-reinterpret-cast | 8 |
| cppcoreguidelines-avoid-c-arrays | 5 |
| cppcoreguidelines-pro-type-vararg | 4 |
| cppcoreguidelines-narrowing-conversions | 3 |
| cppcoreguidelines-special-member-functions | 2 |
| cppcoreguidelines-avoid-do-while | 1 |
| cppcoreguidelines-missing-std-forward | 1 |
| cppcoreguidelines-no-malloc | 1 |
| cppcoreguidelines-owning-memory | 1 |
| cppcoreguidelines-prefer-member-initializer | 1 |

## cppcheck

Herramienta: `Cppcheck 2.22.0` (18 archivos, 18076 líneas).

| Indicador | Valor | Cumplimiento |
|---|---|---|
| archivos sin hallazgos | 10 de 18 | 55.6 % |
| hallazgos | 73 | — |
| hallazgos por cada 1000 líneas | 4.04 | — |
| severidad `style` | 71 | — |
| severidad `warning` | 2 | — |

Hallazgos por tipo:

| Id | Cantidad |
|---|---|
| useStlAlgorithm | 44 |
| shadowFunction | 12 |
| functionStatic | 8 |
| knownConditionTrueFalse | 4 |
| duplicateCondition | 2 |
| uninitMemberVarNoCtor | 2 |
| suspiciousFloatingPointCast | 1 |

Errores y avisos (revisar uno por uno):

- `backend/src/vm.cpp:2319` [uninitMemberVarNoCtor] Member variable 'AlSalir::destino' has no initializer.
- `runtime/logic_mem/include/mem_core.hpp:62` [uninitMemberVarNoCtor] Member variable 'Read::status' has no initializer.

## Sanitizadores (la suite de la VM instrumentada)

| Sanitizador | Pruebas limpias | Notas | Cumplimiento |
|---|---|---|---|
| AddressSanitizer | 115 de 115 (0 omitidas) | `build-asan/bin/suriax-hir.exe` | 100.0 % |
| UndefinedBehaviorSanitizer | 115 de 115 (0 omitidas) | clang no trae el runtime de UBSan para esta arquitectura: modo trampa (detiene el programa; no dice qué regla se rompió); trampa verificada: un desborde con signo detiene el programa | 100.0 % |

**Cumplimiento medio:** 69.0 %
