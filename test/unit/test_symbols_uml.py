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
