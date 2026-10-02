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
from helpers import lex, omitir  # noqa: E402

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
                             text=True, encoding="utf-8", errors="replace", timeout=120)
        assert out.returncode == 0, out.stderr
        huellas.add(out.stdout.strip())
    assert len(huellas) == 1, (
        f"tres procesos, {len(huellas)} artefactos distintos del mismo "
        "programa: la serialización no es reproducible")


def test_el_codec_propio_coincide_con_google_protobuf():
    """El `.phir` que escribimos es protobuf DE VERDAD, no un formato parecido.

    Desde que el HIR se serializa a mano (``src/HIR/wire.py``, ver
    ``PROTOBUF_BRIDGE.md``), el emisor y el lector del proyecto son del mismo
    autor: podrían compartir un malentendido del formato y las pruebas de ida
    y vuelta pasarían igual. Esta es la que no puede: los bytes los parsea
    ``google.protobuf`` con el descriptor generado del ``.proto``, y se
    comprueba que re-serializarlos dé el MISMO mensaje.

    No compara bytes: el orden de las entradas de un ``map`` no es parte del
    dato, y protobuf ni siquiera lo garantiza estable entre implementaciones
    (este codec sí lo fija, por clave). Lo que tiene que coincidir es el
    mensaje.

    La referencia se genera AQUÍ, con ``protoc``, en un temporal: el proyecto
    ya no genera stubs (ver ``src/HIR/stubs.py``). Antes esta prueba buscaba
    el stub en ``V0/src/HIR/gen/``, que nada volvió a crear, y hacía
    ``return`` — así que "pasaba" en todas partes, también en la CI, sin
    haber comparado nunca un byte.

    Se OMITE (visible, con el motivo) si falta ``google.protobuf`` o
    ``protoc``: el compilador no los necesita, solo esta comprobación.
    """
    import importlib.util
    import shutil
    import subprocess
    import tempfile

    try:
        import google.protobuf  # noqa: F401
    except ImportError:
        omitir("google.protobuf no está instalado (pip install protobuf): es "
               "la referencia independiente contra la que se compara el codec")
    protoc = shutil.which("protoc")
    if protoc is None:
        omitir("protoc no está en el PATH: hace falta para generar desde "
               "hir.proto el descriptor de referencia")

    proto = os.path.join(_V0, "src", "HIR", "proto", "hir.proto")
    with tempfile.TemporaryDirectory(prefix="suriax-pb2-") as tmp:
        gen = subprocess.run(
            [protoc, f"--proto_path={os.path.dirname(proto)}",
             f"--python_out={tmp}", proto],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        assert gen.returncode == 0, (
            f"protoc no pudo compilar {proto} (exit {gen.returncode}):\n"
            f"{gen.stderr}")

        stub = os.path.join(tmp, "hir_pb2.py")
        spec = importlib.util.spec_from_file_location("hir_pb2_real", stub)
        real = importlib.util.module_from_spec(spec)
        sys.modules["hir_pb2_real"] = real
        try:
            spec.loader.exec_module(real)
        except Exception as exc:  # noqa: BLE001 - se omite CON la causa
            # un protoc y un google.protobuf de versiones que se rechazan
            # entre sí: es un problema de la máquina, no del codec.
            omitir(f"el stub que generó {protoc} no carga con este "
                   f"google.protobuf ({type(exc).__name__}: {exc})")

        nuestros, _modulo = _emitir()
        a = real.Module()
        a.ParseFromString(nuestros)                  # falla si los bytes no valen
        b = real.Module()
        b.ParseFromString(a.SerializeToString(deterministic=True))
        assert a == b, "protobuf no reconstruye el mismo mensaje desde nuestros bytes"


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
            # 'emmit_IR' es el emisor; 'wire' es el codec que IMPLEMENTA
            # 'SerializeToString'. La regla es sobre quien lo LLAMA —nadie
            # debe saltarse el emisor— no sobre quien lo define.
            if path.endswith(os.path.join("HIR", "emmit_IR.py")) \
                    or path.endswith(os.path.join("HIR", "wire.py")):
                continue
            with open(path, encoding="utf-8") as fh:
                if "SerializeToString" in fh.read():
                    fuera.append(os.path.relpath(path, _REPO_ROOT))
    assert not fuera, (
        f"serializan el HIR fuera de emmit_IR.serialize: {fuera} — se saltan "
        "la serialización determinista")
