"""Errores INTERNOS del compilador (ICE000): un fallo del compilador, no del programa.

Lo que se protege aquí:

- un fallo interno sale con su PROPIO código de salida (6), no con el 1 de
  "tu programa tiene errores";
- el informe es el de Python: la traza de la excepción original (dónde y por
  qué dentro del compilador) más la fase y el archivo que se procesaba;
- un error DEL PROGRAMA que antes reventaba como traceback (un fuente que no
  es UTF-8) es un diagnóstico normal, no un ICE.

Los fallos se provocan sustituyendo UNA función del compilador por otra que
lanza: es la forma de tener un "bug" reproducible sin romper el código real.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from error_handler.InternalCompilerError import InternalCompilerError  # noqa: E402

_PROGRAMA = "fn __write__(str s) -> void;\nfn main() -> int { return 0; };\n"


def _lanza(*_args, **_kwargs):
    raise KeyError("simbolo_que_no_esta")


@contextlib.contextmanager
def _sustituido(modulo, nombre, nuevo):
    """Sustituye ``modulo.nombre`` durante el bloque, y lo restaura siempre."""
    original = getattr(modulo, nombre)
    setattr(modulo, nombre, nuevo)
    try:
        yield
    finally:
        setattr(modulo, nombre, original)


def _fuente_temporal(tmp: str, contenido: bytes, nombre: str = "prog.srcx") -> str:
    ruta = os.path.join(tmp, nombre)
    with open(ruta, "wb") as fh:
        fh.write(contenido)
    return ruta


# --------------------------------------------------------------------------- #
# la clase
# --------------------------------------------------------------------------- #

def _ice_de_prueba() -> InternalCompilerError:
    try:
        _lanza()
    except KeyError as exc:
        return InternalCompilerError.desde(exc, phase="semantica", file="prog.srcx")
    raise AssertionError("_lanza no lanzó")


def test_un_ice_tiene_codigo_severidad_y_fase_propios():
    ice = _ice_de_prueba()
    assert ice.code == "ICE000"
    assert ice.severity == "panic"
    assert ice.phase == "semantica"
    assert ice.file == "prog.srcx"
    assert isinstance(ice.cause, KeyError)
    assert ice.__cause__ is ice.cause, "la excepción original tiene que ir encadenada"


def test_un_ice_no_inventa_una_posicion_en_el_fuente():
    """Un ICE no ocurre en una línea del programa: darle 'línea 1, columna 1'
    señalaría una posición falsa en el código de quien compila."""
    ice = _ice_de_prueba()
    assert ice.line is None and ice.column is None, (ice.line, ice.column)
    assert ice.loc is None


def test_el_mensaje_nombra_la_excepcion_y_el_sitio_del_compilador():
    """Es lo único que ve un editor (no muestra trazas): tiene que bastar para
    saber qué falló y dónde, sin reproducirlo."""
    ice = _ice_de_prueba()
    assert "KeyError" in ice.message, ice.message
    assert "simbolo_que_no_esta" in ice.message, ice.message
    assert "test_errores_internos.py" in ice.message, ice.message
    assert "_lanza()" in ice.message, ice.message


def test_el_informe_es_el_de_python_mas_la_fase():
    informe = _ice_de_prueba().render()
    assert informe.startswith("Traceback (most recent call last):"), informe
    assert "KeyError: 'simbolo_que_no_esta'" in informe, informe
    assert "ICE000: error interno del compilador en la fase 'semantica'" in informe
    assert "procesando: prog.srcx" in informe
    assert "no de tu programa" in informe
    # el "qué" va DESPUÉS de la traza, como la última línea de Python
    assert informe.index("Traceback") < informe.index("ICE000")


def test_el_catalogo_del_lenguaje_publica_ICE000():
    """``--emit-lang-info`` enumera la taxonomía de errores para el LSP."""
    from include.lang_info import build_language_info
    codigos = {e["code"] for e in build_language_info()["errors"]}
    assert "ICE000" in codigos, sorted(codigos)


# --------------------------------------------------------------------------- #
# el driver
# --------------------------------------------------------------------------- #

def test_el_driver_convierte_un_fallo_inesperado_en_ICE_con_su_fase():
    from driver import CompileOptions, compile_source
    from src.frontend.parser import typed_ast

    with tempfile.TemporaryDirectory(prefix="suriax-ice-") as tmp:
        ruta = _fuente_temporal(tmp, _PROGRAMA.encode())
        with _sustituido(typed_ast, "resolve_types", _lanza):
            try:
                compile_source(ruta, CompileOptions())
            except InternalCompilerError as ice:
                assert ice.phase == "ast-tipado", ice.phase
                assert ice.file == ruta
                assert isinstance(ice.__cause__, KeyError)
            else:
                raise AssertionError("el fallo interno no se reportó como ICE")


def test_execute_convierte_un_fallo_del_interprete_en_ICE():
    from driver import CompileOptions, compile_source, execute
    from runtime.interpreter import interpreter

    with tempfile.TemporaryDirectory(prefix="suriax-ice-") as tmp:
        ruta = _fuente_temporal(tmp, _PROGRAMA.encode())
        # el motor del INTERPRETE: el que se esta probando (el defecto, con la
        # VM construida, es la VM)
        resultado = compile_source(ruta, CompileOptions(run="interpreter"))
        assert resultado.should_run, [d.code for d in resultado.diagnostics]
        with _sustituido(interpreter, "run", _lanza):
            try:
                execute(resultado)
            except InternalCompilerError as ice:
                assert ice.phase == "interprete", ice.phase
            else:
                raise AssertionError("el fallo del intérprete no se reportó como ICE")


# --------------------------------------------------------------------------- #
# la CLI
# --------------------------------------------------------------------------- #

def test_la_cli_muestra_el_ICE_y_sale_con_6():
    from cli import main
    from driver import EXIT_INTERNAL_ERROR
    from src.frontend.parser import typed_ast

    assert EXIT_INTERNAL_ERROR == 6
    with tempfile.TemporaryDirectory(prefix="suriax-ice-") as tmp:
        ruta = _fuente_temporal(tmp, _PROGRAMA.encode())
        err, out = io.StringIO(), io.StringIO()
        with _sustituido(typed_ast, "resolve_types", _lanza), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            codigo = main(["V0/main.py", ruta])
    assert codigo == 6, (codigo, err.getvalue())
    assert "Traceback (most recent call last):" in err.getvalue(), err.getvalue()
    assert "ICE000: error interno del compilador en la fase 'ast-tipado'" in err.getvalue()


def test_emit_stage_ante_un_fallo_interno_no_devuelve_exito():
    """Antes devolvía 0 con 'no se pudo volcar la fase': un fallo del
    compilador que el visualizador leía como éxito."""
    from driver import inspect as driver_inspect
    from src.frontend.parser import parser as modulo_parser

    with tempfile.TemporaryDirectory(prefix="suriax-ice-") as tmp:
        ruta = _fuente_temporal(tmp, _PROGRAMA.encode())
        with _sustituido(modulo_parser.Parser, "run_stage", _lanza):
            codigo, mensaje = driver_inspect.emit_stage(ruta, "ast", from_stdin=False)
    assert codigo == 6, (codigo, mensaje)
    assert "ICE000" in mensaje and "KeyError" in mensaje, mensaje


# --------------------------------------------------------------------------- #
# lo que NO es un ICE
# --------------------------------------------------------------------------- #

def test_un_fuente_que_no_es_utf8_es_LEX008_y_no_un_traceback():
    """Un error del PROGRAMA: antes tumbaba la CLI con un traceback crudo."""
    with tempfile.TemporaryDirectory(prefix="suriax-ice-") as tmp:
        ruta = _fuente_temporal(tmp, b"fn main() -> int { return 0; };\n\xff\xfe\n")
        proc = subprocess.run([sys.executable, os.path.join(_V0, "main.py"), ruta],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=tmp, timeout=120)
    salida = proc.stdout + proc.stderr
    assert proc.returncode == 1, (proc.returncode, salida)
    assert "LEX008" in salida, salida
    assert "Traceback" not in salida, salida
    assert "ICE000" not in salida, salida
