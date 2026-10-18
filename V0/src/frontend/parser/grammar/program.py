"""Punto de entrada gramatical: ``program = { top_level } EOF`` (EBNF).

El bucle raiz y la recuperacion de errores viven aqui; el despacho de cada
item y su prefijo de modificadores (visibilidad, ``hook``/``dunder``) los dueña
``grammar/modifiers.py`` (``top_level = [ visibility ] [ hook | dunder ]
declaration``). ``extern_block`` se despacha dentro de
``directives.parse_directive`` (mismo token ``DIRECTIVE``).
"""

from __future__ import annotations

from typing import List

try:
    from include import ast_nodes as ast
    from include.t_types import TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import TokenType  # type: ignore
    import ParseError  # type: ignore

try:
    from include.ast_walk import child_fields, deeper_than
except ImportError:  # pragma: no cover - ejecucion directa
    from ast_walk import child_fields, deeper_than  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor
from ..recovery import synchronize
from .modifiers import parse_top_level_item


#: Niveles que puede anidar una declaracion (ella es el nivel 1; cada nodo
#: hijo, uno mas). Es un limite DEL LENGUAJE, no del parser: el arbol lo
#: recorren despues pasadas recursivas, el HIR lo guarda como mensajes
#: anidados y sus lectores tienen su propio tope, calculado a partir de este
#: (ver 'src/hir/contrato.md'). Sin el, una suma de 300 terminos —que NO anida
#: al escribirse, pero si al recorrerse— tumbaba al emisor del HIR.
#:
#: 500 (decision del mantenedor) deja compilar una cadena de ~496 operadores
#: y ~247 bloques anidados; el codigo real de este repositorio no pasa de 26
#: (medido sobre 1646 declaraciones). Los parentesis no cuentan: no dejan
#: nodo en el arbol, y de su anidamiento extremo se ocupa 'parse_program'.
MAX_NESTING = 500


def parse_program(cursor: Cursor, ctx: ParserContext) -> ast.Program:
    """Analiza el flujo completo. Nunca lanza: los errores de sintaxis se
    acumulan en ``ctx.errors`` (modo panico, ver ``recovery.synchronize``) y
    el AST devuelto es el mejor esfuerzo posible con lo que sí se pudo parsear.

    Tambien captura ``RecursionError``: el parser es de descenso recursivo
    (parentesis/prefijos unarios anidados consumen un nivel de pila de Python
    por nivel de anidamiento), asi que una entrada con anidamiento extremo
    -- adversarial o generada -- puede agotar la pila. Se convierte a
    ``ParseError.ExpressionTooDeepError`` en el mismo punto de recuperacion
    en vez de dejar que el proceso termine con una excepcion no controlada.
    Cuando esto ocurre la pila ya se desenrollo por completo (la excepcion se
    propaga liberando cada marco), asi que hay margen de sobra para construir
    el error y llamar a ``synchronize`` con normalidad.
    """
    tok = cursor.peek()
    items: List[ast.ASTNode] = []

    while not cursor.at_end():
        start_pos = cursor.pos
        try:
            item = parse_top_level_item(cursor, ctx)
            hondo = deeper_than(item, MAX_NESTING)
            if hondo is not None:
                # la declaracion entera se descarta: dejar pasar un arbol que
                # las pasadas siguientes no pueden recorrer cambiaria un
                # diagnostico por un fallo interno mas adelante.
                ctx.errors.append(ParseError.ExpressionTooDeepError(
                    f"la construccion anida mas de {MAX_NESTING} niveles; "
                    + _nesting_advice(item, hondo),
                    line=hondo.ln, column=hondo.col,
                ))
                continue
            # '@impl Tipo { ... }' se APLANA en sus métodos (dunders de nombre
            # llano): las fases posteriores solo ven FunctionDecl, nunca ImplDecl.
            if isinstance(item, ast.ImplDecl):
                items.extend(item.methods)
            else:
                items.append(item)
        except ParseError.ParseError as exc:
            # un token ERROR es un error LEXICO ya informado (el lexer lo
            # anoto en su lista): el parser que tropieza con el solo repetiria
            # el mismo error con otras palabras ('token inesperado en
            # expresion: ERROR'). El item se descarta igual.
            if not _on_lexical_error(cursor, exc):
                ctx.errors.append(exc)
            synchronize(cursor, start_pos)
        except RecursionError:
            err_tok = cursor.peek()
            ctx.errors.append(ParseError.ExpressionTooDeepError(
                "construccion anidada excede la profundidad soportada por el parser",
                line=err_tok.ln, column=err_tok.col,
            ))
            synchronize(cursor, start_pos)

    return ast.Program(ln=tok.ln, col=tok.col, items=items)


def _on_lexical_error(cursor: Cursor, exc) -> bool:
    """¿El error de sintaxis es el tropiezo con un token ``ERROR``? Lo es si
    el parser se detuvo EN ese token y el error apunta a el."""
    tok = cursor.peek()
    return (tok.type is TokenType.ERROR
            and (exc.line, exc.column) == (tok.ln, tok.col))


def _path_to(root: ast.ASTNode, target: ast.ASTNode) -> List[ast.ASTNode]:
    """Los nodos de ``root`` a ``target`` (ambos incluidos). Iterativo: el
    arbol es justamente el que no cabe en una pasada recursiva."""
    parent = {id(root): None}
    stack = [root]
    while stack:
        node = stack.pop()
        if node is target:
            break
        for name in child_fields(type(node)):
            child = getattr(node, name)
            for c in (child if child.__class__ is list else (child,)):
                if isinstance(c, ast.ASTNode) and id(c) not in parent:
                    parent[id(c)] = node
                    stack.append(c)
    path, node = [], target
    while node is not None:
        path.append(node)
        node = parent.get(id(node))
    return path[::-1]


def _nesting_advice(item: ast.ASTNode, deep: ast.ASTNode) -> str:
    """Que anida tanto, en el camino hasta el nodo que se paso, y que hacer.

    El mensaje era siempre el de la cadena de operadores, tambien con
    bloques anidados (un 'if' dentro de otro, 250 veces), donde la
    sugerencia de 'variables intermedias' no sirve de nada."""
    path = _path_to(item, deep)
    blocks = sum(1 for n in path if isinstance(n, ast.Block))
    operators = sum(1 for n in path if isinstance(n, ast.BinaryOp))
    if blocks * 2 >= len(path) // 2 and blocks >= operators:
        # cada bloque cuenta dos niveles: la sentencia y su bloque
        return (f"son {blocks} bloques anidados (un 'if', 'while', 'match' "
                "o 'try' dentro de otro): saca los bloques interiores a "
                "funciones")
    if operators >= len(path) // 2:
        return ("una cadena de operadores ('a + b + c + ...') anida uno "
                "por operador: repartela en variables intermedias")
    return ("son expresiones anidadas (llamadas, indices o accesos dentro de "
            "otros): guarda los resultados intermedios en variables")


__all__ = ["parse_program"]
