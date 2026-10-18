"""grammar/option — la sintaxis del paso 3 ("Option"): ``x ?? d``, ``case v``
y las variantes de un enum GENÉRICO escritas con sus tipos.

``??`` no es un token del lexer: son dos ``?`` PEGADOS que el parser junta en
posición de operador (como ``>>``), así que ``int??`` sigue siendo un tipo
con dos sufijos. Asocia a la DERECHA y liga menos que ``or`` (C#, Swift).

``Res<int, str>.Ok(5)``: tras ``nombre<tipos>`` un ``.`` es la tercera
lectura genérica (junto a ``{`` de un literal y ``(`` de una llamada); los
argumentos quedan en el ``obj`` del acceso.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import parse  # noqa: E402
from include import ast_nodes as ast  # noqa: E402


def _items(source: str):
    program, errors, lex_errors = parse(source)
    assert not lex_errors, f"errores léxicos: {[e.message for e in lex_errors]}"
    assert not errors, f"errores de sintaxis: {[e.message for e in errors]}"
    return program.items


def _expr(source: str):
    """La expresión de ``var int x = <expr>;`` dentro de una función."""
    fn = _items("fn f() -> void { var int x = " + source + "; };")[0]
    return fn.body.statements[0].value


def _errors(source: str) -> list:
    _, errors, lex_errors = parse(source)
    return [(e.code, e.line, e.column) for e in [*lex_errors, *errors]]


# --------------------------------------------------------------------------- #
# x ?? d
# --------------------------------------------------------------------------- #

def test_null_coalesce_is_a_binary_operator():
    e = _expr("a ?? 0")
    assert isinstance(e, ast.BinaryOp) and e.operator == "??"
    assert isinstance(e.left, ast.Identifier) and e.left.name == "a"


def test_null_coalesce_associates_to_the_right():
    e = _expr("a ?? b ?? c")
    assert e.operator == "??" and isinstance(e.left, ast.Identifier)
    assert isinstance(e.right, ast.BinaryOp) and e.right.operator == "??"
    assert (e.right.left.name, e.right.right.name) == ("b", "c")


def test_null_coalesce_binds_less_than_or():
    """``a ?? b or c`` es ``a ?? (b or c)``: ``??`` está por debajo de ``or``."""
    e = _expr("a ?? b or c")
    assert e.operator == "??"
    assert isinstance(e.right, ast.BinaryOp) and e.right.operator == "or"
    e = _expr("a or b ?? c")
    assert e.operator == "??" and e.left.operator == "or"


def test_null_coalesce_binds_less_than_arithmetic_and_comparison():
    e = _expr("a ?? b + 1 == c")
    assert e.operator == "??" and e.right.operator == "=="


def test_null_coalesce_binds_more_than_assignment():
    fn = _items("fn f() -> void { x = a ?? b; };")[0]
    asignacion = fn.body.statements[0].expr
    assert isinstance(asignacion, ast.Assignment)
    assert asignacion.value.operator == "??"


def test_two_separate_question_marks_are_not_the_operator():
    """Como ``> >``: con un espacio en medio no es ``??``."""
    assert _errors("fn f() -> void { var int x = a ? ? 0; };") == [("PAR003", 1, 32)]


def test_a_single_question_mark_is_not_an_operator():
    assert _errors("fn f() -> void { var int x = a ? 0; };") == [("PAR003", 1, 32)]


def test_a_double_nullable_type_still_parses():
    """El lexer no emite ``??``: ``int??`` sigue siendo dos sufijos."""
    fn = _items("fn f() -> void { var int?? x = null; };")[0]
    tipo = fn.body.statements[0].type
    assert isinstance(tipo, ast.NullableTypeExpr)
    assert isinstance(tipo.inner, ast.NullableTypeExpr)


# --------------------------------------------------------------------------- #
# case v (la Semántica decide que LIGA; la sintaxis es la de siempre)
# --------------------------------------------------------------------------- #

def test_case_null_and_case_name_parse_as_patterns():
    fn = _items("fn f(int? x) -> void { match (x) { case null { } case v { } }; };")[0]
    arms = fn.body.statements[0].cases
    assert isinstance(arms[0].pattern, ast.Literal) and arms[0].pattern.literal_kind == "null"
    assert isinstance(arms[1].pattern, ast.Identifier) and arms[1].pattern.name == "v"
    assert not arms[1].binds   # lo decide la Semántica, no el parser


# --------------------------------------------------------------------------- #
# enum genérico: declaración y variantes con sus tipos
# --------------------------------------------------------------------------- #

def test_generic_enum_declaration_keeps_its_parameters():
    decl = _items("enum Res<T, E> { Ok(T), Err(E), Nada };")[0]
    assert isinstance(decl, ast.EnumDecl)
    assert decl.type_params == ["T", "E"]
    assert [i.name for i in decl.items] == ["Ok", "Err", "Nada"]


def test_a_plain_enum_has_no_parameters():
    assert _items("enum Color { ROJO, VERDE };")[0].type_params == []


def test_generic_variant_with_type_arguments():
    e = _expr("Res<int, str>.Ok(5)")
    assert isinstance(e, ast.Call)
    callee = e.callee
    assert isinstance(callee, ast.MemberAccess) and callee.member == "Ok"
    assert isinstance(callee.obj, ast.Identifier) and callee.obj.name == "Res"
    assert [t.name for t in callee.obj.type_args] == ["int", "str"]


def test_generic_unit_variant_with_type_arguments():
    e = _expr("Res<int, str>.Nada")
    assert isinstance(e, ast.MemberAccess) and e.member == "Nada"
    assert [t.name for t in e.obj.type_args] == ["int", "str"]


def test_generic_variant_of_a_library_enum():
    e = _expr("lib.Res<int, str>.Ok(5)")
    obj = e.callee.obj
    assert isinstance(obj, ast.MemberAccess) and obj.member == "Res"
    assert [t.name for t in obj.type_args] == ["int", "str"]


def test_generic_variant_as_a_case_pattern():
    """En un ``case`` no se admite un literal de struct (el ``{`` es el
    cuerpo), pero la variante genérica sí."""
    fn = _items("fn f(Res<int, str> r) -> void { match (r) { "
                "case Res<int, str>.Ok(v) { } case Res<int, str>.Nada { } }; };")[0]
    arms = fn.body.statements[0].cases
    assert [t.name for t in arms[0].pattern.callee.obj.type_args] == ["int", "str"]
    assert [t.name for t in arms[1].pattern.obj.type_args] == ["int", "str"]


def test_a_comparison_chain_is_still_a_comparison():
    """``a < b > c`` no tiene ``.``, ``(`` ni ``{`` tras el ``>``: se
    retrocede y son dos comparaciones, como siempre."""
    e = _expr("a < b > c")
    assert isinstance(e, ast.BinaryOp) and e.operator == ">"
    assert e.left.operator == "<"
