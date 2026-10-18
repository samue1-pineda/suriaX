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
from typing import Dict, List, Optional, Tuple

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
    HOOK = auto()    # metodo del set FIJO reconocido como hook de un tipo (ver hooks.py)
    DUNDER = auto()  # metodo especial LIBRE del usuario ('dunder fn'), indexado por (tipo, nombre)


class ScopeKind(Enum):
    GLOBAL = auto()
    FUNCTION = auto()
    BLOCK = auto()


@dataclass(slots=True)
class Symbol:
    name: str
    kind: SymbolKind
    ln: int
    col: int
    type: Optional[Type] = None
    mutable: bool = False
    visibility: Optional[str] = None
    """Reserva de visibilidad del simbolo: ``"public"`` (o ``None``, el
    default) / ``"private"`` (mismo paquete) / ``"internal"`` (mismo archivo).
    La usa el enforcement en ``linker_p`` + ``collect.define_import`` para
    filtrar que se expone a cada consumidor."""
    moved_at: Optional[int] = None
    # solo relevante si kind is SymbolKind.HOOK (ver semantic/hooks.py)
    hook_kind: Optional[HookKind] = None
    hook_owner: Optional[str] = None
    # nombre completo ('__gravity__') SOLO en los hooks declarados por el
    # proyecto (HookKind.EXTENDED): son los unicos cuya identidad no cabe en
    # el enum. Ver semantic/extensions.py y htims/readme.md.
    hook_name: Optional[str] = None
    # extensión que DECLARÓ el hook ('physics'): solo procedencia, para los
    # diagnósticos y para el .phir. None en el vocabulario fijo.
    hook_module: Optional[str] = None
    # HOOK __min__/__max__: el valor LITERAL que su cuerpo devuelve, leido en
    # compilacion. Es el unico dato de un cuerpo que el frontend mira, y solo
    # de estos dos hooks: sin el, el rango de un tipo de libreria no existiria
    # hasta la ejecucion y un literal fuera de rango no se podria rechazar.
    const_value: Optional[int] = None
    # STRUCT/TYPE: nombres de sus parametros de tipo ('Vector<T>' -> ('T',)).
    # Vacio en un tipo corriente. Es lo que permite verificar la ARIDAD de un
    # uso ('Vector<int,str>' sobre un generico de un parametro) y saber que
    # sustituir en sus campos y firmas.
    #: Nombre CANONICO del tipo que declara este simbolo ('a.Node'), cuando
    #: declara uno. No es 'name': ese es la clave del scope, y dentro de la
    #: libreria el tipo se sigue nombrando 'Node'. Es lo que hace unica su
    #: identidad frente a un homonimo de otra unidad — hooks, conversiones y
    #: dunders se indexan por el (ver 'SemanticContext.qualify').
    type_name: Optional[str] = None
    type_params: Tuple[str, ...] = ()
    # FUNCTION/HOOK: tipos de sus parametros en orden (para validar aridad y,
    # a futuro Fase 3, compatibilidad de argumentos). 'type' es el retorno.
    param_types: Optional[Tuple[Type, ...]] = None
    # IMPORT: nombres que la libreria tiene pero que ESTE consumidor no ve,
    # con el motivo ('internal' | 'private'). Solo para explicar el
    # diagnostico: acceder a uno sigue siendo un error.
    ocultos: Optional[Dict[str, str]] = None
    # STRUCT: campos | ENUM: items | IMPORT: exports de la libreria.
    # Sub-namespace plano O(1); NO participa de la cadena de scopes.
    members: Optional[Dict[str, "Symbol"]] = None
    # Scope donde se DEFINIO (ver Scope.sid). Lo pone 'define_*', asi que
    # ningun sitio que declare simbolos tiene que acordarse de ponerlo.
    scope_id: int = 0
    # FUNCION GENERICA: los tipos (que nombran sus parametros) de los valores
    # que COPIA su cuerpo, cada uno con donde ('vector.libsrx:128: se copia
    # ...'). Instanciarla con un tipo que tiene destructor es SEM038: la copia
    # lo destruiria dos veces. Lo calcula scope_resolver al cerrar el modulo
    # y viaja con el Symbol a quien importe la libreria.
    copias: Tuple[Tuple[Type, str], ...] = ()
    # FUNCION GENERICA: los tipos (que nombran sus parametros) que su cuerpo
    # ORDENA ('a < b'), con donde. Instanciarla con un tipo que no se ordena
    # (ni primitivo ordenable ni '__cmp__') es SEM039, en la llamada.
    ordenes: Tuple[Tuple[Type, str], ...] = ()
    # FUNCION GENERICA: los tipos de elemento (un parametro de tipo) cuyo
    # elemento PRESTA su cuerpo con '&b[i]' ('Vector.at'). Un escalar no se
    # presta (ningun motor tiene punteros al interior de un bloque): con un
    # tipo concreto escalar es SEM013, en la llamada.
    elem_borrows: Tuple[Tuple[Type, str], ...] = ()
    # FUNCION GENERICA: los tipos (un parametro de tipo) a los que su cuerpo
    # pide 'hash(x)'. Con un tipo sin hash (una funcion, un 'float', un
    # struct sin '__hash__') es el mismo error que fuera de un generico.
    hashes: Tuple[Tuple[Type, str], ...] = ()
    # FUNCION GENERICA: los tipos (un parametro de tipo) cuyo tamano pide su
    # cuerpo con 'sizeof'. Con un tipo sin '__sizeof__' (un primitivo, una
    # funcion) es el mismo error que fuera de un generico.
    sizes: Tuple[Tuple[Type, str], ...] = ()
    # FUNCTION: se declaro SIN cuerpo (un prototipo: el cuerpo lo pone el
    # host o un '#extern'). No es un valor: no hay una funcion del programa
    # que entregar, y cada motor la implementa a su manera (un intrinseco,
    # una llamada a C++). Viaja con el Symbol a quien importe la libreria.
    prototype: bool = False
    # GENERICO (funcion, metodo, struct, enum, type): las COTAS ya resueltas
    # de sus parametros de tipo, '<T: Ord>' -> (('T', (BoundRef Ord,)),). En un
    # metodo van juntas las de su '@impl Tipo<T: ...>' y las propias. Cada
    # instancia tiene que cumplirlas (se comprueba en la llamada o en la
    # anotacion), y viajan con el Symbol a quien importe la libreria.
    type_bounds: Tuple[Tuple[str, Tuple["object", ...]], ...] = ()
    # STRUCT: los traits que declara cumplir con '@impl(Contrato)' (su
    # BoundRef). La conformidad es EXPLICITA: es lo unico que hace que el
    # tipo cumpla una cota de trait.
    traits: Tuple["object", ...] = ()


