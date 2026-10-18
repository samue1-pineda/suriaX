"""El ROLLBACK al esquema 1 del HIR, en Python (emisor + lector).

El esquema del HIR está VERSIONADO: el 2 (pool de tipos) rinde más que el 1
(cada tipo inline), y precisamente por estar versionado el 1 puede seguir
funcionando. ``--hir-schema 1`` lo emite y los lectores aceptan los dos. Ver
la cabecera de ``V0/src/HIR/proto/hir.proto`` y ``V0/src/HIR/schema_v1.py``.

Lo que se sostiene aquí:

- un ``.phir`` v1 no lleva ``Module.types`` ni ningún índice: cada tipo va
  inline, en su campo;
- normalizar el v1 da, BYTE A BYTE, el v2 del mismo programa (salvo
  ``schema_version``): es el mismo módulo lógico, con el pool en el mismo
  orden que el del emisor. Se comprueba sobre programas reales del repositorio;
- la vista legible de los dos coincide (salvo la cabecera, que dice el esquema);
- lo que no es un v1 limpio (con pool, con índices) y las versiones que nadie
  conoce (0, 3) se rechazan con su mensaje.

La ejecución (mismo programa, misma salida en los dos esquemas) está en
``test/e2e/test_hir_schema_v1.py``.
"""

from __future__ import annotations

import contextlib
import glob
import io
import os
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, os.path.join(_REPO_ROOT, "test"))
from helpers import lex  # noqa: E402

_FIXTURES_WEB = os.path.join(_REPO_ROOT, "test", "web", "fixtures")

#: toca cada campo de tipo que cambió entre los esquemas, y una lambda cuyo
#: retorno ('char') es un tipo NUEVO que el emisor registra antes que el de su
#: cuerpo ('float'): si el orden del pool del normalizador no fuera el del
#: emisor, el payload de 'Marca' apuntaría a otros índices.
_PROGRAMA = """
fn main() -> int {
    var int letra = probar(lambda (int v) -> char {
        var float x = cast<float>(v);
        if (x > 1.5) { return 'a'; }
        return 'b';
    }, 3);
    var Punto p = Punto{ x: 3, y: 4 };
    var Forma c = Forma.Rect(p.x, p.y);
    try { throw "x"; } catch (str e) { letra = letra + 1; }
    return letra + area(&c) + p.x;
}

fn probar(fn(int) -> char f, int v) -> int {
    if (f(v) == 'a') { return 1; }
    return 0;
}

struct { int x; int y; } Punto;

enum Forma { Nada, Circulo(int), Rect(int, int) };

enum Marca { Ninguna, Letra(char), Medida(float) };

fn area(Forma ptr f) -> int {
    match (f) {
        case Forma.Circulo(r) { return 3 * r * r; };
        case Forma.Rect(a, b) { return a * b; };
        case Forma.Nada { return 0; };
    };
    return 0;
}
"""


def _modulo(source: str = _PROGRAMA, schema_version: int = 2):
    """Fuente -> ``Module`` por el camino real del emisor."""
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze
    from src.HIR.emmit_IR import build_module

    tokens, lex_errors = lex(source)
    assert not lex_errors, [e.code for e in lex_errors]
    parser = Parser(tokens)
    program = parser.parse()
    assert not parser.ctx.errors, [e.code for e in parser.ctx.errors]
    resolve_types(program)
    table, sem_errors = analyze(program, source_path="<test>")
    assert not sem_errors, [e.code for e in sem_errors]
    module, hir_errors = build_module(program, table, source_file="<test>",
                                      schema_version=schema_version)
    assert not hir_errors, [e.code for e in hir_errors]
    return module


def _leer(datos: bytes):
    from src.HIR.stubs import load_hir_pb2
    module = load_hir_pb2().Module()
    module.ParseFromString(datos)
    return module


def _normalizado_como_v2(datos_v1: bytes) -> bytes:
    """Bytes v1 -> normalizados -> serializados con ``schema_version`` 2."""
    from src.HIR.emmit_IR import serialize
    from src.HIR.schema_v1 import normalize_v1
    module = normalize_v1(_leer(datos_v1))
    module.schema_version = 2
    return serialize(module)


def _campos_de_tipo(module):
    """Cuántos campos de tipo inline e índices lleva el árbol de ``module``."""
    from src.HIR.schema_v1 import TYPE_FIELDS, _recorrer
    cuenta = {"inline": 0, "indices": 0}

    def contar(msg, id_campo, inline, repetido):
        if repetido:
            cuenta["inline"] += len(getattr(msg, inline))
            cuenta["indices"] += len(getattr(msg, id_campo))
        else:
            cuenta["inline"] += int(msg.HasField(inline))
            cuenta["indices"] += int(getattr(msg, id_campo) != 0)

    assert TYPE_FIELDS  # la lista que recorre el contador
    for decl in module.items:
        _recorrer(decl, contar)
    return cuenta


# --------------------------------------------------------------------------- #
# el emisor
# --------------------------------------------------------------------------- #

