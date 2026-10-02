# Cumplimiento: Python (PEP 8, PEP 20, PEP 257)

> Documento GENERADO por `docs/quality/tools/quality.py` a partir de `docs/quality/reports/`. No se edita a mano: se vuelve a medir.

Herramientas: `flake8 7.4.1 (mccabe: 0.7.0, pycodestyle: 2.15.0, pyflakes: 4.0.0)`; `black, 26.5.1 (compiled: yes)`; `pylint 4.1.1`; `pydocstyle 6.3.0`

Configuración: `.flake8` y `pyproject.toml` (largo de línea 99 en las tres herramientas). Qué mide cada fila y por qué: `docs/quality/normas/python.md`.

## Compilador: `V0`, `runtime`, `htims`, `config`, `suri`, `dev`, `main.py`, `version.py`

| Norma | Indicador | Valor | Cumplimiento |
|---|---|---|---|
| PEP 8 | archivos sin violaciones de pycodestyle (E/W) | 111 de 141 | 78.7 % |
| PEP 8 | violaciones por cada 1000 líneas | 4.36 | — |
| (informativo) | archivos con el formato de black (más estricto que PEP 8) | 35 de 141 | 24.8 % (fuera del promedio) |
| PEP 8 / PEP 20 | nota de pylint (sobre 10) | 9.36 | 93.6 % |
| PEP 257 | definiciones públicas con docstring | 606 de 824 | 73.5 % |
| PEP 257 | violaciones de forma por docstring (pydocstyle, D2xx-D4xx) | 1.11 | — |
| PEP 20 | funciones con complejidad ciclomática ≤ 15 | 1199 funciones, 13 por encima | 98.9 % |
| PEP 20 | `except` que no se tragan el error | 0 silenciosos de 146 | 100.0 % |
| PEP 20 | importaciones con `*` | 0 | — |
| PEP 20 | bloques de código duplicado (pylint) | 13 | — |
| — | errores lógicos de pyflakes (F) | 16 | — |

**Cumplimiento medio de los PEP:** 88.9 % (black se reporta aparte: no es una norma)

Violaciones de PEP 8 más frecuentes:

| Código | Cantidad |
|---|---|
| E501 | 34 |
| E265 | 20 |
| E127 | 11 |
| E261 | 10 |
| W291 | 9 |
| E302 | 8 |
| E262 | 8 |
| E303 | 7 |
| W293 | 3 |
| E305 | 3 |
| W391 | 2 |
| E272 | 2 |

Mensajes de pylint por categoría:

| Categoría | Cantidad |
|---|---|
| convention | 504 |
| error | 4 |
| refactor | 189 |
| warning | 109 |

Mensajes de pylint más frecuentes:

| Mensaje | Cantidad |
|---|---|
| import-outside-toplevel | 141 |
| missing-function-docstring | 125 |
| invalid-name | 72 |
| missing-class-docstring | 53 |
| line-too-long | 33 |
| unused-argument | 31 |
| too-many-locals | 28 |
| protected-access | 26 |
| too-many-return-statements | 26 |
| too-many-arguments | 22 |
| too-few-public-methods | 22 |
| ungrouped-imports | 21 |

Violaciones de forma de PEP 257 más frecuentes:

| Código | Cantidad |
|---|---|
| D400 | 227 |
| D205 | 191 |
| D209 | 171 |
| D204 | 63 |
| D401 | 7 |
| D301 | 6 |
| D403 | 3 |
| D402 | 2 |
| D208 | 1 |
| D210 | 1 |

Hallazgos de pyflakes (revisar uno por uno):

- `V0/driver/artifacts.py:21` F401 'os' imported but unused
- `V0/driver/artifacts.py:22` F401 'sys' imported but unused
- `V0/driver/artifacts.py:23` F401 'typing.Optional' imported but unused
- `V0/driver/artifacts.py:265` F401 'src.HIR.pretty.format_type' imported but unused
- `V0/include/lang_info.py:175` F401 '.t_types.TokenType as _TT' imported but unused
- `V0/src/HIR/schema.py:33` F401 'typing.Tuple' imported but unused
- `V0/src/HIR/wire.py:32` F401 'typing.Iterator' imported but unused
- `V0/src/HIR/wire.py:34` F401 '.schema as _schema' imported but unused
- `V0/src/HIR/wire.py:500` F841 local variable 'tipo_wire' is assigned to but never used
- `V0/src/frontend/parser/grammar/traits.py:33` F401 'ParseError' imported but unused
- `V0/src/frontend/semantic/extensions.py:34` F401 'include.ast_nodes as ast' imported but unused
- `config/compilerconfig.py:52` F401 '.dumps.hir_pretty_path' imported but unused
- `runtime/interpreter/interpreter.py:19` F401 'typing.Any' imported but unused
- `runtime/interpreter/interpreter.py:27` F401 '.values.TypeValue' imported but unused
- `runtime/interpreter/memory/block.py:19` F401 'typing.Any' imported but unused
- `runtime/interpreter/memory/pointer.py:24` F401 'typing.Optional' imported but unused