@dataclass(slots=True)
class Scope:
    kind: ScopeKind
    parent: Optional["Scope"] = None
    types: Dict[str, Symbol] = field(default_factory=dict)
    values: Dict[str, Symbol] = field(default_factory=dict)
    # IDENTIDAD del scope (0 = global) y de quién es ('main', el 'while' de
    # la línea 8...). No los usa ninguna decisión de la Semántica: existen
    # para poder ENSEÑAR la tabla de símbolos como lo que es —un árbol— en
    # vez de como la lista aplanada de su nivel global. El resolver ya crea
    # y destruye estos scopes; lo único nuevo es que quedan numerados.
    sid: int = 0
    label: str = ""

    def define_type(self, symbol: Symbol, *, alias: Optional[str] = None) -> bool:
        """Registra en el namespace de TIPOS de este scope. ``False`` si el
        nombre ya existe EN ESTE scope (un scope padre con el mismo nombre
        sí se puede *shadowear*, no es colisión).

        ``alias`` registra el MISMO símbolo bajo otra clave. Lo usa
        ``collect`` para que un tipo de librería responda tanto al nombre con
        el que se escribe dentro de ella (``Vector``) como al canónico que
        lleva su identidad (``vector.Vector``).
        """
        clave = alias or symbol.name
        if clave in self.types:
            return False
        symbol.scope_id = self.sid
        self.types[clave] = symbol
        return True

    def define_value(self, symbol: Symbol) -> bool:
        """Igual que :meth:`define_type` para el namespace de VALORES."""
        if symbol.name in self.values:
            return False
        symbol.scope_id = self.sid
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
    __slots__ = ("global_scope", "hooks", "casts", "dunders", "traits",
                 "scopes", "uses")

    def __init__(self) -> None:
        self.global_scope = Scope(kind=ScopeKind.GLOBAL)
        # TODOS los scopes creados durante el analisis, en orden de creacion
        # (el 0 es el global). El resolver los apila y los desapila; aqui
        # quedan registrados para poder recorrer el ARBOL despues, que es
        # como se lee una tabla de simbolos de verdad: 'x' de 'main' y 'x'
        # del bucle son dos entradas distintas, y la lista global no lo dice.
        self.scopes: List[Scope] = [self.global_scope]
        # REFERENCIAS CRUZADAS: id(Symbol) -> [(linea, columna), ...] de cada
        # USO del nombre. Quien resuelve un nombre es el unico que sabe a que
        # simbolo apunta —dos 'x' en scopes distintos se escriben igual—, asi
        # que la lista se llena alli y no re-recorriendo el arbol despues.
        self.uses: Dict[int, List[Tuple[int, int]]] = {}
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

    def register_hook(self, owner_type: str, kind: HookKind, symbol: Symbol,
                      *, name: Optional[str] = None) -> bool:
        """Registra un hook para ``owner_type``. ``False`` si ya existe uno
        con la misma clave (el llamador reporta
        ``SemanticError.DuplicateHookError``).

        La clave es la TERNA ``(dueño, kind, nombre)``: los hooks del
        vocabulario fijo la cierran con ``""`` porque el ``kind`` ya los
        distingue, y los declarados por el proyecto (``EXTENDED``) necesitan
        el nombre — si no, dos hooks de usuario del mismo tipo colisionarían
        entre sí. Es la misma clave que viaja al HIR y con la que despacha el
        intérprete.
        """
        key = (owner_type, kind, name or "")
        if key in self.hooks:
            return False
        self.hooks[key] = symbol
        return True

    def lookup_hook(self, owner_type: str, kind: HookKind,
                    *, name: Optional[str] = None) -> Optional[Symbol]:
        return self.hooks.get((owner_type, kind, name or ""))

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
            for (owner, kind, _name), symbol in table.hooks.items()
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
