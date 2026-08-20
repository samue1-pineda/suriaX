"""grammar/ast — cada producción de ``docs/gramar/grammar.ebnf``, aislada.

Un caso MÍNIMO por regla de la gramática, afirmando la forma del AST. La
diferencia con ``unit/test_parser.py`` (que cubre las construcciones más
usadas) es la intención: aquí se recorre la EBNF regla a regla, para que un
fallo de gramática se localice sin leer el resto del pipeline. Si uno de
estos falla, el problema está en el parser; si pasa y falla el de
``negative_tests``/``e2e`` del mismo nombre, está más abajo.

Convención: ``_items`` exige compilación sintáctica limpia, así que un test
que pasa demuestra a la vez que la construcción PARSEA y que produce la
forma esperada.
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


def _body(source: str):
    """Sentencias del cuerpo de la primera función del fuente."""
    return _items(source)[0].body.statements


def _expr(source: str):
    """La expresión de ``var int x = <expr>;`` dentro de una función."""
    stmt = _body("fn f() -> void { var int x = " + source + "; };")[0]
    return stmt.value


# --------------------------------------------------------------------------- #
# directive = import_dir | export_dir | from_dir
# --------------------------------------------------------------------------- #

def test_import_simple():
    d = _items("#import IO;")[0]
    assert isinstance(d, ast.ImportDirective)
    assert d.lib == "IO" and d.alias is None


def test_import_punteado():
    d = _items("#import IO.stdp;")[0]
    assert d.lib == "IO.stdp", "el nombre punteado viaja entero al AST"


def test_import_con_alias():
    d = _items("#import IO.stdp as p;")[0]
    assert d.lib == "IO.stdp" and d.alias == "p"


def test_import_sin_punto_y_coma():
    """El ';' es opcional en las directivas (EBNF: '[ \";\" ]')."""
    assert _items("#import IO")[0].lib == "IO"


def test_from_directive():
    d = _items("#from IO.stdp #import print;")[0]
    assert isinstance(d, ast.FromDirective)
    assert (d.lib, d.name, d.alias) == ("IO.stdp", "print", None)


def test_from_directive_con_alias():
    d = _items("#from IO.stdp #import print as w;")[0]
    assert d.alias == "w"


def test_export_simple_y_con_as():
    """'#export print' y '#export as print' son equivalentes."""
    for src in ("#export print", "#export as print"):
        d = _items(src)[0]
        assert isinstance(d, ast.ExportDirective)
        assert d.alias == "print" and d.package is False, src


def test_export_package():
    d = _items("#export package as IO")[0]
    assert d.alias == "IO" and d.package is True


def test_import_binding():
    """``const NAME = #import lib;`` (ast_nodes.ImportBinding)."""
    b = _items("const IO = #import IO;")[0]
    assert isinstance(b, ast.ImportBinding)
    assert b.name == "IO" and b.qualifier == "const"
    assert isinstance(b.source, ast.ImportDirective)


# --------------------------------------------------------------------------- #
# function_decl / param_list / decorator_decl / test_decl
# --------------------------------------------------------------------------- #

def test_funcion_sin_params():
    fn = _items("fn f() -> int { return 0; };")[0]
    assert isinstance(fn, ast.FunctionDecl) and fn.params == []


def test_prototipo_es_body_none():
    """Un prototipo (sin cuerpo) es lo que liga el intérprete a un intrínseco."""
    assert _items("fn __write__(str s) -> void;")[0].body is None


def test_funcion_dunder():
    fn = _items("fn __print__(S ptr s) -> void { return; };")[0]
    assert fn.name == "__print__"


def test_decorador_sobre_funcion():
    d = _items("@inline fn f() -> void { };")[0]
    assert isinstance(d, ast.DecoratorDecl)
    assert isinstance(d.target, ast.FunctionDecl)


def test_test_decl():
    t = _items('test "suma bien" { var int x = 1; };')[0]
    assert isinstance(t, ast.TestDecl) and t.name == "suma bien"