def test_un_phir_v1_no_lleva_pool_y_cada_tipo_va_inline():
    from src.HIR.emmit_IR import serialize
    v1 = _leer(serialize(_modulo(schema_version=1)))
    assert v1.schema_version == 1
    assert len(v1.types) == 0, "un .phir del esquema 1 no lleva Module.types"
    cuenta = _campos_de_tipo(v1)
    assert cuenta["indices"] == 0, cuenta
    assert cuenta["inline"] > 0, cuenta

    v2 = _leer(serialize(_modulo()))
    assert v2.schema_version == 2
    assert len(v2.types) > 1
    cuenta2 = _campos_de_tipo(v2)
    assert cuenta2["inline"] == 0, cuenta2
    # el MISMO numero de anotaciones: una por campo, en los dos esquemas
    assert cuenta2["indices"] == cuenta["inline"], (cuenta, cuenta2)


def test_cada_campo_de_tipo_del_esquema_1_aparece_inline():
    """Ninguno de los siete se queda sin cubrir por el programa de prueba."""
    from src.HIR.emmit_IR import serialize
    from src.HIR.schema_v1 import TYPE_FIELDS, _recorrer
    vistos = set()

    def anotar(msg, _id, inline, repetido):
        lleno = len(getattr(msg, inline)) if repetido else msg.HasField(inline)
        if lleno:
            vistos.add(f"{msg._desc.name}.{inline}")

    v1 = _leer(serialize(_modulo(schema_version=1)))
    for decl in v1.items:
        _recorrer(decl, anotar)
    esperados = {f"{m}.{inline}" for m, campos in TYPE_FIELDS.items()
                 for _id, inline, _r in campos}
    assert vistos == esperados, sorted(esperados - vistos)


def test_emitir_el_v1_no_toca_el_module_del_v2():
    from src.HIR.emmit_IR import serialize
    from src.HIR.schema_v1 import to_schema_v1
    module = _modulo()
    antes = serialize(module)
    to_schema_v1(module)
    assert serialize(module) == antes


def test_un_esquema_que_no_se_sabe_emitir_se_rechaza():
    from src.HIR.emmit_IR import build_module
    try:
        build_module(None, None, schema_version=3)
    except ValueError as exc:
        assert "schema_version 3" in str(exc)
    else:
        raise AssertionError("build_module aceptó un esquema que no existe")


def test_la_cli_acepta_1_y_2_y_por_defecto_emite_el_2():
    from cli.args import build_parser
    parser = build_parser()
    assert parser.parse_args(["a.srcx"]).hir_schema == 2
    assert parser.parse_args(["a.srcx", "--hir-schema", "1"]).hir_schema == 1
    for malo in ("3", "0", "x"):
        try:
            # argparse escribe su error en stderr: se recoge para no ensuciar
            # la salida de la suite
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["a.srcx", "--hir-schema", malo])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"--hir-schema {malo} se aceptó")


# --------------------------------------------------------------------------- #
# normalizar = el mismo módulo lógico
# --------------------------------------------------------------------------- #

def test_normalizar_el_v1_da_el_v2_byte_a_byte():
    from src.HIR.emmit_IR import serialize
    v2 = serialize(_modulo())
    v1 = serialize(_modulo(schema_version=1))
    assert v1 != v2
    assert _normalizado_como_v2(v1) == v2


def test_ida_y_vuelta_sobre_los_phir_reales_del_repositorio():
    """Los golden del backend web (bytes REALES del compilador, incluidas las
    unidades de la librería estándar): desplegar el pool y volver a plegarlo
    devuelve exactamente el archivo."""
    from src.HIR.emmit_IR import serialize
    from src.HIR.schema_v1 import to_schema_v1
    archivos = sorted(glob.glob(os.path.join(_FIXTURES_WEB, "*.phir")))
    probados = 0
    for ruta in archivos:
        with open(ruta, "rb") as fh:
            datos = fh.read()
        module = _leer(datos)
        if module.schema_version != 2:
            continue   # los fixtures del propio esquema 1
        # se compara contra la serialización CANÓNICA del archivo y no contra
        # sus bytes: algún fixture viejo ('IO.stdp.phir') se generó con otro
        # orden de entradas de map, mismos datos y otros bytes
        canonico = serialize(module)
        v1 = serialize(to_schema_v1(module))
        assert _normalizado_como_v2(v1) == canonico, os.path.basename(ruta)
        probados += 1
    assert probados >= 10, f"solo {probados} fixtures v2: ¿se movieron?"


def test_el_fixture_v1_del_web_es_el_v2_normalizado():
    """Los fixtures que el lector web compara entre sí también cumplen la
    regla en Python: es el mismo contrato en los tres lectores."""
    for v2, v1 in (("rollback.phir", "rollback_v1.phir"),
                   ("calc.phir", "calc_v1.phir")):
        with open(os.path.join(_FIXTURES_WEB, v2), "rb") as fh:
            datos_v2 = fh.read()
        with open(os.path.join(_FIXTURES_WEB, v1), "rb") as fh:
            datos_v1 = fh.read()
        assert _leer(datos_v1).schema_version == 1
        assert _normalizado_como_v2(datos_v1) == datos_v2, v1


