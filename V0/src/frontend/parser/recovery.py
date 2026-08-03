"""Recuperacion de errores: modo panico consciente de profundidad de llaves.

Ante un ``ParseError`` (o ``RecursionError``) al parsear un item de nivel
superior, ``grammar/program.py`` llama a :func:`synchronize` para descartar
**ese item completo, como unidad**, y reanudar en el siguiente. Se le pasa
``start_pos``: la posicion del cursor justo ANTES de intentar el item que
fallo.

Diseño (revision de calidad -- version anterior tenia un bug real):

La primera version de esta funcion escaneaba hacia ADELANTE desde la
posicion del ERROR (no desde el inicio del item), buscando el primer token
perteneciente a un conjunto SYNC precomputado (``FIRST`` de cualquier
declaracion/sentencia). Como ese conjunto incluye practicamente todo token
que puede iniciar una expresion (identificadores, literales, parentesis...),
la recuperacion se detenia tras descartar un unico token en casi cualquier
caso real. Verificado: un simple parentesis faltante en un ``if`` dentro de
una funcion hacia que TODA la funcion desapareciera del AST (sus sentencias
internas reaparecian como items de nivel superior sueltos), con 3 errores en
cascada en vez de 1. El modulo ``firstsets.py`` que sostenia ese conjunto se
elimino junto con este rediseño: ya no tiene ningun consumidor real.

La version actual **rebobina al inicio del item roto** (``start_pos``) y
cuenta profundidad de ``{``/``}`` DESDE CERO -- un item de nivel superior
siempre arranca a profundidad 0 -- avanzando hasta que la profundidad vuelve
a como mucho 1 tras haberse abierto (el ``}`` que cierra el propio item), o
hasta un ``;`` visto a profundidad 0 (formas que terminan en ``;`` sin
llegar a abrir ninguna llave). Esto descarta el item completo de una sola
vez, sin importar en que profundidad interna ocurrio el error original, y
reporta un unico diagnostico por error real en vez de una cascada.
"""

from __future__ import annotations

try:
    from include.t_types import TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from t_types import TokenType  # type: ignore

from .cursor import Cursor


def synchronize(cursor: Cursor, start_pos: int) -> None:
    """Descarta el item de nivel superior que arrancaba en ``start_pos``.

    Garantia de progreso: cada iteracion o retorna, o llama
    ``cursor.advance()`` (que nunca retrocede y se detiene solo en EOF), asi
    que la funcion siempre termina.
    """
    cursor.pos = start_pos
    depth = 0

    while not cursor.at_end():
        tok = cursor.peek()

        if tok.type is TokenType.L_BRACE:
            depth += 1
            cursor.advance()
            continue

        if tok.type is TokenType.R_BRACE:
            cursor.advance()
            if depth <= 1:
                return  # cierra el '{' del propio item (o llave suelta): fin
            depth -= 1
            continue

        if depth == 0 and tok.type is TokenType.SEMICOLON:
            cursor.advance()
            return

        cursor.advance()

    # EOF alcanzado sin cerrar: no hay mas que hacer, el bucle de
    # 'parse_program' termina solo por 'cursor.at_end()'.


__all__ = ["synchronize"]
