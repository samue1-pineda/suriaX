"""Utilidades compartidas por la suite (sin framework externo).

Un solo lugar sabe *cómo* invocar cada fase del compilador, así que cuando
cambie una firma se arregla aquí y no en cada test. Todas las funciones son
puras respecto al disco salvo :func:`compile_source`/:func:`run_source`, que
usan un directorio temporal propio y lo limpian.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --------------------------------------------------------------------------- #
# fases del frontend, en proceso (rápido: sin lanzar subprocesos)
# --------------------------------------------------------------------------- #

def lex(source: str, *, file: str = "<test>"):
    """``str`` -> ``(tokens, errores_lexicos)``."""
    from src.frontend.lexer.lexer import Lexer
    lexer = Lexer(source, file=file)
    return lexer.tokenize(), lexer.errors


def parse(source: str, *, file: str = "<test>"):
    """``str`` -> ``(Program, errores_sintaxis, errores_lexicos)``."""
    from src.frontend.parser.parser import Parser
    tokens, lex_errors = lex(source, file=file)
    parser = Parser(tokens)
    program = parser.parse()
    return program, parser.ctx.errors, lex_errors


def typed(source: str, *, file: str = "<test>"):
    """Parser + AST-tipado. Devuelve ``(Program, errores_sintaxis)``."""
    from src.frontend.parser.typed_ast import resolve_types
    program, parse_errors, _ = parse(source, file=file)
    resolve_types(program)
    return program, parse_errors


def analyze(source: str, *, file: str = "<test>", source_path: Optional[str] = None):
    """Pipeline completo del frontend.

    Devuelve ``(Program, SymbolTable, todos_los_errores)`` — léxicos,
    sintácticos y semánticos concatenados en ese orden.
    """
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze as semantic_analyze

    tokens, lex_errors = lex(source, file=file)
    parser = Parser(tokens)
    program = parser.parse()
    resolve_types(program)
    table, sem_errors = semantic_analyze(program, source_path=source_path)
    return program, table, [*lex_errors, *parser.ctx.errors, *sem_errors]


def error_codes(source: str, **kwargs) -> List[str]:
    """Códigos (``SEM001``...) que produce ``source``, en orden de aparición.

    El contrato de la suite negativa: se comprueba el CÓDIGO, nunca el texto
    del mensaje (los mensajes se reescriben; los códigos son estables)."""
    _, _, errors = analyze(source, **kwargs)
    return [e.code for e in errors]


def assert_ok(source: str, **kwargs) -> None:
    """El programa compila SIN ningún diagnóstico."""
    codes = error_codes(source, **kwargs)
    assert not codes, f"se esperaba compilación limpia, hubo: {codes}"


def assert_has_code(source: str, code: str, **kwargs) -> None:
    """El programa produce (al menos) el diagnóstico ``code``."""
    codes = error_codes(source, **kwargs)
    assert code in codes, f"se esperaba {code}; se obtuvo: {codes or '(ninguno)'}"


# --------------------------------------------------------------------------- #
# pipeline completo por CLI (e2e): compila y ejecuta un .srcx real
# --------------------------------------------------------------------------- #

def run_source(source: str, *, args: Optional[List[str]] = None,
               name: str = "prog") -> Tuple[int, str, str]:
    """Escribe ``source`` en un temporal, corre ``V0/main.py`` y devuelve
    ``(exit_code, stdout, stderr)``.

    Cada llamada usa su propio directorio temporal (aislamiento total: los
    ``dumps/``/``log/`` de un test no contaminan a otro) y lo borra al salir.
    """
    with tempfile.TemporaryDirectory(prefix="suriax-test-") as tmp:
        src_path = os.path.join(tmp, f"{name}.srcx")
        with open(src_path, "w", encoding="utf-8") as fh:
            fh.write(source)
        cmd = [sys.executable, os.path.join(_V0, "main.py"), src_path]
        cmd += args or []
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp,
                              timeout=120)
        return proc.returncode, proc.stdout, proc.stderr


def run_program(source: str, **kwargs) -> Tuple[int, str, str]:
    """Compila y EJECUTA (``--run``) devolviendo ``(exit, stdout, stderr)``."""
    args = kwargs.pop("args", []) + ["--run"]
    return run_source(source, args=args, **kwargs)


def run_project(files: dict, *, main: str = "main.srcx",
                args: Optional[List[str]] = None) -> Tuple[int, str, str]:
    """Escribe un PROYECTO entero en un temporal y corre ``V0/main.py``.

    ``files`` mapea ruta relativa (con ``/``, se crean los subdirectorios) a
    contenido; ``main`` es la que se compila. Es lo que hace falta para
    probar librerías y paquetes: el linker busca primero en el directorio
    del fuente y luego en ``./lib`` relativo a la raíz del proyecto, así que
    un ``lib/io/main.libsrx`` dentro del temporal se resuelve igual que en
    el repo — sin depender del estado real de ``lib/``.
    """
    with tempfile.TemporaryDirectory(prefix="suriax-proj-") as tmp:
        for rel, content in files.items():
            path = os.path.join(tmp, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        cmd = [sys.executable, os.path.join(_V0, "main.py"),
               os.path.join(tmp, *main.split("/"))]
        cmd += args or []
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp,
                              timeout=120)
        return proc.returncode, proc.stdout, proc.stderr


def assert_project_output(files: dict, expected: str, **kwargs) -> None:
    """El proyecto compila, EJECUTA y su stdout contiene ``expected``."""
    args = kwargs.pop("args", []) + ["--run"]
    code, out, err = run_project(files, args=args, **kwargs)
    assert expected in out, (
        f"salida esperada no encontrada.\n  esperado: {expected!r}\n"
        f"  stdout:   {out!r}\n  stderr:   {err!r}"
    )


def assert_output(source: str, expected: str, **kwargs) -> None:
    """El programa se ejecuta y su stdout CONTIENE ``expected``."""
    code, out, err = run_program(source, **kwargs)
    assert expected in out, (
        f"salida esperada no encontrada.\n  esperado: {expected!r}\n"
        f"  stdout:   {out!r}\n  stderr:   {err!r}"
    )


__all__ = [
    "lex", "parse", "typed", "analyze", "error_codes",
    "assert_ok", "assert_has_code",
    "run_source", "run_program", "assert_output",
    "run_project", "assert_project_output",
]
