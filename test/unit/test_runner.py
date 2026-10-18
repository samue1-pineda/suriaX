"""El runner de la suite (``test/main.py``) no puede mentir sobre lo que corrió.

Lo que se protege:

- una prueba OMITIDA no cuenta como pasada (antes una prueba se saltaba con
  ``return`` y el resumen la sumaba al verde);
- un fallo dice dónde (archivo:línea de la prueba), qué (la aserción) y por
  qué (los valores, si la aserción no trae mensaje);
- un módulo que no se puede importar es un fallo reportado, no un runner
  caído que oculta el resultado de todos los demás;
- el resumen JSON (el que convierte la CI en medalla) separa las tres cosas.

Cada caso escribe un módulo de prueba FALSO en un temporal y se lo da al
runner real.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

_TEST_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TEST_DIR not in sys.path:
    sys.path.insert(0, _TEST_DIR)


def _runner():
    """``test/main.py`` cargado como módulo (no se ejecuta su ``__main__``)."""
    spec = importlib.util.spec_from_file_location(
        "runner_de_suriax", os.path.join(_TEST_DIR, "main.py"))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _correr(fuente: str):
    """Corre un módulo de prueba falso -> (pasadas, fallidas, omitidas,
    fallos, omisiones)."""
    runner = _runner()
    omitida = runner._preparar_ruta()
    with tempfile.TemporaryDirectory(prefix="suriax-runner-") as tmp:
        ruta = os.path.join(tmp, "test_falso.py")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        fallos, omisiones = [], []
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            p, f, s = runner._run_module(ruta, "unit", omitida, fallos, omisiones)
    return p, f, s, fallos, omisiones


def test_una_omitida_no_cuenta_como_pasada():
    p, f, s, _fallos, omisiones = _correr(
        "from helpers import omitir\n"
        "def test_a():\n    omitir('falta node')\n"
        "def test_b():\n    pass\n")
    assert (p, f, s) == (1, 0, 1), (p, f, s)
    assert omisiones == [{"category": "unit", "module": "test_falso",
                          "test": "test_a", "reason": "falta node"}], omisiones


def test_un_fallo_dice_donde_que_y_por_que():
    _p, f, _s, fallos, _o = _correr(
        "def test_a():\n"
        "    err = 'el parametro sobra'\n"
        "    assert 'dos parametros' in err\n")
    assert f == 1
    fallo = fallos[0]
    assert fallo["test"] == "test_a"
    assert fallo["line"] == 3, fallo["line"]
    assert fallo["file"].endswith("test_falso.py"), fallo["file"]
    # qué se comprobaba: la línea de la aserción, no un 'AssertionError' mudo
    assert "assert 'dos parametros' in err" in fallo["error"], fallo["error"]
    # por qué: el valor con el que falló
    assert any("err = 'el parametro sobra'" in l for l in fallo["locals"]), fallo["locals"]
    # y la traza empieza en la prueba, no en el runner
    assert "main.py" not in fallo["traceback"].split("\n")[1], fallo["traceback"]


def test_una_excepcion_cualquiera_tambien_es_un_fallo():
    _p, f, _s, fallos, _o = _correr("def test_a():\n    {}['x']\n")
    assert f == 1
    assert fallos[0]["error"].startswith("KeyError"), fallos[0]["error"]


def test_una_prueba_que_termina_el_proceso_es_un_fallo_y_no_corta_la_corrida():
    """Una prueba que llama a algo que hace ``SystemExit`` (el ``main`` de
    una herramienta) mataba el runner: la corrida terminaba sin resumen y
    las categorías siguientes no corrían. Ahora es un fallo más, y las
    pruebas de después corren. Lo mismo al importar el módulo."""
    p, f, s, fallos, _o = _correr(
        "def test_a():\n    raise SystemExit(3)\n"
        "def test_b():\n    pass\n")
    assert (p, f, s) == (1, 1, 0), (p, f, s)
    assert fallos[0]["test"] == "test_a"
    assert fallos[0]["error"].startswith("SystemExit"), fallos[0]["error"]

    p, f, s, fallos, _o = _correr("raise SystemExit(1)\ndef test_a():\n    pass\n")
    assert (p, f, s) == (0, 1, 0), (p, f, s)
    assert fallos[0]["test"] == "<importación del módulo>"


def test_un_modulo_que_no_importa_es_un_fallo_reportado():
    """Antes tumbaba el runner entero y se perdía el resultado del resto."""
    p, f, s, fallos, _o = _correr("def test_a(:\n    pass\n")
    assert (p, f, s) == (0, 1, 0), (p, f, s)
    assert fallos[0]["test"] == "<importación del módulo>"
    assert fallos[0]["error"].startswith("SyntaxError"), fallos[0]["error"]
    assert fallos[0]["file"].endswith("test_falso.py"), fallos[0]["file"]
    assert fallos[0]["line"] == 1, fallos[0]["line"]


def test_el_json_separa_pasadas_fallidas_y_omitidas():
    runner = _runner()
    with tempfile.TemporaryDirectory(prefix="suriax-runner-") as tmp:
        destino = os.path.join(tmp, "resumen.json")
        runner._write_summary(
            destino, 5, 1, 2, 3, ["unit"],
            [{"category": "unit", "module": "m", "test": "t", "file": "f.py",
              "line": 1, "error": "E", "traceback": "T", "locals": ["x = 1"]}],
            [{"category": "unit", "module": "m", "test": "u", "reason": "r"}])
        with open(destino, encoding="utf-8") as fh:
            datos = json.load(fh)
    assert (datos["passed"], datos["failed"], datos["skipped"]) == (5, 1, 2)
    assert datos["total"] == 8, "el total incluye las omitidas: no se esconden"
    assert datos["skips"][0]["reason"] == "r"
    assert "locals" not in datos["failures"][0], "los valores locales son para la consola"


def test_una_categoria_desconocida_es_un_error():
    """Antes se avisaba y se seguía: 'python test/main.py unti' corría cero
    pruebas y salía con 0."""
    runner = _runner()
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()) as err, \
            contextlib.redirect_stdout(io.StringIO()):
        codigo = runner.run_tests(["unti"])
    assert codigo == 2, codigo
    assert "unti" in err.getvalue()
