"""La Semántica hace TRES pasadas, no cuatro.

``type_resolver`` era la pasada 2: un recorrido plano de todo el árbol que
validaba los tipos nominales sin saber en qué scope estaba. Se fundió dentro
de ``scope_resolver``, que ya recorría lo mismo CON scopes. Su lógica no se
duplicó ni se tiró — vive en ``TypeBinder`` y se invoca en el punto donde
cada anotación entra en juego.

Estos tests fijan las dos cosas que el cambio tenía que conseguir a la vez:
que el recorrido de más desaparezca (rendimiento) y que la validación siga
siendo la misma (corrección). Sin el primero, la duplicación de recorridos
vuelve a colarse; sin el segundo, se pierde silenciosamente cobertura.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, os.path.join(_REPO_ROOT, "test"))

from helpers import assert_has_code, assert_ok  # noqa: E402


def test_la_semantica_corre_tres_pasadas():
    """Guarda contra la reaparición del recorrido duplicado."""
    import inspect

    from src.frontend.semantic import semantic

    fuente = inspect.getsource(semantic.analyze)
    assert "type_resolver" not in fuente, (
        "'type_resolver' volvió a ser una pasada: su trabajo lo hace "
        "'scope_resolver' con el TypeBinder, en el mismo recorrido")


def test_type_resolver_ya_no_expone_una_pasada():
    from src.frontend.semantic import type_resolver

    assert not hasattr(type_resolver, "run"), (
        "'type_resolver.run' existe otra vez: sería un segundo recorrido del "
        "árbol haciendo lo que 'scope_resolver' ya hace")
    assert hasattr(type_resolver, "TypeBinder")


# --------------------------------------------------------------------------- #
# la validación que hacía la pasada 2 sigue entera
# --------------------------------------------------------------------------- #

def test_un_tipo_inexistente_en_una_variable_se_reporta():
    assert_has_code("fn f() -> void { var Inexistente x; };", "AST005")


def test_un_tipo_inexistente_en_un_parametro_se_reporta():
    assert_has_code("fn f(Inexistente p) -> void { };", "AST005")


def test_un_tipo_inexistente_en_el_retorno_se_reporta():
    assert_has_code("fn f() -> Inexistente { };", "AST005")


def test_un_tipo_inexistente_en_un_campo_de_struct_se_reporta():
    """Los structs no tienen cuerpo que recorrer, así que ``scope_resolver``
    no los visitaba: hubo que añadirlos al fundir la pasada."""
    assert_has_code("struct { Inexistente a; } T;", "AST005")


def test_un_tipo_inexistente_en_un_prototipo_se_reporta():
    """Un prototipo no tiene cuerpo y ``resolve_function`` cortaba antes de
    mirar su firma: la validación tiene que ocurrir igual."""
    assert_has_code("fn f(Inexistente p) -> void;", "AST005")


def test_un_tipo_inexistente_bajo_ptr_y_nullable_se_reporta():
    assert_has_code("fn f() -> void { var Inexistente ptr p; };", "AST005")
    assert_has_code("fn f() -> void { var Inexistente? q; };", "AST005")


def test_un_tipo_inexistente_en_sizeof_se_reporta():
    assert_has_code("fn f() -> int { return sizeof(Inexistente); };", "AST005")


def test_un_tipo_inexistente_en_cast_se_reporta():
    assert_has_code("fn f() -> void { var int x = cast<Inexistente>(1); };",
                    "AST005")


def test_los_tipos_validos_no_producen_falsos_positivos():
    assert_ok("struct { int x; int y; } Punto;\n"
              "fn area(Punto ptr p) -> int { return p.x * p.y; };\n"
              "fn main() -> int { var Punto p = Punto{ x: 1, y: 2 }; "
              "return area(&p); };")
