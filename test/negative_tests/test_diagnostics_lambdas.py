"""negative_tests/diagnostics: lambdas que no escapan (paso 6 del análisis de
paradigmas).

``lambda (int ptr x) -> bool: x[0] > 3`` (forma corta) y
``lambda (int ptr x) -> bool { ...; return ...; }`` (forma de bloque), con los
tipos SIEMPRE escritos.

- Solo vale como ARGUMENTO de una llamada cuyo parámetro está escrito como
  ``fn(...) -> R``; en cualquier otro sitio (una variable, un campo, un
  ``return``, un ``T``, un ``(fn...)?``, un prototipo) es ``SEM050``.
- Un parámetro de tipo función es PRESTADO: solo se llama o se pasa a otro
  parámetro de tipo función; guardarlo, devolverlo, compararlo o pasarlo a
  un ``T`` es ``SEM051``. Es lo que impide que la función que recibe una
  lambda la haga escapar.
- Su tipo es ``fn(A) -> R`` y se comprueba como el de una función con nombre
  (``AST006``, ``SEM008``); participa en la deducción.
- Captura implícita de SOLO LECTURA: asignar, mover, liberar, llamar a un
  método que modifica o escribir a través de un puntero capturado es
  ``SEM003``/``SEM015``; ceder (``return``) algo con destructor capturado es
  ``SEM036``; ``&x`` de algo capturado es un ``ptr`` de solo lectura.
- ``return`` devuelve de la lambda (``AST012`` contra SU retorno) y
  ``break``/``continue`` no la cruzan (``PAR013``).

Todo va por ``analyze`` y no por ``helpers.error_codes``/``assert_ok``: lo
que pasa por ``error_codes`` entra en el corpus del diferencial V0/V1
(``bootstrap/test_diagnosticos_v1``), y la V1 todavía no conoce esta sintaxis.

Se comprueban el CÓDIGO, la POSICIÓN y que no salga NADA más.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze, parse  # noqa: E402


def _diagnostics(source: str) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errors = analyze(source)
    return [(e.code, e.line, e.column) for e in errors]


def _expect(source: str, expected: list) -> None:
    got = _diagnostics(source)
    assert got == expected, f"se esperaba {expected}; se obtuvo {got}"


def _main(body: str, before: str = "") -> str:
    return before + "fn main() -> int {\n" + body + "\n    return 0;\n}\n"


APPLY = "fn apply(fn(int) -> int f, int v) -> int { return f(v); }\n"     # 1
VEC = "#import array.vector as vec\n#import func\n"
R = ("struct { int id; } R;\n"                                              # 1
     "hook fn __free__(R ptr r) -> void { }\n"                              # 2
     "fn take(R r) -> void { }\n")                                          # 3


# --------------------------------------------------------------------------- #
# 1. sintaxis: las dos formas, solo en posicion de expresion
# --------------------------------------------------------------------------- #

def test_both_forms_parse_into_one_node_with_a_block_body():
    from include import ast_nodes as ast
    program, errors, lex_errors = parse(_main(
        "    apply(lambda (int x) -> int: x + 1, 2);\n"
        "    apply(lambda (int x) -> int { var int y = x; return y; }, 2);",
        before=APPLY))
    assert errors == [] and lex_errors == [], (errors, lex_errors)
    main = program.items[1]
    short, block = (s.expr.args[0] for s in main.body.statements[:2])
    assert isinstance(short, ast.Lambda) and short.short
    assert isinstance(block, ast.Lambda) and not block.short
    # la forma corta es '{ return e; }'
    assert [type(s).__name__ for s in short.body.statements] == ["ReturnStmt"]
    assert [type(s).__name__ for s in block.body.statements] == ["VarDecl",
                                                                 "ReturnStmt"]
    assert [p.name for p in short.params] == ["x"]


def test_a_short_void_lambda_is_its_expression_alone():
    from include import ast_nodes as ast
    program, errors, lex_errors = parse(_main(
        "    each(lambda (int x) -> void: show(x));",
        before="fn each(fn(int) -> void f) -> void { f(1); }\n"
               "fn show(int x) -> void { }\n"))
    assert errors == [] and lex_errors == [], (errors, lex_errors)
    lam = program.items[2].body.statements[0].expr.args[0]
    assert [type(s).__name__ for s in lam.body.statements] == ["ExprStmt"]


def test_lambda_is_a_reserved_word():
    _expect("fn main() -> int {\n    var int lambda = 1;\n    return 0;\n}\n",
            [("PAR003", 2, 13)])


def test_the_return_type_is_always_written():
    _expect(_main("    apply(lambda (int x): x, 2);", before=APPLY),
            [("PAR003", 3, 25)])


def test_a_lambda_without_a_body_is_par003():
    _expect(_main("    apply(lambda (int x) -> int, 2);", before=APPLY),
            [("PAR003", 3, 32)])


def test_break_and_continue_do_not_cross_a_lambda():
    _expect(_main("    while (true) {\n"
                  "        apply(lambda (int x) -> int { break; return x; }, 1);\n"
                  "    }", before=APPLY),
            [("PAR013", 4, 39)])
    _expect(_main("    while (true) {\n"
                  "        apply(lambda (int x) -> int { continue; return x; }, 1);\n"
                  "    }", before=APPLY),
            [("PAR013", 4, 39)])


def test_a_loop_inside_the_lambda_has_its_own_break():
    _expect(_main("    apply(lambda (int x) -> int {\n"
                  "        while (true) { break; }\n"
                  "        return x;\n"
                  "    }, 1);", before=APPLY), [])


def test_return_inside_a_finally_is_the_lambdas_own():
    """El 'return' de una lambda escrita dentro de un 'finally' no sale del
    'finally': devuelve de la lambda."""
    _expect(_main("    try { apply(lambda (int x) -> int: x, 1); }\n"
                  "    finally { apply(lambda (int x) -> int { return x; }, 1); }",
                  before=APPLY), [])


# --------------------------------------------------------------------------- #
# 2. su tipo: fn(A) -> R, comprobado como una funcion con nombre
# --------------------------------------------------------------------------- #

def test_a_lambda_is_checked_against_the_parameter_like_a_named_function():
    _expect(_main("    apply(lambda (int x) -> bool: x > 0, 1);\n"
                  "    apply(lambda (int x, int y) -> int: x, 1);\n"
                  "    apply(lambda (str x) -> int: 0, 1);", before=APPLY),
            [("AST006", 3, 11), ("AST006", 4, 11), ("AST006", 5, 11)])


def test_return_returns_from_the_lambda_with_its_type():
    _expect(_main("    apply(lambda (int x) -> int { return \"no\"; }, 1);",
                  before=APPLY), [("AST012", 3, 35)])
    # y no del 'main' que la contiene: 'return 5' es el 'int' de la lambda
    _expect("fn main() -> void {\n"
            "    apply(lambda (int x) -> int { return 5; }, 1);\n"
            "}\n" + APPLY, [])


def test_a_lambda_takes_part_in_type_deduction():
    _expect(VEC + _main(
        "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"
        "    var vec.Vector<str> s = func.map(&v, lambda (int ptr x) -> str: f\"{x[0]}\");\n"
        "    var int n = func.fold(&v, 0, lambda (int a, int ptr x) -> int: a + x[0]);"),
        [])


def test_a_deduction_conflict_from_a_lambda_is_ast007():
    _expect(VEC + _main(
        "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"
        "    var int n = func.fold(&v, 0, lambda (str a, int ptr x) -> str: a);"),
        [("AST007", 5, 17)])


# --------------------------------------------------------------------------- #
# 3. solo como argumento de un parametro escrito fn(...) -> R: SEM050
# --------------------------------------------------------------------------- #

def test_a_lambda_outside_an_argument_is_sem050():
    _expect(_main("    var fn(int) -> int g = lambda (int x) -> int: x;",
                  before=APPLY), [("SEM050", 3, 28)])
    _expect("struct { fn(int) -> int f; } C;\n"
            "fn main() -> int {\n"
            "    var C c = C{ f: lambda (int x) -> int: x };\n"
            "    return 0;\n}\n", [("SEM050", 3, 21)])
    _expect("fn g() -> fn(int) -> int { return lambda (int x) -> int: x; }\n",
            [("SEM050", 1, 35)])
    _expect(_main("    lambda (int x) -> int: x;"), [("SEM050", 2, 5)])


def test_a_lambda_compared_or_in_an_fstring_is_sem050():
    _expect(_main("    var bool b = (lambda (int x) -> int: x) == (lambda (int y) -> int: y);\n"
                  "    var str s = f\"{(lambda (int x) -> int: x)}\";"),
            [("SEM050", 2, 19), ("SEM050", 2, 49), ("SEM050", 3, 21)])
    # sin parentesis, el ':' de la forma corta es el del FORMATO de la
    # interpolacion (como en Python): no llega a ser una lambda
    _expect(_main("    var str s = f\"{lambda (int x) -> int: x}\";"),
            [("PAR012", 2, 20)])


def test_the_short_body_extends_as_far_as_it_can():
    """Como en Python, el cuerpo corto llega hasta donde llega la expresion:
    'lambda (...) -> int: x == lambda ...' compara DENTRO del cuerpo."""
    _expect(_main("    var bool b = lambda (int x) -> int: x == lambda (int y) -> int: y;"),
            [("SEM050", 2, 18), ("SEM050", 2, 46), ("AST006", 2, 41),
             ("AST012", 2, 41), ("AST006", 2, 5)])


def test_a_lambda_to_a_type_parameter_is_sem050():
    """Un 'T' instanciado con un tipo funcion sigue siendo un 'T': el cuerpo
    del generico puede guardarlo."""
    _expect(_main("    var int n = id(lambda (int x) -> int: x)(1);",
                  before="fn id<T>(T x) -> T { return x; }\n"),
            [("SEM050", 3, 20)])


def test_a_lambda_to_an_optional_function_parameter_is_sem050():
    _expect(_main("    keep(lambda (int x) -> int: x);",
                  before="fn keep((fn(int) -> int)? f) -> void { }\n"),
            [("SEM050", 3, 10)])


def test_a_lambda_to_a_prototype_is_sem050():
    """El cuerpo de un prototipo lo pone el host, que podria guardarla."""
    _expect(_main("    host(lambda (int x) -> int: x);",
                  before="fn host(fn(int) -> int f) -> void;\n"),
            [("SEM050", 3, 10)])


def test_a_lambda_to_print_or_a_variant_is_sem050():
    _expect(_main("    print(lambda (int x) -> int: x);"),
            [("SEM001", 2, 5), ("SEM050", 2, 11)])
    _expect("enum E { A(fn(int) -> int) };\n" + _main(
        "    var E e = E.A(lambda (int x) -> int: x);"),
        [("SEM050", 3, 19)])


def test_a_call_with_the_wrong_arity_does_not_also_report_the_lambda():
    _expect(_main("    apply(lambda (int x) -> int: x);", before=APPLY),
            [("SEM008", 3, 5)])


def test_lambdas_reach_methods_values_and_bounded_methods():
    """La regla es la del parametro DECLARADO, venga la llamada de donde
    venga: un metodo de una libreria, un valor funcion, un metodo de una
    cota."""
    _expect(VEC + _main(
        "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"
        "    v.sort_by(lambda (int ptr a, int ptr b) -> int: b[0] - a[0]);\n"
        "    var vec.Vector<int> w = v.filter(lambda (int ptr x) -> bool: x[0] > 1);\n"
        "    var fn(fn(int) -> int, int) -> int ap = apply;\n"
        "    var int n = ap(lambda (int x) -> int: x, 3);", before=APPLY), [])
    _expect("@trait struct { fn run(self ptr s, fn(int) -> int f) -> int; } Runs;\n"
            "@impl(Runs) struct { int n; } B;\n"
            "@impl B { fn run(B ptr self, fn(int) -> int f) -> int { return f(self.n); } }\n"
            "fn go<T: Runs>(T ptr t) -> int { return t.run(lambda (int x) -> int: x); }\n",
            [])


# --------------------------------------------------------------------------- #
# 4. un parametro de tipo funcion es prestado: SEM051
# --------------------------------------------------------------------------- #

def test_storing_or_returning_a_function_parameter_is_sem051():
    _expect("struct { fn(int) -> int f; } C;\n"
            "fn keep(fn(int) -> int f) -> C { return C{ f: f }; }\n"
            "fn give(fn(int) -> int f) -> fn(int) -> int { return f; }\n"
            "fn copy(fn(int) -> int f) -> int { var fn(int) -> int g = f; return g(1); }\n",
            [("SEM051", 2, 47), ("SEM051", 3, 54), ("SEM051", 4, 59)])


def test_comparing_or_writing_a_function_parameter_is_sem051():
    _expect("fn same(fn(int) -> int f, fn(int) -> int g) -> bool { return f == g; }\n"
            "fn text(fn(int) -> int f) -> str { return f\"{f}\"; }\n",
            [("SEM051", 1, 62), ("SEM051", 1, 67), ("SEM051", 2, 46)])


def test_passing_a_function_parameter_to_a_type_parameter_is_sem051():
    _expect("fn id<T>(T x) -> T { return x; }\n"
            "fn leak(fn(int) -> int f) -> int { return id(f)(1); }\n",
            [("SEM051", 2, 46)])


def test_calling_or_passing_a_function_parameter_on_is_fine():
    _expect(APPLY +
            "fn twice(fn(int) -> int f, int v) -> int { return apply(f, apply(f, v)); }\n"
            "fn inner(fn(int) -> int f) -> int {\n"
            "    return apply(lambda (int x) -> int: f(x) + 1, 1);\n"
            "}\n", [])


def test_an_optional_function_parameter_can_be_stored():
    """El camino para guardar una funcion que se recibe: '(fn...)?', que no
    admite lambdas."""
    _expect("struct { (fn(int) -> int)? f; } C;\n"
            "fn keep((fn(int) -> int)? f) -> C { return C{ f: f }; }\n", [])


def test_a_lambda_parameter_of_function_type_is_borrowed_too():
    _expect("fn outer(fn(fn(int) -> int) -> int g) -> int {\n"
            "    return g(lambda (int x) -> int: x);\n"
            "}\n"
            "fn main() -> int {\n"
            "    return outer(lambda (fn(int) -> int h) -> int: h(2));\n"
            "}\n", [])
    _expect("fn outer(fn(fn(int) -> int) -> int g) -> int { return 0; }\n"
            "fn main() -> int {\n"
            "    return outer(lambda (fn(int) -> int h) -> int { var fn(int) -> int k = h; return 0; });\n"
            "}\n", [("SEM051", 3, 76)])


# --------------------------------------------------------------------------- #
# 5. captura de solo lectura
# --------------------------------------------------------------------------- #

def test_a_lambda_reads_locals_parameters_and_globals():
    _expect("var int G = 1;\n" + APPLY +
            "fn f(int p) -> int {\n"
            "    var int k = 2;\n"
            "    return apply(lambda (int x) -> int: x + p + k + G, 1);\n"
            "}\n", [])


def test_assigning_a_capture_is_sem003():
    _expect(_main("    var int n = 0;\n"
                  "    apply(lambda (int x) -> int { n = x; return x; }, 1);\n"
                  "    apply(lambda (int x) -> int { n += 1; return x; }, 1);",
                  before=APPLY),
            [("SEM003", 4, 35), ("SEM003", 5, 35)])


def test_a_global_is_not_a_capture_and_can_be_assigned():
    _expect("var int G = 0;\n" + APPLY + _main(
        "    apply(lambda (int x) -> int { G = x; return x; }, 1);"), [])


def test_the_lambdas_own_locals_and_parameters_are_writable():
    _expect(_main("    apply(lambda (int x) -> int { var int y = 1; y = 2; x = 3; return x + y; }, 1);",
                  before=APPLY), [])


def test_moving_or_freeing_a_capture_is_sem003():
    _expect(R + APPLY + _main(
        "    var R r = R{ id: 1 };\n"
        "    var int ptr p = mem_ptr();\n"
        "    apply(lambda (int x) -> int { take(move r); return x; }, 1);\n"
        "    apply(lambda (int x) -> int { move r; return x; }, 1);\n"
        "    apply(lambda (int x) -> int { free p; return x; }, 1);",
        before="fn mem_ptr() -> int ptr;\n"),
        [("SEM003", 9, 40), ("SEM003", 10, 35), ("SEM003", 11, 35)])


def test_moving_the_lambdas_own_owner_parameter_is_fine():
    _expect(R + _main(
        "    eat(lambda (R r) -> int { take(move r); return 0; });",
        before="fn eat(fn(R) -> int f) -> void { var R q = R{ id: 2 }; f(move q); }\n"),
        [])


def test_returning_a_captured_owner_is_sem036():
    _expect(R + _main(
        "    var R r = R{ id: 1 };\n"
        "    var R s = make(lambda () -> R { return r; });",
        before="fn make(fn() -> R f) -> R { return f(); }\n"),
        [("SEM036", 7, 44)])


def test_a_capture_with_a_destructor_can_be_read_through_its_fields():
    _expect(R + APPLY + _main(
        "    var R r = R{ id: 1 };\n"
        "    apply(lambda (int x) -> int: x + r.id, 1);\n"
        "    apply(lambda (int x) -> int: x + see(&r), 1);",
        before="fn see(R ptr r) -> int { return r.id; }\n"), [])


def test_a_mutating_method_on_a_capture_is_sem003():
    _expect(VEC + APPLY + _main(
        "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
        "    apply(lambda (int x) -> int { v.push(x); return v.len(); }, 1);"),
        [("SEM003", 6, 35)])


def test_writing_through_a_captured_mutable_pointer_is_sem015():
    _expect(APPLY + _main(
        "    var int n = 0;\n"
        "    var int ptr mutable p = &n;\n"
        "    apply(lambda (int x) -> int { p[0] = x; return p[0]; }, 1);"),
        [("SEM015", 5, 35)])


def test_a_captured_mutable_pointer_is_seen_read_only():
    """Ni '&x' de algo capturado ni un 'ptr mutable' capturado llegan a
    quien escribiria."""
    _expect(APPLY + _main(
        "    var int n = 0;\n"
        "    var int ptr mutable p = &n;\n"
        "    apply(lambda (int x) -> int { inc(&n); return x; }, 1);\n"
        "    apply(lambda (int x) -> int { inc(p); return x; }, 1);\n"
        "    apply(lambda (int x) -> int: look(p) + look(&n), 1);",
        before="fn inc(int ptr mutable p) -> void { p[0] = p[0] + 1; }\n"
               "fn look(int ptr p) -> int { return p[0]; }\n"),
        [("AST006", 7, 39), ("AST006", 8, 39)])


def test_reading_a_capture_that_was_moved_before_is_sem004():
    _expect(R + APPLY + _main(
        "    var R r = R{ id: 1 };\n"
        "    take(move r);\n"
        "    apply(lambda (int x) -> int: r.id, 1);"),
        [("SEM004", 8, 34)])


def test_a_lambda_parameter_shadows_the_environment():
    """Los nombres del cuerpo resuelven primero a los suyos: el 'n' de la
    lambda es su parametro, y asignarlo no toca el 'n' de fuera."""
    _expect(APPLY + _main(
        "    var int n = 5;\n"
        "    apply(lambda (int n) -> int { n = n + 1; return n; }, 1);"), [])


def test_nested_lambdas_capture_through_the_outer_one():
    _expect(APPLY + _main(
        "    var int k = 1;\n"
        "    apply(lambda (int x) -> int: apply(lambda (int y) -> int: x + y + k, 1), 1);\n"
        "    apply(lambda (int x) -> int {\n"
        "        return apply(lambda (int y) -> int { x = y; return y; }, 1);\n"
        "    }, 1);"),
        [("SEM003", 6, 46)])


def test_a_lambda_inside_a_generic_function_sees_its_type_parameters():
    _expect(VEC +
            "fn count<T: Ord>(vec.Vector<T> ptr v, T min) -> int {\n"
            "    var vec.Vector<T> w = v.filter(lambda (T ptr x) -> bool: not (x[0] < min));\n"
            "    return w.len();\n"
            "}\n", [])
