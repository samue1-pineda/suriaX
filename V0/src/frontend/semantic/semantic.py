"""Semántica de suriaX: orquestador.

La fase ejecuta TRES pasadas sobre el mismo contexto compartido:

    1. ``collect``         registra símbolos, hooks e imports de librerías
    2. ``scope_resolver``  alcance, tipos nominales, mutabilidad, aridad,
                           miembros y enlace de hooks
    3. ``memory_check``    reglas de memoria y movimiento de valores

Eran cuatro. ``type_resolver`` era un recorrido PLANO que validaba los tipos
nominales antes de que nadie abriera un scope, y por eso un ``type``
declarado dentro de una función no lo veía nadie: su primer uso salía como
``AST005``. Su lógica no se duplicó ni se tiró — vive en
``type_resolver.TypeBinder`` y la invoca ``scope_resolver`` en el punto donde
cada anotación entra en juego, que es el único sitio que conoce el scope.
El frontend hace un recorrido menos.

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

from . import collect, memory_check, scope_resolver
from .context import SemanticContext
from .symbol_table import SymbolTable


def analyze(
    program: ast.Program,
    *,
    source_path: Optional[str] = None,
    config: Optional[dict] = None,
    notes: Optional[List] = None,
    libraries: Optional[dict] = None,
    unit: str = "",
) -> Tuple[SymbolTable, List]:
    """Punto de entrada de la fase Semántica.

    ``source_path`` (ruta del ``.srcx``) ancla la búsqueda de ``.libsrx``;
    ``config`` es la configuración ya cargada (``libraries.libsrx_paths``).
    Ambos son opcionales: sin ellos los imports se buscan solo en las rutas
    por defecto. Si se pasa ``notes`` (lista), las NOTAS de la fase (avisos
    no-error, p. ej. '.srcx usado como librería') se acumulan ahí para que
    el llamador las enrute a ``log/notes.jsonl``.

    ``unit`` es el alias del ``#export`` cuando lo que se analiza es una
    LIBRERÍA (``""`` para el programa principal). Con él los tipos que
    declare nacen calificados (``a.Node``), que es lo que impide que dos
    tipos homónimos de librerías distintas compartan hooks — ver
    ``SemanticContext.qualify``. Tiene que ser el MISMO alias que usó el
    linker al cargarla, o la tabla del consumidor y el ``.phir`` de la
    librería quedarían indexados con nombres distintos.

    Nunca lanza: los diagnósticos se acumulan en la lista devuelta, mismo
    contrato que ``parser.parse()`` / ``Lexer.errors``.
    """
    ctx = SemanticContext(SymbolTable(), source_path=source_path, config=config,
                          unit=unit)
    for pass_ in (collect, scope_resolver, memory_check):
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
