"""unit/symbols_uml — la tabla de símbolos -> diagrama de clases Mermaid
(``--dump-symbols-table``), el formato que consume la web de /documentation.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze  # noqa: E402
from include.symbols_uml import symbol_table_to_mermaid  # noqa: E402

SRC = """
fn __write__(str s) -> void;
struct { int x; int y; } Point;
struct { Point origin; int id; } Shape;
@impl Point {
    fn sum(Point ptr self) -> int { return self.x + self.y; }
    fn shift(Point ptr mutable self, int d) -> void { self.x = self.x + d; }
}
enum Color { Rojo, Verde, Azul };
fn free_fn(int n) -> int { return n; }
"""


def _mermaid():
    _program, table, _errors = analyze(SRC)
    return symbol_table_to_mermaid(table)


def test_empieza_con_class_diagram():
    assert _mermaid().startswith("classDiagram")


def test_struct_es_una_clase_con_campos():
    out = _mermaid()
    assert "class Point {" in out
    assert "+int x" in out and "+int y" in out


def test_metodos_del_impl_aparecen_sin_receptor():
    """El receptor (primer parámetro) NO se muestra: 'sum()' no 'sum(Point ptr)'."""
    out = _mermaid()
    assert "+sum() int" in out
    assert "+shift(int) void" in out


def test_enum_lleva_estereotipo():
    out = _mermaid()
    assert "class Color {" in out
    assert "<<enumeration>>" in out
    assert "Rojo" in out and "Azul" in out


def test_campo_nominal_es_una_asociacion():
    """Un campo cuyo tipo es otro tipo -> flecha de asociación."""
    assert "Shape --> Point : origin" in _mermaid()


def test_funciones_libres_en_su_caja():
    out = _mermaid()
    assert "<<module>>" in out
    assert "+free_fn(int) int" in out


# --- lo que la tabla guarda ADEMÁS de los tipos -----------------------------
# Un programa de funciones libres producía una sola caja <<module>>, y eso se
# leía como "la tabla de símbolos no maneja nada más". Estas pruebas fijan que
# el resto de lo que la tabla SÍ conoce llegue al diagrama.

SRC_COMPLETO = """
#from io #import stdp
#import d_types.dt_variables as dt

const int LIMITE = 10;
var int contador = 0;

fn main() -> int { return LIMITE; }
"""


def _mermaid_completo():
    _program, table, _errors = analyze(SRC_COMPLETO)
    return symbol_table_to_mermaid(table)


def test_globales_tienen_su_caja():
    out = _mermaid_completo()
    assert "<<scope global>>" in out
    assert "+const int LIMITE" in out
    assert "+int contador" in out


def test_el_import_muestra_lo_que_expone():
    """'println' no está en el lenguaje: se ve de qué unidad viene."""
    out = _mermaid_completo()
    assert "class stdp {" in out
    assert "<<import>>" in out
    assert "+println(str) void" in out


def test_un_import_puede_exportar_tipos():
    assert "+type int8" in _mermaid_completo()


def test_las_conversiones_alcanzables_se_listan():
    out = _mermaid_completo()
    assert "<<__cast__>>" in out
    assert "+cast(int) int8" in out


def test_sin_importaciones_no_hay_cajas_vacias():
    """Cada caja se dibuja solo si tiene contenido."""
    out = _mermaid()
    assert "<<import>>" not in out
    assert "<<scope global>>" not in out
