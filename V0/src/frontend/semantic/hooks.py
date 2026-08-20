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
    - ``__cast__``: no hay instancia del destino todavía, así que se asocia
      por el lado NOMINAL de su firma.

    Hubo un tercer caso, ``__make__``, que se asociaba por su tipo de
    RETORNO porque producía la instancia. Se retiró con el modelo por
    regiones: su único disparador era ``make T in r``.

Cómo se dispara cada hook (el "consumidor nunca escribe ``__foo__``"):

    ============  =====================================  ==================
    Hook          Dispara con                            Quién lo enlaza
    ============  =====================================  ==================
    ``__free__``   ``free x;`` y el cierre del ámbito     ``scope_resolver``
    ``__sizeof__`` ``sizeof(T)``                          ``type_resolver``
    ``__print__``  ``print(x)`` / ``x.print()``           ``scope_resolver``
    ``__len__``    ``len(x)`` / ``x.len()``               ``scope_resolver``
    ``__cast__``   ``cast<T>(x)`` (T nominal)             ``type_resolver``
    ``__min__``    un LITERAL escrito donde se espera T   ``scope_resolver``
    ``__max__``    un LITERAL escrito donde se espera T   ``scope_resolver``
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
    SIZEOF = auto()    # __sizeof__: fn __sizeof__(T ptr x) -> int
    PRINT = auto()     # __print__:  fn __print__(T ptr x) -> void
    LEN = auto()       # __len__:    fn __len__(T ptr x) -> int
    CAST = auto()      # __cast__:   fn __cast__(X x) -> T  (T nominal, plano o ptr)
    INDEX = auto()     # __index__:  fn __index__(T ptr x, int i) -> Elem  (v[i])
    INDEX_SET = auto() # __index_set__: fn __index_set__(T ptr mutable x, int i, Elem v) -> void  (v[i] = x)
    EQ = auto()        # __eq__:     fn __eq__(T ptr a, T ptr b) -> bool  (a == b)
    MIN = auto()       # __min__:    fn __min__(T ptr x) -> int   (cota inferior)
    MAX = auto()       # __max__:    fn __max__(T ptr x) -> int   (cota superior)
    EXTENDED = auto()  # hook DECLARADO POR EL PROYECTO (HTIMS): su identidad
                       # es el NOMBRE, no este miembro. Ver semantic/extensions.py


@dataclass(slots=True, frozen=True)
class HookSpec:
    """Convención de firma de un hook: qué exige y cómo se asocia a su tipo.

    ``owner_from_return``: el dueño sale del tipo de RETORNO en vez del
    primer parámetro. ``return_primitive``: nombre del primitivo que el hook
    debe devolver (``None`` = el retorno define al dueño). ``exact_params``:
    número exacto de parámetros exigido (``None`` = libre).
    """
    kind: HookKind
    owner_from_return: bool
    return_primitive: Optional[str]
    exact_params: Optional[int]
    #: firma EXACTA que prometió una extensión del proyecto (HTIMS). Cuando
    #: está presente manda sobre las convenciones genéricas de arriba: no se
    #: comprueba "el retorno debe ser int" sino "la firma debe ser LA que
    #: declaró physics.py". ``None`` en los hooks del vocabulario fijo.
    declared: Optional[object] = None


# nombre "dunder" SIN guiones (Token.value, ver scanners/ident.py) -> spec.
# Única fuente de verdad de qué nombres son hooks reconocidos y su firma.
HOOK_SPECS: dict[str, HookSpec] = {
    "free":   HookSpec(HookKind.FREE,   owner_from_return=False, return_primitive="void", exact_params=1),
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
    # __min__/__max__: el RANGO de un tipo numerico de libreria. Son los
    # unicos hooks que el compilador lee en COMPILACION (no los ejecuta: lee
    # el literal de su 'return'), y existen porque sin ellos un
    # 'const dt.int8 a = 10;' no se puede aceptar sin mentir — el compilador
    # sabe que int8 mide 1 byte pero no si ese byte va de -128 a 127 o de 0 a
    # 255, asi que no puede decidir si el 10 cabe. Con ellos la conversion
    # implicita de un LITERAL es exacta: cabe o es un error que dice el rango.
    "min":    HookSpec(HookKind.MIN,    owner_from_return=False, return_primitive="int",   exact_params=1),
    "max":    HookSpec(HookKind.MAX,    owner_from_return=False, return_primitive="int",   exact_params=1),
}

# compatibilidad con el vocabulario anterior (nombre -> HookKind)
KNOWN_HOOKS: dict[str, HookKind] = {name: spec.kind for name, spec in HOOK_SPECS.items()}