# --------------------------------------------------------------------------- #
# struct_decl / enum_decl / type_decl
# --------------------------------------------------------------------------- #

def test_struct_decl():
    d = _items("struct { int x; Nodo ptr? sig; } Nodo;")[0]
    assert isinstance(d, ast.StructDecl) and d.name == "Nodo"
    assert [f.name for f in d.fields] == ["x", "sig"]


def test_enum_decl_y_valores_explicitos():
    d = _items("enum Color { Rojo, Verde = 5, Azul };")[0]
    assert isinstance(d, ast.EnumDecl)
    assert [i.name for i in d.items] == ["Rojo", "Verde", "Azul"]
    assert d.items[0].value is None and d.items[1].value is not None


def test_type_decl_opaco():
    d = _items("const type int8;")[0]
    assert isinstance(d, ast.TypeDecl) and d.name == "int8"


# --------------------------------------------------------------------------- #
# type: primitivos, ptr (postfijo), nullable, error
# --------------------------------------------------------------------------- #

def test_tipo_puntero_es_postfijo():
    """'T ptr' — nunca 'ptr T'; 'mutable' se pega al ptr."""
    fn = _items("fn f(Nodo ptr mutable p) -> void { };")[0]
    assert isinstance(fn.params[0].type, ast.PointerTypeExpr)
    assert fn.params[0].type.mutable is True


def test_tipos_envueltos_parsean():
    for t in ("int", "float", "bool", "char", "str", "void",
              "Nodo ptr", "Nodo ptr mutable", "Nodo?", "Nodo ptr?"):
        _items(f"fn f() -> {t} {{ }};")  # no debe dar error de sintaxis


def test_tipo_error_en_retorno():
    """'error T': la firma de una función que puede lanzar."""
    _items("fn f() -> error int { throw 1; };")


# --------------------------------------------------------------------------- #
# statement: var_decl, assignment, if/while/match, break/continue/return
# --------------------------------------------------------------------------- #

def test_var_decl_con_y_sin_inicializador():
    stmts = _body("fn f() -> void { var int a = 1; var int b; };")
    assert all(isinstance(s, ast.VarDecl) for s in stmts)
    assert stmts[0].value is not None and stmts[1].value is None


def test_const_es_qualifier():
    s = _body("fn f() -> void { const int a = 1; };")[0]
    assert s.qualifier == "const"


def test_assignment_a_variable_y_a_campo():
    """La asignacion es una EXPRESION; como sentencia va envuelta en ExprStmt."""
    stmts = _body("fn f() -> void { x = 1; p.v = 2; };")
    assert isinstance(stmts[0].expr, ast.Assignment)
    assert isinstance(stmts[1].expr.target, ast.MemberAccess)


def test_if_else():
    s = _body("fn f() -> void { if (a) { }; else { }; };")[0]
    assert isinstance(s, ast.IfStmt) and s.else_branch is not None


def test_while_con_break_y_continue():
    s = _body("fn f() -> void { while (a) { break; continue; }; };")[0]
    assert isinstance(s, ast.WhileStmt)
    assert isinstance(s.body.statements[0], ast.BreakStmt)
    assert isinstance(s.body.statements[1], ast.ContinueStmt)


def test_match_con_cases_en_bloque():
    """'case X { ... }': con llaves el ':' se omite (EBNF: case_arm)."""
    s = _body("fn f() -> void { match (c) { case Rojo { } case Azul { } } };")[0]
    assert isinstance(s, ast.MatchStmt) and len(s.cases) == 2


def test_match_case_pattern_no_come_el_bloque():
    """El patron de un 'case' no absorbe el '{' del cuerpo como literal."""
    s = _body("fn f() -> void { match (c) { case Origen { g(1); }; } };")[0]
    assert len(s.cases) == 1
    assert isinstance(s.cases[0].body, ast.Block)


def test_struct_literal_valido_dentro_de_un_patron():
    """La supresion se levanta dentro de delimitadores: 'case f(N{...})'."""
    s = _body("fn f() -> void { match (c) { case g(N{ v: 1 }) { }; } };")[0]
    assert len(s.cases) == 1


