"""negative_tests/diagnostics: lo que compilaba y fallaba (o no hacía nada)
al ejecutar, y ahora se dice al compilar.

- ``const`` y ``T ptr`` protegen también de los MÉTODOS que modifican su
  receptor y de los campos ANIDADOS (``SEM003`` / ``SEM015``), y ``&c.n``
  hereda la mutabilidad del lugar.
- Una global que usa otra declarada después (``SEM045``).
- ``s[0] = c`` sobre un ``str`` (``SEM031``).
- ``&b[i]`` de un escalar, directo o por instancia de un genérico
  (``Vector.at`` sobre un ``Vector<int>``): ``SEM013``.
- ``void`` como argumento de tipo (``SEM025``).
- Construcciones dudosas: ``case`` repetido (``SEM046``), patrón que liga dos
  veces (``SEM002``), expresión sin efecto (``SEM047``) y el AVISO de código
  inalcanzable (``SEM048``).
- ``len(3)`` y ``print`` de un puntero (``SEM001``; ``print(5)`` ya
  compila), ``hash`` por instancia (``AST006``/``SEM001``),
  los argumentos de tipo que faltan (``AST007``) y el aviso de un tipo menos
  visible en la firma de una función de librería (``SEM049``).

Se comprueban el CÓDIGO, la POSICIÓN y que no salga NADA más.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze, assert_ok  # noqa: E402


def _diagnostics(source: str, **kwargs) -> list:
    """``[(código, línea, columna)]`` de ``source``, en orden."""
    _, _, errors = analyze(source, **kwargs)
    return [(e.code, e.line, e.column) for e in errors]


def _expect(source: str, expected: list, **kwargs) -> None:
    got = _diagnostics(source, **kwargs)
    assert got == expected, f"se esperaba {expected}; se obtuvo {got}"


_C = ("struct { int n; } C;\n"                                              # 1
      "@impl C {\n"                                                         # 2
      "    fn up(C ptr mutable self) -> void { self.n = self.n + 1; }\n"    # 3
      "    fn read(C ptr self) -> int { return self.n; }\n"                 # 4
      "}\n"                                                                 # 5
      "struct { C c; } D;\n")                                               # 6


# --------------------------------------------------------------------------- #
# 1. const y 'T ptr' protegen de métodos y de campos anidados
# --------------------------------------------------------------------------- #

def test_a_mutating_method_on_a_const_is_sem003():
    _expect(_C + "fn main() -> int {\n"                  # 7
                 "    const C k = C{ n: 1 };\n"          # 8
                 "    k.up();\n"                         # 9
                 "    return 0;\n}\n", [("SEM003", 9, 5)])


def test_a_mutating_method_through_a_read_only_pointer_is_sem015():
    _expect(_C + "fn f(C ptr p) -> void {\n"             # 7
                 "    p.up();\n"                         # 8
                 "}\n", [("SEM015", 8, 5)])


def test_push_through_a_read_only_vector_pointer_is_sem015():
    _expect("#import array.vector as vec\n"
            "fn f(vec.Vector<int> ptr v) -> void {\n"
            "    v.push(3);\n"
            "}\n", [("SEM015", 3, 5)])


def test_a_nested_field_of_a_const_is_sem003():
    _expect(_C + "fn main() -> int {\n"                  # 7
                 "    const D d = D{ c: C{ n: 1 } };\n"  # 8
                 "    d.c.n = 5;\n"                      # 9
                 "    d.c.up();\n"                       # 10
                 "    return 0;\n}\n",
            [("SEM003", 9, 5), ("SEM003", 10, 5)])


def test_a_field_of_a_const_is_sem003():
    _expect(_C + "fn main() -> int {\n"
                 "    const C c = C{ n: 1 };\n"
                 "    c.n = 5;\n"
                 "    return 0;\n}\n", [("SEM003", 9, 5)])


def test_a_nested_field_through_a_read_only_pointer_is_sem015():
    _expect(_C + "fn f(D ptr p) -> void {\n"             # 7
                 "    p.c.n = 5;\n"                      # 8
                 "}\n", [("SEM015", 8, 5)])


def test_the_address_of_a_const_field_is_read_only():
    """``&c.n`` daba un ``int ptr mutable`` aunque ``c`` fuera ``const``:
    una puerta para escribir lo que no se puede escribir."""
    _expect(_C + "fn main() -> int {\n"                              # 7
                 "    const C c = C{ n: 1 };\n"                      # 8
                 "    var int ptr mutable q = &c.n;\n"               # 9
                 "    return 0;\n}\n", [("AST006", 9, 5)])


def test_a_pattern_on_a_const_subject_does_not_modify_the_payload():
    _expect(_C + "enum F { Has(C), No };\n"                          # 7
                 "fn main() -> int {\n"                              # 8
                 "    const F f = F.Has(C{ n: 1 });\n"               # 9
                 "    match (f) { case Has(k): { k.n = 9; } case No: { } }\n"
                 "    return 0;\n}\n", [("SEM003", 10, 32)])


def test_what_is_mutable_still_compiles():
    """Sin falsos positivos: lo mutable se modifica, a cualquier
    profundidad; un patrón sobre una variable y lo atrapado por un 'catch'
    se modifican (son decisiones ya probadas en e2e/test_copias_y_globales);
    leer un 'const' con un método de 'ptr self' vale; un puntero 'const'
    a algo mutable ('const C ptr mutable p') escribe lo apuntado."""
    assert_ok(_C + "enum F { Has(C), No };\n"
                   "fn g(C ptr mutable p, D ptr mutable q) -> void {\n"
                   "    p.up(); q.c.n = 1; q.c.up();\n"
                   "}\n"
                   "fn main() -> int {\n"
                   "    var C c = C{ n: 1 };\n"
                   "    c.up(); c.n = 2;\n"
                   "    var D d = D{ c: C{ n: 1 } };\n"
                   "    d.c.n = 3; d.c.up();\n"
                   "    const C k = C{ n: 1 };\n"
                   "    var int r = k.read();\n"
                   "    const C ptr mutable pc = &c;\n"
                   "    pc.n = 4;\n"
                   "    var int ptr mutable q = &c.n;\n"
                   "    var F f = F.Has(C{ n: 1 });\n"
                   "    match (f) { case Has(h): { h.n = 9; h.up(); } case No: { } }\n"
                   "    try { throw C{ n: 1 }; } catch (C e) { e.n = 2; }\n"
                   "    return 0;\n}\n")


# --------------------------------------------------------------------------- #
# 2. una global no puede usar otra declarada después
# --------------------------------------------------------------------------- #

def test_a_global_using_a_later_one_is_sem045():
    _expect("var int a = b + 1;\n"
            "var int b = 2;\n"
            "fn main() -> int { return a; }\n", [("SEM045", 1, 13)])


def test_a_global_using_itself_is_sem045():
    _expect("var int a = a + 1;\n"
            "fn main() -> int { return a; }\n", [("SEM045", 1, 13)])


def test_a_global_field_of_a_later_global_is_sem045():
    _expect("struct { int n; } P;\n"
            "const P q = P{ n: z.n };\n"
            "const P z = P{ n: 1 };\n"
            "fn main() -> int { return q.n; }\n", [("SEM045", 2, 19)])


def test_globals_in_order_and_functions_using_later_globals_compile():
    """Una función puede usar una global de más abajo: cuando se la llama,
    el nivel superior ya terminó."""
    assert_ok("var int a = 1;\n"
              "var int b = a + 1;\n"
              "fn lee() -> int { return c; }\n"
              "fn main() -> int { return b + lee(); }\n"
              "var int c = 3;\n")


# --------------------------------------------------------------------------- #
# 3. un 'str' no se escribe por índice
# --------------------------------------------------------------------------- #

def test_writing_a_char_of_a_str_is_sem031():
    _expect("fn main() -> int {\n"
            "    var str s = \"hola\";\n"
            "    s[0] = 'x';\n"
            "    var char c = s[0];\n"
            "    return 0;\n}\n", [("SEM031", 3, 5)])


# --------------------------------------------------------------------------- #
# 4. '&b[i]' de un escalar
# --------------------------------------------------------------------------- #

_MEM = ("#import mem\n"                                                  # 1
        "#import array.vector as vec\n"                                  # 2
        "struct { int n; } P;\n")                                        # 3


def test_the_address_of_a_scalar_element_is_sem013():
    _expect(_MEM + "fn main() -> int {\n"                                 # 4
                   "    var int ptr mutable b = mem.reserve<int>(3);\n"   # 5
                   "    var int ptr p = &b[0];\n"                         # 6
                   "    mem.release<int>(b);\n"                           # 7
                   "    return 0;\n}\n", [("SEM013", 6, 21)])


def test_the_address_of_a_char_of_a_str_is_sem013():
    _expect("fn main() -> int {\n"
            "    var str s = \"hola\";\n"
            "    var char ptr p = &s[0];\n"
            "    return 0;\n}\n", [("SEM013", 3, 22)])


def test_vector_at_on_a_scalar_vector_is_sem013_in_the_call():
    """'Vector.at' presta con '&self.datos[i]': con 'int' era RT011 al
    ejecutar en los dos motores. Ahora lo decide la instancia."""
    _expect(_MEM + "fn main() -> int {\n"                                 # 4
                   "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"   # 5
                   "    v.push(1);\n"                                     # 6
                   "    var int ptr q = v.at(0);\n"                       # 7
                   "    var int ptr mutable w = v.at_mut(0);\n"           # 8
                   "    return 0;\n}\n",
            [("SEM013", 7, 21), ("SEM013", 8, 29)])


def test_a_generic_that_borrows_propagates_to_its_caller_instance():
    _expect(_MEM + "fn first<T>(vec.Vector<T> ptr v) -> T ptr { return v.at(0); }\n"
                   "fn main() -> int {\n"                                 # 5
                   "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"   # 6
                   "    var int ptr q = first<int>(&v);\n"                # 7
                   "    return 0;\n}\n", [("SEM013", 7, 21)])


def test_borrowing_object_elements_still_compiles():
    assert_ok(_MEM + "fn main() -> int {\n"
                     "    var P ptr mutable b = mem.reserve<P>(3);\n"
                     "    b[0] = P{ n: 1 };\n"
                     "    var P ptr p = &b[0];\n"
                     "    mem.release<P>(b);\n"
                     "    var vec.Vector<P> v = vec.dynamic<P>(2);\n"
                     "    v.push(P{ n: 1 });\n"
                     "    var P ptr q = v.at(0);\n"
                     "    v.at_mut(0).n = 5;\n"
                     "    var int x = v.get(0).n;\n"
                     "    return 0;\n}\n")


# --------------------------------------------------------------------------- #
# 5. 'void' no es un argumento de tipo
# --------------------------------------------------------------------------- #

def test_void_as_a_type_argument_is_sem025():
    _expect("#import array.vector as vec\n"
            "struct { int n; } Caja<T>;\n"
            "fn main() -> int {\n"
            "    var vec.Vector<void> v = vec.dynamic<void>(2);\n"
            "    var Caja<void> c = Caja<void>{ n: 1 };\n"
            "    return 0;\n}\n",
            [("SEM025", 4, 5), ("SEM025", 4, 30),
             ("SEM025", 5, 5), ("SEM025", 5, 24)])


def test_a_type_that_only_wraps_void_is_still_valid():
    assert_ok("struct { int n; } Caja<T>;\n"
              "fn main() -> int {\n"
              "    var Caja<void ptr>? c = null;\n"
              "    return 0;\n}\n")


# --------------------------------------------------------------------------- #
# 6. construcciones dudosas: error; código inalcanzable: aviso
# --------------------------------------------------------------------------- #

def test_a_repeated_case_is_sem046():
    _expect("enum Color { ROJO, VERDE };\n"                          # 1
            "fn f(int n, Color c, str s) -> int {\n"                 # 2
            "    match (n) {\n"                                      # 3
            "        case 1: { return 1; }\n"                        # 4
            "        case -2: { return 2; }\n"                       # 5
            "        case 1: { return 3; }\n"                        # 6
            "        case -2: { return 4; }\n"                       # 7
            "    }\n"                                                # 8
            "    match (c) {\n"                                      # 9
            "        case ROJO: { return 1; }\n"                     # 10
            "        case Color.ROJO: { return 2; }\n"               # 11
            "        case VERDE: { return 3; }\n"                    # 12
            "    }\n"                                                # 13
            "    match (s) { case \"a\": { } case \"a\": { } }\n"    # 14
            "    return 0;\n}\n",
            [("SEM046", 6, 9), ("SEM046", 7, 9), ("SEM046", 11, 9),
             ("SEM046", 14, 31)])


def test_a_repeated_destructuring_variant_is_sem046():
    _expect("enum Dato { Vacio, Par(int, int) };\n"
            "fn f(Dato d) -> int {\n"
            "    match (d) {\n"
            "        case Dato.Par(a, b): { return a; }\n"
            "        case Dato.Par(x, y): { return y; }\n"
            "        case Dato.Vacio: { return 0; }\n"
            "    }\n"
            "    return 0;\n}\n", [("SEM046", 5, 9)])


def test_distinct_cases_compile():
    assert_ok("enum Color { ROJO, VERDE };\n"
              "fn f(int n, Color c) -> int {\n"
              "    match (n) { case 1: { return 1; } case 2: { return 2; } case -1: { return 3; } }\n"
              "    match (c) { case ROJO: { return 1; } case VERDE: { return 2; } }\n"
              "    return 0;\n}\n")


def test_a_pattern_binding_a_name_twice_is_sem002():
    _expect("enum Dato { Vacio, Par(int, int) };\n"
            "fn f(Dato d) -> int {\n"
            "    match (d) {\n"
            "        case Dato.Par(x, x): { return x; }\n"
            "        case Dato.Vacio: { return 0; }\n"
            "    }\n"
            "    return 0;\n}\n", [("SEM002", 4, 26)])


def test_a_function_or_a_comparison_as_a_statement_is_sem047():
    _expect("struct { int n; } P;\n"                                  # 1
            "fn g() -> int { return 1; }\n"                           # 2
            "fn main() -> int {\n"                                    # 3
            "    var int n = 1;\n"                                    # 4
            "    var P p = P{ n: 1 };\n"                              # 5
            "    g;\n"                                                # 6
            "    n == 1;\n"                                           # 7
            "    n < 2;\n"                                            # 8
            "    n;\n"                                                # 9
            "    p.n;\n"                                              # 10
            "    5;\n"                                                # 11
            "    return 0;\n}\n",
            [("SEM047", 6, 5), ("SEM047", 7, 5), ("SEM047", 8, 5),
             ("SEM047", 9, 5), ("SEM047", 10, 5), ("SEM047", 11, 5)])


def test_statements_that_do_something_compile():
    assert_ok("#import io.stdp as stdp\n"
              "fn g() -> int { return 1; }\n"
              "fn main() -> int {\n"
              "    var int n = 1;\n"
              "    g();\n"
              "    n = 2;\n"
              "    stdp.println(\"x\");\n"
              "    return 0;\n}\n")


def test_code_after_an_exit_is_a_sem048_warning():
    source = ("fn f(int n) -> int {\n"                                # 1
              "    while (n > 0) {\n"                                 # 2
              "        break;\n"                                      # 3
              "        n = n - 1;\n"                                  # 4
              "    }\n"                                               # 5
              "    if (n == 3) { throw \"x\"; n = 4; }\n"            # 6
              "    return n;\n"                                       # 7
              "    n = 2;\n"                                          # 8
              "    n = 3;\n"                                          # 9
              "}\n")
    _expect(source, [("SEM048", 4, 9), ("SEM048", 6, 30), ("SEM048", 8, 5)])
    _, _, errors = analyze(source)
    assert all(e.severity == "warning" for e in errors), \
        [(e.code, e.severity) for e in errors]


def test_an_exit_at_the_end_of_its_block_does_not_warn():
    assert_ok("fn f(int n) -> int {\n"
              "    while (n > 0) { n = n - 1; if (n == 2) { continue; } }\n"
              "    if (n == 1) { return 1; } else { return 2; }\n"
              "}\n")


# --------------------------------------------------------------------------- #
# 7. 'print'/'len' sobre un tipo que no puede tener el hook
# --------------------------------------------------------------------------- #

def test_len_of_a_primitive_and_print_of_a_pointer_are_sem001():
    """``print(5)`` y ``print("hola")`` ya compilan (decision del
    mantenedor: ``print`` escribe un primitivo en todas partes, como un
    f-string; ver ``e2e/test_print_of_primitives.py``). ``len`` no cambia,
    y un puntero a un primitivo no es un primitivo."""
    _expect("fn main() -> int {\n"
            "    print(5);\n"
            "    print(\"hola\");\n"
            "    var int n = len(3);\n"
            "    var int ptr p = &n;\n"
            "    print(p);\n"
            "    return 0;\n}\n",
            [("SEM001", 4, 17), ("SEM001", 6, 5)])


def test_print_of_a_type_with_its_hook_and_len_of_a_str_compile():
    assert_ok("struct { int n; } P;\n"
              "hook fn __print__(P ptr p) -> void { }\n"
              "fn main() -> int {\n"
              "    var P q = P{ n: 1 };\n"
              "    print(q);\n"
              "    print(&q);\n"
              "    var int n = len(\"hola\");\n"
              "    return 0;\n}\n")


# --------------------------------------------------------------------------- #
# 8. 'hash' dentro de un genérico: por instancia, con el código de fuera
# --------------------------------------------------------------------------- #

_H = ("struct { int n; } P;\n"                                        # 1
      "fn g(int x) -> int { return x; }\n"                            # 2
      "fn h<T>(T x) -> int { return hash(x); }\n")                    # 3


def test_hash_of_a_function_in_a_generic_is_ast006_in_the_call():
    _expect(_H + "fn main() -> int {\n"                               # 4
                 "    var int a = h<fn(int) -> int>(g);\n"            # 5
                 "    return a;\n}\n", [("AST006", 5, 17)])


def test_hash_of_a_float_or_a_type_without_hash_in_a_generic():
    _expect(_H + "fn main() -> int {\n"                               # 4
                 "    var int a = h<float>(1.5);\n"                   # 5
                 "    var int b = h<P>(P{ n: 1 });\n"                 # 6
                 "    return a + b;\n}\n",
            [("AST006", 5, 17), ("SEM001", 6, 17)])


def test_a_dictionary_with_a_function_key_is_ast006_where_it_hashes():
    _expect("#import collections.dictionary as dic\n"                 # 1
            "fn g(int x) -> int { return x; }\n"                      # 2
            "fn main() -> int {\n"                                    # 3
            "    var dic.Dictionary<fn(int) -> int, int> d = dic.make<fn(int) -> int, int>(4);\n"
            "    d.put(g, 1);\n"                                      # 5
            "    return 0;\n}\n", [("AST006", 5, 5)])


def test_hash_in_a_generic_with_hashable_types_compiles():
    assert_ok(_H + "enum E { A, B };\n"
                   "hook fn __hash__(P ptr p) -> int { return p.n; }\n"
                   "fn main() -> int {\n"
                   "    var int a = h<int>(1) + h<str>(\"x\") + h<E>(E.A) + h<P>(P{ n: 1 });\n"
                   "    return a;\n}\n")


# --------------------------------------------------------------------------- #
# 11. faltan los argumentos de tipo: un solo error que dice cuáles y cómo
# --------------------------------------------------------------------------- #

def test_func_map_deduces_its_type_arguments():
    """Paso 4: ``T`` sale de ``Vector<T> ptr`` y ``U`` de ``fn(T ptr) -> U``.
    Antes era AST007 (y antes aún, tres AST006)."""
    _expect("#import array.vector as vec\n"
            "#import func\n"
            "fn label(int ptr x) -> str { return \"x\"; }\n"
            "fn main() -> int {\n"
            "    var vec.Vector<int> v = vec.dynamic<int>(4);\n"
            "    var vec.Vector<str> m = func.map(&v, label);\n"
            "    return 0;\n}\n", [])


def test_missing_type_arguments_still_check_the_other_arguments():
    """``T`` solo llega con un ``null`` (contexto no deducido): AST007, y el
    otro argumento se sigue comprobando."""
    _expect("fn put<T>(T? c, int k) -> int { return k; }\n"
            "fn main() -> int {\n"
            "    var int r = put(null, \"x\");\n"
            "    return 0;\n}\n", [("AST007", 3, 17), ("AST006", 3, 27)])


def test_written_or_deduced_type_arguments_compile():
    assert_ok("struct { int n; } Caja<T>;\n"
              "fn put<T>(Caja<T> ptr c, int k) -> int { return k; }\n"
              "fn first<T>(T a) -> T { return a; }\n"
              "fn main() -> int {\n"
              "    var Caja<int> c = Caja<int>{ n: 1 };\n"
              "    var int r = put<int>(&c, 2) + first(1);\n"
              "    return 0;\n}\n")


# --------------------------------------------------------------------------- #
# 12. aviso: una función de librería que se ve más que un tipo de su firma
# --------------------------------------------------------------------------- #

_LIB = ("private struct { int n; } P;\n"                               # 1
        "internal struct { int n; } Q;\n"                              # 2
        "struct { int n; } R;\n")                                      # 3


def test_a_narrower_type_in_a_library_signature_is_a_sem049_warning():
    source = (_LIB +
              "fn make() -> P { return P{ n: 1 }; }\n"                 # 4
              "private fn make2() -> Q { return Q{ n: 1 }; }\n"        # 5
              "fn take(R r, P ptr p) -> int { return r.n; }\n"         # 6
              "#export as geo\n")
    path = os.path.join("lib_dir", "geo.libsrx")
    _expect(source, [("SEM049", 4, 1), ("SEM049", 5, 9), ("SEM049", 6, 1)],
            source_path=path)
    _, _, errors = analyze(source, source_path=path)
    assert all(e.severity == "warning" for e in errors)


def test_matching_visibility_or_a_program_does_not_warn():
    source = (_LIB +
              "private fn make() -> P { return P{ n: 1 }; }\n"
              "internal fn make2() -> Q { return Q{ n: 1 }; }\n"
              "fn ok() -> R { return R{ n: 1 }; }\n")
    assert_ok(source + "#export as geo\n",
              source_path=os.path.join("lib_dir", "geo.libsrx"))
    # un parametro de tipo se registra como tipo 'internal' de la libreria:
    # no es un tipo de la firma (era un falso positivo en vector, mem, func)
    assert_ok("struct { int n; } Caja<T>;\n"
              "fn id<T>(T x) -> T { return x; }\n"
              "fn wrap<V>(V x) -> Caja<V> { return Caja<V>{ n: 1 }; }\n"
              "#export as geo\n",
              source_path=os.path.join("lib_dir", "geo.libsrx"))
    # en un programa nadie importa nada: no hay a quien avisar
    assert_ok(_LIB + "fn make() -> P { return P{ n: 1 }; }\n"
              "fn main() -> int { return make().n; }\n")