# hooks que se disparan con una LLAMADA por nombre plano o member-access
# ('print(x)' / 'x.print()'); free/make/sizeof se disparan con sus keywords.
CALL_HOOKS: dict[str, HookKind] = {
    "print": HookKind.PRINT,
    "len": HookKind.LEN,
    # 'min(T)' / 'max(T)': el rango de un tipo numerico de libreria. NO son
    # keywords (no cuestan vocabulario) y su argumento puede nombrar un TIPO
    # o un VALOR — igual que 'sizeof'. La diferencia con print/len es que
    # estos no despachan en ejecucion: el rango YA es una constante de
    # compilacion (por eso '__min__'/'__max__' tienen el cuerpo restringido a
    # un literal), asi que la llamada se pliega al entero que devuelven.
    "min": HookKind.MIN,
    "max": HookKind.MAX,
}


def classify_hook(dunder_name: str) -> Optional[HookKind]:
    """``FunctionDecl.dunder`` -> ``HookKind`` reconocido, o ``None`` si el
    nombre no es un hook conocido (se ignora de forma permisiva)."""
    spec = HOOK_SPECS.get(dunder_name)
    return spec.kind if spec is not None else None


def validate_hook(fn: ast.FunctionDecl, dunder_name: str,
                  spec: Optional[HookSpec] = None) -> Tuple[Optional[str], Optional[str]]:
    """Valida la firma COMPLETA de un hook y devuelve ``(owner, error)``.

    - ``(owner, None)``: firma válida; ``owner`` es el nombre del tipo dueño.
    - ``(None, mensaje)``: firma inválida; el llamador reporta
      ``SemanticError.InvalidHookSignatureError`` con el mensaje.

    Se valida parámetros Y tipo de retorno (antes solo se miraba el lado que
    define al dueño: ``__free__`` sin retorno ``void`` pasaba sin queja).
    """
    # El spec puede venir del vocabulario FIJO o del que aporta el proyecto
    # (HTIMS). Se recibe como parámetro en vez de buscarlo en un diccionario
    # de módulo porque el vocabulario ya no es el mismo para todos: depende
    # del proyecto que se esté compilando.
    if spec is None:
        spec = HOOK_SPECS[dunder_name]

    if spec.declared is not None:
        return _validate_declared(fn, spec.declared)

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


def _validate_declared(fn: ast.FunctionDecl, firma) -> Tuple[Optional[str], Optional[str]]:
    """Valida un hook de usuario contra la firma que declaró su extensión.

    Es una comparación EXACTA, tipo a tipo: la extensión prometió una firma y
    el ``.srcx`` tiene que cumplirla. No hay convención genérica que aplicar
    —el compilador no sabe qué significa ``__gravity__``— y precisamente por
    eso la promesa escrita es lo único que se puede hacer cumplir.

    El dueño sale del PRIMER parámetro, como en el resto de hooks de
    instancia, y además debe coincidir con el ``owner`` declarado: un
    ``__gravity__`` de ``Body`` no puede implementarse sobre ``Sound``.
    """
    from .extensions import format_type
    from ..parser.typed_ast import resolve_type_expr

    esperados = firma.params
    if len(fn.params) != len(esperados):
        return None, (
            f"'{fn.name}' debe declarar {len(esperados)} parámetro(s) — es lo "
            f"que promete la extensión '{firma.module}': {firma.describe()}"
        )

    for i, (param, esperado) in enumerate(zip(fn.params, esperados), start=1):
        try:
            real = resolve_type_expr(param.type)
        except Exception:
            real = None
        if real != esperado:
            visto = format_type(real) if real is not None else "<?>"
            return None, (
                f"el parámetro {i} de '{fn.name}' es '{visto}' y la extensión "
                f"'{firma.module}' lo declaró '{format_type(esperado)}' "
                f"({firma.describe()})"
            )

    try:
        retorno = resolve_type_expr(fn.return_type) if fn.return_type is not None else None
    except Exception:
        retorno = None
    if retorno != firma.returns:
        visto = format_type(retorno) if retorno is not None else "<?>"
        return None, (
            f"'{fn.name}' devuelve '{visto}' y la extensión '{firma.module}' "
            f"lo declaró '{format_type(firma.returns)}'"
        )

    owner = _nominal_ptr_target(fn.params[0].type)
    if owner is None:
        return None, (
            f"el primer parámetro de '{fn.name}' debe ser 'T ptr' (T nominal): "
            "es lo que hace del hook un hook DE un tipo"
        )
    if owner != firma.owner:
        return None, (
            f"'{fn.name}' se implementa sobre '{owner}' pero la extensión "
            f"'{firma.module}' lo declaró de '{firma.owner}'"
        )
    return owner, None


def hook_owner_type_name(fn: ast.FunctionDecl, kind: HookKind) -> Optional[str]:
    """Nombre del tipo nominal dueño del hook, según su convención de firma.

    Vista permisiva (solo el lado que define al dueño, sin validar el resto
    de la firma); para el registro real usar :func:`validate_hook`, que
    valida la firma completa.
    """
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
