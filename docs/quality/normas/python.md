# Python: PEP 8, PEP 20 y PEP 257

El frontend, el intérprete, el driver y las herramientas están escritos en
Python. Estos son los lineamientos contra los que se mide ese código, y las
herramientas que lo miden.

## Lineamientos

| PEP | Qué es | Por qué aplica |
|---|---|---|
| **PEP 8**, *Style Guide for Python Code* | la guía de estilo de la biblioteca estándar: nombres, espacios, largo de línea, imports, comparaciones | es la referencia común de Python; un código que la sigue lo lee cualquiera que sepa Python, y esto importa en un compilador **educativo** |
| **PEP 20**, *The Zen of Python* | 19 aforismos de diseño ("Simple is better than complex", "Errors should never pass silently"...) | son los principios del proyecto: el compilador nunca silencia un error (regla del proyecto) y cada fase se puede leer por separado |
| **PEP 257**, *Docstring Conventions* | qué se documenta (módulos, clases, funciones públicas) y cómo (línea de resumen, comillas triples) | la documentación del compilador ES parte del producto: se lee para entender cada fase |

## Cómo se mide cada uno

**PEP 8.** flake8 corre pycodestyle (códigos `E` y `W`). La medida es el % de
archivos sin ninguna violación; se informan también las violaciones por cada
1000 líneas y las más frecuentes.

**PEP 257.**
- *Qué se documenta:* un análisis propio del AST cuenta las definiciones
  públicas (el módulo, sus clases y funciones, y los métodos de sus clases
  públicas) y cuántas tienen docstring.
- *Cómo se escribe:* pydocstyle, con `convention = "pep257"`. Sus códigos
  `D2xx`-`D4xx` son violaciones de forma; los `D1xx` (docstring que falta) ya
  los cuenta el análisis anterior.

**PEP 20.** No se puede verificar entero: "Beautiful is better than ugly" no
tiene medida. Se miden los aforismos que sí la tienen:

| Aforismo | Medida |
|---|---|
| *Simple is better than complex* | % de funciones con complejidad ciclomática ≤ 15 (mccabe, `C901`) |
| *Flat is better than nested* | bloques demasiado anidados (pylint `too-many-nested-blocks`) |
| *Errors should never pass silently* | % de `except` que no se tragan el error (cuerpo que no es solo `pass`), más `bare-except` y `broad-exception-caught` de pylint |
| *Explicit is better than implicit* | importaciones con `*` (pyflakes `F403`/`F405`) |
| *There should be one obvious way to do it* | bloques de código duplicado (pylint `duplicate-code`) |

**pylint** da una nota global sobre 10 que mezcla PEP 8, errores probables y
diseño. Se informa multiplicada por 10, con sus mensajes por categoría.

**black** es un formateador: **solo se mide** (`black --check`) y **no entra
en el promedio**. No es una norma, sino uno de los muchos formatos que PEP 8
admite, más estricto que PEP 8. Aplicarlo produciría un diff enorme que
taparía los cambios reales; se decidió medirlo y no reformatear.

## Configuración

- `.flake8`: largo 99, complejidad 15, `E203` ignorado (contradice a black).
- `pyproject.toml`: `[tool.black]`, `[tool.pylint]`, `[tool.pydocstyle]` y
  `[tool.coverage]`.
- El largo de línea es **99** en las tres herramientas. PEP 8 lo permite:
  "hasta 99 caracteres si el equipo lo acuerda". **Desviación documentada:**
  PEP 8 pide 72 caracteres en comentarios y docstrings; aquí rige el mismo 99.
  Con 79, el 3.6 % de las líneas del proyecto no cumpliría; con 99, el 0.2 %.

## Herramientas

| Herramienta | Qué hace | Nota |
|---|---|---|
| flake8 (pycodestyle + pyflakes + mccabe) | PEP 8, errores lógicos (nombres no definidos, imports sin usar), complejidad | |
| pylint | análisis amplio: convenciones, errores, diseño, duplicación | |
| black | formato canónico (solo `--check`) | |
| pydocstyle | la forma de los docstrings según PEP 257 | el proyecto upstream está archivado (su sucesor son las reglas `D` de ruff); sigue funcionando y es la implementación de referencia de PEP 257 |
| coverage.py | qué líneas y ramas del compilador ejecuta la suite | mide también los subprocesos (`patch = ["subprocess"]`), porque la suite corre casi todo por la CLI |

Se instalan con `pip install -r docs/quality/requirements.txt`; no son
dependencias del compilador.

El resultado vigente está en [../cumplimiento/python.md](../cumplimiento/python.md).