def test_match_case_con_dos_puntos():
    """'case X: stmt;': sin llaves el ':' es OBLIGATORIO."""
    s = _body("fn f() -> void { match (c) { case Rojo: x = 1; } };")[0]
    assert len(s.cases) == 1


def test_match_case_con_dos_puntos_y_bloque():
    """'case X: { ... }': la costumbre de C. El ':' sobra con llaves, pero
    escribirlo no puede caer en 'token inesperado en expresion: L_BRACE' —
    un bloque no es un 'statement' de la gramatica y ahi terminaba."""
    s = _body("fn f() -> void { match (c) { case Rojo: { x = 1; }; } };")[0]
    assert len(s.cases) == 1
    assert isinstance(s.cases[0].body, ast.Block)


def test_return_con_y_sin_valor():
    stmts = _body("fn f() -> void { return 1; };")
    assert isinstance(stmts[0], ast.ReturnStmt) and stmts[0].value is not None
    assert _body("fn f() -> void { return; };")[0].value is None


def test_bloque_suelto_no_es_sentencia():
    """La EBNF no lista 'block' en 'statement': un '{ }' suelto NO es valido
    (es lo que hace inequivoco reconocer 'Nodo{...}' como literal)."""
    _program, errors, _ = parse("fn f() -> void { { var int x = 1; }; };")
    assert errors, "un bloque suelto deberia ser un error de sintaxis"


# --------------------------------------------------------------------------- #
# statement: throw / try-catch, move / free (memoria)
# --------------------------------------------------------------------------- #

def test_throw_stmt():
    s = _body("fn f() -> void { throw 7; };")[0]
    assert isinstance(s, ast.ThrowStmt)


def test_try_catch():
    s = _body("fn f() -> void { try { throw 1; } catch (e) { }; };")[0]
    assert isinstance(s, ast.TryStmt)
    assert len(s.catches) == 1
    assert s.catches[0].name == "e", "el nombre del catch se liga en su bloque"
    assert s.catches[0].type is None, "'catch (e)' no filtra por tipo"


def test_try_con_varios_catch_tipados():
    """``catch (T e)``: cada rama filtra por tipo. El tipo es opcional y se
    decide con un lookahead de un token — dentro de los paréntesis, un solo
    nombre es el binding y dos cosas son tipo + binding."""
    s = _body("fn f() -> void { try { throw 1; } "
              "catch (Fallo f) { } catch (int n) { } catch (e) { }; };")[0]
    assert len(s.catches) == 3
    assert [c.name for c in s.catches] == ["f", "n", "e"]
    assert s.catches[0].type is not None and s.catches[1].type is not None
    assert s.catches[2].type is None


def test_move_stmt():
    s = _body("fn f() -> void { move x; };")[0]
    assert isinstance(s, ast.MoveStmt)


def test_free_stmt():
    """'free' es SENTENCIA, no expresión: nunca compone en aritmética."""
    s = _body("fn f() -> void { free p; };")[0]
    assert isinstance(s, ast.FreeStmt)


# --------------------------------------------------------------------------- #
# expression: precedencia, asociatividad, unarios, postfijos
# --------------------------------------------------------------------------- #

def test_precedencia_producto_sobre_suma():
    """'1 + 2 * 3' agrupa como '1 + (2 * 3)'."""
    e = _expr("1 + 2 * 3")
    assert isinstance(e, ast.BinaryOp) and e.operator == "+"
    assert isinstance(e.right, ast.BinaryOp) and e.right.operator == "*"


def test_asociatividad_izquierda_de_la_resta():
    """'1 - 2 - 3' agrupa como '(1 - 2) - 3'."""
    e = _expr("1 - 2 - 3")
    assert isinstance(e.left, ast.BinaryOp) and e.left.operator == "-"


