# Calidad de suriaX: normas, lineamientos y su cumplimiento

Esta carpeta responde tres preguntas sobre el compilador:

1. **¿Qué normas y lineamientos sigue, y por qué esos?** → [`normas/`](normas/)
2. **¿Cuánto los cumple?** → [`cumplimiento/`](cumplimiento/README.md) (porcentajes)
3. **¿Cómo se mide?** → [`tools/`](tools/) (las automatizaciones)

El target web queda fuera por ahora: tiene sus propias normas
([`normas/alcance.md`](normas/alcance.md)).

## Normas y lineamientos

| Documento | Qué |
|---|---|
| [normas/alcance.md](normas/alcance.md) | qué se revisa, qué no y por qué; por qué no hay una norma ISO de "compiladores" |
| [normas/iso_iec_25010.md](normas/iso_iec_25010.md) | **ISO/IEC 25010**: el modelo de calidad del producto (marco principal, medido) |
| [normas/iso_iec_12207.md](normas/iso_iec_12207.md) | **ISO/IEC/IEEE 12207**: los procesos del ciclo de vida (referencia adaptada, autoevaluada) |
| [normas/iso_iec_ieee_29119.md](normas/iso_iec_ieee_29119.md) | **ISO/IEC/IEEE 29119**: las pruebas de software (referencia de la suite, autoevaluada) |
| [normas/python.md](normas/python.md) | **PEP 8, PEP 20, PEP 257**, con flake8, pylint, black y pydocstyle |
| [normas/cpp.md](normas/cpp.md) | **C++ Core Guidelines**, con clang-tidy, cppcheck y los sanitizadores |

## Cumplimiento

[`cumplimiento/`](cumplimiento/README.md) tiene el porcentaje de cada norma.
Esos documentos **se generan**, no se escriben a mano:

- "medido" sale de una herramienta;
- "autoevaluado" es un juicio con sus evidencias (12207 y 29119 son normas de
  proceso, y no hay herramienta que las mida);
- lo que no se midió dice NO MEDIDO y no cuenta en ningún promedio.

## Cómo se mide

```console
pip install -r docs/quality/requirements.txt       # una vez
python docs/quality/tools/quality.py all            # todo: minutos a horas
python docs/quality/tools/quality.py python cpp     # solo lo estático (minutos)
python docs/quality/tools/quality.py report         # regenerar los documentos
```

| Medición | Qué corre | Tiempo aproximado |
|---|---|---|
| `python` | flake8, black `--check`, pylint, pydocstyle y el conteo de docstrings | minutos |
| `cpp` | cppcheck y clang-tidy (necesita un build con `compile_commands.json`) | 1–2 min |
| `portability` | busca dependencias del sistema operativo en el código Python | segundos |
| `suite` | la suite completa (`test/main.py --todo`) con resumen JSON | como la suite |
| `sanitizers` | construye la VM con ASan y con UBSan y corre `backend` y `bootstrap` con cada una | largo |
| `coverage` | la suite completa bajo coverage.py (con subprocesos) | varias veces la suite |

Cada medición deja su JSON crudo en `reports/`. Esa carpeta no se versiona:
se regenera. Los documentos de `cumplimiento/` se rehacen con todo lo medido.

## Relación con la suite de pruebas

Esto **no** es parte de `test/main.py` ni corre con él:

- la **suite** se corre en cada cambio y responde "¿el compilador hace lo que
  debe?";
- la **calidad** se mide en los lotes grandes, los que tocan varias fases del
  compilador a la vez, y responde "¿cómo está escrito y cuánto cumple las
  normas?".

La medición `suite` solo *lee* el resultado de la suite como un indicador más
(ISO/IEC 25010, corrección funcional); no la modifica.

La configuración de las herramientas vive en la raíz, donde cada herramienta
la busca: `.flake8`, `.clang-tidy` y `pyproject.toml`.
