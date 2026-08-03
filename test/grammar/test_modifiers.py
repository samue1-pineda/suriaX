"""grammar/modifiers — reservas de visibilidad, especificador ``hook``/
``dunder`` y las operaciones de región del modelo híbrido.

Forma del AST (parser) y, donde aplica, el símbolo/hook resultante
(semántica). Convención: ``_items``/``_stmt`` exigen compilación sintáctica
limpia, así que un test que pasa demuestra que la construcción PARSEA y que
produce la forma esperada.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze, error_codes, parse  # noqa: E402
from include import ast_nodes as ast  # noqa: E402


def _items(source: str):
    program, errors, lex_errors = parse(source)
    assert not lex_errors, [e.message for e in lex_errors]
    assert not errors, [e.message for e in errors]
    return program.items


def _stmt(body_stmt: str):
    """Primera sentencia del cuerpo de ``fn f() -> void { <body_stmt> }``."""
    return _items("fn f() -> void { " + body_stmt + " };")[0].body.statements[0]


# --------------------------------------------------------------------------- #
# reservas de visibilidad
# --------------------------------------------------------------------------- #

def test_visibilidad_en_funcion():
    assert _items("public fn f() -> void { };")[0].visibility == "public"


def test_visibilidad_en_struct():
    assert _items("private struct { int x; } P;")[0].visibility == "private"


def test_visibilidad_en_enum():
    assert _items("internal enum E { A, B };")[0].visibility == "internal"


def test_visibilidad_en_binding_global():
    assert _items("public const int MAX = 10;")[0].visibility == "public"


def test_visibilidad_en_type_decl():
    assert _items("internal const type int8;")[0].visibility == "internal"


def test_sin_visibilidad_es_none():
    assert _items("fn f() -> void { };")[0].visibility is None


def test_visibilidad_tras_el_decorador_recae_en_la_funcion():
    d = _items("@inline public fn f() -> void { };")[0]
    assert isinstance(d, ast.DecoratorDecl)
    assert d.target.visibility == "public"


# --------------------------------------------------------------------------- #
# especificador hook / dunder (el compilador ya no adivina por la forma)
# --------------------------------------------------------------------------- #

def test_hook_specifier():
    fn = _items("hook fn __free__(P ptr p) -> void { };")[0]
    assert fn.specifier == "hook" and fn.dunder == "free"


def test_dunder_specifier():
    fn = _items("dunder fn __tag__(int a) -> int { return a; };")[0]
    assert fn.specifier == "dunder" and fn.dunder == "tag"


def test_fn_dunder_sin_specifier_es_funcion_normal():
    fn = _items("fn __x__() -> void { };")[0]
    assert fn.specifier is None and fn.dunder == "x"


def test_visibilidad_antes_del_specifier():
    fn = _items("private hook fn __free__(P ptr p) -> void { };")[0]
    assert fn.visibility == "private" and fn.specifier == "hook"


def test_hook_registra_en_la_tabla():
    from src.frontend.semantic.hooks import HookKind
    _, table, errors = analyze(
        "struct { int x; } P;\nhook fn __free__(P ptr p) -> void { };")
    assert not errors, errors
    assert table.lookup_hook("P", HookKind.FREE) is not None


def test_dunder_es_hook_del_usuario_indexado_por_tipo():
    """Un 'dunder' es un hook del USUARIO: se indexa por (tipo, nombre), no en
    la tabla de hooks del set fijo."""
    _, table, errors = analyze(
        "struct { int x; } P;\ndunder fn __tag__(P ptr self) -> int { return 1; };")
    assert not errors, errors
    assert not table.hooks, "un 'dunder' NO va a la tabla de hooks del set fijo"
    assert ("P", "__tag__") in table.dunders


def test_fn_dunder_desnudo_no_registra_hook():
    """'fn __free__' sin especificador es función normal, NO un hook."""
    from src.frontend.semantic.hooks import HookKind
    _, table, errors = analyze(
        "struct { int x; } P;\nfn __free__(P ptr p) -> void { };")
    assert not errors, errors
    assert table.lookup_hook("P", HookKind.FREE) is None


# --------------------------------------------------------------------------- #
# traits y decoradores generalizados
# --------------------------------------------------------------------------- #

def test_trait_struct_agrupa_metodos():
    t = _items("@trait struct { fn __next__(self ptr) -> int?; "
               "fn __reset__(self ptr) -> void; } iterable;")[0]
    assert isinstance(t, ast.TraitDecl)
    assert t.name == "iterable" and len(t.methods) == 2
    assert t.methods[0].name == "__next__"


def test_trait_suelto_un_metodo():
    t = _items("@trait dunder fn __sumable__(self ptr, self ptr) -> self;")[0]
    assert isinstance(t, ast.TraitDecl) and t.name == "__sumable__"
    assert len(t.methods) == 1


def test_self_en_tipo_es_selftypeexpr():
    t = _items("@trait struct { fn __next__(self ptr) -> void; } it;")[0]
    param0 = t.methods[0].params[0]
    assert isinstance(param0, ast.PointerTypeExpr)
    assert isinstance(param0.inner, ast.SelfTypeExpr)


def test_impl_es_decorador_con_args_sobre_struct():
    d = _items("@impl(iterable) internal struct { int x; } L;")[0]
    assert isinstance(d, ast.DecoratorDecl) and d.name == "impl"
    assert d.args == ["iterable"]
    assert isinstance(d.target, ast.StructDecl) and d.target.visibility == "internal"


def test_decorador_sobre_enum():
    d = _items("@derive enum E { A, B };")[0]
    assert isinstance(d, ast.DecoratorDecl)
    assert isinstance(d.target, ast.EnumDecl)


# --------------------------------------------------------------------------- #
# regiones: modelo híbrido (modificadores + new/delete/in/move-region)
# --------------------------------------------------------------------------- #

def test_region_mods_orden_libre():
    r = _stmt("shrd mutable na region r { };")
    assert isinstance(r, ast.RegionStmt)
    assert r.shared and r.mutable and r.na and r.name == "r"


def test_region_sin_mods():
    r = _stmt("region r { };")
    assert not r.shared and not r.mutable and not r.na


def test_new_stmt():
    n = _stmt("new(shrd region c);")
    assert isinstance(n, ast.NewStmt) and n.name == "c" and n.shared
    assert not n.mutable and not n.na


def test_delete_externo():
    d = _stmt("delete(region c);")
    assert isinstance(d, ast.DeleteStmt) and d.name == "c"


def test_delete_interno_sin_argumento():
    d = _stmt("delete();")
    assert isinstance(d, ast.DeleteStmt) and d.name is None


def test_in_region_forma_corta():
    i = _stmt("in region c: return;")
    assert isinstance(i, ast.InRegionStmt) and i.region == "c"
    assert isinstance(i.body, ast.ReturnStmt)


def test_in_region_forma_bloque():
    i = _stmt("in region c { return; };")
    assert isinstance(i, ast.InRegionStmt) and isinstance(i.body, ast.Block)


def test_move_region():
    m = _stmt("move region a -> region b;")
    assert isinstance(m, ast.MoveRegionStmt) and m.src == "a" and m.dst == "b"


def test_move_valor_sigue_siendo_move_stmt():
    m = _stmt("move x;")
    assert isinstance(m, ast.MoveStmt)


def test_mutable_region_no_es_mal_uso():
    """'mutable region r' es válido; 'mutable int x' sigue siendo error."""
    r = _stmt("mutable region r { };")
    assert isinstance(r, ast.RegionStmt) and r.mutable
    assert error_codes("fn f() -> void { mutable int x = 1; };"), \
        "'mutable int' debe seguir siendo error"
