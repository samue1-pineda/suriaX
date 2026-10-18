"""unit/tipo_funcion — el tipo ``fn(A, B) -> R``: sintaxis, servicio de tipos
y su forma en el HIR.

El HIR es lo que leen los demás consumidores (la VM, el target web): su forma
se fija aquí con precisión, porque es el contrato sobre el que se construyen
los lectores. Un tipo función es ``TypeKind.FUNCTION`` (13; ``FUNCTION_TYPE`` en el ``.proto``) con los
PARÁMETROS en ``args`` y el RETORNO en ``inner``; ``Tipo.metodo`` es un
``MemberAccess`` cuyo ``obj`` lleva el tipo ``META``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze, parse, typed  # noqa: E402


def _var_type(source: str):
    """El ``restype`` (ya resuelto) del primer ``VarDecl`` de ``source``."""
    from include import ast_nodes as ast
    program, errors = typed(source)
    assert not errors, errors
    for item in program.items:
        if isinstance(item, ast.VarDecl):
            return item.restype
    raise AssertionError("no hay ningun VarDecl")


# --------------------------------------------------------------------------- #
# sintaxis: a que se pega cada sufijo
# --------------------------------------------------------------------------- #

def test_params_in_args_and_return_in_inner():
    from include.types_ast import PRIMITIVE_TYPES, TypeKind
    t = _var_type("var fn(int, str) -> bool f = g;")
    assert t.kind is TypeKind.FUNCTION
    assert t.args == (PRIMITIVE_TYPES["int"], PRIMITIVE_TYPES["str"])
    assert t.inner == PRIMITIVE_TYPES["bool"]


def test_the_suffix_after_the_arrow_belongs_to_the_return():
    """``fn(int) -> int?`` DEVUELVE un ``int?``; no es una función opcional."""
    from include.types_ast import TypeKind
    t = _var_type("var fn(int) -> int? f = g;")
    assert t.kind is TypeKind.FUNCTION
    assert t.inner.kind is TypeKind.NULLABLE
    t = _var_type("var fn(int) -> int ptr f = g;")
    assert t.kind is TypeKind.FUNCTION and t.inner.kind is TypeKind.POINTER


def test_an_optional_function_goes_in_parentheses():
    from include.types_ast import TypeKind
    t = _var_type("var (fn(int) -> int)? f = null;")
    assert t.kind is TypeKind.NULLABLE
    assert t.inner.kind is TypeKind.FUNCTION


def test_without_arrow_returns_void_and_no_params_is_fine():
    from include.types_ast import TypeKind
    t = _var_type("var fn() f = g;")
    assert t.kind is TypeKind.FUNCTION and t.args == ()
    assert t.inner.kind is TypeKind.VOID


def test_the_return_can_be_another_function():
    from include.types_ast import TypeKind
    t = _var_type("var fn(int) -> fn(int) -> int f = g;")
    assert t.inner.kind is TypeKind.FUNCTION
    assert repr(t) == "fn(int) -> fn(int) -> int"


def test_the_type_text_has_parentheses_where_needed():
    from src.frontend.semantic.extensions import format_type
    t = _var_type("var (fn(int, str) -> int)? f = null;")
    assert repr(t) == "(fn(int, str) -> int)?"
    assert format_type(t) == "(fn(int, str) -> int)?"
    t = _var_type("var (fn(int) -> int) ptr p = q;")
    assert format_type(t) == "(fn(int) -> int) ptr"


def test_fn_with_a_name_is_still_a_declaration():
    from include import ast_nodes as ast
    program, errors, _ = parse("fn doble(int x) -> int { return x * 2; }\n"
                                "fn(int) -> int g = doble;\n")
    assert not errors
    assert isinstance(program.items[0], ast.FunctionDecl)
    assert isinstance(program.items[1], ast.VarDecl)
    assert isinstance(program.items[1].type, ast.FunctionTypeExpr)


# --------------------------------------------------------------------------- #
# servicio de tipos
# --------------------------------------------------------------------------- #

def test_assignable_only_to_the_exact_type():
    from include.types_ast import PRIMITIVE_TYPES, function_of, nullable_of
    from src.frontend.semantic.type_service import is_assignable
    i, s = PRIMITIVE_TYPES["int"], PRIMITIVE_TYPES["str"]
    f = function_of((i,), i)
    assert is_assignable(f, function_of((i,), i))
    assert not is_assignable(f, function_of((s,), i))
    assert not is_assignable(f, function_of((i,), s))
    assert not is_assignable(f, function_of((i, i), i))
    assert not is_assignable(f, i)
    assert not is_assignable(i, f)
    assert is_assignable(nullable_of(f), f)


def test_substitution_reaches_params_and_return():
    from include.types_ast import (PRIMITIVE_TYPES, function_of, nominal,
                                   pointer_of)
    from src.frontend.semantic.type_service import mentions_param, substitute
    T, i = nominal("T"), PRIMITIVE_TYPES["int"]
    f = function_of((pointer_of(T), pointer_of(T)), T)
    assert mentions_param(f, {"T"})
    assert substitute(f, {"T": i}) == function_of((pointer_of(i), pointer_of(i)), i)


# --------------------------------------------------------------------------- #
# HIR: la forma que leen los demas consumidores
# --------------------------------------------------------------------------- #

def _module(source: str):
    from src.HIR.emmit_IR import build_module
    program, table, errors = analyze(source)
    assert not errors, errors
    module, hir_errors = build_module(program, table, source_file="<test>")
    assert not hir_errors, hir_errors
    return module


def _kind(pb, name: str) -> int:
    return pb.TypeKind.Value(name)


def test_the_hir_carries_function_13_with_args_and_inner():
    from src.HIR.stubs import load_hir_pb2
    pb = load_hir_pb2()
    assert pb.TypeKind.Value("FUNCTION_TYPE") == 13
    module = _module("fn doble(int x) -> int { return x * 2; }\n"
                     "fn main() -> int {\n"
                     "    var fn(int) -> int g = doble;\n"
                     "    return g(3);\n"
                     "}\n")
    fns = [t for t in module.types if t.kind == _kind(pb, "FUNCTION_TYPE")]
    assert len(fns) == 1
    f = fns[0]
    assert [a.kind for a in f.args] == [_kind(pb, "INT")]
    assert f.inner.kind == _kind(pb, "INT")


def test_the_value_and_the_callee_carry_the_function_type():
    from src.HIR.stubs import load_hir_pb2
    pb = load_hir_pb2()
    module = _module("fn doble(int x) -> int { return x * 2; }\n"
                     "fn main() -> int {\n"
                     "    var fn(int) -> int g = doble;\n"
                     "    return g(3);\n"
                     "}\n")
    main = [d.function for d in module.items
            if d.WhichOneof("node") == "function" and d.function.name == "main"][0]
    var = main.body.statements[0].var_decl
    assert var.value.WhichOneof("node") == "identifier"
    assert module.types[var.value.type_id].kind == _kind(pb, "FUNCTION_TYPE")
    call = main.body.statements[1].return_stmt.value.call
    assert module.types[call.callee.type_id].kind == _kind(pb, "FUNCTION_TYPE")
    assert not call.hook.owner_type


def test_a_method_value_is_a_member_with_meta_obj():
    from src.HIR.stubs import load_hir_pb2
    pb = load_hir_pb2()
    module = _module("struct { int x; } Punto;\n"
                     "@impl Punto {\n"
                     "    fn escala(Punto ptr self, int k) -> int { return self.x * k; }\n"
                     "}\n"
                     "fn main() -> int {\n"
                     "    var fn(Punto ptr, int) -> int m = Punto.escala;\n"
                     "    return 0;\n"
                     "}\n")
    main = [d.function for d in module.items
            if d.WhichOneof("node") == "function" and d.function.name == "main"][0]
    value = main.body.statements[0].var_decl.value
    assert value.WhichOneof("node") == "member"
    assert value.member.member == "escala"
    assert module.types[value.member.obj.type_id].kind == _kind(pb, "META")
    typ = module.types[value.type_id]
    assert typ.kind == _kind(pb, "FUNCTION_TYPE")
    # el dueño del metodo es el nucleo nominal del receptor (args[0])
    assert typ.args[0].kind == _kind(pb, "POINTER")
    assert typ.args[0].inner.name == "Punto"


def test_a_program_without_function_values_does_not_use_the_new_kind():
    """Cambio aditivo: lo que ya existía no cambia ni un byte por esto."""
    from src.HIR.stubs import load_hir_pb2
    pb = load_hir_pb2()
    module = _module("fn doble(int x) -> int { return x * 2; }\n"
                     "fn main() -> int { return doble(2); }\n")
    assert all(t.kind != _kind(pb, "FUNCTION_TYPE") for t in module.types)


def test_the_pretty_view_writes_the_function_type():
    import io
    from src.HIR.pretty import write_pretty
    module = _module("fn doble(int x) -> int { return x * 2; }\n"
                     "fn main() -> int {\n"
                     "    var (fn(int) -> int)? g = doble;\n"
                     "    return 0;\n"
                     "}\n")
    out = io.StringIO()
    write_pretty(module, out)
    text = out.getvalue()
    assert "(fn(int) -> int)?" in text
    assert "doble:(fn(int) -> int)" in text
