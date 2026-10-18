"""e2e/lambdas — funciones sin nombre que no escapan (paso 6).

``lambda (A a) -> R: e`` o ``lambda (A a) -> R { ...; return ...; }``, como
argumento de un parámetro ``fn(...) -> R``. Lee los locales y parámetros de
quien la escribe (captura de solo lectura) sin copiarlos: los ve VIVOS, con
el valor que tienen cuando se la llama. ``return`` devuelve de la lambda.
Los parámetros que posee y sus locales con destructor mueren al terminar
cada llamada a la lambda, una vez.

Se comprueba la SALIDA EXACTA del intérprete (``--run interpreter``). La
VM y el target web las rechazan (``VM004``/``WEB104``; ver
``backend/test_backend_cpp_lambdas.py`` y ``test/web/lambdas.test.ts``).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

HEAD = ("#from io #import stdp\n"
        "#import array.vector as vec\n"
        "#import func\n")


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


def _ints(name: str, values) -> str:
    text = f"    var vec.Vector<int> {name} = vec.dynamic<int>({len(values)});\n"
    return text + "".join(f"    {name}.push({v});\n" for v in values)


def test_sort_by_with_a_lambda_on_a_struct_field():
    _output(HEAD + "struct { str nombre; int edad; } P;\n"
            "fn main() -> int {\n"
            "    var vec.Vector<P> v = vec.dynamic<P>(3);\n"
            "    v.push(P{ nombre: \"ana\", edad: 30 });\n"
            "    v.push(P{ nombre: \"bea\", edad: 20 });\n"
            "    v.push(P{ nombre: \"cris\", edad: 25 });\n"
            "    v.sort_by(lambda (P ptr a, P ptr b) -> int: a.edad - b.edad);\n"
            "    stdp.println(f\"{v.at(0).nombre} {v.at(1).nombre} {v.at(2).nombre}\");\n"
            "    return 0;\n}\n", "bea cris ana\n")


def test_filter_reads_a_captured_threshold():
    _output(HEAD + "fn main() -> int {\n" + _ints("v", [5, 1, 8, 3]) +
            "    var int umbral = 3;\n"
            "    var vec.Vector<int> w = v.filter(lambda (int ptr x) -> bool: x[0] > umbral);\n"
            "    stdp.println(f\"{w.len()} {w.get(0)} {w.get(1)}\");\n"
            "    return 0;\n}\n", "2 5 8\n")


def test_map_and_fold_deduce_their_types_from_the_lambda():
    _output(HEAD + "fn main() -> int {\n" + _ints("v", [1, 2, 3]) +
            "    var str pre = \"#\";\n"
            "    var vec.Vector<str> e = func.map(&v, lambda (int ptr x) -> str: f\"{pre}{x[0]}\");\n"
            "    var int s = func.fold(&v, 10, lambda (int acc, int ptr x) -> int: acc + x[0]);\n"
            "    stdp.println(f\"{e.get(0)}{e.get(2)} {s}\");\n"
            "    return 0;\n}\n", "#1#3 16\n")


def test_block_form_returns_from_the_lambda_not_from_the_function():
    """El 'return' de dentro devuelve de la lambda: 'main' sigue y escribe
    las dos lineas."""
    _output(HEAD + "fn apply(fn(int) -> int f, int v) -> int { return f(v); }\n"
            "fn main() -> int {\n"
            "    var int r = apply(lambda (int x) -> int {\n"
            "        if (x > 10) { return 1; }\n"
            "        var int y = x * 2;\n"
            "        return y;\n"
            "    }, 4);\n"
            "    stdp.println(f\"{r}\");\n"
            "    stdp.println(f\"{apply(lambda (int x) -> int { if (x > 10) { return 1; } return 0; }, 11)}\");\n"
            "    return 0;\n}\n", "8\n1\n")


def test_a_capture_is_read_live_not_copied():
    """La lambda lee la variable, no una copia tomada al escribirla: si la
    funcion que la recibe cambia el valor (por un puntero que le dio quien la
    escribio) entre dos llamadas, la segunda llamada ve el valor nuevo."""
    _output(HEAD + "fn change_between(int ptr mutable p, fn(int) -> int f) -> int {\n"
            "    var int a = f(0);\n"
            "    p[0] = 50;\n"
            "    return a + f(0);\n"
            "}\n"
            "fn main() -> int {\n"
            "    var int n = 1;\n"
            "    var int r = change_between(&n, lambda (int x) -> int: n);\n"
            "    stdp.println(f\"{r} {n}\");\n"
            "    return 0;\n}\n", "51 50\n")


def test_nested_lambdas_and_shadowing():
    _output(HEAD + "fn apply(fn(int) -> int f, int v) -> int { return f(v); }\n"
            "fn main() -> int {\n"
            "    var int k = 100;\n"
            "    var int n = 5;\n"
            "    var int r = apply(lambda (int x) -> int: apply(lambda (int y) -> int: x + y + k, 2), 1);\n"
            "    var int s = apply(lambda (int n) -> int { n = n + 1; return n; }, 7);\n"
            "    stdp.println(f\"{r} {s} {n}\");\n"
            "    return 0;\n}\n", "103 8 5\n")


def test_a_lambda_in_a_generic_function_reads_its_parameter():
    _output(HEAD + "fn at_least<T: Ord>(vec.Vector<T> ptr v, T min) -> int {\n"
            "    var vec.Vector<T> w = v.filter(lambda (T ptr x) -> bool: not (x[0] < min));\n"
            "    return w.len();\n"
            "}\n"
            "fn main() -> int {\n" + _ints("v", [4, 9, 2, 7]) +
            "    stdp.println(f\"{at_least(&v, 5)}\");\n"
            "    return 0;\n}\n", "2\n")


def test_a_function_parameter_is_passed_on_and_called():
    """Lo que SEM051 deja hacer con un parametro de tipo funcion: llamarlo y
    pasarlo, tambien a otra lambda que lo llama."""
    _output(HEAD + "fn apply(fn(int) -> int f, int v) -> int { return f(v); }\n"
            "fn twice(fn(int) -> int f, int v) -> int {\n"
            "    return apply(lambda (int x) -> int: f(f(x)), v);\n"
            "}\n"
            "fn main() -> int {\n"
            "    var int k = 3;\n"
            "    stdp.println(f\"{twice(lambda (int x) -> int: x * k, 2)}\");\n"
            "    return 0;\n}\n", "18\n")


def test_owned_parameters_and_locals_of_a_lambda_die_once_per_call():
    """Un parametro por valor con destructor es SUYO (se lo cede quien la
    llama, con 'move'): muere al terminar cada llamada, salvo que la lambda
    lo ceda. Sus locales tambien. Ninguno dos veces."""
    _output(HEAD + "struct { int id; } R;\n"
            "hook fn __free__(R ptr r) -> void { stdp.println(f\"free {r.id}\"); }\n"
            "fn keep(R r) -> void { stdp.println(f\"keep {r.id}\"); }\n"
            "fn feed(fn(R) -> int f) -> int {\n"
            "    var R a = R{ id: 1 };\n"
            "    var R b = R{ id: 2 };\n"
            "    return f(move a) + f(move b);\n"
            "}\n"
            "fn main() -> int {\n"
            "    var int s = feed(lambda (R r) -> int {\n"
            "        var R local = R{ id: r.id * 10 };\n"
            "        if (r.id == 2) { keep(move r); }\n"
            "        return local.id;\n"
            "    });\n"
            "    stdp.println(f\"s={s}\");\n"
            "    return 0;\n}\n",
            "free 10\nfree 1\nkeep 2\nfree 2\nfree 20\ns=30\n")


def test_a_throw_inside_a_lambda_crosses_the_call():
    _output(HEAD + "fn apply(fn(int) -> int f, int v) -> int { return f(v); }\n"
            "fn main() -> int {\n"
            "    try {\n"
            "        apply(lambda (int x) -> int { throw x; }, 7);\n"
            "    } catch (int e) {\n"
            "        stdp.println(f\"atrapado {e}\");\n"
            "    }\n"
            "    return 0;\n}\n", "atrapado 7\n")


def test_a_block_lambda_that_falls_off_the_end_is_a_runtime_error():
    """Sin analisis de flujo (decision del mantenedor: fuera), caerse por el
    final de una lambda que devuelve algo se detecta al ejecutar, como en una
    funcion: RT, nunca un 'null' silencioso."""
    code, out, err = run_source(
        HEAD + "fn apply(fn(int) -> int f, int v) -> int { return f(v); }\n"
        "fn main() -> int {\n"
        "    return apply(lambda (int x) -> int { if (x > 5) { return 1; } }, 1);\n"
        "}\n", args=["--run", "interpreter"])
    text = out + err
    assert code != 0, text
    assert "lambda de la linea 6" in text and "sin devolver" in text, text


def test_reading_what_the_callee_is_moving_is_a_runtime_error():
    """Lo que la regla no cubre (como el resto de los prestamos): la lambda
    lee 'v' mientras 'sort_by' tiene sus elementos fuera de su sitio. Es un
    error de ejecucion explicito (RT001), no un valor equivocado."""
    code, out, err = run_source(
        HEAD + "fn main() -> int {\n" + _ints("v", [3, 1, 2]) +
        "    v.sort_by(lambda (int ptr a, int ptr b) -> int { var int s = v.get(0); return a[0] - b[0]; });\n"
        "    return 0;\n}\n", args=["--run", "interpreter"])
    text = out + err
    assert code != 0, text
    assert "RT001" in text, text
