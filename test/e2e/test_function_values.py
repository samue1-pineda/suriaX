"""e2e/funciones_valor — funciones con nombre como valores, sin capturas.

Una función del módulo, de una librería (``lib.f``) o un método de
``@impl`` (``Tipo.metodo``) es un valor de tipo ``fn(A, B) -> R``: se guarda
en una variable, un campo o un vector, se pasa, se devuelve y se llama. No
captura nada, así que se copia libremente y no tiene destructor. ``==`` es
identidad y un f-string la escribe ``<fn nombre>``.

Se comprueba la SALIDA EXACTA del intérprete. También el arreglo de P4 (un
``E ptr`` que viene de ``mem.reserve`` es su elemento 0, también en ``match``)
y el de un método que pisaba a una función homónima.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

IO = "#from io #import stdp\n"


def _output(source: str, expected: str, *, exit_code: int = 0) -> str:
    code, out, err = run_source(source, args=["--run", "interpreter"])
    lines = [l for l in out.splitlines()
              if not l.startswith(("frontend OK", "HIR (", "  unidad '"))]
    got = "\n".join(lines) + ("\n" if lines else "")
    assert code == exit_code, (
        f"exit {code}, se esperaba {exit_code}\nstdout: {out!r}\nstderr: {err!r}")
    assert got == expected, (
        f"salida distinta.\n  esperada: {expected!r}\n  obtenida: {got!r}\n"
        f"  stderr: {err!r}")
    return err


def test_a_function_is_stored_passed_and_called():
    _output(IO + "fn doble(int x) -> int { return x * 2; }\n"
            "fn aplica(fn(int) -> int f, int x) -> int { return f(x); }\n"
            "fn main() -> int {\n"
            "    var fn(int) -> int g = doble;\n"
            "    fn(int) -> int h = g;\n"
            "    stdp.println(f\"{g(5)} {aplica(doble, 7)} {h(1)}\");\n"
            "    return 0;\n"
            "}\n", "10 14 2\n")


def test_an_fstring_writes_fn_and_the_name():
    _output(IO + "fn doble(int x) -> int { return x * 2; }\n"
            "fn main() -> int {\n"
            "    var fn(int) -> int g = doble;\n"
            "    stdp.println(f\"{g} [{g!r}]\");\n"
            "    return 0;\n"
            "}\n", "<fn doble> [<fn doble>]\n")


def test_equality_is_identity():
    _output(IO + "fn doble(int x) -> int { return x * 2; }\n"
            "fn triple(int x) -> int { return x * 3; }\n"
            "fn main() -> int {\n"
            "    var fn(int) -> int g = doble;\n"
            "    var (fn(int) -> int)? q = null;\n"
            "    stdp.println(f\"{g == doble} {g == triple} {g != triple} "
            "{q == null} {stdp.println == stdp.println}\");\n"
            "    return 0;\n"
            "}\n", "true false true true true\n")


def test_a_function_that_returns_a_function():
    _output(IO + "fn doble(int x) -> int { return x * 2; }\n"
            "fn triple(int x) -> int { return x * 3; }\n"
            "fn elige(bool b) -> fn(int) -> int {\n"
            "    if (b) { return doble; }\n"
            "    return triple;\n"
            "}\n"
            "fn main() -> int {\n"
            "    stdp.println(f\"{elige(true)(5)} {elige(false)(5)}\");\n"
            "    return 0;\n"
            "}\n", "10 15\n")


def test_in_a_field_and_in_a_vector():
    _output(IO + "#import array.vector as vec\n"
            "fn doble(int x) -> int { return x * 2; }\n"
            "fn triple(int x) -> int { return x * 3; }\n"
            "struct { fn(int) -> int op; int k; } Paso;\n"
            "fn main() -> int {\n"
            "    var Paso p = Paso{ op: triple, k: 4 };\n"
            "    var vec.Vector<fn(int) -> int> ops = vec.dynamic<fn(int) -> int>(2);\n"
            "    ops.push(doble);\n"
            "    ops.push(p.op);\n"
            "    var Paso q = p;\n"
            "    stdp.println(f\"{p.op(p.k)} {ops.get(0)(7)} {ops.get(1)(7)} {q.op == p.op}\");\n"
            "    return 0;\n"
            "}\n", "12 14 21 true\n")


def test_an_impl_method_is_a_function_with_its_receiver():
    _output(IO + "struct { int x; } Punto;\n"
            "@impl Punto {\n"
            "    fn escala(Punto ptr self, int k) -> int { return self.x * k; }\n"
            "}\n"
            "fn main() -> int {\n"
            "    var Punto p = Punto{ x: 4 };\n"
            "    var fn(Punto ptr, int) -> int m = Punto.escala;\n"
            "    stdp.println(f\"{m(&p, 3)} {Punto.escala(&p, 10)} {m}\");\n"
            "    return 0;\n"
            "}\n", "12 40 <fn Punto.escala>\n")


def test_a_library_function_is_a_value():
    _output(IO + "fn main() -> int {\n"
            "    var fn(str) -> void w = stdp.println;\n"
            "    w(\"hola\");\n"
            "    return 0;\n"
            "}\n", "hola\n")


def test_a_generic_receives_behaviour_as_a_function():
    """Lo que antes se intentaba con ``f.aplica(x)`` sobre un ``F`` (SEM043):
    el comportamiento se pasa como función, con los tipos escritos."""
    _output(IO + "#import array.vector as vec\n"
            "fn mapa<A, B>(vec.Vector<A> ptr v, fn(A) -> B f) -> vec.Vector<B> {\n"
            "    var vec.Vector<B> r = vec.dynamic<B>(v.len());\n"
            "    var int i = 0;\n"
            "    while (i < v.len()) {\n"
            "        r.push(f(v.get(i)));\n"
            "        i = i + 1;\n"
            "    }\n"
            "    return r;\n"
            "}\n"
            "fn texto(int x) -> str { return f\"<{x}>\"; }\n"
            "fn main() -> int {\n"
            "    var vec.Vector<int> v = vec.dynamic<int>(3);\n"
            "    v.push(1); v.push(2); v.push(3);\n"
            "    var vec.Vector<str> m = mapa<int, str>(&v, texto);\n"
            "    stdp.println(f\"{m.get(0)}{m.get(1)}{m.get(2)}\");\n"
            "    return 0;\n"
            "}\n", "<1><2><3>\n")


def test_an_owner_passed_through_a_function_value_is_destroyed_once():
    _output(IO + "struct { int id; } R;\n"
            "hook fn __free__(R ptr r) -> void { stdp.println(f\"free {r.id}\"); }\n"
            "fn toma(R r) -> int { return r.id; }\n"
            "fn main() -> int {\n"
            "    var fn(R) -> int t = toma;\n"
            "    var R a = R{ id: 1 };\n"
            "    stdp.println(f\"{t(move a)}\");\n"
            "    stdp.println(f\"{t(R{ id: 2 })}\");\n"
            "    stdp.println(\"fin\");\n"
            "    return 0;\n"
            "}\n", "free 1\n1\nfree 2\n2\nfin\n")


def test_calling_a_null_optional_function_is_rt004():
    err = _output(IO + "fn main() -> int {\n"
                  "    var (fn(int) -> int)? f = null;\n"
                  "    stdp.println(\"antes\");\n"
                  "    var int n = f(1);\n"
                  "    return 0;\n"
                  "}\n", "antes\n", exit_code=70)
    assert "RT004" in err and "(5:17)" in err, err


def test_a_method_does_not_shadow_a_same_named_function():
    """``fn distancia`` y ``@impl Punto { fn distancia }`` conviven; el
    intérprete indexaba las dos por nombre y la llamada ejecutaba el método."""
    _output(IO + "fn distancia(int a) -> int { return a + 1; }\n"
            "struct { int x; } Punto;\n"
            "@impl Punto {\n"
            "    fn distancia(Punto ptr self) -> int { return self.x * 10; }\n"
            "}\n"
            "fn main() -> int {\n"
            "    var Punto p = Punto{ x: 4 };\n"
            "    var fn(int) -> int d = distancia;\n"
            "    stdp.println(f\"{distancia(5)} {p.distancia()} {d(1)}\");\n"
            "    return 0;\n"
            "}\n", "6 40 2\n")


# --------------------------------------------------------------------------- #
# P4: un puntero a un bloque de mem es su elemento 0
# --------------------------------------------------------------------------- #

TREE = (IO + "#import mem\n"
         "enum Expr { Num(int), Suma(Expr ptr, Expr ptr), Por(Expr ptr, Expr ptr) };\n"
         "fn caja(Expr e) -> Expr ptr mutable {\n"
         "    var Expr ptr mutable b = mem.reserve<Expr>(1);\n"
         "    b[0] = e;\n"
         "    return b;\n"
         "}\n"
         "fn evalua(Expr ptr e) -> int {\n"
         "    match (e) {\n"
         "        case Expr.Num(n)     { return n; }\n"
         "        case Expr.Suma(a, b) { return evalua(a) + evalua(b); }\n"
         "        case Expr.Por(a, b)  { return evalua(a) * evalua(b); }\n"
         "    };\n"
         "    return -1;\n"
         "}\n")


def test_match_on_a_block_enters_its_arm():
    """Antes no entraba en ninguna y el árbol calculaba 0 en silencio."""
    _output(TREE + "fn main() -> int {\n"
            "    var Expr raiz = Expr.Por(caja(Expr.Suma(caja(Expr.Num(2)), "
            "caja(Expr.Num(3)))), caja(Expr.Num(4)));\n"
            "    stdp.println(f\"valor = {evalua(&raiz)}\");\n"
            "    return 0;\n"
            "}\n", "valor = 20\n")


def test_block_borrow_and_element_agree():
    _output(IO + "#import mem\n"
            "enum E { A(int), B };\n"
            "fn que(E ptr e) -> str {\n"
            "    match (e) {\n"
            "        case E.A(n) { return f\"A({n})\"; }\n"
            "        case E.B    { return \"B\"; }\n"
            "    };\n"
            "    return \"NINGUNA\";\n"
            "}\n"
            "fn main() -> int {\n"
            "    var E ptr mutable b = mem.reserve<E>(1);\n"
            "    b[0] = E.A(7);\n"
            "    var E x = E.A(7);\n"
            "    stdp.println(f\"{que(b)} {que(&x)} {que(&b[0])}\");\n"
            "    mem.release<E>(b);\n"
            "    return 0;\n"
            "}\n", "A(7) A(7) A(7)\n")


def test_a_field_through_a_block_is_element_0s():
    _output(IO + "#import mem\n"
            "struct { int x; } P;\n"
            "fn lee(P ptr p) -> int { return p.x; }\n"
            "fn main() -> int {\n"
            "    var P ptr mutable b = mem.reserve<P>(2);\n"
            "    b[0] = P{ x: 5 };\n"
            "    b[1] = P{ x: 9 };\n"
            "    stdp.println(f\"{lee(b)} {b.x} {lee(&b[1])}\");\n"
            "    mem.release<P>(b);\n"
            "    return 0;\n"
            "}\n", "5 5 9\n")


def test_a_value_pattern_also_derefs_the_block():
    _output(IO + "#import mem\n"
            "fn main() -> int {\n"
            "    var int ptr mutable b = mem.reserve<int>(1);\n"
            "    b[0] = 3;\n"
            "    var int ptr p = b;\n"
            "    match (p) { case 3 { stdp.println(\"tres\"); } };\n"
            "    mem.release<int>(b);\n"
            "    return 0;\n"
            "}\n", "tres\n")
