"""unit/parser — forma del AST para cada construcción de la gramática.

Comprueba la ESTRUCTURA que el parser produce (clases de nodo y campos),
no el texto: es el contrato parser -> AST-tipado -> Semántica -> HIR.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import parse  # noqa: E402
from include import ast_nodes as ast  # noqa: E402


def _items(source: str):
    program, errors, lex_errors = parse(source)
    assert not lex_errors, f"errores léxicos: {lex_errors}"
    assert not errors, f"errores de sintaxis: {[e.message for e in errors]}"
    return program.items


def _body(source: str):
    """Sentencias del cuerpo de la primera función declarada."""
    fn = _items(source)[0]
    return fn.body.statements


def test_funcion_con_params_y_retorno():
    fn = _items("fn suma(int a, int b) -> int { return a + b; };")[0]
    assert isinstance(fn, ast.FunctionDecl)
    assert fn.name == "suma"
    assert [p.name for p in fn.params] == ["a", "b"]
    assert isinstance(fn.body.statements[0], ast.ReturnStmt)


def test_prototipo_sin_cuerpo():
    fn = _items("fn escribe(str s) -> void;")[0]
    assert fn.body is None, "un prototipo debe tener body=None"


def test_struct_nombre_al_final():
    decl = _items("struct { int x; int y; } Punto;")[0]
    assert isinstance(decl, ast.StructDecl)
    assert decl.name == "Punto"
    assert [f.name for f in decl.fields] == ["x", "y"]


def test_struct_literal():
    stmt = _body("fn f() -> void { var P p = P{ x: 1, y: 2 }; };")[0]
    lit = stmt.value
    assert isinstance(lit, ast.StructLiteral)
    assert lit.type_name == "P"
    assert lit.field_names == ["x", "y"], lit.field_names
    assert len(lit.values) == 2


def test_struct_literal_coma_final_tolerada():
    stmt = _body("fn f() -> void { var P p = P{ x: 1, }; };")[0]
    assert isinstance(stmt.value, ast.StructLiteral)


def test_addr_of_es_nodo_propio():
    """'&x' produce AddrOf, no un UnaryOp genérico."""
    stmt = _body("fn f() -> void { var int a = 1; var int ptr p = &a; };")[1]
    assert isinstance(stmt.value, ast.AddrOf), type(stmt.value).__name__


def test_try_catch():
    stmt = _body('fn f() -> void { try { var int a = 1; } catch (e) { var int b = 2; }; };')[0]
    assert isinstance(stmt, ast.TryStmt)
    assert len(stmt.catches) == 1
    assert stmt.catches[0].name == "e"
    assert len(stmt.try_block.statements) == 1
    assert len(stmt.catches[0].block.statements) == 1


def test_throw():
    stmt = _body("fn f() -> void { throw 42; };")[0]
    assert isinstance(stmt, ast.ThrowStmt)
    assert isinstance(stmt.value, ast.Literal)


def test_test_decl_estilo_zig():
    decl = _items('test "mi caso" { var int a = 1; };')[0]
    assert isinstance(decl, ast.TestDecl)
    assert decl.name == "mi caso"
    assert len(decl.body.statements) == 1


def test_cast_con_argumento_de_tipo():
    stmt = _body("fn f() -> void { var float x = cast<float>(3); };")[0]
    assert isinstance(stmt.value, ast.CastExpr)


def test_tipo_error_con_inner():
    fn = _items("fn f() -> error int { return 1; };")[0]
    assert isinstance(fn.return_type, ast.ErrorTypeExpr)
    assert isinstance(fn.return_type.inner, ast.PrimitiveTypeExpr)


def test_tipo_error_solo():
    fn = _items("fn f() -> error;")[0]
    assert isinstance(fn.return_type, ast.ErrorTypeExpr)
    assert fn.return_type.inner is None, "'error' sola no lleva inner"


def test_sufijos_de_tipo_izquierda_a_derecha():
    """'T ptr?' (puntero nullable) != 'T? ptr' (puntero a nullable)."""
    a = _body("fn f() -> void { var int ptr? p = null; };")[0]
    assert isinstance(a.type, ast.NullableTypeExpr)
    assert isinstance(a.type.inner, ast.PointerTypeExpr)

    b = _body("fn f() -> void { var int? ptr q = null; };")[0]
    assert isinstance(b.type, ast.PointerTypeExpr)
    assert isinstance(b.type.inner, ast.NullableTypeExpr)


def test_puntero_mutable():
    stmt = _body("fn f() -> void { var int ptr mutable p = null; };")[0]
    assert isinstance(stmt.type, ast.PointerTypeExpr)
    assert stmt.type.mutable is True


def test_precedencia_aritmetica():
    """'1 + 2 * 3' agrupa como '1 + (2 * 3)'."""
    stmt = _body("fn f() -> void { var int x = 1 + 2 * 3; };")[0]
    top = stmt.value
    assert isinstance(top, ast.BinaryOp) and top.operator == "+"
    assert isinstance(top.right, ast.BinaryOp) and top.right.operator == "*"


def test_if_else_encadenado():
    stmt = _body("fn f() -> void { if (1 < 2) { }; else { if (2 < 3) { }; }; };")[0]
    assert isinstance(stmt, ast.IfStmt)
    assert stmt.else_branch is not None


def test_match_con_dos_ramas():
    stmt = _body("fn f() -> void { var int s = 0; match (s) { case 0: s = 1; case 1: s = 2; }; };")[1]
    assert isinstance(stmt, ast.MatchStmt)
    assert len(stmt.cases) == 2


def test_fstring_interpolada_en_ast():
    stmt = _body('fn f() -> void { var int a = 1; var str s = f"v={a}"; };')[1]
    interp = stmt.value
    assert isinstance(interp, ast.InterpolatedString)
    assert any(isinstance(p, ast.Expression) for p in interp.parts)


def test_recuperacion_de_errores_continua():
    """Un error de sintaxis no aborta: se reportan y se sigue parseando."""
    program, errors, _ = parse("int 1mal;\nfn ok() -> void { };")
    assert errors, "debería haber al menos un error de sintaxis"
    assert any(isinstance(i, ast.FunctionDecl) for i in program.items), (
        "el parser debe recuperarse y parsear la función siguiente"
    )
