"""negative_tests/diagnostics: cotas, conceptos, traits, deducción y métodos
genéricos (paso 4 del análisis de paradigmas).

- COTAS ``<T: A + B>`` en toda declaración genérica (funciones, structs,
  enums, ``const type`` y ``@impl``). Dentro del cuerpo, ``T`` ofrece lo que
  prometen: ``<`` con ``Ord``, ``hash`` con ``Hash``, ``print`` con
  ``Print`` y los métodos de un trait, comprobados en la DEFINICIÓN. En cada
  instancia el argumento de tipo tiene que cumplirlas, y si no, el error sale
  en la llamada con el código de la operación que falta (``SEM039`` sin
  orden, ``AST006``/``SEM001`` sin hash, ``SEM001`` sin ``__print__``,
  ``SEM021`` sin ``@impl(Contrato)``). Un parámetro de tipo sin la cota que
  hace falta es ``SEM043``; sin cota, ``Ord`` y ``Hash`` se siguen
  comprobando por instancia, como antes.
- Una cota que no nombra un trait de este archivo ni un concepto: ``SEM021``.
- DEDUCCIÓN de argumentos de tipo (``T``, ``T ptr``, ``T?``,
  ``Nombre<..T..>``, ``fn(..T..) -> R``), sin conversiones: dos tipos
  distintos para el mismo ``T``, o un ``T`` que no sale de ningún argumento,
  son ``AST007``; o se escriben todos o ninguno (``SEM027``).
- MÉTODOS GENÉRICOS (``fn f<U>`` dentro de ``@impl Caja<T>``).

Todo va por ``analyze`` y no por ``helpers.error_codes``/``assert_ok``: lo
que pasa por ``error_codes`` entra en el corpus del diferencial V0/V1
(``bootstrap/test_diagnosticos_v1``), y la V1 todavía no conoce esta sintaxis.

Se comprueban el CÓDIGO, la POSICIÓN y que no salga NADA más.
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


def _main(body: str, before: str = "") -> str:
    return before + "fn main() -> int {\n" + body + "\n    return 0;\n}\n"


P = "struct { int x; } P;\n"

SHAPE = ("@trait struct {\n"                                                    # 1
         "    fn area(self ptr s) -> int;\n"                                    # 2
         "    dunder fn __name__(self ptr) -> str;\n"                           # 3
         "} Shape;\n"                                                           # 4
         "@impl(Shape) struct { int r; } Circle;\n"                             # 5
         "@impl Circle { fn area(Circle ptr self) -> int { return self.r; } }\n"  # 6
         "dunder fn __name__(Circle ptr c) -> str { return \"c\"; }\n")         # 7

MENOR = "fn menor<T: Ord>(T a, T b) -> T { if (a < b) { return a; } return b; }\n"


# --------------------------------------------------------------------------- #
# 1. declarar cotas
# --------------------------------------------------------------------------- #

def test_bounds_on_every_generic_declaration_compile():
    _expect("@trait struct { fn area(self ptr s) -> int; } Shape;\n"
            "fn f<T: Ord + Hash, U>(T a, U b) -> T { return a; }\n"
            "struct { K k; V v; } Pair<K: Ord, V: Eq>;\n"
            "enum Res<T: Ord, E> { Ok(T), Err(E) };\n"
            "const type Handle<T: Hash>;\n"
            "struct { T v; } Box<T>;\n"
            "@impl Box<T: Print> { fn show(Box<T> ptr self) -> void { print(self.v); } }\n"
            "fn g<S: Shape>(S ptr s) -> int { return s.area(); }\n", [])


def test_unknown_bound_is_sem021_where_it_is_written():
    _expect("fn f<T: Ord + Zzz>(T a) -> T { return a; }\n", [("SEM021", 1, 15)])


def test_a_trait_of_another_library_is_not_a_bound_yet():
    _expect("#import array.vector as vec\n"
            "fn f<T: vec.Vector>(T a) -> T { return a; }\n", [("SEM021", 2, 9)])


def test_a_user_trait_shadows_a_native_concept_name():
    """Los conceptos no ocupan ningún espacio de nombres: un trait del
    archivo llamado ``Ord`` manda, y se cumple con ``@impl(Ord)``."""
    _expect("@trait struct { fn rank(self ptr s) -> int; } Ord;\n" + P +
            "@impl(Ord) struct { int n; } R;\n"
            "@impl R { fn rank(R ptr self) -> int { return self.n; } }\n"
            "fn top<T: Ord>(T ptr a) -> int { return a.rank(); }\n" +
            _main("    var R r = R{ n: 1 };\n"
                  "    var int n = top(&r);\n"
                  "    var P p = P{ x: 1 };\n"
                  "    var int m = top(&p);"), [("SEM021", 10, 17)])


# --------------------------------------------------------------------------- #
# 2. dentro del cuerpo: lo que la cota promete se comprueba en la definición
# --------------------------------------------------------------------------- #

def test_ord_bound_orders_at_the_definition():
    _expect(_main("    var int a = menor(3, 4);\n"
                  "    var str s = menor(\"b\", \"a\");", MENOR), [])


def test_trait_bound_offers_its_methods():
    """Un dunder del trait y un método de ``@impl`` que el trait pide."""
    _expect(_main("    var Circle c = Circle{ r: 2 };\n"
                  "    var str s = describe(&c);",
                  SHAPE + "fn describe<T: Shape>(T ptr x) -> str "
                  "{ return f\"{x.__name__()}{x.area()}\"; }\n"), [])


def test_trait_bound_does_not_offer_other_methods():
    _expect(SHAPE + "fn f<T: Shape>(T ptr x) -> int { return x.perimeter(); }\n",
            [("SEM043", 8, 41)])


def test_print_bound_offers_print():
    _expect(_main("    show(P{ x: 1 });\n    show(5);\n    show(\"s\");",
                  P + "hook fn __print__(P ptr p) -> void { }\n"
                  "fn show<T: Print>(T x) -> void { print(x); x.print(); }\n"), [])


def test_print_without_bound_is_still_sem001():
    _expect("fn show<T>(T x) -> void { print(x); }\n", [("SEM001", 1, 27)])


def test_a_mutating_trait_method_needs_a_writable_receiver():
    _expect("@trait struct { fn bump(self ptr mutable s) -> void; } Bumpable;\n"
            "fn up<T: Bumpable>(T ptr x) -> void { x.bump(); }\n"
            "fn upm<T: Bumpable>(T ptr mutable x) -> void { x.bump(); }\n",
            [("SEM015", 2, 39)])


def test_bounds_implied_by_the_receiver_need_no_repetition():
    """Un método o un hook de ``Pair<K>`` con ``Pair<K: Ord>``: no existe un
    ``Pair`` cuya ``K`` no se ordene."""
    _expect("struct { K k; } Pair<K: Ord>;\n"
            "@impl Pair<K> { fn less(Pair<K> ptr self, K o) -> bool "
            "{ return self.k < o; } }\n"
            "hook fn __cmp__(Pair<K> ptr a, Pair<K> ptr b) -> int "
            "{ if (a.k < b.k) { return -1; } return 1; }\n", [])


# --------------------------------------------------------------------------- #
# 3. en cada instancia: el error en la llamada, con el código de lo que falta
# --------------------------------------------------------------------------- #

def test_ord_bound_unmet_is_sem039_at_the_call():
    _expect(_main("    var P p = menor(P{ x: 1 }, P{ x: 2 });", P + MENOR),
            [("SEM039", 4, 15)])


def test_ord_bound_message_says_the_bound_and_the_argument():
    """La única prueba de texto de este archivo: el pedido dice qué cota
    falta y desde qué argumento se dedujo el tipo que no la cumple."""
    _, _, errors = analyze(_main("    var P p = P{ x: 1 };\n"
                                 "    var int n = pick(1, p);",
                                 P + "fn pick<A, B: Ord>(A a, B b) -> A { return a; }\n"))
    assert [(e.code, e.line, e.column) for e in errors] == [("SEM039", 5, 17)]
    message = errors[0].message
    assert "'B: Ord'" in message and "desde el argumento 2" in message, message


def test_trait_bound_unmet_is_sem021():
    _expect(_main("    var P p = P{ x: 1 };\n"
                  "    var int n = area_of(&p);",
                  SHAPE + P + "fn area_of<T: Shape>(T ptr x) -> int { return x.area(); }\n"),
            [("SEM021", 12, 17)])


def test_print_bound_unmet_and_simple_enums_are_sem001():
    """Un enum sin datos es un entero al ejecutar: dentro del genérico su
    ``__print__`` no se llamaría, así que no cumple ``Print``."""
    _expect(_main("    show(P{ x: 1 });\n    show(Color.ROJO);",
                  P + "enum Color { ROJO, AZUL };\n"
                  "hook fn __print__(Color ptr c) -> void { }\n"
                  "fn show<T: Print>(T x) -> void { print(x); }\n"),
            [("SEM001", 6, 5), ("SEM001", 7, 5)])


def test_hash_bound_rules_are_those_of_hash():
    _expect(_main("    var int a = h(1) + h(\"s\") + h(Color.AZUL);\n"
                  "    var int b = h(2.5);\n"
                  "    var int c = h(P{ x: 1 });",
                  P + "enum Color { ROJO, AZUL };\n"
                  "fn h<T: Hash>(T x) -> int { return hash(x); }\n"),
            [("AST006", 6, 17), ("SEM001", 7, 17)])


def test_eq_is_met_by_every_type():
    _expect(_main("    var bool a = same(1, 1) and same(P{ x: 1 }, P{ x: 1 }) "
                  "and same(2.5, 2.5);",
                  P + "fn same<T: Eq>(T a, T b) -> bool { return a == b; }\n"), [])


def test_type_bounds_are_checked_in_annotations_and_literals():
    _expect(_main("    var Pair<int, P> a = Pair<int, P>{ k: 1, v: P{ x: 1 } };\n"
                  "    var Pair<P, int> b = Pair<P, int>{ k: P{ x: 1 }, v: 2 };",
                  P + "struct { K k; V v; } Pair<K: Ord, V>;\n"),
            [("SEM039", 5, 5), ("SEM039", 5, 26)])


def test_enum_bounds_are_checked_in_the_annotation():
    _expect(_main("    var Res<int, str> a = Res<int, str>.Ok(1);\n"
                  "    var Res<P, str> b = Res<P, str>.Err(\"x\");",
                  P + "enum Res<T: Ord, E> { Ok(T), Err(E) };\n"),
            [("SEM039", 5, 5)])


def test_impl_bounds_are_checked_on_the_method_call():
    _expect(_main("    var Bag<int> a = Bag<int>{ v: 2 };\n"
                  "    var bool r = a.below(3);\n"
                  "    var Bag<P> b = Bag<P>{ v: P{ x: 1 } };\n"
                  "    var bool s = b.below(P{ x: 2 });",
                  P + "struct { T v; } Bag<T>;\n"
                  "@impl Bag<T: Ord> { fn below(Bag<T> ptr self, T o) -> bool "
                  "{ return self.v < o; } }\n"),
            [("SEM039", 8, 18)])


def test_an_unbounded_caller_keeps_ord_per_instance():
    """Sin cota todo sigue como antes: ``wrap<U>`` llama a ``menor<T: Ord>``
    y se comprueba en cada instancia de ``wrap``."""
    _expect(_main("    var int i = wrap(1, 2);\n"
                  "    var P p = wrap(P{ x: 1 }, P{ x: 2 });",
                  P + MENOR + "fn wrap<U>(U a, U b) -> U { return menor(a, b); }\n"),
            [("SEM039", 6, 15)])


def test_an_unbounded_parameter_cannot_meet_a_trait_bound():
    _expect(SHAPE + "fn area_of<T: Shape>(T ptr x) -> int { return x.area(); }\n"
            "fn wrap<U>(U ptr x) -> int { return area_of(x); }\n",
            [("SEM043", 9, 37)])


def test_a_bounded_caller_of_an_unbounded_orderer_reports_once():
    _expect(_main("    var P p = wrap(P{ x: 1 }, P{ x: 2 });",
                  P + "fn menor<T>(T a, T b) -> T { if (a < b) { return a; } return b; }\n"
                  "fn wrap<U: Ord>(U a, U b) -> U { return menor(a, b); }\n"),
            [("SEM039", 5, 15)])


def test_an_annotation_needs_the_bound_of_its_type():
    """La firma, el cuerpo y un campo: ``Pair<U>`` con ``U`` sin ``Ord``.

    Decision del mantenedor (A06): dentro de una FUNCION, ``Ord`` y ``Hash``
    que el parametro no promete se comprueban por instancia, como al llamar
    a una funcion acotada; antes la firma y el cuerpo eran SEM043. En la
    declaracion de otro tipo (``Node<K>``) no hay instancia que lo decida y
    sigue siendo SEM043."""
    _expect("struct { K k; } Pair<K: Ord>;\n"
            "fn g<U>(U a) -> int { var Pair<U> p = Pair<U>{ k: a }; return 1; }\n"
            "fn mk<U>(U a) -> Pair<U> { return Pair<U>{ k: a }; }\n"
            "struct { Pair<K> ptr? next; } Node<K>;\n"
            "fn ok<U: Ord>(U a) -> Pair<U> { return Pair<U>{ k: a }; }\n",
            [("SEM043", 4, 21)])
    # ...y la instancia que no se ordena falla en la llamada
    codes = [c for c, _, _ in _diagnostics(
        "struct { K k; } Pair<K: Ord>;\n"
        "fn g<U>(U a) -> int { var Pair<U> p = Pair<U>{ k: a }; return 1; }\n"
        "fn main() -> int { var int a = g(1); var int b = g(true); return 0; }\n")]
    assert codes == ["SEM039"], codes


# --------------------------------------------------------------------------- #
# 4. deducción de argumentos de tipo
# --------------------------------------------------------------------------- #

def test_deduces_through_ptr_optional_nested_generic_and_function_type():
    _expect(_main("    var int n = 3;\n"
                  "    var int a = first(&n);\n"
                  "    var int? m = 4;\n"
                  "    var int b = unwrap(m);\n"
                  "    var Box<Box<int>> bb = Box<Box<int>>{ v: Box<int>{ v: 1 } };\n"
                  "    var int c = inner(bb);\n"
                  "    var int d = apply(2, twice);",
                  "struct { T v; } Box<T>;\n"
                  "fn first<T>(T ptr p) -> T { return p[0]; }\n"
                  "fn unwrap<T>(T? x) -> int { return 1; }\n"
                  "fn inner<T>(Box<Box<T>> b) -> T { return b.v.v; }\n"
                  "fn apply<T>(T x, fn(T) -> T f) -> T { return f(x); }\n"
                  "fn twice(int x) -> int { return x * 2; }\n"), [])


def test_two_arguments_giving_different_types_is_ast007():
    """No se elige uno: ni entre dos ``T``, ni dentro de un tipo función."""
    _expect(_main("    var int a = two(1, \"s\");\n"
                  "    var int b = apply(\"s\", twice);",
                  "fn two<T>(T a, T b) -> T { return a; }\n"
                  "fn apply<T>(T x, fn(T) -> T f) -> T { return f(x); }\n"
                  "fn twice(int x) -> int { return x * 2; }\n"),
            [("AST007", 5, 17), ("AST007", 6, 17)])


def test_no_conversion_null_or_return_only_is_ast007():
    """Un ``int`` no liga el ``T`` de un ``T?`` (sería convertirlo); de un
    ``null`` ni del retorno no sale ningún tipo."""
    _expect(_main("    var int a = unwrap(5);\n"
                  "    var int b = unwrap(null);\n"
                  "    var int? c = make();",
                  "fn unwrap<T>(T? x) -> int { return 1; }\n"
                  "fn make<T>() -> T? { return null; }\n"),
            [("AST007", 4, 17), ("AST007", 5, 17), ("AST007", 6, 18)])


def test_a_null_does_not_bind_a_bare_parameter():
    _expect(_main("    var int a = id(null);",
                  "fn id<T>(T x) -> int { return 1; }\n"),
            [("AST007", 3, 17)])


def test_type_arguments_are_written_all_or_none():
    _expect(_main("    var int a = f<int>(1, 2);\n"
                  "    var int b = f<int, int>(1, 2);",
                  "fn f<T, U>(T a, U b) -> T { return a; }\n"),
            [("SEM027", 3, 17), ("AST006", 3, 27)])


# --------------------------------------------------------------------------- #
# 5. métodos genéricos
# --------------------------------------------------------------------------- #

BOX = "struct { T v; } Box<T>;\n"


def test_generic_methods_with_written_or_deduced_arguments():
    _expect(_main("    var Box<int> b = Box<int>{ v: 21 };\n"
                  "    var Box<str> s = b.map(label);\n"
                  "    var Box<str> t = b.map<str>(label);\n"
                  "    var int k = b.pick(4);",
                  BOX + "@impl Box<T> {\n"
                  "    fn map<U>(Box<T> ptr self, fn(T) -> U f) -> Box<U> "
                  "{ return Box<U>{ v: f(self.v) }; }\n"
                  "    fn pick<U: Ord>(Box<T> ptr self, U o) -> U { return o; }\n"
                  "}\n"
                  "fn label(int x) -> str { return f\"{x}\"; }\n"), [])


def test_generic_method_errors():
    """Un ``U`` que solo está en el retorno (AST007), una cota propia que no
    se cumple (SEM039) y argumentos de tipo para un método que no es
    genérico (SEM027)."""
    _expect(_main("    var Box<int> b = Box<int>{ v: 21 };\n"
                  "    var int? n = b.none();\n"
                  "    var P p = b.pick(P{ x: 1 });\n"
                  "    var int z = b.size<int>();",
                  P + BOX + "@impl Box<T> {\n"
                  "    fn none<U>(Box<T> ptr self) -> U? { return null; }\n"
                  "    fn pick<U: Ord>(Box<T> ptr self, U o) -> U { return o; }\n"
                  "    fn size(Box<T> ptr self) -> int { return 1; }\n"
                  "}\n"),
            [("AST007", 10, 18), ("SEM039", 11, 15), ("SEM027", 12, 17)])


def test_a_generic_method_cannot_repeat_its_impl_parameter():
    _expect(BOX + "@impl Box<T> { fn f<T>(Box<T> ptr self, T x) -> int { return 1; } }\n",
            [("SEM002", 2, 16)])


def test_a_generic_method_is_not_a_value():
    _expect(_main("    var fn(C ptr, int) -> int f = C.get;",
                  "struct { int n; } C;\n"
                  "@impl C { fn get<U>(C ptr self, U u) -> U { return u; } }\n"),
            [("SEM044", 4, 35)])


# --------------------------------------------------------------------------- #
# 6. la librería: 'Vector.sort' con 'T: Ord'
# --------------------------------------------------------------------------- #

def test_vector_sort_without_order_is_sem039_at_the_call():
    _expect(_main("    var vec.Vector<int> a = vec.dynamic<int>(2);\n"
                  "    a.sort();\n"
                  "    var vec.Vector<P> b = vec.dynamic<P>(2);\n"
                  "    b.sort();",
                  "#import array.vector as vec\n" + P),
            [("SEM039", 7, 5)])


def test_vector_sort_bound_is_checked_in_place_not_per_instance():
    """Con la cota, el ``SEM039`` sale en su orden, ANTES del error de la línea
    siguiente; la comprobación por instancia lo daba al cerrar el módulo,
    después de todo lo demás."""
    _expect(_main("    var vec.Vector<P> b = vec.dynamic<P>(2);\n"
                  "    b.sort();\n"
                  "    var int z = \"s\";",
                  "#import array.vector as vec\n" + P),
            [("SEM039", 5, 5), ("AST006", 6, 5)])


def test_vector_sort_inside_an_unbounded_generic_is_per_instance():
    _expect(_main("    var vec.Vector<P> b = vec.dynamic<P>(2);\n"
                  "    order(&b);",
                  "#import array.vector as vec\n" + P +
                  "fn order<U>(vec.Vector<U> ptr mutable v) -> void { v.sort(); }\n"),
            [("SEM039", 6, 5)])
