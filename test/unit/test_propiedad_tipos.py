"""``type_service.owns_resources``: qué tipos tienen una obligación de destrucción.

Es la noción central del modelo de memoria (ownership + drop + arenas) y la
precondición del drop automático: sin esta pregunta, el compilador no puede
saber qué destruir al cerrar un ámbito — tendría que invocar un destructor
sobre todo, o sobre nada.

Lo que se fija aquí son las tres reglas y sus consecuencias. La primera —que
un ``ptr`` no posee— no es solo semántica: es lo que hace que la recursión
TERMINE, porque los tipos recursivos del lenguaje se cierran a través de
punteros. Si alguien la relaja, estos tests se cuelgan antes de fallar, y por
eso hay uno con reloj.
"""

from __future__ import annotations

import os
import signal
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0, os.path.join(_REPO_ROOT, "test")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from helpers import lex  # noqa: E402

_PROGRAMA = """
struct { int ptr datos; int largo; } Buffer;
hook fn __free__(Buffer ptr b) -> void { };

struct { Buffer b; int n; } Caja;
struct { Buffer ptr prestado; int n; } Vista;
struct { Caja c; } Envoltorio;
struct { int x; int y; } Punto;
struct { Nodo ptr sig; int v; } Nodo;
enum Color { Rojo, Verde };

fn main() -> int { return 0; };
"""


def _tabla(source: str = _PROGRAMA):
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze

    tokens, lex_errors = lex(source)
    assert not lex_errors, [e.code for e in lex_errors]
    parser = Parser(tokens)
    program = parser.parse()
    assert not parser.ctx.errors, [e.message for e in parser.ctx.errors]
    resolve_types(program)
    table, sem_errors = analyze(program, source_path="<test>")
    assert not sem_errors, [e.message for e in sem_errors]
    return table


def _posee(nombre_o_tipo, table=None):
    from src.frontend.semantic import type_service
    from include.types_ast import nominal

    table = table or _tabla()
    t = nominal(nombre_o_tipo) if isinstance(nombre_o_tipo, str) else nombre_o_tipo
    return type_service.owns_resources(t, table.global_scope, table)


# --------------------------------------------------------------------------- #
# regla 2: lo declara con '__free__'
# --------------------------------------------------------------------------- #

def test_un_tipo_con_free_posee():
    assert _posee("Buffer") is True


def test_un_tipo_de_solo_primitivos_no_posee():
    assert _posee("Punto") is False


def test_un_enum_no_posee():
    assert _posee("Color") is False


def test_un_primitivo_no_posee():
    from include.types_ast import PRIMITIVE_TYPES
    assert _posee(PRIMITIVE_TYPES["int"]) is False


def test_sin_tipo_no_posee():
    assert _posee(None) is False


def test_un_nombre_que_no_resuelve_no_posee():
    """No se inventa una obligación sobre un tipo que no se pudo ver; el
    diagnóstico del nombre inexistente lo da quien resolvió el scope."""
    assert _posee("Fantasma") is False


# --------------------------------------------------------------------------- #
# regla 1: un 'ptr' es un préstamo, no un dueño
# --------------------------------------------------------------------------- #

def test_un_puntero_a_un_tipo_que_posee_no_posee():
    """Lo apuntado tiene dueño en otra parte. Si un ``ptr`` poseyera, salir de
    ámbito destruiría el valor de otro."""
    from include.types_ast import nominal, pointer_of
    assert _posee(pointer_of(nominal("Buffer"))) is False


def test_un_campo_puntero_no_contagia_la_propiedad():
    assert _posee("Vista") is False


# --------------------------------------------------------------------------- #
# regla 3: contener un dueño es ser dueño
# --------------------------------------------------------------------------- #

def test_un_struct_con_un_campo_que_posee_posee():
    """'Caja' no declara ``__free__``, pero lleva un 'Buffer' POR VALOR."""
    assert _posee("Caja") is True


def test_la_propiedad_es_transitiva_a_traves_de_varios_saltos():
    """Envoltorio -> Caja -> Buffer: ninguno de los dos primeros declara nada."""
    assert _posee("Envoltorio") is True


# --------------------------------------------------------------------------- #
# envoltorios
# --------------------------------------------------------------------------- #

def test_un_nullable_hereda_la_propiedad_de_lo_que_envuelve():
    from include.types_ast import nominal, nullable_of
    tabla = _tabla()
    assert _posee(nullable_of(nominal("Buffer")), tabla) is True
    assert _posee(nullable_of(nominal("Punto")), tabla) is False


# --------------------------------------------------------------------------- #
# terminación
# --------------------------------------------------------------------------- #

def test_un_tipo_recursivo_por_puntero_termina():
    """'Nodo' se cierra sobre sí mismo a través de un 'ptr': la regla 1 corta
    ahí. Si alguien hace que un puntero posea, esto no falla — se cuelga."""
    assert _posee("Nodo") is False


def test_un_struct_que_se_contiene_por_valor_no_cuelga():
    """Un tipo de tamaño infinito ya lo rechaza el frontend (``SEM026``), pero
    este predicado tiene que sobrevivir igual: corre sobre el AST del programa
    aunque haya diagnósticos, y colgarse sería peor que equivocarse.

    Se construye el ciclo a mano, saltándose el análisis, para probar el
    guardia y no el rechazo — el rechazo tiene su propio test.
    """
    from src.frontend.semantic.symbol_table import Symbol, SymbolKind
    from include.types_ast import nominal

    tabla = _tabla()
    ciclo = Symbol(name="Ciclo", kind=SymbolKind.STRUCT, ln=1, col=1,
                   type=nominal("Ciclo"), members={})
    ciclo.members["yo"] = Symbol(name="yo", kind=SymbolKind.FIELD, ln=1, col=1,
                                 type=nominal("Ciclo"))
    tabla.global_scope.define_type(ciclo)
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(5)
    try:
        assert _posee("Ciclo", tabla) is False
    finally:
        signal.alarm(0)


def _timeout(*_args):
    raise AssertionError(
        "owns_resources no terminó: el guardia de ciclos dejó de funcionar")


# --------------------------------------------------------------------------- #
# tipos opacos de librería
# --------------------------------------------------------------------------- #

def test_un_tipo_opaco_posee_si_declara_free():
    """Un ``const type T;`` de una librería no expone campos, así que la regla
    3 no puede decir nada; su ``__free__`` viaja en la tabla de hooks y ES su
    contrato de destrucción completo."""
    from src.frontend.semantic.hooks import HookKind
    from src.frontend.semantic.symbol_table import Symbol, SymbolKind
    from include.types_ast import nominal

    tabla = _tabla()
    opaco = Symbol(name="Opaco", kind=SymbolKind.TYPE, ln=1, col=1,
                   type=nominal("Opaco"))
    tabla.global_scope.define_type(opaco)
    assert _posee("Opaco", tabla) is False, "sin '__free__' no posee"

    destructor = Symbol(name="__free__", kind=SymbolKind.HOOK, ln=1, col=1,
                        hook_kind=HookKind.FREE, hook_owner="Opaco")
    assert tabla.register_hook("Opaco", HookKind.FREE, destructor)
    assert _posee("Opaco", tabla) is True
