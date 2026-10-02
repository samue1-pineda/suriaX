"""e2e/libraries: tipos y hooks publicados por una libreria, y los diagnosticos del linker.

Parte de ``test_libraries.py`` (partido por tema); lo compartido esta en
``libraries_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_project_output, run_project  # noqa: E402
from libraries_support import (  # noqa: E402
    PKG,
    W,
)

# --------------------------------------------------------------------------- #
# tipos publicados por una librería (se nombran CUALIFICADOS)
# --------------------------------------------------------------------------- #

GEO = {
    "lib/geo/main.libsrx": "#export package as geo\n",
    "lib/geo/point.libsrx": """
struct { int x; int y; } Point;
fn build(int a, int b) -> Point { return Point{ x: a, y: b }; }
fn sum(Point ptr p) -> int { return p.x + p.y; }
#export as point
""",
}


def test_tipo_de_libreria_en_una_anotacion():
    """'point.Point' debe UNIFICAR con el 'Point' que devuelve la librería."""
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "fn main() -> int { var point.Point p = point.build(3, 4); "
                                 '__write__(f"{point.sum(&p)}\\n"); return 0; };\n'},
        "7\n")


def test_tipo_de_libreria_construido_con_literal():
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "fn main() -> int { var point.Point p = point.Point{ x: 2, y: 5 }; "
                                 '__write__(f"{point.sum(&p)}\\n"); return 0; };\n'},
        "7\n")


def test_tipo_de_libreria_envuelto_en_puntero_y_nullable():
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "fn total(point.Point ptr p) -> int { return point.sum(p); };\n"
                                 "fn main() -> int { var point.Point p = point.build(10, 5); "
                                 '__write__(f"{total(&p)}\\n"); return 0; };\n'},
        "15\n")


def test_tipo_de_libreria_como_campo_de_un_struct_local():
    assert_project_output(
        {**GEO, "main.srcx": W + "#import geo.point\n"
                                 "struct { point.Point origin; int id; } Shape;\n"
                                 "fn main() -> int { var Shape s = Shape{ origin: point.build(6, 1), id: 9 }; "
                                 '__write__(f"{point.sum(&s.origin)}\\n"); return 0; };\n'},
        "7\n")


def test_enum_de_libreria():
    files = {
        "lib/col/main.libsrx": "#export package as col\n",
        "lib/col/hue.libsrx": "enum Color { Rojo, Verde, Azul };\n"
                              "fn code(int c) -> int { return c * 10; }\n#export as hue\n",
        "main.srcx": W + "#import col.hue\n"
                         'fn main() -> int { __write__(f"{hue.code(hue.Color.Verde)}\\n"); return 0; };\n',
    }
    assert_project_output(files, "10\n")


# --------------------------------------------------------------------------- #
# hooks declarados por una librería
# --------------------------------------------------------------------------- #

def test_hooks_de_un_tipo_de_libreria_despachan():
    """'print(x)'/'len(x)' sobre un tipo de librería van a SUS hooks."""
    files = {
        "lib/txt/main.libsrx": "#export package as txt\n",
        "lib/txt/cadena.libsrx": W + """
struct { str text; int size; } S;
hook fn __print__(S ptr s) -> void { __write__(s.text); }
hook fn __len__(S ptr s) -> int { return s.size; }
fn of(str t, int n) -> S { return S{ text: t, size: n }; }
#export as cadena
""",
        "main.srcx": W + "#import txt.cadena\n"
                         'fn main() -> int { var cadena.S s = cadena.of("hooked\\n", 6); '
                         'print(s); __write__(f"{len(s)}\\n"); return 0; };\n',
    }
    assert_project_output(files, "hooked\n6\n")


# --------------------------------------------------------------------------- #
# diagnósticos del linker de librerías
# --------------------------------------------------------------------------- #

def test_libreria_inexistente_se_reporta():
    code, _out, err = run_project(
        {"main.srcx": "#import noexiste;\nfn main() -> int { return 0; };\n"},
        args=["--run"])
    assert code != 0 and "SEM009" in err, err


def test_submodulo_inexistente_lista_los_disponibles():
    code, _out, err = run_project(
        {**PKG, "main.srcx": "#import text.nada;\nfn main() -> int { return 0; };\n"},
        args=["--run"])
    assert code != 0 and "SEM011" in err, err


def test_alias_del_export_debe_coincidir_con_el_import():
    """Regla central del linker: un módulo se llama como su '#export'."""
    files = {
        "lib/cosa.libsrx": "fn f() -> void { }\n#export as otra\n",
        "main.srcx": "#import cosa;\nfn main() -> int { return 0; };\n",
    }
    code, _out, err = run_project(files, args=["--run"])
    assert code != 0 and "SEM010" in err, err


def test_una_variante_con_payload_de_un_tipo_de_la_misma_libreria():
    """Regresión: dentro de la librería que declara 'E' y 'P', 'E.Uno(P{...})'
    era un AST006 falso ("se esperaba 'P', se encontró 'formas.P'") y la
    unidad no se emitía. El símbolo de la variante guardaba el payload como
    se escribió; el literal de struct ya salía canónico. En el programa (sin
    unidad) los dos nombres coinciden y no se veía."""
    assert_project_output({
        "lib/formas.libsrx": """
public struct { int x; } P;
public enum E { Uno(P), Dos };
public fn crea(int x) -> E { return E.Uno(P{ x: x }); }
public fn valor(E e) -> int {
    match (e) {
        case E.Uno(p): { return p.x; }
        case E.Dos: { return 0; }
    }
    return -1;
}
#export as formas
""",
        "main.srcx": """#from io #import stdp
#import formas
fn main() -> int {
    stdp.println(f"valor={formas.valor(formas.crea(7))} dos={formas.valor(formas.E.Dos)}");
    return 0;
}
""",
    }, "valor=7 dos=0")