def test_la_vista_legible_del_v1_normalizado_es_la_del_v2():
    from src.HIR.emmit_IR import serialize
    from src.HIR.pretty import pretty
    from src.HIR.schema_v1 import normalize_v1
    vista_v2 = pretty(_leer(serialize(_modulo())))
    vista_v1 = pretty(normalize_v1(_leer(serialize(_modulo(schema_version=1)))))
    cabecera_v1, resto_v1 = vista_v1.split("\n", 1)
    cabecera_v2, resto_v2 = vista_v2.split("\n", 1)
    assert "schema 1" in cabecera_v1 and "schema 2" in cabecera_v2
    assert cabecera_v1.replace("schema 1", "schema 2") == cabecera_v2
    assert resto_v1 == resto_v2


# --------------------------------------------------------------------------- #
# el lector del intérprete
# --------------------------------------------------------------------------- #

def _escribir(tmp: str, nombre: str, module) -> str:
    from src.HIR.emmit_IR import serialize
    ruta = os.path.join(tmp, nombre)
    with open(ruta, "wb") as fh:
        fh.write(serialize(module))
    return ruta


def test_el_loader_acepta_el_v1_y_lo_normaliza():
    from runtime.interpreter.loader import SUPPORTED_SCHEMA_VERSIONS, load_module
    assert SUPPORTED_SCHEMA_VERSIONS == frozenset({1, 2})
    with tempfile.TemporaryDirectory() as tmp:
        cargado = load_module(_escribir(tmp, "v1.phir", _modulo(schema_version=1)))
    assert cargado.schema_version == 1, "la versión dice qué se LEYÓ"
    assert len(cargado.types) > 1, "el pool se construyó al cargar"
    cuenta = _campos_de_tipo(cargado)
    assert cuenta["inline"] == 0 and cuenta["indices"] > 0, cuenta


def test_un_v1_con_pool_se_rechaza():
    from runtime.interpreter.loader import HIRLoadError, load_module
    module = _modulo()            # v2, con pool...
    module.schema_version = 1     # ...que dice ser v1
    with tempfile.TemporaryDirectory() as tmp:
        ruta = _escribir(tmp, "mezcla.phir", module)
        try:
            load_module(ruta)
        except HIRLoadError as exc:
            assert "mezcla los dos esquemas" in str(exc), str(exc)
        else:
            raise AssertionError("se aceptó un v1 con pool de tipos")


def test_un_v1_con_pool_y_sin_indices_se_rechaza():
    """El pool solo, sin ningún índice que lo use: sigue siendo un v1 mal
    formado (la comprobación no depende de que algún nodo lo delate)."""
    from runtime.interpreter.loader import HIRLoadError, load_module
    from src.HIR.emmit_IR import serialize
    module = _leer(serialize(_modulo(schema_version=1)))
    module.types.add()
    with tempfile.TemporaryDirectory() as tmp:
        ruta = _escribir(tmp, "mezcla.phir", module)
        try:
            load_module(ruta)
        except HIRLoadError as exc:
            assert "Module.types" in str(exc), str(exc)
        else:
            raise AssertionError("se aceptó un v1 con pool de tipos")


def test_un_v1_con_un_indice_de_tipo_se_rechaza():
    from runtime.interpreter.loader import HIRLoadError, load_module
    from src.HIR.emmit_IR import serialize
    module = _leer(serialize(_modulo(schema_version=1)))
    # un 'type_id' en el primer Expr que se encuentre
    from src.HIR.schema_v1 import _recorrer
    hecho = []

    def sembrar(msg, id_campo, _inline, repetido):
        if not hecho and not repetido and msg._desc.name == "Expr":
            setattr(msg, id_campo, 1)
            hecho.append(True)

    for decl in module.items:
        _recorrer(decl, sembrar)
    assert hecho
    with tempfile.TemporaryDirectory() as tmp:
        ruta = _escribir(tmp, "mezcla.phir", module)
        try:
            load_module(ruta)
        except HIRLoadError as exc:
            assert "Expr.type_id" in str(exc), str(exc)
        else:
            raise AssertionError("se aceptó un v1 con un índice de tipo")


def test_las_versiones_desconocidas_se_siguen_rechazando():
    from runtime.interpreter.loader import HIRLoadError, load_module
    for version in (0, 3):
        module = _modulo()
        module.schema_version = version
        with tempfile.TemporaryDirectory() as tmp:
            ruta = _escribir(tmp, f"v{version}.phir", module)
            try:
                load_module(ruta)
            except HIRLoadError as exc:
                assert f"schema_version {version} no soportada" in str(exc), str(exc)
                assert "soportadas: 1, 2" in str(exc), str(exc)
            else:
                raise AssertionError(f"se aceptó schema_version {version}")
