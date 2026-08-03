"""Vocabulario y lógica de los métodos "dunder" (``__foo__``) como *hooks* de tipo.

El lexer reconoce la FORMA ``__x__`` de cualquier nombre sin validar contra
una lista cerrada (``scanners/ident.py``); este módulo es el único lugar que
decide **qué** nombres son hooks reconocidos, a **qué tipo** pertenece cada
uno y si su **firma completa** (parámetros + retorno) cumple la convención.
Añadir un hook nuevo a futuro se hace agregando una entrada a
:data:`HOOK_SPECS` — sin tocar el lexer, el parser ni ninguna otra fase.

Convención de asociación con el tipo dueño (decisión de usuario). El puntero
se escribe POSTFIJO (``T ptr``, ver ``grammar/types.py``); la FORMA del tipo
en el AST (``PointerTypeExpr`` con ``inner`` nominal) es la misma, así que la
validación de firmas no cambió con la migración a postfijo:

    - ``__free__`` / ``__sizeof__`` / ``__print__`` / ``__len__``: operan
      SOBRE una instancia existente -> su primer parámetro es ``T ptr``; el
      hook pertenece a ``T``.
    - ``__make__``: PRODUCE la instancia (se dispara con ``make T in r``)
      -> no hay nada a lo que apuntar todavía, así que se asocia por su
      TIPO DE RETORNO, que debe ser ``T ptr``.

Cómo se dispara cada hook (el "consumidor nunca escribe ``__foo__``"):

    ============  =====================================  ==================
    Hook          Dispara con                            Quién lo enlaza
    ============  =====================================  ==================
    ``__free__``   ``free x;``                            ``scope_resolver``
    ``__make__``   ``make T in r``                        ``scope_resolver``
    ``__sizeof__`` ``sizeof(T)``                          ``type_resolver``
    ``__print__``  ``print(x)`` / ``x.print()``           ``scope_resolver``
    ``__len__``    ``len(x)`` / ``x.len()``               ``scope_resolver``
    ``__cast__``   ``cast<T>(x)`` (T nominal)             ``type_resolver``
    ============  =====================================  ==================

``print``/``len`` NO son keywords (filosofía libsrX: pocos tokens): son
identificadores que, si no resuelven a una función declarada, despachan al
hook del tipo del primer argumento (:data:`CALL_HOOKS`). Una función normal
llamada ``print`` declarada por el usuario tiene prioridad sobre el hook.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple

try:
    from include import ast_nodes as ast
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore


class HookKind(Enum):
    FREE = auto()      # __free__:   fn __free__(T ptr x) -> void
    MAKE = auto()      # __make__:   fn __make__(...) -> T ptr
    SIZEOF = auto()    # __sizeof__: fn __sizeof__(T ptr x) -> int
    PRINT = auto()     # __print__:  fn __print__(T ptr x) -> void
    LEN = auto()       # __len__:    fn __len__(T ptr x) -> int
    CAST = auto()      # __cast__:   fn __cast__(X x) -> T  (T nominal, plano o ptr)
    INDEX = auto()     # __index__:  fn __index__(T ptr x, int i) -> Elem  (v[i])
    INDEX_SET = auto() # __index_set__: fn __index_set__(T ptr mutable x, int i, Elem v) -> void  (v[i] = x)
    EQ = auto()        # __eq__:     fn __eq__(T ptr a, T ptr b) -> bool  (a == b)


@dataclass(slots=True, frozen=True)
class HookSpec:
    """Convención de firma de un hook: qué exige y cómo se asocia a su tipo.

    ``owner_from_return``: ``True`` para ``__make__`` (dueño = tipo de
    retorno ``ptr T``); ``False`` para el resto (dueño = primer parámetro
    ``ptr T``). ``return_primitive``: nombre del primitivo que el hook debe
    devolver (``None`` = el retorno es ``ptr T`` y define al dueño).
    ``exact_params``: número exacto de parámetros exigido (``None`` = libre,
    solo ``__make__``).
    """
    kind: HookKind
    owner_from_return: bool
    return_primitive: Optional[str]
    exact_params: Optional[int]


# nombre "dunder" SIN guiones (Token.value, ver scanners/ident.py) -> spec.
# Única fuente de verdad de qué nombres son hooks reconocidos y su firma.
HOOK_SPECS: dict[str, HookSpec] = {
    "free":   HookSpec(HookKind.FREE,   owner_from_return=False, return_primitive="void", exact_params=1),
    "make":   HookSpec(HookKind.MAKE,   owner_from_return=True,  return_primitive=None,   exact_params=None),
    "sizeof": HookSpec(HookKind.SIZEOF, owner_from_return=False, return_primitive="int",  exact_params=1),
    "print":  HookSpec(HookKind.PRINT,  owner_from_return=False, return_primitive="void", exact_params=1),
    "len":    HookSpec(HookKind.LEN,    owner_from_return=False, return_primitive="int",  exact_params=1),
    # __cast__ tiene convención PROPIA (ver validate_hook): el dueño es el
    # lado NOMINAL de la firma — el retorno si es nominal (T plano o T ptr:
    # 'fn __cast__(int x) -> int8' pertenece a int8), o si no el primer
    # parámetro ('fn __cast__(int8 x) -> int' también pertenece a int8).
    # Se dispara con 'cast<T>(x)', nunca escribiendo '__cast__' a mano.
    "cast":   HookSpec(HookKind.CAST,   owner_from_return=True,  return_primitive=None,   exact_params=1),
    # __index__: 'v[i]'. Dueño = primer parámetro (el receptor 'T ptr'); el
    # SEGUNDO parámetro es el índice y el retorno es el ELEMENTO (tipo libre:
    # return_primitive=None NO fuerza un retorno concreto, ver validate_hook).
    "index":  HookSpec(HookKind.INDEX,  owner_from_return=False, return_primitive=None,   exact_params=2),
    # __index_set__: 'v[i] = x'. Receptor 'T ptr mutable' (escribe), índice y
    # valor; sin retorno. 3 parámetros; el valor es de tipo libre (el elemento).
    "index_set": HookSpec(HookKind.INDEX_SET, owner_from_return=False, return_primitive="void", exact_params=3),
    # __eq__: 'a == b'. Dos receptores del MISMO tipo, retorna 'bool'.
    "eq":     HookSpec(HookKind.EQ,     owner_from_return=False, return_primitive="bool",  exact_params=2),
}

# compatibilidad con el vocabulario anterior (nombre -> HookKind)
KNOWN_HOOKS: dict[str, HookKind] = {name: spec.kind for name, spec in HOOK_SPECS.items()}

# hooks que se disparan con una LLAMADA por nombre plano o member-access
# ('print(x)' / 'x.print()'); free/make/sizeof se disparan con sus keywords.
CALL_HOOKS: dict[str, HookKind] = {
    "print": HookKind.PRINT,
    "len": HookKind.LEN,
}


def classify_hook(dunder_name: str) -> Optional[HookKind]:
    """``FunctionDecl.dunder`` -> ``HookKind`` reconocido, o ``None`` si el
    nombre no es un hook conocido (se ignora de forma permisiva)."""
    spec = HOOK_SPECS.get(dunder_name)
    return spec.kind if spec is not None else None


def validate_hook(fn: ast.FunctionDecl, dunder_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Valida la firma COMPLETA de un hook y devuelve ``(owner, error)``.

    - ``(owner, None)``: firma válida; ``owner`` es el nombre del tipo dueño.
    - ``(None, mensaje)``: firma inválida; el llamador reporta
      ``SemanticError.InvalidHookSignatureError`` con el mensaje.

    Se valida parámetros Y tipo de retorno (antes solo se miraba el lado que
    define al dueño: ``__free__`` sin retorno ``void`` pasaba sin queja).
    """
    spec = HOOK_SPECS[dunder_name]

    if spec.exact_params is not None and len(fn.params) != spec.exact_params:
        return None, (
            f"'{fn.name}' debe declarar exactamente {spec.exact_params} "
            f"parámetro(s), tiene {len(fn.params)}"
        )

    if spec.kind is HookKind.CAST:
        # convención propia: el dueño es el lado NOMINAL (plano o ptr) de la
        # firma; el retorno tiene prioridad ('-> int8' gana sobre '(int8 x)').
        owner = _nominal_target(fn.return_type)
        if owner is None and fn.params:
            owner = _nominal_target(fn.params[0].type)
        if owner is None:
            return None, (
                f"'{fn.name}' debe involucrar un tipo nominal en su firma "
                "(retorno o primer parámetro) para asociarse a él"
            )
        return owner, None

    if spec.owner_from_return:
        owner = _nominal_ptr_target(fn.return_type)
        if owner is None:
            return None, f"'{fn.name}' debe devolver 'T ptr' (T nominal) para asociarse a T"
        return owner, None

    owner = _nominal_ptr_target(fn.params[0].type) if fn.params else None
    if owner is None:
        return None, f"el primer parámetro de '{fn.name}' debe ser 'T ptr' (T nominal)"

    expected = spec.return_primitive
    # 'return_primitive=None' aquí (no owner_from_return, no CAST) significa
    # RETORNO LIBRE: '__index__' devuelve el elemento, de cualquier tipo.
    if expected is not None and not (
            isinstance(fn.return_type, ast.PrimitiveTypeExpr)
            and fn.return_type.name == expected):
        return None, f"'{fn.name}' debe devolver '{expected}'"
    return owner, None


