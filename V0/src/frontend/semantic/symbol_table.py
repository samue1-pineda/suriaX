"""Tabla de símbolos: estructura central de la fase Semántica.

Sin lógica de análisis — solo la estructura y sus operaciones O(1) (por
nivel de scope) / O(profundidad de anidamiento) (resolución). Ver
``ARQUITECTURA.md`` secc. 6 para el diseño completo y su justificación.

Namespaces separados (``types`` vs ``values``) igual que C/C++: un
``struct Punto`` y una función/variable ``Punto`` no colisionan porque
viven en espacios distintos.

``SymbolKind.TYPE`` (``const type int8;``) vive en el namespace de TIPOS
junto a ``STRUCT``/``ENUM``, sin ``members``: es un tipo nominal opaco, sin
representación escrita en suriaX.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Tuple

try:
    from include.types_ast import Type
except ImportError:  # pragma: no cover - ejecucion directa
    from types_ast import Type  # type: ignore

from .hooks import HookKind


class SymbolKind(Enum):
    FUNCTION = auto()
    STRUCT = auto()
    ENUM = auto()
    TYPE = auto()    # tipo nominal OPACO declarado con 'type' (ver ast_nodes.TypeDecl)
    ENUM_ITEM = auto()
    PARAM = auto()
    VAR = auto()
    FIELD = auto()   # campo de un struct (vive en Symbol.members del struct)
    IMPORT = auto()
    REGION = auto()  # nombre de una 'region r { ... }' (resoluble solo dentro de su bloque)
    HOOK = auto()    # metodo del set FIJO reconocido como hook de un tipo (ver hooks.py)
    DUNDER = auto()  # metodo especial LIBRE del usuario ('dunder fn'), indexado por (tipo, nombre)


class ScopeKind(Enum):
    GLOBAL = auto()
    FUNCTION = auto()
    BLOCK = auto()
    REGION = auto()


@dataclass(slots=True)
class Symbol:
    name: str
    kind: SymbolKind
    ln: int
    col: int
    type: Optional[Type] = None
    mutable: bool = False
    region: Optional[str] = None
    shared: bool = False  # solo kind REGION: 'shrd region r {}' (compartible)
    region_mutable: bool = False  # solo kind REGION: 'mutable region r' (muta/divide)
    region_na: bool = False       # solo kind REGION: 'na region r' (no auto-liberada)
    visibility: Optional[str] = None
    """Reserva de visibilidad del simbolo: ``"public"`` (o ``None``, el
    default) / ``"private"`` (mismo paquete) / ``"internal"`` (mismo archivo).
    La usa el enforcement en ``linker_p`` + ``collect.define_import`` para
    filtrar que se expone a cada consumidor."""
    moved_at: Optional[int] = None
    # solo relevante si kind is SymbolKind.HOOK (ver semantic/hooks.py)
    hook_kind: Optional[HookKind] = None
    hook_owner: Optional[str] = None
    # FUNCTION/HOOK: tipos de sus parametros en orden (para validar aridad y,
    # a futuro Fase 3, compatibilidad de argumentos). 'type' es el retorno.
    param_types: Optional[Tuple[Type, ...]] = None
    # STRUCT: campos | ENUM: items | IMPORT: exports de la libreria.
    # Sub-namespace plano O(1); NO participa de la cadena de scopes.
    members: Optional[Dict[str, "Symbol"]] = None


@dataclass(slots=True)
class Scope:
    kind: ScopeKind
    parent: Optional["Scope"] = None
    types: Dict[str, Symbol] = field(default_factory=dict)
    values: Dict[str, Symbol] = field(default_factory=dict)

    def define_type(self, symbol: Symbol) -> bool:
        """Registra en el namespace de TIPOS de este scope. ``False`` si el
        nombre ya existe EN ESTE scope (un scope padre con el mismo nombre
        sí se puede *shadowear*, no es colisión)."""
        if symbol.name in self.types:
            return False
        self.types[symbol.name] = symbol
        return True

    def define_value(self, symbol: Symbol) -> bool:
        """Igual que :meth:`define_type` para el namespace de VALORES."""
        if symbol.name in self.values:
            return False
        self.values[symbol.name] = symbol
        return True

    def resolve_type(self, name: str) -> Optional[Symbol]:
        scope: Optional[Scope] = self
        while scope is not None:
            sym = scope.types.get(name)
            if sym is not None:
                return sym
            scope = scope.parent
        return None

    def resolve_value(self, name: str) -> Optional[Symbol]:
        scope: Optional[Scope] = self
        while scope is not None:
            sym = scope.values.get(name)
            if sym is not None:
                return sym
            scope = scope.parent
        return None


@dataclass(slots=True, frozen=True)
class TraitSig:
    """Firma de UN método requerido por un trait (ver ``semantic/traits.py``).

    ``params`` incluye el receptor; los tipos pueden contener el placeholder
    ``SELF_TYPE`` (se sustituye por el tipo que implementa al verificar)."""
    name: str
    params: Tuple[Type, ...]
    ret: Optional[Type]


class SymbolTable:
    __slots__ = ("global_scope", "hooks", "casts", "dunders", "traits")

    def __init__(self) -> None:
        self.global_scope = Scope(kind=ScopeKind.GLOBAL)
        # (nombre de tipo nominal, HookKind) -> Symbol del hook que lo implementa.
        # __cast__ NO vive aqui: un tipo puede declarar VARIOS (ver 'casts').
        self.hooks: Dict[Tuple[str, HookKind], Symbol] = {}
        # DUNDERS del usuario (metodos especiales LIBRES): (tipo_dueno, nombre)
        # -> Symbol. Indexados por tipo igual que los hooks, para que varios
        # tipos tengan su propio '__next__' sin colisionar. Se despachan con
        # 'x.__nombre__()' (member-dispatch) y habilitan los traits.
        self.dunders: Dict[Tuple[str, str], Symbol] = {}
        # TRAITS (contratos definidos por el usuario): nombre -> lista de firmas
        # requeridas. '@impl(trait)' verifica que un tipo las provea todas.
        self.traits: Dict[str, Tuple["TraitSig", ...]] = {}
        # TABLA DE CONVERSIONES: (Type origen, Type destino) -> Symbol del
        # __cast__ que la implementa. Clave por PAR, no por tipo dueño: un
        # tipo puede declarar tantas conversiones como pares distintos
        # (int->int8, int8->int, str->Estado, Estado->vec...). 'Type' es
        # frozen/hashable, el lookup es O(1). El encadenamiento NO es
        # automatico: cada paso se escribe (cast<B>(cast<A>(x))).
        self.casts: Dict[Tuple[Type, Type], Symbol] = {}

    def register_hook(self, owner_type: str, kind: HookKind, symbol: Symbol) -> bool:
        """Registra un hook para ``owner_type``. ``False`` si ya existe uno
        del mismo ``HookKind`` para ese tipo (el llamador reporta
        ``SemanticError.DuplicateHookError``)."""
        key = (owner_type, kind)
        if key in self.hooks:
            return False
        self.hooks[key] = symbol
        return True

    def lookup_hook(self, owner_type: str, kind: HookKind) -> Optional[Symbol]:
        return self.hooks.get((owner_type, kind))

    def register_cast(self, source: Type, target: Type, symbol: Symbol) -> bool:
        """Registra una conversión ``source -> target``. ``False`` si ese par
        exacto ya tiene un ``__cast__`` (duplicado; el llamador reporta)."""
        key = (source, target)
        if key in self.casts:
            return False
        self.casts[key] = symbol
        return True

    def lookup_cast(self, source: Optional[Type], target: Optional[Type]) -> Optional[Symbol]:
        if source is None or target is None:
            return None
        return self.casts.get((source, target))

    def register_dunder(self, owner_type: str, name: str, symbol: Symbol) -> bool:
        """Registra un dunder ``name`` (con guiones, p. ej. ``__next__``) para
        ``owner_type``. ``False`` si ya existe ese par exacto (duplicado)."""
        key = (owner_type, name)
        if key in self.dunders:
            return False
        self.dunders[key] = symbol
        return True

    def lookup_dunder(self, owner_type: Optional[str], name: str) -> Optional[Symbol]:
        if owner_type is None:
            return None
        return self.dunders.get((owner_type, name))


def to_debug_dict(table: SymbolTable) -> dict:
    """Vista serializable de una ``SymbolTable`` (para ``#test sem``).

    ``table.hooks`` usa tuplas como clave (``(owner_type, HookKind)``), no
    válidas como clave JSON directa; se proyecta a una lista de objetos
    planos antes de pasar por el serializador genérico
    (``include/ast_json.py``), que sí sabe reflejar ``Symbol`` (dataclass) y
    diccionarios anidados con claves ``str``. El scope global se vuelca
    completo (namespaces ``types`` y ``values``); los scopes de bloque no
    sobreviven a la fase (se descartan al cerrarse) y por eso no aparecen.
    """
    return {
        "global": {
            "types": table.global_scope.types,
            "values": table.global_scope.values,
        },
        "hooks": [
            {"owner_type": owner, "hook": kind.name, "symbol": symbol}
            for (owner, kind), symbol in table.hooks.items()
        ],
        "casts": [
            {"from": repr(source), "to": repr(target), "symbol": symbol}
            for (source, target), symbol in table.casts.items()
        ],
        "dunders": [
            {"owner_type": owner, "name": name, "symbol": symbol}
            for (owner, name), symbol in table.dunders.items()
        ],
        "traits": [
            {"name": name, "methods": [
                {"name": s.name, "params": [repr(p) for p in s.params],
                 "ret": repr(s.ret) if s.ret is not None else None}
                for s in sigs]}
            for name, sigs in table.traits.items()
        ],
    }


__all__ = ["SymbolKind", "ScopeKind", "Symbol", "Scope", "SymbolTable",
           "TraitSig", "to_debug_dict"]