Errores de pylint (E/F; revisar uno por uno, pueden ser falsos positivos):

- `V0/driver/execute.py:77` E0601 used-before-assignment
- `V0/src/HIR/wire.py:108` E1101 no-member
- `V0/src/frontend/lexer/scanners/c_dir.py:151` E0606 possibly-used-before-assignment
- `dev/bench_hir.py:31` E0401 import-error

Funciones por encima del límite de complejidad:

- `V0/driver/pipeline.py:232 '_compilar' is too complex (34)`
- `V0/include/symbols_uml.py:139 'symbol_table_to_mermaid' is too complex (27)`
- `V0/src/HIR/emmit_IR.py:347 '_Emitter._emit_decl' is too complex (16)`
- `V0/src/HIR/pretty.py:168 '_Printer._expr_text' is too complex (17)`
- `V0/src/HIR/pretty.py:272 '_Printer.stmt' is too complex (21)`
- `V0/src/frontend/lexer/scanners/strings.py:122 '_scan_quoted' is too complex (19)`
- `V0/src/frontend/semantic/collect.py:548 'define_import' is too complex (18)`
- `V0/src/frontend/semantic/memory_check.py:155 '_PropiedadChecker.check_stmt' is too complex (24)`
- `htims/declarations.py:146 '_scan_decorator' is too complex (27)`
- `htims/manifest.py:87 'parse' is too complex (16)`
- `runtime/interpreter/evaluator.py:271 'Evaluator.call_function' is too complex (16)`
- `runtime/interpreter/evaluator.py:1059 'Evaluator._texto' is too complex (21)`
- `runtime/interpreter/evaluator.py:1253 'Evaluator._expr_binary' is too complex (26)`

## Suite de pruebas: `test`

| Norma | Indicador | Valor | Cumplimiento |
|---|---|---|---|
| PEP 8 | archivos sin violaciones de pycodestyle (E/W) | 44 de 69 | 63.8 % |
| PEP 8 | violaciones por cada 1000 líneas | 4.5 | — |
| (informativo) | archivos con el formato de black (más estricto que PEP 8) | 2 de 69 | 2.9 % (fuera del promedio) |
| PEP 8 / PEP 20 | nota de pylint (sobre 10) | 6.77 | 67.7 % |
| PEP 257 | definiciones públicas con docstring | 673 de 1219 | 55.2 % |
| PEP 257 | violaciones de forma por docstring (pydocstyle, D2xx-D4xx) | 0.04 | — |
| PEP 20 | funciones con complejidad ciclomática ≤ 15 | 1371 funciones, 1 por encima | 99.9 % |
| PEP 20 | `except` que no se tragan el error | 0 silenciosos de 25 | 100.0 % |
| PEP 20 | importaciones con `*` | 0 | — |
| PEP 20 | bloques de código duplicado (pylint) | 15 | — |
| — | errores lógicos de pyflakes (F) | 9 | — |

**Cumplimiento medio de los PEP:** 77.3 % (black se reporta aparte: no es una norma)

Violaciones de PEP 8 más frecuentes:

| Código | Cantidad |
|---|---|
| E501 | 62 |
| E741 | 12 |
| E127 | 5 |
| E303 | 2 |
| E305 | 1 |
| E302 | 1 |
| E306 | 1 |

Mensajes de pylint por categoría:

| Categoría | Cantidad |
|---|---|
| convention | 962 |
| error | 219 |
| refactor | 34 |
| warning | 136 |

Mensajes de pylint más frecuentes:

