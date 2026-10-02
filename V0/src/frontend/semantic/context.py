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

from .hooks import HOOK_SPECS
from .symbol_table import Scope, ScopeKind, Symbol, SymbolTable


class SemanticContext:
    __slots__ = (
        "table",
        "unit",
        "scope",
        "current_fn",
        "errors",
        "notes",
        "source_path",
        "config",
        "fn_locals",
        "fn_symbols",
        "loaded_libraries",
        "hook_specs",
        "copias",
        "instancias",
    )

    def __init__(
        self,
        table: SymbolTable,
        *,
        source_path: Optional[str] = None,
        config: Optional[dict] = None,
        unit: str = "",
    ) -> None:
        self.table = table
        # UNIDAD que se está analizando: el alias de su '#export' ('' = el
        # programa principal). Es lo que hace ÚNICA la identidad de un tipo:
        # un 'Node' declarado aquí se llama 'a.Node' en todo el pipeline, y
        # así deja de compartir su '__free__' con el 'Node' de otra librería
        # (ver 'qualify').
        self.unit = unit
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
        # FunctionDecl (por id) -> su Symbol (funcion o metodo). Lo llena
        # 'collect' (pasada 1) y lo usa scope_resolver para guardar la FIRMA
        # ya canonica: en la pasada 1 las anotaciones todavia estan tal como
        # se escribieron ('vec.Vector<int>'), y quien la consulte despues
        # compara contra tipos canonicos ('vector.Vector<int>').
        self.fn_symbols: Dict[int, Symbol] = {}
        # FunctionDecl (por id) -> las COPIAS de un valor generico que hace su
        # cuerpo: (tipo que nombra un parametro, donde). Y cada llamada a un
        # generico: (Symbol del llamador o None, sus parametros de tipo,
        # Symbol del llamado, mapa de la instancia, nombre, linea, columna).
        # Con las dos, scope_resolver decide al cerrar el modulo que
        # instancias copiarian un valor con destructor (SEM038).
        self.copias: Dict[int, List[Any]] = {}
        self.instancias: List[Any] = []
        # unidades .libsrx CARGADAS en esta compilacion: alias publico ->
        # ruta del archivo. La fase HIR emite un .phir por unidad y el
        # modulo principal solo las referencia (Module.libraries).
        self.loaded_libraries: Dict[str, str] = {}
        # VOCABULARIO de hooks de ESTA compilacion: el fijo del compilador mas
        # el que declara el proyecto (HTIMS, 'extends.srcx'). Deja de ser una
        # constante de modulo porque ya no es el mismo para todos: depende del
        # proyecto. Se construye una vez, aqui, y las pasadas lo consultan.
        self.hook_specs: Dict[str, Any] = dict(HOOK_SPECS)
        extensiones = (config or {}).get("_extensions")
        if extensiones is not None:
            from .extensions import build_vocabulary
            aportados, problemas = build_vocabulary(extensiones)
            # una extension NO puede redefinir el vocabulario fijo: htims ya
            # lo rechaza al declarar (EXT027), y aqui se sostiene aunque el
            # conjunto llegue por otra via.
            for nombre, spec in aportados.items():
                if nombre not in self.hook_specs:
                    self.hook_specs[nombre] = spec
            self.notes.extend(problemas)

    # ------------------------------------------------------------------ #
    # pila de scopes (via cadena 'parent', sin lista auxiliar)
    # ------------------------------------------------------------------ #
    def push_scope(self, kind: ScopeKind, label: str = "") -> Scope:
        """Abre un scope hijo. ``label`` dice DE QUIÉN es (``'main'``, el
        ``while`` de la línea 8): no lo mira ninguna decisión semántica, es
        lo que permite dibujar después el árbol de scopes con nombres en vez
        de con números sueltos.

        Cada scope queda además REGISTRADO en la tabla. El resolver los
        apila y los desapila igual que antes —la resolución sigue subiendo
        por ``parent``—, pero al terminar el análisis ya no se han perdido:
        una tabla de símbolos es un árbol, y hasta ahora solo sobrevivía su
        raíz.
        """
        self.scope = Scope(kind=kind, parent=self.scope,
                           sid=len(self.table.scopes), label=label)
        self.table.scopes.append(self.scope)
        return self.scope

    def usar(self, symbol: Symbol, ln: int, col: int) -> None:
        """Anota que ``symbol`` se USA en esa posición.

        Se llama donde un nombre se RESUELVE, que es el único sitio que sabe
        a qué símbolo apunta: dos variables distintas se escriben igual, y
        buscar el nombre en el fuente después contestaría las dos. Con esto
        la tabla de símbolos puede decir, de cada entrada, dónde se declaró y
        dónde se usa — que es la mitad que le faltaba para ser útil.
        """
        self.table.uses.setdefault(id(symbol), []).append((ln, col))

    def pop_scope(self) -> None:
        assert self.scope.parent is not None, "pop del scope global"
        self.scope = self.scope.parent

    def qualify(self, name: str) -> str:
        """El nombre CANÓNICO de un tipo declarado en esta unidad.

        Un tipo es único por (unidad, nombre), no por nombre a secas: los
        hooks, las conversiones y los dunders se indexan por ese nombre, así
        que sin la unidad dos ``Node`` de librerías distintas comparten
        entrada y despacha el que se cargara primero — en silencio.

        Un nombre que YA viene calificado se devuelve tal cual: nombra un
        tipo de otra unidad, y esa unidad ya lo calificó.
        """
        if not self.unit or "." in name:
            return name
        return f"{self.unit}.{name}"

    def error(self, exc: Any) -> None:
        self.errors.append(exc)


__all__ = ["SemanticContext"]