def hook_owner_type_name(fn: ast.FunctionDecl, kind: HookKind) -> Optional[str]:
    """Nombre del tipo nominal dueño del hook, según su convención de firma.

    Vista permisiva (solo el lado que define al dueño, sin validar el resto
    de la firma); para el registro real usar :func:`validate_hook`, que
    valida la firma completa.
    """
    if kind is HookKind.MAKE:
        return _nominal_ptr_target(fn.return_type)
    if not fn.params:
        return None
    return _nominal_ptr_target(fn.params[0].type)


def _nominal_ptr_target(type_expr: ast.TypeExpr) -> Optional[str]:
    """``T ptr`` (T nominal) -> ``"T"``; cualquier otra forma -> ``None``.

    Mira la FORMA del AST (``PointerTypeExpr`` con ``inner`` nominal), que es
    idéntica se escriba ``T ptr`` (hoy) o ``ptr T`` (sintaxis retirada)."""
    if isinstance(type_expr, ast.PointerTypeExpr) and isinstance(type_expr.inner, ast.NominalTypeExpr):
        return type_expr.inner.name
    return None


def _nominal_target(type_expr: ast.TypeExpr) -> Optional[str]:
    """``T`` o ``T ptr`` (T nominal) -> ``"T"``; otra forma -> ``None``.

    Variante de :func:`_nominal_ptr_target` que también acepta el nominal
    PLANO: ``__cast__`` produce/consume VALORES (``-> int8``), no solo
    referencias como el resto de hooks."""
    if isinstance(type_expr, ast.NominalTypeExpr):
        return type_expr.name
    return _nominal_ptr_target(type_expr)


__all__ = [
    "HookKind", "HookSpec", "HOOK_SPECS", "KNOWN_HOOKS", "CALL_HOOKS",
    "classify_hook", "validate_hook", "hook_owner_type_name",
]