| Mensaje | Cantidad |
|---|---|
| missing-function-docstring | 546 |
| import-outside-toplevel | 241 |
| import-error | 179 |
| wrong-import-position | 77 |
| subprocess-run-check | 51 |
| line-too-long | 44 |
| no-name-in-module | 39 |
| invalid-name | 35 |
| unused-variable | 31 |
| protected-access | 18 |
| duplicate-code | 15 |
| redefined-outer-name | 9 |

Violaciones de forma de PEP 257 más frecuentes:

| Código | Cantidad |
|---|---|
| D205 | 8 |
| D209 | 8 |
| D400 | 8 |
| D204 | 1 |

Hallazgos de pyflakes (revisar uno por uno):

- `test/backend/test_backend_cpp.py:430` F841 local variable 'pb' is assigned to but never used
- `test/e2e/test_lote10.py:13` F401 'helpers.run_program' imported but unused
- `test/e2e/test_web_wasm.py:298` F541 f-string is missing placeholders
- `test/fuzz/test_stress.py:81` F541 f-string is missing placeholders
- `test/unit/test_diagnostics_channel.py:23` F401 'tempfile' imported but unused
- `test/unit/test_diagnostics_channel.py:249` F811 redefinition of unused 'tempfile' from line 23
- `test/unit/test_genericos.py:358` F811 redefinition of unused 'test_el_menor_que_sigue_siendo_una_comparacion' from line 255
- `test/unit/test_hir_reproducible.py:96` F401 'hashlib' imported but unused
- `test/unit/test_types.py:16` F401 'include.ast_nodes as ast' imported but unused

Errores de pylint (E/F; revisar uno por uno, pueden ser falsos positivos):

