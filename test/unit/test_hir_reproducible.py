"""El ``.phir`` es REPRODUCIBLE: mismo programa, mismos bytes.

No lo era. Los campos ``map<string, Symbol>`` de la ``SymbolTable`` se
serializan en un orden no especificado, así que compilar dos veces el mismo
archivo producía artefactos con los mismos datos y distintos bytes (tres
corridas seguidas, tres hashes distintos; fijar ``PYTHONHASHSEED`` no lo
arreglaba, porque el orden lo decide la tabla hash de ``upb``, no la de
Python).

Eso rompe todo lo que compare artefactos: los golden ``.phir`` del backend
web, una caché de build por hash, y cualquier diferencial que quiera
demostrar que un cambio del emisor NO alteró la salida — que es justo la
herramienta que necesita el plan de ``docs/plan_hir_v2.md``.

``emmit_IR.serialize`` es ahora el único sitio que serializa y usa la
serialización determinista de protobuf. Este archivo lo mantiene así.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, os.path.join(_REPO_ROOT, "test"))
from helpers import lex  # noqa: E402

_PROGRAMA = """
struct { int x; int y; } Punto;

enum Color { ROJO, VERDE = 5, AZUL, };

fn suma(int a, int b) -> int { return a + b; }

hook fn __print__(Punto ptr p) -> void { }

fn main() -> int {
    var Punto p = Punto{ x: 1, y: 2 };
    var int total = suma(p.x, p.y);
    var Color c = Color.VERDE;
    if (total > 2) { total = total - 1; }
    return 0;
}
"""


def _emitir(source: str = _PROGRAMA):
    """Fuente -> (bytes del .phir, Module), por el camino real del emisor."""
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze
    from src.HIR.emmit_IR import build_module, serialize

    tokens, lex_errors = lex(source)
    assert not lex_errors, [e.code for e in lex_errors]
    parser = Parser(tokens)
    program = parser.parse()
    assert not parser.ctx.errors, [e.code for e in parser.ctx.errors]
    resolve_types(program)
    table, sem_errors = analyze(program, source_path="<test>")
    assert not sem_errors, [e.code for e in sem_errors]
    module, hir_errors = build_module(program, table, source_file="<test>")
    assert not hir_errors, [e.code for e in hir_errors]
    return serialize(module), module


def test_el_phir_reserializado_es_identico():
    """La forma barata de detectar el fallo, y la única que funciona dentro
    de un solo proceso.

    Emitir dos veces seguidas NO lo detecta: el orden de un mapa es estable
    mientras la tabla hash sea la misma. Pero un ``Module`` re-parseado
    construye tablas NUEVAS, así que re-serializarlo solo devuelve los mismos
    bytes si el orden no depende de ellas.
    """
    from src.HIR.emmit_IR import serialize
    from src.HIR.stubs import load_hir_pb2

    data, _ = _emitir()
    module = load_hir_pb2().Module()
    module.ParseFromString(data)
    assert serialize(module) == data, (
        "el .phir re-serializado difiere del original: el orden de los mapas "
        "depende de la tabla hash del proceso")


def test_dos_procesos_emiten_los_mismos_bytes():
    """La garantía de verdad: compilar el mismo programa en dos procesos
    distintos produce artefactos idénticos. Es lo que hace comparables los
    golden del backend web y lo que permite cachear un build por hash."""
    import hashlib
    import subprocess
    import textwrap

    script = textwrap.dedent(f"""
        import hashlib, sys
        sys.path[:0] = [{_V0!r}, {_REPO_ROOT!r}]
        from src.frontend.lexer.lexer import Lexer
        from src.frontend.parser.parser import Parser
        from src.frontend.parser.typed_ast import resolve_types
        from src.frontend.semantic import analyze
        from src.HIR.emmit_IR import build_module, serialize
        program = Parser(Lexer({_PROGRAMA!r}, file="<t>").tokenize()).parse()
        resolve_types(program)
        table, _ = analyze(program, source_path="<t>")
        module, _ = build_module(program, table, source_file="<t>")
        print(hashlib.sha256(serialize(module)).hexdigest())
    """)
    huellas = set()
    for _ in range(3):
        out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                             text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        huellas.add(out.stdout.strip())
    assert len(huellas) == 1, (
        f"tres procesos, {len(huellas)} artefactos distintos del mismo "
        "programa: la serialización no es reproducible")


def test_el_emisor_es_el_unico_que_serializa():
    """Frontera: el conocimiento de ``google.protobuf`` se queda en el
    paquete HIR (lo dice el docstring de ``module_to_text``, y durante un
    tiempo ``V0/main.py`` lo incumplía llamando a ``SerializeToString``)."""
    fuera = []
    for carpeta, _dirs, files in os.walk(_REPO_ROOT):
        if any(p in carpeta for p in ("__pycache__", ".git", "node_modules",
                                      "documentation", "dev", "test")):
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(carpeta, name)
            if path.endswith(os.path.join("HIR", "emmit_IR.py")):
                continue
            with open(path, encoding="utf-8") as fh:
                if "SerializeToString" in fh.read():
                    fuera.append(os.path.relpath(path, _REPO_ROOT))
    assert not fuera, (
        f"serializan el HIR fuera de emmit_IR.serialize: {fuera} — se saltan "
        "la serialización determinista")
