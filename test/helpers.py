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
# omitir una prueba: SIEMPRE de forma explícita
# --------------------------------------------------------------------------- #

class Omitida(Exception):
    """Una prueba que NO se ejecutó, con el motivo.

    Existe porque la forma anterior de saltarse una prueba era ``return``:
    el runner la contaba como PASADA. Así, una suite corrida sin node, sin el
    binario C++ o sin ``memory_c`` daba el mismo verde que una que lo había
    ejecutado todo, y la medalla sumaba como probado lo que nadie probó.

    El runner (``test/main.py``) la cuenta aparte y la lista con su motivo.
    No hace fallar la corrida: una máquina sin node no es un error del
    compilador, pero tiene que quedar a la vista.
    """


def omitir(motivo: str) -> None:
    """Termina la prueba actual como OMITIDA por ``motivo``.

    El motivo dice qué falta en la máquina y, si aplica, cómo conseguirlo:
    es lo único que verá quien lea el resumen.
    """
    raise Omitida(motivo)


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
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=tmp,
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
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=tmp,
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
    "Omitida", "omitir",
    "lex", "parse", "typed", "analyze", "error_codes",
    "assert_ok", "assert_has_code",
    "run_source", "run_program", "assert_output",
    "run_project", "assert_project_output",
]


# --------------------------------------------------------------------------- #
# portabilidad: lo que cambia de un sistema operativo a otro, en un solo lugar
# --------------------------------------------------------------------------- #

def hir_binary() -> Optional[str]:
    """El ejecutable ``suriax-hir`` (la VM), o ``None`` si no está construido.

    Orden: ``SURIAX_HIR_BIN`` (una ruta relativa se toma desde la raíz del
    repositorio, no desde el directorio temporal de cada prueba), después
    ``build/bin`` y después los otros ``build-*/bin`` (los de ASan al final:
    son más lentos). En Windows el ejecutable lleva ``.exe``; se prueban los
    dos nombres en todos los sistemas.
    """
    escrito = os.environ.get("SURIAX_HIR_BIN")
    if escrito:
        if not os.path.isabs(escrito):
            escrito = os.path.join(_REPO_ROOT, escrito)
        candidatas = [escrito]
    else:
        carpetas = sorted(
            (c for c in os.listdir(_REPO_ROOT)
             if c.startswith("build-") and os.path.isdir(os.path.join(_REPO_ROOT, c))),
            key=lambda c: (_carpeta_sanitizada(c), c))
        candidatas = [os.path.join(_REPO_ROOT, c, "bin", "suriax-hir")
                      for c in ["build", *carpetas]]
    for base in candidatas:
        for ruta in (base, base + ".exe"):
            if os.path.isfile(ruta) and os.access(ruta, os.X_OK):
                return ruta
    return None


def _carpeta_sanitizada(nombre: str) -> bool:
    """¿La carpeta de build es de un sanitizador? Es la convención de
    ``docs/quality/tools/sanitizers.py``: ``build-asan``, ``build-ubsan``."""
    return "san" in nombre


def vm_sanitizada(ruta: str) -> bool:
    """¿El ``suriax-hir`` de ``ruta`` es el de un sanitizador (vive en
    ``build-asan/bin`` o ``build-ubsan/bin``)? Una VM así es MUCHO más lenta
    —el punto fijo del bootstrap tarda unas 2 h por etapa con ASan en Debug,
    frente a 11 s—, y las pruebas largas la saltan diciéndolo."""
    carpeta = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(ruta))))
    return _carpeta_sanitizada(carpeta)


def run_with_timeout(fn, seconds: float, message: str):
    """Llama ``fn()`` y falla con ``message`` si no termina en ``seconds``.

    Reemplaza a ``signal.alarm``, que solo existe en POSIX. La llamada corre
    en un hilo daemon: si se cuelga, la prueba falla igual y el hilo no
    impide que el proceso termine. Una excepción de ``fn`` se propaga.
    """
    import threading

    resultado: dict = {}

    def _correr() -> None:
        try:
            resultado["valor"] = fn()
        except BaseException as exc:  # se relanza en el hilo de la prueba
            resultado["error"] = exc

    hilo = threading.Thread(target=_correr, daemon=True)
    hilo.start()
    hilo.join(seconds)
    if hilo.is_alive():
        raise AssertionError(message)
    if "error" in resultado:
        raise resultado["error"]
    return resultado.get("valor")


def link_lib(destination: str) -> None:
    """Pone la ``lib/`` del repositorio dentro de ``destination``: un enlace
    simbólico si el sistema lo permite y, si no, una copia. Windows exige un
    privilegio para crear enlaces (WinError 1314); sin la copia, las pruebas
    fallaban ahí antes de tocar lo que probaban.

    Solo para pruebas que LEEN la librería: con un enlace, escribir dentro
    de ``lib`` escribiría en el repositorio."""
    import shutil

    origen = os.path.join(_REPO_ROOT, "lib")
    enlace = os.path.join(destination, "lib")
    try:
        os.symlink(origen, enlace, target_is_directory=True)
    except (OSError, NotImplementedError):
        shutil.copytree(origen, enlace)
