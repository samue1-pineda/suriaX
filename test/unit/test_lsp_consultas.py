"""unit/lsp_consultas — la traducción del índice del compilador al LSP.

``tooling/lsp/consultas.py`` son funciones puras: se prueban sin lanzar el
servidor. La sesión entera, por las tuberías, está en
``test/e2e/test_servidor_lsp.py``.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO, os.path.join(_REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_cada_tipo_de_simbolo_del_compilador_tiene_su_traduccion():
    """Un ``SymbolKind`` nuevo sin traducir tiene que romper aquí, no salir
    en el esquema del editor con un icono cualquiera."""
    from src.frontend.semantic.symbol_table import SymbolKind
    from tooling.lsp import consultas

    del_compilador = {k.name.lower() for k in SymbolKind} | {"method"}
    assert set(consultas.TIPO_DE_SIMBOLO) == del_compilador
    assert set(consultas.TIPO_DE_COMPLETADO) == del_compilador


def test_la_version_del_indice_es_la_que_el_servidor_sabe_leer():
    from src.frontend.semantic.index import INDEX_VERSION
    from tooling.lsp import consultas

    assert consultas.INDEX_VERSION_SOPORTADA == INDEX_VERSION, (
        "el índice cambió de forma: actualiza tooling/lsp/consultas.py y "
        "después INDEX_VERSION_SOPORTADA")


def test_columnas_utf16_ida_y_vuelta():
    from tooling.lsp.consultas import a_utf16, desde_utf16

    linea = 'var str s = "😀ñ"; x'
    x = linea.index("x")
    assert a_utf16(linea, x) == x + 1          # el emoji ocupa dos unidades
    assert desde_utf16(linea, x + 1) == x
    assert a_utf16(linea, linea.index("ñ")) == linea.index("ñ") + 1
    assert a_utf16(linea, 999) == a_utf16(linea, len(linea)), "se queda en el final"


def test_uri_y_ruta_ida_y_vuelta():
    from tooling.lsp.consultas import misma_ruta, ruta_a_uri, uri_a_ruta

    ruta = os.path.join(_REPO, "lib", "io", "año con espacio.libsrx")
    assert misma_ruta(uri_a_ruta(ruta_a_uri(ruta)), ruta)
    if sys.platform == "win32":
        # así lo escribe VS Code: unidad en minúscula y ':' codificado
        assert uri_a_ruta("file:///c%3A/Users/x%20y/a.srcx").lower() == r"c:\users\x y\a.srcx"
    assert uri_a_ruta("untitled:Untitled-1") is None


def test_un_diagnostico_de_otro_archivo_se_ve_aqui_con_su_enlace():
    """Un manifiesto roto o una nota de una librería: no se publica en un
    documento ajeno, ni se calla."""
    from tooling.lsp.consultas import diagnosticos

    propio = os.path.join(_REPO, "prog.srcx")
    ajeno = os.path.join(_REPO, "extends.srcx")
    salida = diagnosticos({"diagnostics": [
        {"code": "EXT001", "message": "hook mal declarado", "line": 3, "column": 5,
         "severity": "critical", "file": ajeno},
        {"code": "X", "message": "m", "line": 1, "column": 1, "severity": "rara",
         "file": propio}]}, ["fn main() -> int { return 0; }"], propio)
    externo, raro = salida
    assert externo["range"]["start"] == {"line": 0, "character": 0}
    assert externo["message"].startswith("extends.srcx:3:5: ")
    assert externo["relatedInformation"][0]["location"]["range"]["start"] == \
        {"line": 2, "character": 4}
    # una severidad desconocida se ve (como error) y dice cuál era
    assert raro["severity"] == 1 and "'rara'" in raro["message"]


def test_el_nombre_se_busca_desde_la_declaracion():
    """El índice da dónde empieza la DECLARACIÓN (``fn``, ``var``, o un
    struct que lleva el nombre al final); el editor quiere el nombre."""
    from tooling.lsp.consultas import tramo_del_nombre

    lineas = ["struct { int x; int y; } Punto;", "fn doble(int n) -> int {",
              "    var int a = 1;"]
    assert tramo_del_nombre(lineas, 1, 1, "Punto") == (0, 25, 30)
    assert tramo_del_nombre(lineas, 1, 10, "x") == (0, 13, 14)
    assert tramo_del_nombre(lineas, 2, 1, "doble") == (1, 3, 8)
    assert tramo_del_nombre(lineas, 3, 5, "a") == (2, 12, 13)
    # si no aparece, se queda en la columna y sin ancho
    assert tramo_del_nombre(lineas, 1, 3, "otro") == (0, 2, 2)