- `test/helpers.py:57` E0401 import-error
- `test/helpers.py:64` E0401 import-error
- `test/helpers.py:73` E0401 import-error
- `test/helpers.py:85` E0401 import-error
- `test/helpers.py:86` E0401 import-error
- `test/helpers.py:87` E0401 import-error
- `test/backend/test_backend_cpp.py:223` E0401 import-error
- `test/backend/test_backend_cpp.py:249` E0401 import-error
- `test/backend/test_backend_cpp.py:272` E0401 import-error
- `test/backend/test_backend_cpp.py:350` E0401 import-error
- `test/backend/test_backend_cpp.py:427` E0401 import-error
- `test/bootstrap/test_bootstrap_lexer.py:28` E0401 import-error
- `test/bootstrap/test_bootstrap_parser.py:36` E0611 no-name-in-module
- `test/bootstrap/test_bootstrap_parser.py:37` E0401 import-error
- `test/bootstrap/test_bootstrap_parser.py:38` E0401 import-error
- `test/e2e/test_ancho_fijo.py:95` E0401 import-error
- `test/e2e/test_extern_cpp.py:185` E0401 import-error
- `test/e2e/test_extern_cpp.py:199` E0401 import-error
- `test/e2e/test_extern_cpp.py:200` E0401 import-error
- `test/e2e/test_extern_cpp.py:302` E0401 import-error
- `test/e2e/test_extern_cpp.py:319` E0401 import-error
- `test/e2e/test_extern_cpp.py:330` E0401 import-error
- `test/e2e/test_native_memory.py:20` E0401 import-error
- `test/e2e/test_native_memory.py:41` E0401 import-error
- `test/e2e/test_native_memory.py:48` E0401 import-error
- `test/e2e/test_playground.py:51` E0401 import-error
- `test/e2e/test_playground.py:264` E0401 import-error
- `test/e2e/test_playground.py:305` E0401 import-error
- `test/e2e/test_playground.py:330` E0401 import-error
- `test/e2e/test_playground.py:354` E0401 import-error
- `test/e2e/test_playground.py:354` E0611 no-name-in-module
- `test/e2e/test_playground.py:355` E0401 import-error
- `test/e2e/test_playground.py:355` E0611 no-name-in-module
- `test/e2e/test_playground.py:371` E0401 import-error
- `test/e2e/test_playground.py:371` E0611 no-name-in-module
- `test/e2e/test_playground.py:433` E0401 import-error
- `test/e2e/test_playground.py:457` E0401 import-error
- `test/e2e/test_playground.py:475` E0401 import-error
- `test/e2e/test_playground.py:488` E0401 import-error
- `test/e2e/test_programas_de_fuego.py:192` E0401 import-error
- `test/e2e/test_programas_de_fuego.py:193` E0401 import-error
- `test/fuzz/test_pointer_stress.py:18` E0401 import-error
- `test/fuzz/test_pointer_stress.py:37` E0401 import-error
- `test/fuzz/test_pointer_stress.py:158` E0401 import-error
- `test/grammar/test_grammar_ast.py:23` E0611 no-name-in-module
- `test/grammar/test_modifiers.py:18` E0611 no-name-in-module
- `test/grammar/test_modifiers.py:92` E0401 import-error
- `test/grammar/test_modifiers.py:111` E0401 import-error
- `test/manual/lexer/run_lexer.py:38` E0401 import-error
- `test/manual/lexer/run_lexer.py:39` E0401 import-error
- `test/manual/lexer/run_lexer.py:40` E0401 import-error
- `test/snapshot/test_golden.py:80` E0401 import-error
- `test/snapshot/test_golden.py:80` E0611 no-name-in-module
- `test/snapshot/test_golden.py:87` E0401 import-error
- `test/snapshot/test_golden.py:87` E0611 no-name-in-module
- `test/snapshot/test_golden.py:88` E0401 import-error
- `test/snapshot/test_golden.py:100` E0401 import-error
- `test/snapshot/test_golden.py:114` E0401 import-error
- `test/snapshot/test_golden.py:123` E0401 import-error
- `test/unit/test_config_validacion.py:25` E0401 import-error
- `test/unit/test_config_validacion.py:56` E0401 import-error
- `test/unit/test_config_validacion.py:103` E0401 import-error
- `test/unit/test_config_validacion.py:113` E0401 import-error
- `test/unit/test_config_validacion.py:122` E0401 import-error
- `test/unit/test_config_validacion.py:123` E0401 import-error
- `test/unit/test_diagnostics_channel.py:183` E0401 import-error
- `test/unit/test_diagnostics_channel.py:183` E0611 no-name-in-module
- `test/unit/test_diagnostics_channel.py:232` E0401 import-error
- `test/unit/test_diagnostics_channel.py:254` E0401 import-error
- `test/unit/test_dispatch_completo.py:28` E0611 no-name-in-module
- `test/unit/test_dispatch_completo.py:37` E0401 import-error
- `test/unit/test_dispatch_completo.py:38` E0401 import-error
- `test/unit/test_dispatch_completo.py:39` E0401 import-error
- `test/unit/test_dispatch_completo.py:44` E0611 no-name-in-module
- `test/unit/test_dispatch_completo.py:54` E0611 no-name-in-module
- `test/unit/test_dispatch_completo.py:82` E0611 no-name-in-module
- `test/unit/test_dispatch_completo.py:98` E0611 no-name-in-module
- `test/unit/test_dispatch_completo.py:108` E0611 no-name-in-module
- `test/unit/test_docs_al_dia.py:37` E0401 import-error
- `test/unit/test_docs_al_dia.py:49` E0401 import-error
- `test/unit/test_docs_al_dia.py:63` E0401 import-error
- `test/unit/test_docs_al_dia.py:64` E0401 import-error
- `test/unit/test_docs_al_dia.py:120` E0401 import-error
- `test/unit/test_docs_al_dia.py:137` E0401 import-error
- `test/unit/test_docs_al_dia.py:162` E0401 import-error
- `test/unit/test_docs_al_dia.py:217` E0401 import-error
- `test/unit/test_driver_sin_cli.py:27` E0401 import-error
- `test/unit/test_driver_sin_cli.py:87` E0401 import-error
- `test/unit/test_driver_sin_cli.py:102` E0401 import-error
- `test/unit/test_errores_internos.py:31` E0401 import-error
- `test/unit/test_errores_internos.py:111` E0401 import-error
- `test/unit/test_errores_internos.py:111` E0611 no-name-in-module
- `test/unit/test_errores_internos.py:121` E0401 import-error
- `test/unit/test_errores_internos.py:122` E0401 import-error
- `test/unit/test_errores_internos.py:138` E0401 import-error
- `test/unit/test_errores_internos.py:139` E0401 import-error
- `test/unit/test_errores_internos.py:161` E0401 import-error
- `test/unit/test_errores_internos.py:162` E0401 import-error
- `test/unit/test_errores_internos.py:163` E0401 import-error
- `test/unit/test_errores_internos.py:180` E0401 import-error
- `test/unit/test_errores_internos.py:181` E0401 import-error
- `test/unit/test_extension_vocabulary.py:22` E0401 import-error
- `test/unit/test_extension_vocabulary.py:23` E0401 import-error
- `test/unit/test_extension_vocabulary.py:65` E0401 import-error
- `test/unit/test_extension_vocabulary.py:66` E0401 import-error
- `test/unit/test_extension_vocabulary.py:67` E0401 import-error
- `test/unit/test_extension_vocabulary.py:88` E0401 import-error
- `test/unit/test_extension_vocabulary.py:89` E0401 import-error
- `test/unit/test_extension_vocabulary.py:89` E0611 no-name-in-module
- `test/unit/test_extension_vocabulary.py:100` E0401 import-error
- `test/unit/test_extension_vocabulary.py:116` E0401 import-error
- `test/unit/test_extension_vocabulary.py:125` E0401 import-error
- `test/unit/test_extension_vocabulary.py:133` E0401 import-error
- `test/unit/test_extension_vocabulary.py:134` E0401 import-error
- `test/unit/test_extension_vocabulary.py:135` E0401 import-error
- `test/unit/test_extension_vocabulary.py:146` E0401 import-error
- `test/unit/test_extension_vocabulary.py:147` E0401 import-error
- `test/unit/test_extension_vocabulary.py:148` E0401 import-error
- `test/unit/test_extension_vocabulary.py:164` E0401 import-error
- `test/unit/test_extension_vocabulary.py:194` E0401 import-error
- `test/unit/test_extension_vocabulary.py:207` E0401 import-error
- `test/unit/test_extension_vocabulary.py:214` E0401 import-error
- `test/unit/test_frontera_tooling.py:155` E0401 import-error
- `test/unit/test_genericos.py:24` E0611 no-name-in-module
- `test/unit/test_genericos.py:39` E0611 no-name-in-module
- `test/unit/test_genericos.py:47` E0611 no-name-in-module
- `test/unit/test_genericos.py:138` E0401 import-error
- `test/unit/test_genericos.py:138` E0611 no-name-in-module
- `test/unit/test_genericos.py:149` E0401 import-error
- `test/unit/test_genericos.py:150` E0401 import-error
- `test/unit/test_genericos.py:151` E0401 import-error
- `test/unit/test_genericos.py:152` E0401 import-error
- `test/unit/test_genericos.py:205` E0401 import-error
- `test/unit/test_genericos.py:205` E0611 no-name-in-module
- `test/unit/test_genericos.py:206` E0401 import-error
- `test/unit/test_genericos.py:222` E0611 no-name-in-module
- `test/unit/test_genericos.py:275` E0401 import-error
- `test/unit/test_genericos.py:276` E0401 import-error
- `test/unit/test_genericos.py:276` E0611 no-name-in-module
- `test/unit/test_genericos.py:358` E0102 function-redefined
- `test/unit/test_hir_pretty.py:41` E0401 import-error
- `test/unit/test_hir_pretty.py:42` E0401 import-error
- `test/unit/test_hir_pretty.py:43` E0401 import-error
- `test/unit/test_hir_pretty.py:44` E0401 import-error
- `test/unit/test_hir_pretty.py:45` E0401 import-error
- `test/unit/test_hir_pretty.py:197` E0401 import-error
- `test/unit/test_hir_pretty.py:206` E0401 import-error
- `test/unit/test_hir_pretty.py:207` E0401 import-error
- `test/unit/test_hir_pretty.py:208` E0401 import-error
- `test/unit/test_hir_pretty.py:209` E0401 import-error
- `test/unit/test_hir_reproducible.py:54` E0401 import-error
- `test/unit/test_hir_reproducible.py:55` E0401 import-error
- `test/unit/test_hir_reproducible.py:56` E0401 import-error
- `test/unit/test_hir_reproducible.py:57` E0401 import-error
- `test/unit/test_hir_reproducible.py:81` E0401 import-error
- `test/unit/test_hir_reproducible.py:82` E0401 import-error
- `test/unit/test_hir_type_pool.py:47` E0401 import-error
- `test/unit/test_hir_type_pool.py:48` E0401 import-error
- `test/unit/test_hir_type_pool.py:49` E0401 import-error
- `test/unit/test_hir_type_pool.py:50` E0401 import-error
- `test/unit/test_hook_dispatch_key.py:25` E0401 import-error
- `test/unit/test_hook_dispatch_key.py:27` E0401 import-error
- `test/unit/test_htims_declarations.py:20` E0401 import-error
- `test/unit/test_htims_declarations.py:257` E0401 import-error
- `test/unit/test_htims_declarations.py:267` E0401 import-error
- `test/unit/test_htims_manifest.py:18` E0401 import-error
- `test/unit/test_htims_registry.py:17` E0401 import-error
- `test/unit/test_htims_utils.py:20` E0401 import-error
- `test/unit/test_htims_utils.py:21` E0401 import-error
- `test/unit/test_htims_utils.py:22` E0401 import-error
- `test/unit/test_lang_info.py:18` E0401 import-error
- `test/unit/test_lang_info.py:18` E0611 no-name-in-module
- `test/unit/test_lang_info.py:19` E0401 import-error
- `test/unit/test_lang_info.py:19` E0611 no-name-in-module
- `test/unit/test_lang_info.py:47` E0401 import-error
- `test/unit/test_lang_info.py:129` E0401 import-error
- `test/unit/test_lang_info.py:129` E0611 no-name-in-module
- `test/unit/test_lang_info.py:137` E0401 import-error
- `test/unit/test_lang_info.py:156` E0401 import-error
- `test/unit/test_lexer.py:15` E0401 import-error
- `test/unit/test_lexer.py:15` E0611 no-name-in-module
- `test/unit/test_lsp_index.py:67` E0401 import-error
- `test/unit/test_lsp_index.py:180` E0401 import-error
- `test/unit/test_parser.py:15` E0611 no-name-in-module
- `test/unit/test_pasadas_semanticas.py:34` E0401 import-error
- `test/unit/test_pasadas_semanticas.py:43` E0401 import-error
- `test/unit/test_propiedad_tipos.py:45` E0401 import-error
- `test/unit/test_propiedad_tipos.py:46` E0401 import-error
- `test/unit/test_propiedad_tipos.py:47` E0401 import-error
- `test/unit/test_propiedad_tipos.py:61` E0401 import-error
- `test/unit/test_propiedad_tipos.py:62` E0401 import-error
- `test/unit/test_propiedad_tipos.py:62` E0611 no-name-in-module
- `test/unit/test_propiedad_tipos.py:86` E0401 import-error
- `test/unit/test_propiedad_tipos.py:86` E0611 no-name-in-module
- `test/unit/test_propiedad_tipos.py:107` E0401 import-error
- `test/unit/test_propiedad_tipos.py:107` E0611 no-name-in-module
- `test/unit/test_propiedad_tipos.py:144` E0401 import-error
- `test/unit/test_propiedad_tipos.py:144` E0611 no-name-in-module
- `test/unit/test_propiedad_tipos.py:168` E0401 import-error
- `test/unit/test_propiedad_tipos.py:169` E0401 import-error
- `test/unit/test_propiedad_tipos.py:169` E0611 no-name-in-module
- `test/unit/test_propiedad_tipos.py:193` E0401 import-error
- `test/unit/test_propiedad_tipos.py:194` E0401 import-error
- `test/unit/test_propiedad_tipos.py:195` E0401 import-error
- `test/unit/test_propiedad_tipos.py:195` E0611 no-name-in-module
- `test/unit/test_suri_cli.py:64` E0401 import-error
- `test/unit/test_suri_cli.py:183` E0401 import-error
- `test/unit/test_symbols_uml.py:13` E0401 import-error
- `test/unit/test_symbols_uml.py:13` E0611 no-name-in-module
- `test/unit/test_types.py:16` E0611 no-name-in-module
- `test/unit/test_types.py:17` E0401 import-error
- `test/unit/test_types.py:17` E0611 no-name-in-module
- `test/unit/test_types.py:18` E0401 import-error
- `test/unit/test_types.py:19` E0401 import-error
- `test/unit/test_types.py:126` E0401 import-error
- `test/unit/test_types.py:126` E0611 no-name-in-module
- `test/unit/test_types.py:127` E0401 import-error
- `test/unit/test_web_backend.py:108` E0401 import-error
- `test/unit/test_web_backend.py:109` E0401 import-error

Funciones por encima del límite de complejidad:

- `test/unit/test_hir_type_pool.py:65 '_walk_type_ids' is too complex (22)`
