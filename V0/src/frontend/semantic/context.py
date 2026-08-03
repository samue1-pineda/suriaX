"""Estado compartido entre las pasadas de la fase Semántica.

Mismo patrón que ``parser/context.py``: un objeto liviano con ``__slots__``
que viaja por referencia entre las pasadas (``collect`` -> ``type_resolver``
-> ``scope_resolver`` -> ``memory_check``) en lugar de que cada una
construya/retorne estructuras propias. Ver ``ARQUITECTURA.md`` secc. 7.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from include import ast_nodes as ast
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore

from .symbol_table import Scope, ScopeKind, Symbol, SymbolTable


class SemanticContext:
    __slots__ = (
        "table",
        "scope",
        "current_fn",
        "errors",
        "notes",
        "source_path",
        "config",
        "fn_locals",
        "loaded_libraries",
    )

    def __init__(
        self,
        table: SymbolTable,
        *,
        source_path: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        self.table = table
        # scope ACTUAL: empieza en el global; push/pop lo mueven por la
        # cadena 'parent' (los scopes cerrados se descartan, no se guardan).
        self.scope: Scope = table.global_scope
        # FunctionDecl en curso (para validar 'return' contra return_restype).
        self.current_fn: Optional[ast.FunctionDecl] = None
        # diagnosticos acumulados por TODAS las pasadas (mismo contrato que
        # ParserContext.errors / Lexer.errors: la fase nunca lanza).
        self.errors: List[Any] = []
        # NOTAS: avisos no-error con recomendacion (p. ej. '.srcx usado como
        # libreria'). Dicts planos {code,message,file,line,column}; main.py
        # los puentea a config/logs.py (el frontend no conoce ese paquete).
        self.notes: List[dict] = []
        # ruta del .srcx analizado: ancla de la busqueda de .libsrx.
        self.source_path = source_path
        # configuracion cargada (libraries.libsrx_paths); None = defaults.
        self.config = config
        # FunctionDecl (por id) -> {nombre: Symbol} de sus locales/params.
        # Lo llena scope_resolver (pasada 3) para que memory_check (pasada 4)
        # pueda anotar Symbol.moved_at sin reconstruir scopes.
        self.fn_locals: Dict[int, Dict[str, Symbol]] = {}
        # unidades .libsrx CARGADAS en esta compilacion: alias publico ->
        # ruta del archivo. La fase HIR emite un .phir por unidad y el
        # modulo principal solo las referencia (Module.libraries).
        self.loaded_libraries: Dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # pila de scopes (via cadena 'parent', sin lista auxiliar)
    # ------------------------------------------------------------------ #
    def push_scope(self, kind: ScopeKind) -> Scope:
        self.scope = Scope(kind=kind, parent=self.scope)
        return self.scope

    def pop_scope(self) -> None:
        assert self.scope.parent is not None, "pop del scope global"
        self.scope = self.scope.parent

    def error(self, exc: Any) -> None:
        self.errors.append(exc)


__all__ = ["SemanticContext"]
