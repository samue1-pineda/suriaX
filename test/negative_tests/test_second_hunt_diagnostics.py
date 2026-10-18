"""negative_tests/segunda caza: los diagnosticos del carril de semantica.

Cada prueba es un hallazgo de ``audit/caza2`` (``c_errorstfix.md`` §3b):
H01 (tipo del indice), H02 (aridad de las nativas), H04 (miembro de un
primitivo), A07 (firma de ``__eq__``), A01 (global con tipo de una libreria
con alias), A05 (``match`` sobre un ``E ptr``), A06 (cotas de un tipo, por
instancia), H05 (tapar lo que liga un patron) y los mensajes A03, A04 y H06.

Van por ``analyze`` y no por ``assert_ok``/``error_codes``: usan sintaxis y
reglas que la V1 todavia no conoce (``print`` variadico, por ejemplo).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze  # noqa: E402


def _errors(source: str):
    _, _, errors = analyze(source)
    return errors


def _codes(source: str) -> list:
    return [e.code for e in _errors(source)]


def _main(body: str, *, before: str = "") -> str:
    return before + "fn main() -> int {\n" + body + "    return 0;\n}\n"


_VEC = "#import array.vector as vec\n"
_V = "    var vec.Vector<int> v = vec.dynamic<int>(2);\n    v.push(10);\n"


# --------------------------------------------------------------------------- #
# H01: el tipo del indice
# --------------------------------------------------------------------------- #

def test_index_type_is_checked_against_index_hook():
    """``v["a"]`` era ICE000 y ``v[1.0]`` un EXC002 "fuera de rango"."""
    for index in ('"a"', "1.0", "true", "'c'"):
        codes = _codes(_main(_V + f"    var int a = v[{index}];\n", before=_VEC))
        assert codes == ["AST006"], (index, codes)


def test_index_set_type_is_checked_against_index_set_hook():
    codes = _codes(_main(_V + '    v["a"] = 3;\n', before=_VEC))
    assert codes == ["AST006"], codes


def test_string_index_must_be_int():
    for index in ("1.5", '"x"'):
        codes = _codes(_main(f'    var str s = "ab";\n    var char c = s[{index}];\n'))
        assert codes == ["AST006"], (index, codes)


def test_valid_indexes_still_compile():
    assert _codes(_main(_V + "    var int a = v[0];\n    v[0] = 3;\n"
                        '    var str s = "ab";\n    var char c = s[1];\n',
                        before=_VEC)) == []


def test_element_write_message_uses_contraction():
    """"a el elemento" -> "al elemento"."""
    errors = _errors(_main(_V + '    v[0] = "x";\n', before=_VEC))
    assert [e.code for e in errors] == ["AST006"]
    assert "al elemento" in errors[0].message, errors[0].message


# --------------------------------------------------------------------------- #
# H02: aridad de print/len/hash
# --------------------------------------------------------------------------- #

def test_print_without_arguments_is_sem008():
    assert _codes(_main("    print();\n")) == ["SEM008"]


def test_len_and_hash_take_exactly_one_argument():
    assert _codes(_main('    var int a = len("ab", "xyz");\n')) == ["SEM008"]
    assert _codes(_main("    var int h = hash(1, 2);\n")) == ["SEM008"]
    assert _codes(_main("    var int z = len();\n")) == ["SEM008"]


def test_variadic_print_checks_each_argument_is_printable():
    errors = _errors(_main('    print("q", Q{ y: 1 });\n',
                           before="struct { int y; } Q;\n"))
    assert [e.code for e in errors] == ["SEM001"]
    assert "__print__" in errors[0].message


def test_variadic_print_compiles_with_primitives_and_print_hooks():
    assert _codes(_main('    print("a", 1, 2.5, true, \'c\', P{ x: 1 });\n',
                        before="struct { int x; } P;\n"
                               "hook fn __print__(P ptr p) -> void { print(\"P\", p.x); }\n")) == []


def test_variadic_print_is_decomposed_into_single_argument_prints():
    """El HIR no cambia: la semantica lo descompone en 'print' de UN
    argumento separados por 'print(" ")'; la VM y el web no ven nada nuevo."""
    from include import ast_nodes as ast
    program, _, errors = analyze(_main("    var int n = 4;\n    print(\"n:\", n);\n"))
    assert errors == []
    main = next(i for i in program.items if getattr(i, "name", "") == "main")
    block = main.body.statements[1]
    assert isinstance(block, ast.Block), block
    args = [s.expr.args for s in block.statements]
    assert [len(a) for a in args] == [1, 1, 1]
    assert args[1][0].value == " "


def test_variadic_print_in_an_expression_is_sem008():
    """Solo como SENTENCIA: en una expresion se escribiria el primero y se
    tiraria el resto."""
    codes = _codes(_main("    var int x = 0;\n    x = print(1, 2);\n"))
    assert "SEM008" in codes, codes


def test_user_print_function_keeps_its_own_arity():
    src = ("fn print(int a, int b) -> void { }\n"
           "fn main() -> int { print(1, 2); return 0; }\n")
    assert _codes(src) == []


# --------------------------------------------------------------------------- #
# H04: metodo o campo sobre un primitivo
# --------------------------------------------------------------------------- #

def test_member_on_primitive_is_sem042_with_hint():
    cases = [
        ('    var str s = "ab";\n    var int n = s.len();\n', "len(s)"),
        ('    var str s = "ab";\n    var int n = s.length;\n', "len(s)"),
        ('    var str s = "ab";\n    var str u = s.upper();\n', "text.upper(s)"),
        ("    var int k = 3;\n    var int a = k.abs();\n", "print(k)"),
        ("    var float f = 1.5;\n    var float g = f.abs();\n", "math.abs(f)"),
    ]
    for body, hint in cases:
        errors = _errors(_main(body))
        assert [e.code for e in errors] == ["SEM042"], (body, errors)
        assert hint in errors[0].message, (hint, errors[0].message)


# --------------------------------------------------------------------------- #
# A07: firma de __eq__
# --------------------------------------------------------------------------- #

def test_eq_hook_second_parameter_must_be_owner_ptr():
    src = ("struct { int id; } Q;\n"
           "hook fn __eq__(Q ptr a, int b) -> bool { return a.id == b; }\n"
           "fn main() -> int { return 0; }\n")
    errors = _errors(src)
    assert [e.code for e in errors] == ["SEM006"], errors
    assert "se comparan" in errors[0].message


def test_eq_hook_with_valid_signature_compiles():
    src = ("struct { int id; } Q;\n"
           "hook fn __eq__(Q ptr a, Q ptr b) -> bool { return a.id == b.id; }\n"
           "fn main() -> int { return 0; }\n")
    assert _codes(src) == []


# --------------------------------------------------------------------------- #
# A01: global con tipo de una libreria importada con alias
# --------------------------------------------------------------------------- #

def test_global_typed_with_aliased_library_type_unifies():
    src = ("#import excepciones as exc\n"
           "fn before() -> void { var exc.ValorInvalido y = g; }\n"
           "var exc.ValorInvalido g = exc.ValorInvalido{ mensaje: \"m\" };\n"
           "fn main() -> int {\n"
           "    var exc.ValorInvalido x = exc.ValorInvalido{ mensaje: \"n\" };\n"
           "    x = g;\n    return 0;\n}\n")
    assert _codes(src) == []


# --------------------------------------------------------------------------- #
# A05: SEM030 sobre un 'E ptr'
# --------------------------------------------------------------------------- #

def test_match_on_enum_pointer_warns_missing_variants():
    src = ("enum E { A(int), B, C };\n"
           "fn by_ptr(E ptr e) -> int {\n"
           "    match (e) {\n"
           "        case E.A(n) { return n; }\n"
           "        case E.B { return -1; }\n"
           "    };\n    return 0;\n}\n"
           "fn main() -> int { return 0; }\n")
    assert _codes(src) == ["SEM030"]


# --------------------------------------------------------------------------- #
# A06: Ord/Hash de un tipo acotado, por instancia
# --------------------------------------------------------------------------- #

_BOXES = ("struct { T v; } Box<T: Ord>;\n"
          "struct { T v; } HBox<T: Hash>;\n"
          "struct { T v; } PBox<T: Print>;\n")


def test_bounded_type_from_unbounded_generic_is_checked_per_instance():
    src = _BOXES + (
        "fn boxed<U>(U a) -> int { var Box<U> b = Box<U>{ v: a }; return 1; }\n"
        "fn sig<U>(Box<U> b) -> int { return 1; }\n"
        # en la FIRMA, fuera del primer parametro (que es receptor y ya da
        # la cota implicita): el retorno y un segundo parametro
        "fn ret<U>(U a) -> Box<U> { return Box<U>{ v: a }; }\n"
        "fn second<U>(int x, Box<U> b) -> int { return x; }\n"
        "fn hashed<U>(U a) -> int { var HBox<U> h = HBox<U>{ v: a }; return 1; }\n"
        "fn main() -> int {\n"
        "    var int a = boxed(3);\n"
        "    var int b = sig(Box<int>{ v: 1 });\n"
        "    var Box<int> r = ret(4);\n"
        "    var int s = second(1, Box<int>{ v: 2 });\n"
        "    var int c = hashed(\"s\");\n"
        "    return 0;\n}\n")
    assert _codes(src) == []


def test_bounded_type_instance_that_fails_reports_at_the_call():
    src = _BOXES + (
        "fn boxed<U>(U a) -> int { var Box<U> b = Box<U>{ v: a }; return 1; }\n"
        "fn hashed<U>(U a) -> int { var HBox<U> h = HBox<U>{ v: a }; return 1; }\n"
        "fn main() -> int {\n"
        "    var int a = boxed(true);\n"
        "    var int c = hashed(1.5);\n"
        "    return 0;\n}\n")
    assert _codes(src) == ["SEM039", "AST006"]


def test_print_bound_and_type_declarations_stay_sem043():
    src = _BOXES + (
        "fn printed<U>(U a) -> int { var PBox<U> p = PBox<U>{ v: a }; return 1; }\n"
        "struct { Box<U> b; } Outer<U>;\n"
        "fn main() -> int { return 0; }\n")
    assert _codes(src) == ["SEM043", "SEM043", "SEM043"]


# --------------------------------------------------------------------------- #
# H05: tapar lo que liga un patron
# --------------------------------------------------------------------------- #

def test_shadowing_a_case_binding_is_sem002():
    src = ("enum F { C(int), N };\n" + _main(
        "    var int? x = 1;\n"
        "    match (x) {\n"
        "        case v { var str v = \"t\"; }\n"
        "        case null { }\n"
        "    };\n"
        "    match (F.C(4)) {\n"
        "        case F.C(r) { var str r = \"t\"; }\n"
        "        case F.N { var int r = 2; }\n"
        "    };\n"))
    assert _codes(src) == ["SEM002", "SEM002"]


def test_nested_block_inside_case_may_shadow():
    src = _main("    var int? x = 1;\n"
                "    match (x) {\n"
                "        case v { if (true) { var str v = \"t\"; } }\n"
                "        case null { }\n"
                "    };\n")
    assert _codes(src) == []


# --------------------------------------------------------------------------- #
# A03, A04, H06: mensajes
# --------------------------------------------------------------------------- #

def test_break_and_expect_inside_lambda_name_the_lambda():
    src = (_VEC + "fn main() -> int {\n" + _V +
           "    while (true) {\n"
           "        v.sort_by(lambda (int ptr a, int ptr b) -> int {\n"
           "            if (a[0] == b[0]) { break; }\n"
           "            return 0;\n"
           "        });\n"
           "    }\n    return 0;\n}\n"
           "test \"t\" {\n" + _V +
           "    v.sort_by(lambda (int ptr a, int ptr b) -> int {\n"
           "        expect (a[0] != b[0]);\n"
           "        return 0;\n"
           "    });\n}\n")
    errors = _errors(src)
    assert [e.code for e in errors] == ["PAR013", "PAR013"], errors
    assert all("lambda" in e.message for e in errors), errors


def test_break_in_lambda_without_outer_loop_keeps_plain_message():
    src = (_VEC + "fn main() -> int {\n" + _V +
           "    v.sort_by(lambda (int ptr a, int ptr b) -> int {\n"
           "        if (a[0] == 1) { continue; }\n"
           "        return 0;\n"
           "    });\n    return 0;\n}\n")
    errors = _errors(src)
    assert [e.code for e in errors] == ["PAR013"]
    assert "lambda" not in errors[0].message


def test_yielding_a_case_binding_does_not_talk_about_a_pointer():
    src = ("struct { int id; } R;\n"
           "hook fn __free__(R ptr r) -> void { }\n"
           "fn f(R? o) -> R {\n"
           "    match (o) {\n"
           "        case null { }\n"
           "        case v { return v; }\n"
           "    };\n"
           "    return R{ id: 0 };\n}\n"
           "fn main() -> int { return 0; }\n")
    errors = _errors(src)
    assert [e.code for e in errors] == ["SEM036"]
    message = errors[0].message
    assert "patron" in message and "'o'" in message, message
    assert "puntero" not in message and "&v" not in message, message


def test_operators_from_other_languages_give_a_hint():
    cases = [
        ("var int x = b ? 1 : 2;", "PAR012", "if"),
        ("var int x = (b ? 1 : 2);", "PAR012", "if"),
        ("if (b && n > 1) { }", "PAR012", "and"),
        ("if (b || n > 1) { }", "PAR012", "or"),
        ("if (!b) { }", "LEX001", "not"),
    ]
    for statement, code, hint in cases:
        errors = _errors(_main("    var bool b = true;\n    var int n = 3;\n"
                               f"    {statement}\n"))
        assert errors and errors[0].code == code, (statement, errors)
        assert f"'{hint}" in errors[0].message, (statement, errors[0].message)


def test_real_operators_next_to_those_still_parse():
    """``??`` sigue siendo un operador, y ``a & &b`` CON espacio no es '&&'."""
    assert _codes(_main("    var int? o = null;\n    var int y = o ?? 3;\n"
                        "    var int n = 3;\n    var int z = n & 3;\n"
                        "    var int w = n | 1;\n")) == []
    codes = _codes(_main("    var int n = 3;\n    var int z = n & &n;\n"))
    assert "PAR012" not in codes, codes
