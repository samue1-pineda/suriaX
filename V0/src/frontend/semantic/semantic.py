"""Semántica de suriaX: orquestador.

La fase ejecuta cuatro pasadas sobre el mismo contexto compartido:

    1. ``collect``        registra símbolos, hooks y imports de librerías
    2. ``type_resolver``  resuelve tipos nominales y los hooks asociados
    3. ``scope_resolver``  valida alcance, mutabilidad, aridad y miembros
    4. ``memory_check``   revisa reglas de memoria y movimiento de valores

Cada pasada recorre el AST una vez y acumula los diagnósticos en lugar de
lanzarlos inmediatamente, de modo que el compilador puede reportar todos los
problemas de una corrida de forma consistente.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

try:
    from include import ast_nodes as ast
    from error_handler import SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    import SemanticError  # type: ignore

from . import collect, memory_check, scope_resolver, type_resolver
from .context import SemanticContext
from .symbol_table import SymbolTable


def analyze(
    program: ast.Program,
    *,
    source_path: Optional[str] = None,
    config: Optional[dict] = None,
    notes: Optional[List] = None,
    libraries: Optional[dict] = None,
) -> Tuple[SymbolTable, List]:
    """Punto de entrada de la fase Semántica.

    ``source_path`` (ruta del ``.srcx``) ancla la búsqueda de ``.libsrx``;
    ``config`` es la configuración ya cargada (``libraries.libsrx_paths``).
    Ambos son opcionales: sin ellos los imports se buscan solo en las rutas
    por defecto. Si se pasa ``notes`` (lista), las NOTAS de la fase (avisos
    no-error, p. ej. '.srcx usado como librería') se acumulan ahí para que
    el llamador las enrute a ``log/notes.jsonl``.

    Nunca lanza: los diagnósticos se acumulan en la lista devuelta, mismo
    contrato que ``parser.parse()`` / ``Lexer.errors``.
    """
    ctx = SemanticContext(SymbolTable(), source_path=source_path, config=config)
    for pass_ in (collect, type_resolver, scope_resolver, memory_check):
        try:
            pass_.run(program, ctx)
        except RecursionError:
            # las pasadas recorren las expresiones recursivamente (una trama
            # de Python por nivel): una construccion con miles de niveles
            # agota la pila. Se convierte en diagnostico controlado -- esta
            # fase NUNCA lanza (mismo contrato que 'parser.parse()', que ya
            # hace lo propio con su ExpressionTooDeepError). Cuando llega
            # aqui la pila ya se desenrollo, hay margen para construir el
            # error y seguir con las pasadas restantes.
            ctx.error(SemanticError.ExpressionTooDeepError(
                f"construccion demasiado anidada para la pasada "
                f"'{pass_.__name__.rsplit('.', 1)[-1]}'",
                line=program.ln, column=program.col,
            ))
    if notes is not None:
        notes.extend(ctx.notes)
    if libraries is not None:
        # unidades .libsrx cargadas (alias -> ruta): la fase HIR emite un
        # .phir por unidad (mismo patron de out-param que 'notes').
        libraries.update(ctx.loaded_libraries)
    return ctx.table, ctx.errors


__all__ = ["analyze"]
