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

Lo que va DESPUES de esa llave y sigue siendo del item tambien se descarta:
el ``;`` opcional (``fn f() { ... };``), las clausulas de un ``test`` y el
nombre de un ``struct`` (``struct { ... } S;``). Sin eso, cada uno quedaba
suelto como un item nuevo y daba un error falso (un ``PAR012`` sobre el
``;`` de ``};``, o un ``SEM001`` sobre ``S``).
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
                # cierra el '{' del propio item (o llave suelta): fin. Si era
                # un 'test', sus clausulas son parte del MISMO item; si era un
                # 'struct', tambien su nombre; y el ';' opcional tras la llave
                # ('};') tambien es del item
                _saltar_clausulas(cursor)
                if _is_struct_item(cursor, start_pos):
                    _skip_struct_name(cursor)
                cursor.match(TokenType.SEMICOLON)
                return
            depth -= 1
            continue

        if depth == 0 and tok.type is TokenType.SEMICOLON:
            cursor.advance()
            return

        cursor.advance()

    # EOF alcanzado sin cerrar: no hay mas que hacer, el bucle de
    # 'parse_program' termina solo por 'cursor.at_end()'.


def _is_struct_item(cursor: Cursor, start_pos: int) -> bool:
    """¿El item que empieza en ``start_pos`` es un ``struct`` (tambien el de
    un ``@trait``)? Lo dice un ``struct`` antes de su primera llave."""
    for tok in cursor.tokens[start_pos:]:
        if tok.type is TokenType.STRUCT:
            return True
        if tok.type in (TokenType.L_BRACE, TokenType.SEMICOLON, TokenType.EOF):
            return False
    return False


def _skip_struct_name(cursor: Cursor) -> None:
    """Descarta ``Nombre [<T, ...>] ;`` tras la llave de un ``struct`` roto.

    El nombre de un struct va DESPUES de su cuerpo (``struct { ... } S;``):
    sin esto quedaba suelto como una sentencia de nivel superior (``S;``), y
    el error real arrastraba otro falso (``SEM001: 'S' no esta declarado``).
    Se acepta cualquier palabra como nombre —tambien una reservada: ``struct
    { ... } error;`` ya es el error que se esta recuperando— y, si lo que
    sigue no tiene esa forma, el cursor no se mueve."""
    start = cursor.pos
    if cursor.peek().lexeme.isidentifier():
        cursor.advance()
        if cursor.check(TokenType.LESS):
            while not cursor.at_end() and not cursor.check(TokenType.GREATER):
                if cursor.peek().type in (TokenType.L_BRACE, TokenType.R_BRACE,
                                          TokenType.SEMICOLON):
                    break
                cursor.advance()
            cursor.match(TokenType.GREATER)
        if cursor.match(TokenType.SEMICOLON):
            return
    cursor.pos = start


def _saltar_clausulas(cursor: Cursor) -> None:
    """Descarta las clausulas ``errfinally { }`` / ``finally { }`` que siguen
    al bloque recien cerrado: son de la prueba que se esta descartando. Sin
    esto quedaban sueltas en el nivel superior y cada una era un error en
    cascada (un ``PAR012`` por clausula, ademas del error real)."""
    clausulas = (TokenType.ERRFINALLY, TokenType.FINALLY)
    while cursor.peek().type in clausulas and cursor.peek(1).type is TokenType.L_BRACE:
        cursor.advance()
        depth = 0
        while not cursor.at_end():
            tok = cursor.peek()
            cursor.advance()
            if tok.type is TokenType.L_BRACE:
                depth += 1
            elif tok.type is TokenType.R_BRACE:
                depth -= 1
                if depth == 0:
                    break


__all__ = ["synchronize"]
