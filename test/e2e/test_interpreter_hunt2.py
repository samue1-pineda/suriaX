"""e2e/interpreter_hunt2 — lo que la segunda caza de fallos encontró en el
intérprete (c_errorstfix.md §3b), cada caso con su salida EXACTA.

- A09: un dueño ``R?`` que vale ``null`` no llama a ``__free__``.
- A08: un f-string dentro de un genérico escribe igual que fuera: lo decide
  el VALOR, no el tipo estático ``T``.
- A10, A10b, A02: la variante SIN datos de un enum suma es un valor del enum
  (no un entero): sus ``__eq__``/``__hash__``/``__cmp__`` se llaman y
  ``Vector.at``/``Dictionary.at`` la prestan.
- H03: una excepción lanzada por la stdlib lleva la posición de la LLAMADA
  del programa (``e.linea``/``e.columna``, y el mensaje si nadie la atrapa).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402


def _clean(out: str) -> str:
    lines = [line for line in out.splitlines()
             if not line.startswith(("frontend OK", "HIR (", "  unidad '"))]
    return "\n".join(lines) + ("\n" if lines else "")


def _output(source: str, expected: str, *, exit_code: int = 0) -> str:
    """Corre ``source`` en el intérprete: su stdout es EXACTAMENTE
    ``expected`` y sale con ``exit_code``. Devuelve el stderr."""
    code, out, err = run_source(source, args=["--run", "interpreter"])
    got = _clean(out)
    assert code == exit_code, (
        f"exit {code}, se esperaba {exit_code}\nstdout: {out!r}\nstderr: {err!r}")
    assert got == expected, (
        f"salida distinta.\n  esperada: {expected!r}\n  obtenida: {got!r}\n"
        f"  stderr: {err!r}")
    return err


# --------------------------------------------------------------------------- #
# A09: un 'R?' que vale null no tiene nada que destruir
# --------------------------------------------------------------------------- #

_COUNTED = (
    "#from io #import stdp\n"
    "var int freed = 0;\n"
    "struct { str tag; } R;\n"
    "hook fn __free__(R ptr r) -> void { freed = freed + 1; "
    "stdp.println(f\"free {r.tag}\"); }\n")


def test_null_optional_owner_does_not_call_free():
    """El caso de la caza: local, parámetro y argumento 'null'. El
    destructor LEE un campo: con null era RT004 al cerrar el ámbito."""
    _output(_COUNTED + (
        "fn take(R? r) -> int { return 0; }\n"
        "fn scope() -> void {\n"
        "    var R? none = null;\n"
        "    var R? one = R{ tag: \"uno\" };\n"
        "    take(null);\n"
        "    take(move none);\n"
        "}\n"
        "fn main() -> int {\n"
        "    scope();\n"
        "    stdp.println(f\"freed={freed}\");\n"
        "    var R? a = null;\n"
        "    stdp.println(\"fin\");\n"
        "    return 0;\n"
        "}\n"), "free uno\nfreed=1\nfin\n")


def test_null_optional_in_fields_payloads_elements_and_globals():
    """La misma regla en todo lo que posee: un campo 'R?', el payload de una
    variante, un elemento de un Vector<R?> y una global."""
    _output(_COUNTED + (
        "#import array.vector as vec\n"
        "struct { R? f; int n; } Holder;\n"
        "enum Slot { Full(R?), Empty, };\n"
        "var R? g = null;\n"
        "fn scope() -> void {\n"
        "    var Holder h = Holder{ f: null, n: 1 };\n"
        "    var Slot s = Slot.Full(null);\n"
        "    var vec.Vector<R?> v = vec.dynamic<R?>(2);\n"
        "    v.push(null);\n"
        "    v.push(R{ tag: \"elem\" });\n"
        "}\n"
        "fn main() -> int {\n"
        "    scope();\n"
        "    stdp.println(f\"freed={freed}\");\n"
        "    return 0;\n"
        "}\n"), "free elem\nfreed=1\n")


def test_null_optional_temporary_and_free_do_not_call_free():
    """Un ``R?`` null que nadie recibe (un temporal) y ``free`` sobre un
    puntero a un ``R?`` null: tampoco hay destructor que correr."""
    _output(_COUNTED + (
        "fn none() -> R? { return null; }\n"
        "fn main() -> int {\n"
        "    none();\n"
        "    var R? a = null;\n"
        "    free &a;\n"
        "    stdp.println(f\"freed={freed}\");\n"
        "    return 0;\n"
        "}\n"), "freed=0\n")


def test_uncaught_struct_is_written_like_the_language():
    """Un ``throw`` de un struct sin atrapar lo escribe como el lenguaje
    (``P{x: 3, s: "hi"}``), no como Python (``P{x=3, s='hi'}``)."""
    err = _output(
        "struct { int x; str s; } P;\n"
        "fn main() -> int {\n"
        "    throw P{ x: 3, s: \"hi\" };\n"
        "}\n", "", exit_code=70)
    assert 'RT020: throw P{x: 3, s: "hi"} (3:5)' in err, err


# --------------------------------------------------------------------------- #
# A08: un f-string en un genérico escribe como con el tipo concreto
# --------------------------------------------------------------------------- #

_SHAPES = (
    "#from io #import stdp\n"
    "struct { int x; str s; } P;\n"
    "enum Shape { Circle(int), Dot, };\n"
    "enum Color { ROJO, VERDE, AZUL, };\n"
    "struct { char c; Color k; } Q;\n"
    "enum Res<T, E> { Ok(T), Err(E), };\n"
    "fn show<T>(T x) -> str { return f\"{x}\"; }\n"
    "fn show_r<T>(T x) -> str { return f\"{x!r}\"; }\n"
    "fn show_opt<T>(T? x) -> str { return f\"{x}\"; }\n"
    "fn as_int() -> int { return Color.VERDE; }\n")


def test_fstring_in_generic_writes_like_the_concrete_type():
    _output(_SHAPES + (
        "fn main() -> int {\n"
        "    var P p = P{ x: 3, s: \"hi\" };\n"
        "    var Shape c = Shape.Circle(2);\n"
        "    var Shape d = Shape.Dot;\n"
        "    var Color v = Color.VERDE;\n"
        "    var Res<Color, str> r = Res<Color, str>.Ok(Color.ROJO);\n"
        "    stdp.println(f\"{p} | {show(p)}\");\n"
        "    stdp.println(f\"{c} {d} | {show(c)} {show(d)}\");\n"
        "    stdp.println(f\"{v} {show(v)} {show_r(v)} {show_r(d)}\");\n"
        "    stdp.println(f\"{r} {show(r)} {show_r(r)}\");\n"
        "    var Q q = Q{ c: 'a', k: Color.AZUL };\n"
        "    stdp.println(f\"{q} | {show(q)}\");\n"
        "    return 0;\n"
        "}\n"),
        "P{x: 3, s: \"hi\"} | P{x: 3, s: \"hi\"}\n"
        "Circle(2) Dot | Circle(2) Dot\n"
        "VERDE VERDE Color.VERDE Shape.Dot\n"
        "Ok(ROJO) Ok(ROJO) Res.Ok(Color.ROJO)\n"
        "Q{c: 'a', k: Color.AZUL} | Q{c: 'a', k: Color.AZUL}\n")


def test_fstring_in_generic_optional_and_cast_enum():
    """``T?`` en un genérico, y un item que sale de un ``cast<Color>(1)``:
    también sabe su nombre. Uno que se guardó en un ``int`` ya es el entero,
    también dentro del genérico."""
    _output(_SHAPES + (
        "fn main() -> int {\n"
        "    var Shape? none = null;\n"
        "    var Shape? dot = Shape.Dot;\n"
        "    var Color c = cast<Color>(2);\n"
        "    var int n = Color.VERDE;\n"
        "    stdp.println(f\"{show_opt(none)} {show_opt(dot)} {show(c)} {n} {show(n)} {as_int()}\");\n"
        "    return 0;\n"
        "}\n"), "null Dot AZUL 1 1 1\n")


# --------------------------------------------------------------------------- #
# A10, A10b, A02: la variante sin datos de un enum suma es un valor del enum
# --------------------------------------------------------------------------- #

def test_unit_variant_calls_eq_and_hash_hooks():
    _output(
        "#from io #import stdp\n"
        "enum Shape { Circle(int), Dot, Square, };\n"
        "hook fn __eq__(Shape ptr a, Shape ptr b) -> bool { return true; }\n"
        "hook fn __hash__(Shape ptr s) -> int { return 2; }\n"
        "fn main() -> int {\n"
        "    var Shape c1 = Shape.Circle(1);\n"
        "    var Shape c2 = Shape.Circle(9);\n"
        "    var Shape d = Shape.Dot;\n"
        "    var Shape q = Shape.Square;\n"
        "    stdp.println(f\"{c1 == c2} {d == q} {d != q} {hash(c1)} {hash(q)}\");\n"
        "    match (q) {\n"
        "        case Shape.Dot { stdp.println(\"dot\"); }\n"
        "        case Shape.Square { stdp.println(\"square\"); }\n"
        "        case Shape.Circle(r) { stdp.println(\"circle\"); }\n"
        "    };\n"
        "    return 0;\n"
        "}\n", "true true false 2 2\nsquare\n")


def test_unit_variant_calls_cmp_hook_and_sorts():
    _output(
        "#from io #import stdp\n"
        "#import array.vector as vec\n"
        "enum Shape { Circle(int), Dot, Square, };\n"
        "fn rank(Shape ptr s) -> int {\n"
        "    match (s) {\n"
        "        case Shape.Circle(r) { return r; }\n"
        "        case Shape.Dot { return 100; }\n"
        "        case Shape.Square { return 200; }\n"
        "    };\n"
        "    return 0;\n"
        "}\n"
        "hook fn __cmp__(Shape ptr a, Shape ptr b) -> int "
        "{ return rank(a) - rank(b); }\n"
        "fn main() -> int {\n"
        "    var Shape c = Shape.Circle(5);\n"
        "    var Shape d = Shape.Dot;\n"
        "    var Shape q = Shape.Square;\n"
        "    stdp.println(f\"{c < d} {q < d} {d < c} {d <= d}\");\n"
        "    var vec.Vector<Shape> v = vec.dynamic<Shape>(4);\n"
        "    v.push(Shape.Square);\n"
        "    v.push(Shape.Circle(3));\n"
        "    v.push(Shape.Dot);\n"
        "    v.push(Shape.Circle(1));\n"
        "    v.sort();\n"
        "    stdp.println(f\"{v.get(0)} {v.get(1)} {v.get(2)} {v.get(3)}\");\n"
        "    return 0;\n"
        "}\n", "true false false true\nCircle(1) Circle(3) Dot Square\n")


def test_at_borrows_a_unit_variant():
    """``Vector.at`` y ``Dictionary.at`` prestan la variante sin datos igual
    que la que lleva datos (antes: RT011 desde ``vector.libsrx``)."""
    _output(
        "#from io #import stdp\n"
        "#import array.vector as vec\n"
        "#import collections.dictionary as dic\n"
        "enum Op { Set(int), Del, };\n"
        "fn name(Op ptr o) -> str {\n"
        "    match (o) {\n"
        "        case Op.Set(n) { return f\"set {n}\"; }\n"
        "        case Op.Del { return \"del\"; }\n"
        "    };\n"
        "    return \"?\";\n"
        "}\n"
        "fn main() -> int {\n"
        "    var vec.Vector<Op> v = vec.dynamic<Op>(2);\n"
        "    v.push(Op.Set(3));\n"
        "    v.push(Op.Del);\n"
        "    stdp.println(f\"{name(v.at(0))} {name(v.at(1))}\");\n"
        "    var dic.Dictionary<int, Op> m = dic.make<int, Op>(4);\n"
        "    m.put(1, Op.Del);\n"
        "    m.put(2, Op.Set(7));\n"
        "    stdp.println(f\"{name(m.at(1))} {name(m.at(2))}\");\n"
        "    return 0;\n"
        "}\n", "set 3 del\ndel set 7\n")


# --------------------------------------------------------------------------- #
# H03: la posición de una excepción de la stdlib es la de la llamada
# --------------------------------------------------------------------------- #

_H03_HEAD = (
    "#from io #import stdp\n"
    "#import sistema.archivos as arch\n"
    "#import excepciones as exc\n"
    "#import array.vector as vec\n"
    "#import text\n")


def test_library_exception_has_the_position_of_the_call():
    """Línea 7, 9 y 13: la de la LLAMADA. La columna es la de la expresión
    de la llamada (``arch.leer`` empieza en la 23)."""
    _output(_H03_HEAD + (
        "fn main() -> int {\n"                                              # 6
        "    try { var str r = arch.leer(\"no_existe.txt\"); }\n"          # 7
        "    catch (exc.ErrorDeArchivo e) { stdp.println(f\"leer {e.linea}:{e.columna}\"); };\n"
        "    try { var int n = text.parse_int(\"x\"); }\n"                 # 9
        "    catch (exc.ConversionInvalida e) { stdp.println(f\"parse {e.linea}:{e.columna}\"); };\n"
        "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"
        "    v.push(1);\n"
        "    try { var int a = v.get(4); }\n"                               # 13
        "    catch (exc.IndiceFueraDeRango e) { stdp.println(f\"get {e.linea}:{e.columna} {e.mensaje}\"); };\n"
        "    return 0;\n"
        "}\n"),
        "leer 7:23\nparse 9:23\nget 13:23 índice 4 fuera de rango [0, 1)\n")


def test_uncaught_library_exceptions_name_the_program_line():
    """Sin atrapar: el ``IndiceFueraDeRango`` de ``Vector`` sale como el
    EXC002 del runtime (antes ``RT020: throw ...`` con 0:0), y el
    ``ErrorDeArchivo`` con la línea del programa, no ``<stdlib>``."""
    err = _output(_H03_HEAD + (
        "fn main() -> int {\n"
        "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"
        "    v.push(1);\n"
        "    var int c = v.get(9);\n"                                       # 9
        "    return 0;\n"
        "}\n"), "", exit_code=70)
    assert "excepción no capturada — EXC002: índice 9 fuera de rango [0, 1) (9:17)" \
        in err, err
    err = _output(_H03_HEAD + (
        "fn main() -> int {\n"
        "    var str z = arch.leer(\"no_existe.txt\");\n"                  # 7
        "    return 0;\n"
        "}\n"), "", exit_code=70)
    assert "EXC003: no existe el archivo 'no_existe.txt' (7:17)" in err, err
    assert "<stdlib>" not in err, err


def test_runtime_exception_from_a_user_lambda_keeps_its_own_line():
    """Lo que falla en el código del USUARIO llamado desde la stdlib (una
    lambda de ``Vector.filter``) conserva SU posición: solo se mueve lo que
    nace dentro de la librería."""
    _output(
        "#from io #import stdp\n"
        "#import array.vector as vec\n"
        "#import excepciones as exc\n"
        "fn main() -> int {\n"
        "    var vec.Vector<int> v = vec.dynamic<int>(2);\n"
        "    v.push(0);\n"
        "    try {\n"
        "        var vec.Vector<int> w = v.filter(lambda (int ptr x) -> bool {\n"
        "            return 10 / x[0] > 1;\n"                                # 9
        "        });\n"
        "    } catch (exc.DivisionPorCero e) { stdp.println(f\"{e.linea}\"); };\n"
        "    return 0;\n"
        "}\n", "9\n")