def test_parentesis_ganan_a_la_precedencia():
    e = _expr("(1 + 2) * 3")
    assert e.operator == "*" and isinstance(e.left, ast.BinaryOp) and e.left.operator == "+"


def test_comparacion_bajo_aritmetica():
    """'a + 1 == b' agrupa como '(a + 1) == b'."""
    e = _expr("a + 1 == b")
    assert e.operator == "==" and isinstance(e.left, ast.BinaryOp)


def test_and_liga_mas_que_or():
    """'a or b and c' agrupa como 'a or (b and c)'."""
    e = _expr("a or b and c")
    assert e.operator == "or" and isinstance(e.right, ast.BinaryOp)
    assert e.right.operator == "and"


def test_unario_not_y_negacion():
    assert isinstance(_expr("not a"), ast.UnaryOp)
    assert isinstance(_expr("-a"), ast.UnaryOp)


def test_addr_of_es_expresion():
    """'&x' es un operador de expresión, nunca un modificador de tipo."""
    assert isinstance(_expr("&x"), ast.AddrOf)


def test_postfijos_encadenan():
    """'a.b(1)[2]' — miembro, llamada e índice se encadenan por la izquierda."""
    e = _expr("a.b(1)[2]")
    assert isinstance(e, ast.Index)
    assert isinstance(e.obj, ast.Call)
    assert isinstance(e.obj.callee, ast.MemberAccess)


def test_llamada_con_argumentos():
    e = _expr("f(1, 2, 3)")
    assert isinstance(e, ast.Call) and len(e.args) == 3


def test_cast_expr():
    e = _expr("cast<int8>(10)")
    assert isinstance(e, ast.CastExpr)


def test_sizeof_expr():
    e = _expr("sizeof(Nodo)")
    assert isinstance(e, ast.SizeofExpr)


# --------------------------------------------------------------------------- #
# struct_literal: desnudo y CUALIFICADO por su módulo
# --------------------------------------------------------------------------- #

def test_struct_literal_desnudo():
    e = _expr("Nodo{ v: 1, sig: null }")
    assert isinstance(e, ast.StructLiteral)
    assert e.type_name == "Nodo" and e.field_names == ["v", "sig"]


def test_struct_literal_coma_final():
    assert _expr("Nodo{ v: 1, }").field_names == ["v"]


def test_struct_literal_vacio():
    assert _expr("Vacio{ }").field_names == []


def test_struct_literal_cualificado():
    """Un struct de librería se instancia con su nombre cualificado."""
    e = _expr("point.Point{ x: 1, y: 2 }")
    assert isinstance(e, ast.StructLiteral)
    assert e.type_name == "point.Point"


def test_struct_literal_anidado():
    e = _expr("A{ b: B{ v: 1 } }")
    assert isinstance(e.values[0], ast.StructLiteral)


def test_llamada_no_se_confunde_con_literal():
    """'f(1){...}' no existe: tras una llamada, '{' ya no abre un literal."""
    program, errors, _ = parse("fn f() -> void { var int x = g(1); };")
    assert not errors


# --------------------------------------------------------------------------- #
# literales e interpolación
# --------------------------------------------------------------------------- #

def test_literales_de_cada_tipo():
    for src in ("10", "1.5", "'c'", '"hola"', "true", "false", "null"):
        _expr(src)  # basta con que parsee


def test_fstring_produce_interpolacion():
    """La interpolación es opt-in: solo f\"...\"."""
    e = _expr('f"hola {a}"')
    assert isinstance(e, ast.InterpolatedString)


def test_string_normal_no_interpola():
    e = _expr('"hola {a}"')
    assert not isinstance(e, ast.InterpolatedString)


# --------------------------------------------------------------------------- #
# 'make' dejó de ser palabra clave (se retiró con el modelo por regiones)
# --------------------------------------------------------------------------- #

def test_make_es_identificador_corriente():
    """'make' se retiró de KEYWORDS: es el nombre natural de una fábrica."""
    fn = _items("fn make(int n) -> int { return n; };")[0]
    assert fn.name == "make"
