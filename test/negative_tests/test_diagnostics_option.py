"""negative_tests/diagnostics: desenvolver un ``T?`` y los enums genéricos.

Cada regla del paso 3 ("Option") con su código y su POSICIÓN (línea,
columna), nunca el texto. Los programas válidos no dan nada.

- ``match`` sobre un ``T?``: ``case v`` LIGA un nombre nuevo; uno que ya
  existe es ambiguo (comparar o ligar) y es ``SEM002``. Lo que no entra en
  ninguna rama (``null``, o una variante de un ``E?``) es ``SEM030`` (aviso),
  la regla del ``match`` sobre un enum. Una rama detrás de ``case v`` no se
  ejecuta nunca (``SEM046``), salvo ``case null``. ``v`` es el contenido
  PRESTADO: cederlo es ``SEM036`` y copiarlo con destructor ``SEM032``.
- ``x ?? d``: ``x`` es un ``T?`` y ``d`` exactamente un ``T`` (``AST006``);
  con un contenido con destructor, ``SEM032`` (en un genérico, ``SEM038`` en
  la instancia).
- enum genérico: las variantes se escriben con sus argumentos (``SEM027``
  si faltan, sobran o se escribe pelada), y una instancia no es otra
  (``AST006``).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze  # noqa: E402


def _diagnostics(source: str) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errors = analyze(source)
    return [(e.code, e.line, e.column) for e in errors]


def _expect(source: str, expected: list) -> None:
    got = _diagnostics(source)
    assert got == expected, f"se esperaba {expected}; se obtuvo {got}"


def assert_ok(source: str) -> None:
    """Compila sin ningún diagnóstico. Va por ``analyze`` y no por
    ``helpers.assert_ok`` a propósito: lo que pasa por ``error_codes`` entra
    en el corpus del diferencial V0/V1 (``bootstrap/test_diagnosticos_v1``),
    y la V1 todavía no conoce ``??``, ``case v`` ni los enums genéricos (la
    V1 se pone al día después, decisión del mantenedor)."""
    _expect(source, [])


def _main(body: str, before: str = "") -> str:
    """``before`` + ``fn main`` con ``body`` en la línea 2 (si ``before``
    ocupa una línea, en la 3)."""
    return before + "fn main() -> int {\n" + body + "\n    return 0;\n}\n"


R = ("struct { int n; } R;\n"
     "hook fn __free__(R ptr mutable r) -> void { }\n")
E = "enum E { A(int), B, C };\n"
RES = "enum Res<T, E> { Ok(T), Err(E), Vacio };\n"


# --------------------------------------------------------------------------- #
# match sobre un T?
# --------------------------------------------------------------------------- #

def test_valid_optional_matches_give_nothing():
    assert_ok(_main("    var int? x = 2;\n"
                    "    match (x) { case null { } case v { var int y = v; } };\n"
                    "    match (x) { case null { } case 7 { } };\n"
                    "    match (x) { case 7 { } case null { } case v { } };"))
    assert_ok(_main("    var E? x = E.B;\n"
                    "    match (x) { case null { } case E.A(n) { } case B { } case E.C { } };",
                    before=E))


def test_case_with_an_existing_name_is_ambiguous():
    """``case v`` con ``v`` ya declarada: en un ``match`` sobre un ``int``
    compara con ``v``, aquí ligaría otra. Ni una ni otra en silencio."""
    _expect(_main("    var int v = 1;\n"
                  "    var int? x = 2;\n"
                  "    match (x) { case null { } case v { } };"),
            [("SEM002", 4, 36)])


def test_a_missing_case_null_is_sem030():
    _expect(_main("    var int? x = 2;\n"
                  "    match (x) { case v { } };"),
            [("SEM030", 3, 5)])


def test_a_missing_variant_of_an_optional_enum_is_sem030():
    _expect(_main("    var E? x = E.B;\n"
                  "    match (x) { case null { } case E.A(n) { } case E.B { } };",
                  before=E),
            [("SEM030", 4, 5)])


def test_case_v_covers_every_variant():
    assert_ok(_main("    var E? x = E.B;\n"
                    "    match (x) { case null { } case E.A(n) { } case v { } };",
                    before=E))


def test_an_arm_after_case_v_never_runs():
    """``case 3`` detrás de ``case v`` no corre nunca; ``case null`` sí."""
    _expect(_main("    var int? x = 2;\n"
                  "    match (x) { case v { } case 3 { } case null { } };"),
            [("SEM046", 3, 28)])


def test_case_v_cannot_be_given_away():
    """``v`` es el contenido PRESTADO, como el payload de ``case E.A(x)``."""
    _expect(_main("    var R? x = R{ n: 1 };\n"
                  "    match (x) { case null { } case v { var R r = move v; } };",
                  before=R),
            [("SEM036", 5, 55)])
    _expect(R + "fn f(R? x) -> R {\n"
            "    match (x) { case null { } case v { return v; } };\n"
            "    return R{ n: 0 };\n"
            "}\n"
            "fn main() -> int { return 0; }\n",
            [("SEM036", 4, 47)])


def test_case_v_cannot_be_copied_if_it_owns():
    _expect(_main("    var R? x = R{ n: 1 };\n"
                  "    match (x) { case null { } case v { var R r = v; } };",
                  before=R),
            [("SEM032", 5, 40)])


def test_case_v_is_not_reassigned_and_follows_its_subject():
    _expect(_main("    var int? x = 1;\n"
                  "    match (x) { case null { } case v { v = 3; } };"),
            [("SEM003", 3, 40)])
    _expect(_main("    const S? x = S{ n: 1 };\n"
                  "    match (x) { case null { } case v { v.n = 3; } };",
                  before="struct { int n; } S;\n"),
            [("SEM003", 4, 40)])


# --------------------------------------------------------------------------- #
# x ?? d
# --------------------------------------------------------------------------- #

def test_valid_null_coalesce_gives_nothing():
    assert_ok(_main("    var int? x = null;\n"
                    "    var int? y = 3;\n"
                    "    var int a = x ?? 1;\n"
                    "    var int b = x ?? y ?? 2;\n"
                    "    var bool c = (x ?? 1) == 1 or false;"))


def test_null_coalesce_on_a_value_that_cannot_be_null():
    _expect(_main("    var int x = 1;\n"
                  "    var int y = x ?? 2;"),
            [("AST006", 3, 17)])


def test_null_coalesce_default_must_be_exactly_the_content():
    _expect(_main("    var int? x = 1;\n"
                  "    var int y = x ?? 2.5;"),
            [("AST006", 3, 22)])
    # un 'T?' de defecto tampoco: el resultado tiene que ser un 'T'
    _expect(_main("    var int? x = 1;\n"
                  "    var int? z = 2;\n"
                  "    var int y = x ?? z;"),
            [("AST006", 4, 22)])
    # ni soltar 'mutable'
    _expect(_main("    var int n = 1;\n"
                  "    var int ptr? q = null;\n"
                  "    var int ptr p = q ?? &n;"),
            [("AST006", 4, 26)])


def test_null_coalesce_default_cannot_be_null():
    _expect(_main("    var int? x = 1;\n"
                  "    var int? y = x ?? null;"),
            [("AST006", 3, 23)])


def test_null_coalesce_on_the_null_literal():
    _expect(_main("    var int y = null ?? 2;"), [("AST006", 2, 17)])


def test_null_coalesce_gives_the_content_type():
    _expect(_main("    var int? x = 1;\n"
                  "    var str s = x ?? 2;"),
            [("AST006", 3, 5)])


def test_null_coalesce_does_not_copy_an_owner():
    _expect(_main("    var R? x = R{ n: 1 };\n"
                  "    var R y = x ?? R{ n: 2 };",
                  before=R),
            [("SEM032", 5, 15)])


def test_null_coalesce_in_a_generic_is_checked_per_instance():
    _expect(R + "fn f<T>(T? x, T d) -> T { return x ?? d; }\n"
            + _main("    var int i = f<int>(null, 3);\n"
                    "    var R r = f<R>(null, R{ n: 1 });"),
            [("SEM038", 6, 15)])


# --------------------------------------------------------------------------- #
# enum genérico
# --------------------------------------------------------------------------- #

def test_valid_generic_enum_gives_nothing():
    assert_ok(RES + "fn ok<T>(T x) -> Res<T, str> { return Res<T, str>.Ok(x); }\n"
              + _main("    var Res<int, str> r = Res<int, str>.Ok(5);\n"
                      "    var Res<int, str> s = ok<int>(3);\n"
                      "    var Res<int, int> t = Res<int, int>.Vacio;\n"
                      "    match (r) {\n"
                      "        case Res<int, str>.Ok(v) { var int w = v; }\n"
                      "        case Res<int, str>.Err(m) { var str w = m; }\n"
                      "        case Res<int, str>.Vacio { }\n"
                      "    };"))


def test_a_generic_variant_needs_its_type_arguments():
    _expect(_main("    var Res<int, str> r = Res.Ok(5);", before=RES),
            [("SEM027", 3, 27)])
    _expect(_main("    var Res<int, str> r = Res.Vacio;", before=RES),
            [("SEM027", 3, 27)])


def test_a_bare_generic_variant_is_sem027():
    _expect(_main("    var Res<int, str> r = Ok(5);", before=RES),
            [("SEM027", 3, 27)])
    _expect(_main("    var Res<int, str> r = Vacio;", before=RES),
            [("SEM027", 3, 27)])


def test_generic_variant_arity_and_non_generic_enum():
    _expect(_main("    var Res<int, str> r = Res<int>.Ok(5);", before=RES),
            [("SEM027", 3, 27)])
    _expect(_main("    var Color c = Color<int>.ROJO;",
                  before="enum Color { ROJO, VERDE };\n"),
            [("SEM027", 3, 19)])


def test_generic_variant_payload_is_substituted():
    _expect(_main("    var Res<int, str> r = Res<int, str>.Ok(\"x\");", before=RES),
            [("AST006", 3, 44)])


def test_two_instances_are_two_types():
    _expect(_main("    var Res<int, str> r = Res<str, int>.Ok(\"a\");", before=RES),
            [("AST006", 3, 5)])
    _expect(_main("    var Res<int, str> r = Res<int, str>.Vacio;\n"
                  "    match (r) {\n"
                  "        case Res<str, int>.Ok(x) { }\n"
                  "        case Res<int, str>.Err(e) { }\n"
                  "        case Res<int, str>.Vacio { }\n"
                  "    };", before=RES),
            [("AST006", 5, 14)])


def test_generic_enum_match_is_exhaustive_like_any_enum():
    _expect(_main("    var Res<int, str> r = Res<int, str>.Vacio;\n"
                  "    match (r) { case Res<int, str>.Ok(x) { } case Res<int, str>.Vacio { } };",
                  before=RES),
            [("SEM030", 4, 5)])


def test_a_generic_enum_owns_what_its_payload_owns():
    _expect(_main("    var Res<R, int> a = Res<R, int>.Ok(R{ n: 1 });\n"
                  "    var Res<R, int> b = a;", before=R + RES),
            [("SEM032", 6, 5)])
    assert_ok(_main("    var Res<int, int> a = Res<int, int>.Ok(1);\n"
                    "    var Res<int, int> b = a;", before=RES))


def test_a_repeated_type_parameter_is_sem002():
    """``Par<T, T>``: el segundo tapaba al primero y ``Par<int, str>``
    ligaba ``T`` a ``str``, en silencio. Vale para struct y enum."""
    _expect("enum Par<T, T> { A(T) };\nfn main() -> int { return 0; }\n",
            [("SEM002", 1, 1)])
    _expect("struct { T a; } Par<T, T>;\nfn main() -> int { return 0; }\n",
            [("SEM002", 1, 1)])
