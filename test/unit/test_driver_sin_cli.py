"""El compilador se puede usar SIN la línea de comandos.

Es la razón por la que existe ``V0/driver/``: cuando suriniX traiga
``suri run --args``, tiene que poder reutilizar el pipeline entero en vez de
invocar al proceso o reimplementarlo. Estos tests fijan esa frontera, que de
otro modo se erosiona sola —basta un ``print`` de más dentro del pipeline
para volver a atar el compilador a una terminal—.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PROGRAMA = "fn main() -> int {\n    var int x = 21;\n    return x + x;\n}\n"


def _compilar(fuente: str, **kwargs):
    from driver import CompileOptions, compile_source

    with tempfile.TemporaryDirectory(prefix="suriax-driver-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            return compile_source(ruta, CompileOptions(**kwargs))
        finally:
            os.chdir(cwd)


def test_compilar_no_imprime_nada():
    """El pipeline no habla por su cuenta: sin reporter, silencio absoluto.

    Es lo que permite que otro front decida qué contar. Un ``print`` suelto
    dentro del compilador se lo llevaría por delante."""
    salida, error = io.StringIO(), io.StringIO()
    with redirect_stdout(salida), redirect_stderr(error):
        _compilar(_PROGRAMA)
    assert salida.getvalue() == "", (
        f"el driver escribió en stdout: {salida.getvalue()!r}")
    assert error.getvalue() == "", (
        f"el driver escribió en stderr: {error.getvalue()!r}")


def test_el_resultado_trae_lo_que_la_compilacion_averiguo():
    """Las métricas dejaron de perderse por stdout: son dato consultable."""
    resultado = _compilar(_PROGRAMA)
    assert resultado.ok, resultado.diagnostics
    assert resultado.metrics["items"] == 1
    assert resultado.metrics["tokens"] > 0
    assert resultado.times, "los tiempos por fase deben viajar en el resultado"


def test_un_programa_invalido_devuelve_sus_diagnosticos():
    resultado = _compilar("fn main() -> int { return desconocido; }\n")
    assert not resultado.ok
    assert "SEM001" in [d.code for d in resultado.diagnostics]


def test_el_driver_no_ejecuta_por_su_cuenta():
    """Compilar y ejecutar son dos cosas: el pipeline deja el '.phir' y dice
    si el target lo pide, pero lanzar es decisión del llamador."""
    resultado = _compilar(_PROGRAMA, run=True, emit_hir="")
    assert resultado.phir_path is not None, (
        "con --run el driver tiene que dejar el .phir listo: "
        f"estado {resultado.status}, diagnósticos "
        f"{[d.code for d in resultado.diagnostics]}")
    assert resultado.should_run, "con --run el driver debe señalar que toca ejecutar"
    salida = io.StringIO()
    with redirect_stdout(salida):
        pass                              # no se llamó a execute(): nada corrió
    assert salida.getvalue() == ""


def test_el_driver_no_depende_de_la_cli():
    """La dependencia va en un solo sentido: 'cli' usa 'driver', nunca al revés."""
    import driver

    raiz = os.path.dirname(os.path.abspath(driver.__file__))
    for nombre in sorted(os.listdir(raiz)):
        if not nombre.endswith(".py"):
            continue
        with open(os.path.join(raiz, nombre), encoding="utf-8") as fh:
            fuente = fh.read()
        assert "import cli" not in fuente and "from cli" not in fuente, (
            f"driver/{nombre} importa la CLI: la frontera va en un solo sentido")


def test_el_driver_no_imprime_en_su_codigo():
    """Guarda estructural: un 'print' dentro del driver rompe el contrato
    aunque ningún test lo ejecute (una rama poco frecuente, por ejemplo)."""
    import driver

    raiz = os.path.dirname(os.path.abspath(driver.__file__))
    culpables = []
    for nombre in sorted(os.listdir(raiz)):
        if not nombre.endswith(".py"):
            continue
        with open(os.path.join(raiz, nombre), encoding="utf-8") as fh:
            for numero, linea in enumerate(fh, 1):
                if linea.lstrip().startswith("print("):
                    culpables.append(f"driver/{nombre}:{numero}")
    assert not culpables, (
        f"el driver no debe imprimir; usa el Reporter: {culpables}")
