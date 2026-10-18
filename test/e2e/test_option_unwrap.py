"""e2e/option — desenvolver un ``T?`` y los enums genéricos (paso 3, "Option").

Tres construcciones, decididas por el mantenedor:

- ``match`` sobre un ``T?`` con ``case null`` y ``case v``: ``v`` es el
  CONTENIDO (un ``T``) dentro de la rama, y lo liga igual que ``case E.A(x)``
  liga un payload: prestado, sin copiar. Si ``T`` es un enum, también
  ``case E.A(x)`` (solo encaja si no es null).
- ``x ?? d``: el contenido de ``x`` si no es null; si lo es, ``d``, que solo
  entonces se evalúa (cortocircuito). Asocia a la derecha.
- las variantes de un enum genérico se escriben con sus argumentos de tipo:
  ``Res<int, str>.Ok(5)``, al construir y en un ``case``.

No hay estrechamiento tras un ``if (x != null)``: es deliberado.

Se comprueba la SALIDA EXACTA del intérprete (la VM y el target web lo
RECHAZAN: ``backend/test_backend_cpp_option.py`` y ``test/web``).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import run_project, run_source  # noqa: E402
from libraries_support import W  # noqa: E402

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


# --------------------------------------------------------------------------- #
# match sobre un T?
# --------------------------------------------------------------------------- #

def test_match_on_a_nullable_variable():
    _output(IO + "fn describe(int? x) -> str {\n"
            "    match (x) {\n"
            "        case null { return \"nada\"; }\n"
            "        case v { return f\"vale {v + 1}\"; }\n"
            "    };\n"
            "    return \"?\";\n"
            "}\n"
            "fn main() -> int {\n"
            "    stdp.println(describe(null));\n"
            "    stdp.println(describe(41));\n"
            "    return 0;\n"
            "}\n", "nada\nvale 42\n")


def test_match_on_a_field_and_on_a_call_result():
    _output(IO + "struct { int? edad; } Persona;\n"
            "fn busca(int k) -> int? { if (k > 0) { return k * 10; } return null; }\n"
            "fn main() -> int {\n"
            "    var Persona p = Persona{ edad: 40 };\n"
            "    match (p.edad) {\n"
            "        case null { stdp.println(\"sin edad\"); }\n"
            "        case e { stdp.println(f\"edad {e}\"); }\n"
            "    };\n"
            "    match (busca(2)) {\n"
            "        case null { stdp.println(\"no\"); }\n"
            "        case r { stdp.println(f\"llamada {r}\"); }\n"
            "    };\n"
            "    match (busca(-1)) {\n"
            "        case null { stdp.println(\"llamada null\"); }\n"
            "        case r { stdp.println(\"no deberia\"); }\n"
            "    };\n"
            "    return 0;\n"
            "}\n", "edad 40\nllamada 20\nllamada null\n")


def test_match_on_a_nullable_pointer():
    """``T ptr?``: ``case null`` mira el PUNTERO; ``case p`` liga el
    ``T ptr`` (no lo desreferencia)."""
    _output(IO + "fn lee(int ptr? q) -> str {\n"
            "    match (q) {\n"
            "        case null { return \"puntero nulo\"; }\n"
            "        case p { return f\"apunta a {p[0]}\"; }\n"
            "    };\n"
            "    return \"?\";\n"
            "}\n"
            "fn main() -> int {\n"
            "    var int base = 5;\n"
            "    stdp.println(lee(&base));\n"
            "    stdp.println(lee(null));\n"
            "    return 0;\n"
            "}\n", "apunta a 5\npuntero nulo\n")


def test_case_null_on_a_pointer_to_a_nullable_looks_at_the_pointer():
    """``int? ptr?`` que apunta a un ``int?`` null: el puntero NO es null.
    Antes de la regla, ``case null`` desreferenciaba y encajaba."""
    _output(IO + "fn main() -> int {\n"
            "    var int? vacio = null;\n"
            "    var int? ptr? q = &vacio;\n"
            "    match (q) {\n"
            "        case null { stdp.println(\"puntero nulo\"); }\n"
            "        case p { stdp.println(\"puntero a un opcional\"); }\n"
            "    };\n"
            "    return 0;\n"
            "}\n", "puntero a un opcional\n")


def test_match_on_an_optional_enum_with_variant_patterns():
    _output(IO + "enum Forma { Circulo(int), Cuadro(int, int), Nada };\n"
            "fn area(Forma? f) -> str {\n"
            "    match (f) {\n"
            "        case null { return \"sin forma\"; }\n"
            "        case Forma.Circulo(r) { return f\"circulo {r}\"; }\n"
            "        case Forma.Cuadro(a, b) { return f\"cuadro {a * b}\"; }\n"
            "        case Forma.Nada { return \"nada\"; }\n"
            "    };\n"
            "    return \"?\";\n"
            "}\n"
            "fn main() -> int {\n"
            "    stdp.println(area(Forma.Cuadro(2, 3)));\n"
            "    stdp.println(area(null));\n"
            "    stdp.println(area(Forma.Nada));\n"
            "    return 0;\n"
            "}\n", "cuadro 6\nsin forma\nnada\n")


def test_a_value_pattern_still_compares_and_case_v_takes_the_rest():
    _output(IO + "fn mira(int? x) -> str {\n"
            "    match (x) {\n"
            "        case null { return \"null\"; }\n"
            "        case 7 { return \"siete\"; }\n"
            "        case otro { return f\"otro {otro}\"; }\n"
            "    };\n"
            "    return \"?\";\n"
            "}\n"
            "fn main() -> int {\n"
            "    stdp.println(f\"{mira(7)} {mira(8)} {mira(null)}\");\n"
            "    return 0;\n"
            "}\n", "siete otro 8 null\n")


def test_case_v_borrows_the_content_like_a_payload():
    """``v`` es el contenido MISMO (prestado): cambiar un campo dentro de la
    rama cambia el del sujeto, igual que con el payload de ``case E.A(x)``."""
    _output(IO + "struct { int n; } Caja;\n"
            "fn main() -> int {\n"
            "    var Caja? c = Caja{ n: 1 };\n"
            "    match (c) {\n"
            "        case null { }\n"
            "        case k { k.n = 99; }\n"
            "    };\n"
            "    match (c) {\n"
            "        case null { }\n"
            "        case k { stdp.println(f\"caja {k.n}\"); }\n"
            "    };\n"
            "    return 0;\n"
            "}\n", "caja 99\n")


def test_case_v_on_an_owner_does_not_destroy_it():
    """Lo ligado sigue siendo del sujeto: al cerrar la rama no se destruye,
    y el dueño lo destruye UNA vez al final."""
    _output(IO + "struct { int n; } R;\n"
            "hook fn __free__(R ptr mutable r) -> void { stdp.println(f\"free {r.n}\"); }\n"
            "fn main() -> int {\n"
            "    var R? x = R{ n: 2 };\n"
            "    match (x) {\n"
            "        case null { }\n"
            "        case v { stdp.println(f\"opcional {v.n}\"); }\n"
            "    };\n"
            "    stdp.println(\"fin\");\n"
            "    return 0;\n"
            "}\n", "opcional 2\nfin\nfree 2\n")


# --------------------------------------------------------------------------- #
# x ?? d
# --------------------------------------------------------------------------- #

def test_null_coalesce_gives_the_content_or_the_default():
    _output(IO + "fn busca(bool si) -> int? { if (si) { return 4; } return null; }\n"
            "fn main() -> int {\n"
            "    var int? a = null;\n"
            "    var int? b = 7;\n"
            "    var int x = a ?? 1;\n"
            "    var int y = b ?? 2;\n"
            "    stdp.println(f\"{x} {y} {busca(true) ?? 0} {busca(false) ?? -1}\");\n"
            "    return 0;\n"
            "}\n", "1 7 4 -1\n")


def test_null_coalesce_short_circuits():
    """El defecto solo se evalúa si hace falta: ``caro`` corre una vez."""
    _output(IO + "fn caro() -> int { stdp.println(\"caro\"); return 9; }\n"
            "fn main() -> int {\n"
            "    var int? lleno = 3;\n"
            "    var int? vacio = null;\n"
            "    var int a = lleno ?? caro();\n"
            "    var int b = vacio ?? caro();\n"
            "    stdp.println(f\"{a} {b}\");\n"
            "    return 0;\n"
            "}\n", "caro\n3 9\n")


def test_null_coalesce_chains_to_the_right():
    _output(IO + "fn main() -> int {\n"
            "    var int? a = null;\n"
            "    var int? b = null;\n"
            "    var int? c = 5;\n"
            "    stdp.println(f\"{a ?? b ?? 3} {a ?? c ?? 3}\");\n"
            "    return 0;\n"
            "}\n", "3 5\n")


def test_null_coalesce_precedence_below_arithmetic():
    """``a ?? b + 1`` es ``a ?? (b + 1)``."""
    _output(IO + "fn main() -> int {\n"
            "    var int? a = null;\n"
            "    var int b = 10;\n"
            "    var int? c = 2;\n"
            "    stdp.println(f\"{a ?? b + 1} {c ?? b + 1}\");\n"
            "    return 0;\n"
            "}\n", "11 2\n")


def test_null_coalesce_on_a_pointer_and_on_a_struct_copy():
    """Sobre un ``T ptr?`` da el puntero; sobre un struct sin destructor,
    una COPIA (ligarla a un nombre no cambia el original). El defecto es
    EXACTAMENTE ``int ptr``: ``&`` de un ``const`` (el de un ``var`` sería
    ``int ptr mutable``, y ``??`` no suelta la mutabilidad)."""
    _output(IO + "struct { int n; } P;\n"
            "fn main() -> int {\n"
            "    var int uno = 1;\n"
            "    const int dos = 2;\n"
            "    var int ptr? q = null;\n"
            "    var int ptr p = q ?? &dos;\n"
            "    var P? s = P{ n: 5 };\n"
            "    var P t = s ?? P{ n: 0 };\n"
            "    t.n = 6;\n"
            "    var P? vacio = null;\n"
            "    var P u = vacio ?? P{ n: 8 };\n"
            "    stdp.println(f\"{p[0]} {t.n} {u.n}\");\n"
            "    match (s) { case null { } case v { stdp.println(f\"{v.n}\"); } };\n"
            "    return uno - 1;\n"
            "}\n", "2 6 8\n5\n")


# --------------------------------------------------------------------------- #
# enums genéricos
# --------------------------------------------------------------------------- #

_RES = "enum Res<T, E> { Ok(T), Err(E), Vacio };\n"


def test_generic_enum_construction_and_match():
    _output(IO + _RES +
            "fn divide(int a, int b) -> Res<int, str> {\n"
            "    if (b == 0) { return Res<int, str>.Err(\"division por cero\"); }\n"
            "    return Res<int, str>.Ok(a / b);\n"
            "}\n"
            "fn texto(Res<int, str> r) -> str {\n"
            "    match (r) {\n"
            "        case Res<int, str>.Ok(v) { return f\"ok {v + 1}\"; }\n"
            "        case Res<int, str>.Err(m) { return f\"error: {m}\"; }\n"
            "        case Res<int, str>.Vacio { return \"vacio\"; }\n"
            "    };\n"
            "    return \"?\";\n"
            "}\n"
            "fn main() -> int {\n"
            "    stdp.println(texto(divide(10, 2)));\n"
            "    stdp.println(texto(divide(1, 0)));\n"
            "    stdp.println(texto(Res<int, str>.Vacio));\n"
            "    return 0;\n"
            "}\n", "ok 6\nerror: division por cero\nvacio\n")


def test_generic_enum_payload_is_written_with_its_argument():
    """En un f-string el payload ``T`` se escribe como el tipo que lo
    sustituye: un enum por el nombre de su variante, una cadena con comillas
    en ``!r``."""
    _output(IO + _RES + "enum Color { ROJO, VERDE };\n"
            "fn main() -> int {\n"
            "    var Res<Color, str> c = Res<Color, str>.Ok(Color.VERDE);\n"
            "    stdp.println(f\"{c} {c!r} {Res<str, int>.Ok(\"hola\")!r}\");\n"
            "    return 0;\n"
            "}\n", "Ok(VERDE) Res.Ok(Color.VERDE) Res.Ok(\"hola\")\n")


def test_generic_enum_in_a_generic_function():
    _output(IO + _RES +
            "fn ok<T>(T x) -> Res<T, str> { return Res<T, str>.Ok(x); }\n"
            "fn main() -> int {\n"
            "    match (ok<int>(3)) {\n"
            "        case Res<int, str>.Ok(v) { stdp.println(f\"{v}\"); }\n"
            "        case Res<int, str>.Err(m) { }\n"
            "        case Res<int, str>.Vacio { }\n"
            "    };\n"
            "    return 0;\n"
            "}\n", "3\n")


def test_generic_enum_destroys_an_owner_payload_once():
    """``Res<R, int>`` posee si ``R`` posee: su payload se destruye con él,
    una vez (el ``T`` se sustituye antes de decidir la propiedad)."""
    _output(IO + "enum Res<T, E> { Ok(T), Err(E) };\n"
            "struct { int n; } R;\n"
            "hook fn __free__(R ptr mutable r) -> void { stdp.println(f\"free {r.n}\"); }\n"
            "fn main() -> int {\n"
            "    var Res<R, int> a = Res<R, int>.Ok(R{ n: 1 });\n"
            "    var Res<R, int> b = move a;\n"
            "    match (b) {\n"
            "        case Res<R, int>.Ok(r) { stdp.println(f\"tengo {r.n}\"); }\n"
            "        case Res<R, int>.Err(e) { }\n"
            "    };\n"
            "    stdp.println(\"fin\");\n"
            "    return 0;\n"
            "}\n", "tengo 1\nfin\nfree 1\n")


def test_an_optional_generic_enum():
    _output(IO + _RES +
            "fn main() -> int {\n"
            "    var Res<int, str>? q = Res<int, str>.Ok(8);\n"
            "    match (q) {\n"
            "        case null { stdp.println(\"sin resultado\"); }\n"
            "        case Res<int, str>.Ok(v) { stdp.println(f\"ok {v}\"); }\n"
            "        case Res<int, str>.Err(m) { stdp.println(m); }\n"
            "        case Res<int, str>.Vacio { }\n"
            "    };\n"
            "    return 0;\n"
            "}\n", "ok 8\n")


def test_a_generic_enum_from_a_library():
    lib = ("enum Res<T, E> { Ok(T), Err(E), Nada };\n"
           "fn bueno(int n) -> Res<int, str> { return Res<int, str>.Ok(n); }\n"
           "#export as res\n")
    main = W + ("#import res\n"
                "fn main() -> int {\n"
                "    var res.Res<int, str> s = res.bueno(7);\n"
                "    var res.Res<int, str> n = res.Res<int, str>.Nada;\n"
                "    match (s) {\n"
                "        case res.Res<int, str>.Ok(v) { __write__(f\"ok {v}\\n\"); }\n"
                "        case res.Res<int, str>.Err(e) { __write__(e); }\n"
                "        case res.Res<int, str>.Nada { }\n"
                "    };\n"
                "    match (n) {\n"
                "        case res.Res<int, str>.Nada { __write__(\"nada\\n\"); }\n"
                "        case res.Res<int, str>.Ok(v) { }\n"
                "        case res.Res<int, str>.Err(e) { }\n"
                "    };\n"
                "    return 0;\n"
                "}\n")
    code, out, err = run_project({"lib/res.libsrx": lib, "main.srcx": main},
                                 args=["--run", "interpreter"])
    assert code == 0, (out, err)
    assert out.endswith("ok 7\nnada\n"), out
