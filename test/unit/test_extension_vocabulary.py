"""El vocabulario que aporta el proyecto: de la declaración al ``Module``.

``V0/src/frontend/semantic/extensions.py`` traduce lo que HTIMS descubrió (una
firma escrita en tipos del lenguaje, dentro de un ``.py``) al vocabulario que
la Semántica hace cumplir. Aquí se fija esa traducción y lo que acaba viajando
en el HIR, sin pasar por la CLI ni por un directorio temporal.
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
from htims import HookDecl  # noqa: E402
from htims.registry import ExtensionModule, ExtensionSet  # noqa: E402

_PROGRAMA = """
struct { int vy; } Body;

hook fn __gravity__(Body ptr mutable b, int dt) -> void {
    b.vy = b.vy - 10 * dt;
}

fn main() -> int {
    var Body b = Body{ vy: 20 };
    b.__gravity__(1);
    return b.vy;
}
"""


def _declaracion(**cambios) -> HookDecl:
    campos = dict(
        name="__gravity__", owner="Body",
        params=("Body ptr mutable", "int"), returns="void",
        logic="gravity_cpp", func="gravity", module="physics",
        file="/proyecto/extensions/calls/physics.py", line=7, column=2,
    )
    campos.update(cambios)
    return HookDecl(**campos)


def _extension_set(*decls: HookDecl) -> ExtensionSet:
    return ExtensionSet(
        root="/proyecto", project="MiJuego", manifest=None,
        logic_dir="/proyecto/extensions/logic",
        calls_dir="/proyecto/extensions/calls",
        modules=(ExtensionModule(name="physics",
                                 path="/proyecto/extensions/calls/physics.py",
                                 hooks=decls),),
        hooks=decls, by_key={d.key: d for d in decls},
    )


def _compilar(source: str = _PROGRAMA, *, extensions=None):
    """Frontend completo con el vocabulario del proyecto inyectado."""
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze

    config = {"_root": "/proyecto", "_extensions": extensions}
    tokens, lex_errors = lex(source)
    assert not lex_errors, [e.code for e in lex_errors]
    parser = Parser(tokens)
    program = parser.parse()
    assert not parser.ctx.errors, [e.code for e in parser.ctx.errors]
    resolve_types(program)
    table, errors = analyze(program, source_path="juego.srcx", config=config)
    return program, table, errors


# --------------------------------------------------------------------------- #
# la traducción de la firma declarada
# --------------------------------------------------------------------------- #

def test_los_tipos_declarados_se_parsean_con_la_gramatica_real():
    """No se comparan cadenas: cada tipo se resuelve con el mismo parser que
    lee un .srcx, así que los espacios sobrantes o una forma equivalente no
    cambian nada."""
    from src.frontend.semantic.extensions import parse_declared_type
    from include.types_ast import PRIMITIVE_TYPES

    assert parse_declared_type("int") == PRIMITIVE_TYPES["int"]
    assert parse_declared_type("  int  ") == PRIMITIVE_TYPES["int"]
    apuntador = parse_declared_type("Body ptr mutable")
    assert apuntador.mut is True and apuntador.inner.name == "Body"
    assert parse_declared_type("Body ptr") != apuntador  # 'mutable' importa
    assert parse_declared_type("int?") is not None


def test_una_firma_que_no_es_del_lenguaje_se_reporta():
    from src.frontend.semantic.extensions import build_vocabulary

    specs, problemas = build_vocabulary(
        _extension_set(_declaracion(params=("Body ptr mutable", "int foo"))))
    assert specs == {}
    assert [p["code"] for p in problemas] == ["EXT030"]
    assert "int foo" in problemas[0]["message"]
    assert problemas[0]["line"] == 7   # la posición del .py, no del .srcx


def test_un_nombre_desconocido_es_un_tipo_NOMINAL_valido():
    """Matiz que conviene tener escrito: la gramática acepta cualquier
    identificador como tipo nominal, así que una firma que dice 'Entero' no
    se rechaza aquí — se rechaza cuando el .srcx intente implementarla, donde
    'Entero' no existe. El error sale con posición en el fuente, que es donde
    el usuario puede arreglarlo."""
    from src.frontend.semantic.extensions import build_vocabulary

    specs, problemas = build_vocabulary(
        _extension_set(_declaracion(params=("Body ptr mutable", "Entero"))))
    assert problemas == []
    assert "gravity" in specs


def test_un_hook_sin_parametros_no_puede_pertenecer_a_un_tipo():
    from src.frontend.semantic.extensions import build_vocabulary

    specs, problemas = build_vocabulary(_extension_set(_declaracion(params=())))
    assert specs == {}
    assert [p["code"] for p in problemas] == ["EXT031"]


def test_el_vocabulario_del_proyecto_se_suma_al_fijo():
    from src.frontend.semantic.context import SemanticContext
    from src.frontend.semantic.hooks import HOOK_SPECS
    from src.frontend.semantic.symbol_table import SymbolTable

    ctx = SemanticContext(SymbolTable(),
                          config={"_extensions": _extension_set(_declaracion())})
    assert set(HOOK_SPECS).issubset(ctx.hook_specs)
    assert "gravity" in ctx.hook_specs
    # y NO se filtra al vocabulario global: otra compilación no lo ve
    assert "gravity" not in HOOK_SPECS


def test_una_extension_no_puede_redefinir_el_vocabulario_fijo():
    from src.frontend.semantic.context import SemanticContext
    from src.frontend.semantic.hooks import HOOK_SPECS
    from src.frontend.semantic.symbol_table import SymbolTable

    intruso = _declaracion(name="__print__", params=("Body ptr",))
    ctx = SemanticContext(SymbolTable(),
                          config={"_extensions": _extension_set(intruso)})
    assert ctx.hook_specs["print"] is HOOK_SPECS["print"], (
        "una extensión pisó un hook del compilador")


# --------------------------------------------------------------------------- #
# la Semántica lo hace cumplir
# --------------------------------------------------------------------------- #

def test_con_la_extension_el_hook_se_registra():
    _program, table, errors = _compilar(extensions=_extension_set(_declaracion()))
    assert not errors, [f"{e.code}: {e.message}" for e in errors]
    from src.frontend.semantic.hooks import HookKind
    símbolo = table.lookup_hook("Body", HookKind.EXTENDED, name="__gravity__")
    assert símbolo is not None
    assert símbolo.hook_module == "physics"


def test_sin_la_extension_el_mismo_programa_no_compila():
    _program, _table, errors = _compilar(extensions=None)
    assert [e.code for e in errors][:1] == ["SEM018"]


def test_la_clave_del_registro_distingue_dos_hooks_del_mismo_tipo():
    """Lo que la clave (dueño, kind) hacía imposible: dos hooks de usuario
    sobre el mismo tipo."""
    decls = (_declaracion(),
             _declaracion(name="__drag__", params=("Body ptr mutable",),
                          func="drag"))
    fuente = _PROGRAMA.replace(
        "fn main()",
        "hook fn __drag__(Body ptr mutable b) -> void { b.vy = 0; }\n\nfn main()")
    _program, table, errors = _compilar(fuente, extensions=_extension_set(*decls))
    assert not errors, [f"{e.code}: {e.message}" for e in errors]
    assert len(table.hooks) == 2


# --------------------------------------------------------------------------- #
# lo que viaja en el artefacto
# --------------------------------------------------------------------------- #

def test_el_hir_lleva_nombre_y_procedencia():
    from src.HIR.emmit_IR import build_module

    program, table, errors = _compilar(extensions=_extension_set(_declaracion()))
    assert not errors
    module, hir_errors = build_module(program, table, source_file="juego.srcx")
    assert not hir_errors, [e.message for e in hir_errors]

    entradas = list(module.symbols.hooks)
    assert len(entradas) == 1
    entrada = entradas[0]
    assert entrada.owner_type == "Body"
    assert entrada.hook_name == "__gravity__"
    assert entrada.extension == "physics"
    from src.HIR.stubs import load_hir_pb2
    assert entrada.kind == load_hir_pb2().HookKind.Value("EXTENDED")


def test_la_llamada_referencia_el_hook_por_su_nombre():
    """El ``HookRef`` del nodo tiene que llevar el nombre: sin él, dos hooks
    de usuario del mismo tipo serían la misma referencia."""
    from src.HIR.emmit_IR import build_module

    program, table, errors = _compilar(extensions=_extension_set(_declaracion()))
    assert not errors
    module, _ = build_module(program, table, source_file="juego.srcx")

    refs = []
    for decl in module.items:
        if decl.WhichOneof("node") != "function" or decl.function.name != "main":
            continue
        for stmt in decl.function.body.statements:
            if stmt.WhichOneof("node") == "expr_stmt":
                expr = stmt.expr_stmt.expr
                if expr.WhichOneof("node") == "call":
                    refs.append(expr.call.hook)
    assert refs, "no se encontró la llamada al hook en 'main'"
    assert refs[0].owner_type == "Body"
    assert refs[0].hook_name == "__gravity__"
