"""negative_tests/diagnostics: funciones como valores y genéricos sin cota.

Cuatro fallos silenciosos (``c_errorstfix.md``, 2h) se cierran con
diagnósticos:

- **P1**: el nombre de una función usado como valor tenía por tipo su
  RETORNO (``var int g = doble;`` compilaba) y llamar a algo que no es una
  función no daba error. Ahora el nombre tiene su tipo ``fn(...) -> R``
  (``AST006`` si no encaja) y llamar a un no invocable es ``SEM042``.
- **P2/P3**: un método, un campo o ``[]`` sobre un valor de un parámetro de
  tipo SIN cota se aceptaba y fallaba al ejecutar, o pasaba el tipo
  equivocado. Ahora es ``SEM043``.
- Lo que NO puede ser un valor (un prototipo, una genérica, un dunder, un
  método de un tipo genérico, un receptor por valor con destructor) es
  ``SEM044``.

Se comprueban el CÓDIGO y la POSICIÓN (línea, columna), nunca el texto.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze, assert_ok  # noqa: E402


def _diagnostics(source: str) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errors = analyze(source)
    return [(e.code, e.line, e.column) for e in errors]


def _expect(source: str, expected: list) -> None:
    got = _diagnostics(source)
    assert got == expected, f"se esperaba {expected}; se obtuvo {got}"


TWICE = "fn doble(int x) -> int { return x * 2; }\n"


def _with_main(body: str, before: str = TWICE) -> str:
    """``antes`` + un ``main`` con ``cuerpo`` (que empieza en la línea 3 si
    ``antes`` ocupa una)."""
    return before + "fn main() -> int {\n" + body + "\n    return 0;\n}\n"


# --------------------------------------------------------------------------- #
# P1: el nombre de una función es un valor de tipo función
# --------------------------------------------------------------------------- #

def test_a_function_name_is_not_its_return_type():
    """Antes ``var int g = doble;`` compilaba: el nombre valía su RETORNO."""
    _expect(_with_main("    var int g = doble;"), [("AST006", 3, 5)])


def test_a_function_name_has_its_function_type():
    assert_ok(_with_main("    var fn(int) -> int g = doble;\n"
                    "    var int r = g(4);"))


def test_a_different_function_type_does_not_fit():
    """Sin varianza: el retorno y cada parámetro tienen que ser los mismos."""
    _expect(_with_main("    var fn(int) -> str g = doble;"), [("AST006", 3, 5)])
    _expect(_with_main("    var fn(int) -> int? g = doble;"), [("AST006", 3, 5)])


def test_an_optional_function_takes_the_function_and_null():
    assert_ok(_with_main("    var (fn(int) -> int)? g = doble;\n"
                    "    g = null;"))


def test_arithmetic_on_a_function_is_not_an_internal_error():
    """``g + 1`` era un ICE000 del intérprete."""
    _expect(_with_main("    var fn(int) -> int g = doble;\n"
                "    var int h = g + 1;"), [("AST006", 4, 17)])


def test_negating_a_function_is_ast006():
    _expect(_with_main("    var fn(int) -> int g = doble;\n"
                "    var int h = -g;"), [("AST006", 4, 17)])


def test_ordering_functions_is_ast006():
    _expect(_with_main("    var fn(int) -> int g = doble;\n"
                "    var bool b = g < g;"), [("AST006", 4, 18)])


def test_a_function_has_no_hash():
    _expect(_with_main("    var fn(int) -> int g = doble;\n"
                "    var int h = hash(g);"), [("AST006", 4, 17)])


def test_a_function_cannot_be_indexed():
    _expect(_with_main("    var fn(int) -> int g = doble;\n"
                "    var int h = g[0];"), [("SEM031", 4, 17)])


def test_print_of_a_function_is_written_with_an_fstring():
    """``print(g)`` despacharía a un ``__print__`` que nadie declara."""
    _expect(_with_main("    var fn(int) -> int g = doble;\n"
                "    print(g);"), [("SEM001", 4, 5)])


def test_comparing_functions_for_equality_is_allowed():
    assert_ok(_with_main("    var fn(int) -> int g = doble;\n"
                    "    var bool b = g == doble;\n"
                    "    var (fn(int) -> int)? q = null;\n"
                    "    var bool c = q == null;"))


def test_ampersand_on_a_function_is_still_sem013():
    _expect(_with_main("    var int ptr p = &doble;"), [("SEM013", 3, 21)])


# --------------------------------------------------------------------------- #
# SEM042: llamar a algo que no es una función
# --------------------------------------------------------------------------- #

def test_calling_an_int_is_sem042():
    """Antes ``n(3)`` pasaba sin decir nada."""
    _expect(_with_main("    var int n = 4;\n    n(3);", before=""), [("SEM042", 3, 5)])


def test_calling_a_missing_method_is_sem042():
    """Antes era RT011 al ejecutar."""
    _expect(_with_main("    var P p = P{ x: 1 };\n    p.noexiste();",
                before="struct { int x; } P;\n"), [("SEM042", 4, 5)])


def test_calling_a_non_function_field_is_sem042():
    _expect(_with_main("    var P p = P{ x: 1 };\n    p.x(2);",
                before="struct { int x; } P;\n"), [("SEM042", 4, 5)])


def test_calling_a_module_is_sem042():
    _expect("#import mem\nfn main() -> int {\n    mem(3);\n    return 0;\n}\n",
          [("SEM042", 3, 5)])


def test_calling_a_dataless_item_is_sem042():
    _expect(_with_main("    var E e = A(1);", before="enum E { A, B };\n"),
          [("SEM042", 3, 15)])


def test_calling_a_pointer_to_function_is_sem042():
    """Se llama a lo apuntado (``p[0](...)``); el puntero no es la función."""
    _expect(_with_main("    var fn(int) -> int g = doble;\n"
                "    var (fn(int) -> int) ptr p = &g;\n"
                "    p(1);\n"
                "    var int r = p[0](1);"), [("SEM042", 5, 5)])


def test_a_function_value_has_no_methods():
    _expect(_with_main("    var fn(int) -> int g = doble;\n    g.algo();"),
          [("SEM042", 4, 5)])


# --------------------------------------------------------------------------- #
# llamar a través de un valor: lo mismo que una llamada directa
# --------------------------------------------------------------------------- #

def test_arity_is_checked_against_the_function_type():
    _expect(_with_main("    var fn(int) -> int g = doble;\n    g(1, 2);"),
          [("SEM008", 4, 5)])


def test_each_argument_type_is_checked():
    _expect(_with_main("    var fn(int) -> int g = doble;\n    g(\"x\");"),
          [("AST006", 4, 7)])


def test_the_call_returns_the_function_type_return():
    _expect(_with_main("    var fn(int) -> int g = doble;\n    var str s = g(1);"),
          [("AST006", 4, 5)])


R = ("struct { int id; } R;\n"
     "hook fn __free__(R ptr r) -> void { }\n"
     "fn toma(R r) -> int { return r.id; }\n")


def test_passing_an_owner_through_a_function_value_needs_move():
    """SEM032, igual que en la llamada directa: el parámetro por valor es el
    nuevo dueño."""
    _expect(_with_main("    var fn(R) -> int t = toma;\n"
                "    var R a = R{ id: 1 };\n"
                "    var int n = t(a);", before=R), [("SEM032", 7, 19)])


def test_with_move_or_a_temporary_there_is_no_diagnostic():
    assert_ok(_with_main("    var fn(R) -> int t = toma;\n"
                    "    var R a = R{ id: 1 };\n"
                    "    var int n = t(move a);\n"
                    "    var int m = t(R{ id: 2 });", before=R))


def test_a_function_field_is_called_with_its_type():
    _expect(_with_main("    var C c = C{ op: doble };\n"
                "    var int a = c.op(1);\n"
                "    var str b = c.op(2);",
                before=TWICE + "struct { fn(int) -> int op; } C;\n"),
          [("AST006", 6, 5)])


# --------------------------------------------------------------------------- #
# SEM044: lo que no puede ser un valor
# --------------------------------------------------------------------------- #

def test_a_prototype_is_not_a_value():
    _expect(_with_main("    var fn(int) -> int g = proto;",
                before="fn proto(int x) -> int;\n"), [("SEM044", 3, 28)])


def test_a_generic_function_is_not_a_value():
    _expect(_with_main("    var fn(int) -> int g = id;",
                before="fn id<T>(T a) -> T { return a; }\n"),
          [("SEM044", 3, 28)])


def test_an_instantiated_generic_without_call_is_par012():
    """``id<int>`` sin llamarla: se ve en el parser, y lo dice ahí."""
    _expect(_with_main("    var fn(int) -> int g = id<int>;",
                before="fn id<T>(T a) -> T { return a; }\n"),
          [("PAR012", 3, 30)])


def test_ordinary_comparison_is_unchanged():
    """``a < b > c`` sigue siendo lo que era: el '<' es un operador."""
    assert_ok(_with_main("    var int a = 1;\n    var int b = 2;\n"
                    "    var bool c = a < b;\n"
                    "    var bool d = (a < b) == (b > a);", before=""))


POINT = ("struct { int x; } Punto;\n"
         "@impl Punto {\n"
         "    fn escala(Punto ptr self, int k) -> int { return self.x * k; }\n"
         "    fn copia(Punto self) -> int { return self.x; }\n"
         "}\n"
         "dunder fn __doble__(Punto ptr self) -> int { return self.x * 2; }\n")


def test_an_impl_method_is_a_value_with_its_receiver():
    assert_ok(_with_main("    var fn(Punto ptr, int) -> int m = Punto.escala;\n"
                    "    var fn(Punto) -> int c = Punto.copia;\n"
                    "    var Punto p = Punto{ x: 2 };\n"
                    "    var int r = m(&p, 3) + Punto.escala(&p, 1);",
                    before=POINT))


def test_a_method_type_includes_the_receiver():
    _expect(_with_main("    var fn(int) -> int m = Punto.escala;", before=POINT),
          [("AST006", 8, 5)])


def test_a_dunder_is_not_a_value():
    _expect(_with_main("    var fn(Punto ptr) -> int d = Punto.__doble__;",
                before=POINT), [("SEM044", 8, 34)])


def test_a_missing_method():
    _expect(_with_main("    var int d = Punto.nada;", before=POINT),
          [("SEM001", 8, 17)])


def test_a_by_value_receiver_with_destructor_is_not_a_value():
    _expect(_with_main("    var fn(R) -> int c = R.consume;",
                before=R + "@impl R {\n"
                          "    fn consume(R self) -> int { return self.id; }\n"
                          "}\n"),
          [("SEM044", 8, 26)])


def test_a_method_of_a_generic_type_is_not_a_value():
    _expect("#import array.vector as vec\n" + _with_main(
        "    var fn(vec.Vector<int> ptr mutable, int) -> void l = vec.Vector.push;",
        before=""),
        [("SEM044", 3, 58)])


def test_a_library_function_is_a_value():
    assert_ok("#from io #import stdp\n" + _with_main(
        "    var fn(str) -> void w = stdp.println;\n"
        "    w(\"hola\");", before=""))


# --------------------------------------------------------------------------- #
# la sintaxis del tipo
# --------------------------------------------------------------------------- #

def test_void_as_function_type_parameter_is_sem025():
    _expect("fn usa(fn(void) -> int g) -> void { }\n", [("SEM025", 1, 8)])


def test_fn_without_name_says_the_name_is_missing():
    """``fn () -> int { ... }`` era una función sin nombre y lo sigue siendo
    (no un binding de tipo función sin nombre)."""
    _expect("fn () -> int { return 0; }\n", [("PAR003", 1, 14)])
    _expect("fn (int x) -> int { return 0; }\n", [("PAR003", 1, 9)])


def test_a_function_type_without_var_declares_a_variable():
    assert_ok(_with_main("    fn(int) -> int g = doble;\n    var int r = g(1);"))


def test_a_global_function_type():
    assert_ok("fn doble(int x) -> int { return x * 2; }\n"
              "fn(int) -> int G = doble;\n"
              "var (fn(int) -> int)? H = null;\n"
              "fn main() -> int { return G(1); }\n")


# --------------------------------------------------------------------------- #
# SEM043: un genérico no le pide nada a su T por su nombre
# --------------------------------------------------------------------------- #

def test_a_method_on_unbounded_t_is_sem043():
    """P2: antes compilaba y era RT011 con un tipo que no lo tenía."""
    _expect("fn usa<F>(F f) -> int { return f.aplica(1); }\n",
          [("SEM043", 1, 32)])


def test_a_dunder_on_unbounded_t_is_sem043():
    _expect("fn usa<F>(F f) -> int { return f.__aplica__(1); }\n",
          [("SEM043", 1, 32)])


def test_a_method_through_a_pointer_to_t_too():
    _expect("fn usa<F>(F ptr f) -> int { return f.aplica(1); }\n",
          [("SEM043", 1, 36)])


def test_indexing_an_unbounded_t_is_sem043():
    """P3: ``f[x]`` sobre ``T`` dejaba pasar el tipo equivocado
    (``map<str>(&v, "hola")`` metía caracteres en un ``Vector<int>``)."""
    _expect("fn usa<F>(F f) -> int { return f[1]; }\n", [("SEM043", 1, 32)])


def test_a_field_of_unbounded_t_is_sem043():
    _expect("fn usa<F>(F f) -> int { return f.k; }\n", [("SEM043", 1, 32)])


def test_what_the_language_does_with_t_still_works():
    """``==``, ``<`` (``SEM039`` por instancia), ``hash``, copiar, escribir en
    un f-string y destruir no se piden por nombre: siguen aceptándose."""
    assert_ok("fn usa<T>(T a, T b) -> str {\n"
              "    var bool i = a == b;\n"
              "    var bool m = a < b;\n"
              "    var int h = hash(a);\n"
              "    var T c = a;\n"
              "    return f\"{c} {i} {m} {h}\";\n"
              "}\n")


def test_indexing_a_block_of_t_still_works():
    """``T ptr`` es memoria (el bloque de un ``Vector``), no un método de T."""
    assert_ok("fn primero<T>(T ptr datos) -> T { return datos[0]; }\n")


def test_a_function_value_is_how_behaviour_reaches_t():
    assert_ok("fn aplica<T>(T x, fn(T) -> T f) -> T { return f(x); }\n"
              "fn doble(int x) -> int { return x * 2; }\n"
              "fn main() -> int { return aplica<int>(3, doble); }\n")


def test_a_function_value_of_t_checks_its_arguments():
    _expect("fn aplica<T>(T x, fn(T) -> T f) -> T { return f(1); }\n",
          [("AST006", 1, 49)])
