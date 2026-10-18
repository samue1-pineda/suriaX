"""``type T;`` dentro de una función: existe, respeta su scope y sombrea bien.

Antes no lo registraba nadie. ``collect`` (pasada 1) solo recorre el nivel
superior, y la validación de tipos nominales era una pasada PLANA que corría
ANTES de que se abriera ningún scope: un ``type`` declarado aquí dentro se
descartaba en silencio y el fallo salía lejos, como un ``AST005`` en el
primer uso.

Al fundir esa pasada dentro de ``scope_resolver`` la validación pasó a ver el
scope, y con ella llegó un riesgo nuevo que estos tests vigilan: la caché de
nombres del binder. Cuando el recorrido era plano, un nombre resolvía siempre
a lo mismo y cachearlo de por vida era correcto; con scopes, un tipo local
puede sombrear a uno global y recordar el primero daría el tipo EQUIVOCADO
—el programa compilaría, mal—.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_has_code, assert_ok, error_codes  # noqa: E402


# --------------------------------------------------------------------------- #
# existe y se puede usar
# --------------------------------------------------------------------------- #

def test_un_type_anidado_se_declara_y_se_usa():
    assert_ok("fn f() -> void { const type Local; const Local? x = null; };")


def test_var_type_anidado_tambien():
    assert_ok("fn f() -> void { var type Local; const Local? x = null; };")


def test_un_type_anidado_admite_punteros_y_nullable():
    assert_ok("fn f() -> void { const type T; const T ptr? p = null; const T? q = null; };")


def test_dos_declaraciones_del_mismo_nombre_en_el_scope_colisionan():
    assert_has_code("fn f() -> void { const type L; const type L; };", "SEM002")


# --------------------------------------------------------------------------- #
# el scope se respeta en las dos direcciones
# --------------------------------------------------------------------------- #

def test_un_type_local_no_se_filtra_a_otra_funcion():
    assert_has_code(
        "fn f() -> void { const type T; };\nfn g() -> void { const T? x = null; };",
        "AST005")


def test_dos_funciones_pueden_declarar_el_mismo_nombre():
    assert_ok("fn f() -> void { const type T; const T? x = null; };\n"
              "fn g() -> void { const type T; const T? y = null; };")


def test_un_type_de_un_bloque_no_sale_del_bloque():
    assert_has_code(
        "fn f() -> void { if (true) { const type B; } const B? x = null; };", "AST005")


def test_un_type_de_la_funcion_si_entra_al_bloque():
    assert_ok("fn f() -> void { const type T; if (true) { const T? x = null; } };")


def test_un_type_del_try_no_sale_al_catch():
    assert_has_code(
        "fn f() -> void { try { const type E; } catch (e) { const E? x = null; } };",
        "AST005")


def test_sin_referencia_hacia_adelante_dentro_de_una_funcion():
    """Los globales SÍ admiten forward reference porque ``collect`` los
    registra antes de recorrer nada; dentro de una función las sentencias se
    resuelven en orden, igual que con las variables."""
    assert_has_code("fn f() -> void { const T? x = null; const type T; };", "AST005")


def test_un_type_global_sigue_admitiendo_referencia_hacia_adelante():
    assert_ok("fn f() -> void { const G? x = null; };\nconst type G;")


# --------------------------------------------------------------------------- #
# sombreado: aquí es donde la caché podría mentir
# --------------------------------------------------------------------------- #

def test_un_type_local_sombrea_al_global_del_mismo_nombre():
    """El local es OPACO y el global es un ``struct``: si la caché filtrara el
    global, el literal ``T{ a: 1 }`` compilaría dentro de la función y el
    programa sería válido con el tipo equivocado."""
    assert_has_code(
        "struct { int a; } T;\n"
        "fn f() -> void { const type T; var T x = T{ a: 1 }; };",
        "AST005")


def test_el_global_sigue_intacto_fuera_del_scope_que_lo_sombrea():
    assert_ok("struct { int a; } T;\n"
              "fn f() -> void { const type T; };\n"
              "fn g() -> void { var T y = T{ a: 1 }; };")


def test_el_sombreado_funciona_con_la_cache_ya_caliente():
    """El caso que de verdad ejercita la invalidación: ``g`` usa el global
    ANTES, así que el nombre ya está cacheado cuando ``f`` lo sombrea."""
    codes = error_codes(
        "struct { int a; } T;\n"
        "fn g() -> void { var y = T{ a: 1 }; };\n"
        "fn f() -> void { const type T; var T x = T{ a: 1 }; };")
    assert "AST005" in codes, (
        f"el tipo local debe ganar dentro de su scope aunque el global ya "
        f"estuviera cacheado; se obtuvo: {codes}")


def test_un_type_de_bloque_no_sobrevive_al_bloque_con_un_global_detras():
    assert_ok("const type T;\n"
              "fn f() -> void { if (true) { const type T; const T? x = null; } "
              "const T? y = null; };")


# --------------------------------------------------------------------------- #
# el inicializador
# --------------------------------------------------------------------------- #

def test_el_inicializador_de_un_type_anidado_resuelve_sus_nombres():
    assert_has_code("fn f() -> void { const type L = _no_existe(1); };",
                    "SEM001")


def test_el_inicializador_de_un_type_anidado_debe_producir_un_tipo():
    assert_has_code("fn f() -> void { const type L = 5; };", "AST006")


def test_un_inicializador_anidado_valido_compila_limpio():
    assert_ok("fn h(int b) -> type;\n"
              "fn f() -> void { const type L = h(8); };")
